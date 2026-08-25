import math
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.diamonds import calculate_diamond_current, import_diamonds, moon_spring_neap_factor
from app.calculation_cache import (
    calculation_cache_status,
    five_minute_bucket,
    initialise_calculation_cache,
    load_calculation,
    store_calculation,
)
from app.rws_tides import fetch_nearest_high_water, initialise_rws_cache


API_VERSION = "1.3.0"
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("CURRENT_DB", BASE_DIR / "current.sqlite3"))
DIAMONDS_PATH = Path(os.getenv("CURRENT_DIAMONDS_FILE", BASE_DIR / "data" / "diamonds.txt"))
MAX_DISTANCE_KM = float(os.getenv("CURRENT_MAX_POINT_DISTANCE_KM", "15"))
SPATIAL_POINT_COUNT = int(os.getenv("CURRENT_SPATIAL_POINT_COUNT", "4"))
SPATIAL_POWER = float(os.getenv("CURRENT_SPATIAL_POWER", "2"))
EXACT_POINT_KM = 0.001
BATCH_MAX_ITEMS = 100


class BatchQuery(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    time: str


class BatchRequest(BaseModel):
    source: Literal["diamonds"]
    queries: list[BatchQuery] = Field(min_length=1, max_length=BATCH_MAX_ITEMS)


def initialise_data() -> dict:
    if not DIAMONDS_PATH.exists():
        raise RuntimeError(f"Diamond source file not found: {DIAMONDS_PATH}")
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    result = import_diamonds(DB_PATH, DIAMONDS_PATH)
    initialise_calculation_cache(DB_PATH)
    initialise_rws_cache(DB_PATH)
    return result


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialise_data()
    yield


app = FastAPI(
    title="Current API",
    description="Shared tidal-current service for nautical applications.",
    version=API_VERSION,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def request_id(request: Request) -> str:
    return request.headers.get("X-Request-ID") or str(uuid4())


def envelope(request: Request, **content):
    return {"apiVersion": API_VERSION, "requestId": request_id(request), **content}


def error_code(status: int) -> str:
    return {404: "not_found", 422: "invalid_request", 503: "upstream_unavailable"}.get(
        status, "request_failed"
    )


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=envelope(
            request,
            error={"code": error_code(exc.status_code), "message": str(exc.detail)},
        ),
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    fields = [".".join(str(part) for part in item["loc"] if part != "query") for item in exc.errors()]
    return JSONResponse(
        status_code=422,
        content=envelope(
            request,
            error={
                "code": "invalid_request",
                "message": "One or more query parameters are invalid.",
                "fields": fields,
            },
        ),
    )


def parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(422, "time must be a valid ISO 8601 date-time") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HTTPException(422, "time must include a timezone")
    return parsed.astimezone(timezone.utc)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0088
    lat1_rad, lat2_rad = math.radians(lat1), math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
    )
    return 2 * radius_km * math.asin(math.sqrt(value))


def database_ready() -> bool:
    try:
        with sqlite3.connect(DB_PATH) as connection:
            return connection.execute("SELECT COUNT(*) FROM diamond_points").fetchone()[0] > 0
    except sqlite3.DatabaseError:
        return False


def find_candidate_diamonds(lat: float, lon: float):
    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT p.id AS point_id, p.diamond_number, p.lat, p.lon,
                   rp.code AS reference_port_code, rp.name AS reference_port,
                   s.area_code, s.source_sha256, s.imported_at
            FROM diamond_points p
            JOIN diamond_sources s ON s.id = p.source_id
            JOIN reference_ports rp ON rp.id = p.reference_port_id
            WHERE s.id = (
                SELECT id FROM diamond_sources ORDER BY imported_at DESC, id DESC LIMIT 1
            )
            """
        ).fetchall()
    points = []
    for row in rows:
        point = dict(row)
        point["distance_km_raw"] = haversine_km(lat, lon, row["lat"], row["lon"])
        point["distance_km"] = round(point["distance_km_raw"], 3)
        points.append(point)
    return sorted(points, key=lambda point: point["distance_km_raw"])


def load_rates(point_id: int):
    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        return [
            dict(row)
            for row in connection.execute(
                """
                SELECT hours_from_high_water, direction_deg,
                       spring_speed_knots, neap_speed_knots
                FROM diamond_hourly_rates
                WHERE diamond_point_id=? ORDER BY hours_from_high_water
                """,
                (point_id,),
            ).fetchall()
        ]


def point_calculation(source: str, point: dict, bucket: datetime) -> dict:
    cached = load_calculation(
        DB_PATH,
        source=source,
        point_id=point["point_id"],
        atlas_sha256=point["source_sha256"],
        bucket=bucket,
    )
    if cached:
        calculation = cached["payload"]
        calculated_at = cached["calculated_at"]
        cache_status = "hit"
    else:
        high_water = fetch_nearest_high_water(
            point["reference_port_code"], bucket, DB_PATH
        )
        hours_from_high_water = (bucket - high_water["time"]).total_seconds() / 3600
        spring_neap_factor = moon_spring_neap_factor(bucket)
        current = calculate_diamond_current(
            load_rates(point["point_id"]), hours_from_high_water, spring_neap_factor
        )
        calculation = {
            "current": current,
            "referenceHighWater": high_water["time"].isoformat(),
            "hoursFromHighWater": round(hours_from_high_water, 3),
            "springNeapFactor": round(spring_neap_factor, 4),
            "highWater": {
                "provider": high_water["source"],
                "dataset": high_water["dataset"],
                "station": high_water["station_code"],
                "cache": high_water.get("cache", "none"),
            },
        }
        calculated_at = store_calculation(
            DB_PATH,
            source=source,
            point_id=point["point_id"],
            atlas_sha256=point["source_sha256"],
            bucket=bucket,
            payload=calculation,
        )
        cache_status = "miss"
    calculated = datetime.fromisoformat(calculated_at.replace("Z", "+00:00"))
    return {
        **calculation,
        "cacheStatus": cache_status,
        "calculatedAt": calculated_at,
        "cacheAgeSeconds": max(
            0, int((datetime.now(timezone.utc) - calculated).total_seconds())
        ),
    }


def spatial_weights(points: list[dict]) -> list[float]:
    if len(points) == 1:
        return [1.0]
    if points[0]["distance_km_raw"] <= EXACT_POINT_KM:
        return [1.0] + [0.0] * (len(points) - 1)
    raw = [1 / (point["distance_km_raw"] ** SPATIAL_POWER) for point in points]
    total = sum(raw)
    return [value / total for value in raw]


def interpolate_vectors(calculations: list[dict], weights: list[float]) -> dict:
    u = sum(item["current"]["u"] * weight for item, weight in zip(calculations, weights))
    v = sum(item["current"]["v"] * weight for item, weight in zip(calculations, weights))
    speed_mps = math.hypot(u, v)
    direction = round(math.degrees(math.atan2(u, v)) % 360, 3) % 360
    return {
        "directionDegreesTrue": direction,
        "speedKnots": round(speed_mps / 0.514444, 3),
        "speedMetersPerSecond": round(speed_mps, 3),
        "eastwardMetersPerSecond": round(u, 3),
        "northwardMetersPerSecond": round(v, 3),
    }


@app.get("/")
def root(request: Request):
    return envelope(
        request,
        service="current-api",
        message="Fair winds. Tidal current data is ready when you are.",
        status="ok" if database_ready() else "degraded",
        links={
            "documentation": "/docs",
            "health": "/health",
            "sources": "/v1/sources",
            "coverage": "/v1/coverage?source=diamonds",
            "example": "/v1/current?source=diamonds&lat=51.9&lon=3.8&time=2026-08-25T12:00:00Z",
            "batch": "/v1/current/batch",
        },
    )


@app.get("/health")
def health(request: Request):
    return envelope(
        request,
        status="ok" if database_ready() else "degraded",
        service="current-api",
        calculationCache=calculation_cache_status(DB_PATH),
    )


@app.get("/ready")
def ready(request: Request):
    if not database_ready():
        raise HTTPException(503, "Current dataset is not ready")
    return envelope(request, status="ready", service="current-api")


@app.get("/v1/sources")
def sources(request: Request):
    return envelope(
        request,
        sources=[{
            "id": "diamonds",
            "name": "Tidal diamonds",
            "area": "voordelta",
            "status": "available" if database_ready() else "unavailable",
        }],
    )


@app.get("/v1/coverage")
def coverage(request: Request, source: Literal["diamonds"] = Query(...)):
    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT COUNT(*) AS point_count, MIN(lat) AS min_lat, MAX(lat) AS max_lat,
                   MIN(lon) AS min_lon, MAX(lon) AS max_lon FROM diamond_points
            """
        ).fetchone()
    return envelope(
        request,
        source=source,
        area="voordelta",
        pointCount=row["point_count"],
        bounds={
            "south": row["min_lat"], "west": row["min_lon"],
            "north": row["max_lat"], "east": row["max_lon"],
        },
        maximumPointDistanceKm=MAX_DISTANCE_KM,
        spatialInterpolation={"maximumPoints": SPATIAL_POINT_COUNT, "distancePower": SPATIAL_POWER},
    )


def calculate_current(source: str, lat: float, lon: float, at: datetime) -> dict:
    available_points = find_candidate_diamonds(lat, lon)
    if not available_points:
        raise HTTPException(503, "Current dataset is unavailable")
    nearest = available_points[0]
    if nearest["distance_km_raw"] > MAX_DISTANCE_KM:
        raise HTTPException(
            404,
            f"No current data within {MAX_DISTANCE_KM:g} km; nearest diamond is "
            f"{nearest['distance_km']:.3f} km away",
        )
    candidates = [
        point for point in available_points
        if point["distance_km_raw"] <= MAX_DISTANCE_KM
    ][:SPATIAL_POINT_COUNT]
    if nearest["distance_km_raw"] <= EXACT_POINT_KM:
        candidates = [nearest]
    bucket = five_minute_bucket(at)
    try:
        calculations = [point_calculation(source, point, bucket) for point in candidates]
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(503, str(exc)) from exc
    weights = spatial_weights(candidates)
    current = interpolate_vectors(calculations, weights)
    point_contexts = [
        {
            "number": point["diamond_number"],
            "latitude": point["lat"],
            "longitude": point["lon"],
            "distanceKm": point["distance_km"],
            "weight": round(weight, 6),
            "referencePort": point["reference_port"],
            "referenceHighWater": calculation["referenceHighWater"],
            "hoursFromHighWater": calculation["hoursFromHighWater"],
            "springNeapFactor": calculation["springNeapFactor"],
            "calculationCache": {
                "status": calculation["cacheStatus"],
                "calculatedAt": calculation["calculatedAt"],
                "ageSeconds": calculation["cacheAgeSeconds"],
            },
            "highWater": calculation["highWater"],
        }
        for point, calculation, weight in zip(candidates, calculations, weights)
    ]
    primary_calculation = calculations[0]
    return {
        "source": source,
        "query": {"latitude": lat, "longitude": lon, "time": at.isoformat()},
        "current": current,
        "context": {
            "area": nearest["area_code"],
            "referencePort": nearest["reference_port"],
            "calculationTime": bucket.isoformat(),
            "referenceHighWater": primary_calculation["referenceHighWater"],
            "hoursFromHighWater": primary_calculation["hoursFromHighWater"],
            "springNeapFactor": primary_calculation["springNeapFactor"],
            "diamond": {
                "number": nearest["diamond_number"],
                "latitude": nearest["lat"], "longitude": nearest["lon"],
                "distanceKm": nearest["distance_km"],
            },
            "interpolationPoints": point_contexts,
        },
        "quality": {
            "method": "inverse-distance weighted spatial and temporal vector interpolation",
            "spatialInterpolation": len(candidates) > 1,
            "spatialPointCount": len(candidates),
            "spatialDistancePower": SPATIAL_POWER,
            "temporalResolutionMinutes": 5,
            "maximumTimeOffsetSeconds": 150,
            "estimated": True,
        },
        "provenance": {
            "atlas": "tidal-diamonds",
            "highWater": primary_calculation["highWater"],
            "springNeap": "local astronomical calculation",
            "calculationCache": {
                "status": "hit" if all(item["cacheStatus"] == "hit" for item in calculations) else "miss",
                "calculatedAt": primary_calculation["calculatedAt"],
                "ageSeconds": primary_calculation["cacheAgeSeconds"],
                "pointHits": sum(item["cacheStatus"] == "hit" for item in calculations),
                "pointMisses": sum(item["cacheStatus"] == "miss" for item in calculations),
            },
        },
    }


@app.get("/v1/current")
def get_current(
    request: Request,
    source: Literal["diamonds"] = Query(...),
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    time: str = Query(...),
):
    return envelope(request, **calculate_current(source, lat, lon, parse_time(time)))


@app.post("/v1/current/batch")
def get_current_batch(request: Request, batch: BatchRequest):
    results = []
    succeeded = 0
    failed = 0
    point_hits = 0
    point_misses = 0
    for index, query in enumerate(batch.queries):
        input_query = {"latitude": query.lat, "longitude": query.lon, "time": query.time}
        try:
            result = calculate_current(
                batch.source, query.lat, query.lon, parse_time(query.time)
            )
        except HTTPException as exc:
            failed += 1
            results.append({
                "index": index,
                "status": "error",
                "query": input_query,
                "error": {
                    "httpStatus": exc.status_code,
                    "code": error_code(exc.status_code),
                    "message": str(exc.detail),
                },
            })
            continue
        cache = result["provenance"]["calculationCache"]
        point_hits += cache["pointHits"]
        point_misses += cache["pointMisses"]
        succeeded += 1
        results.append({"index": index, "status": "ok", **result})
    return envelope(
        request,
        source=batch.source,
        summary={
            "requested": len(batch.queries),
            "succeeded": succeeded,
            "failed": failed,
            "calculationPointHits": point_hits,
            "calculationPointMisses": point_misses,
        },
        results=results,
    )
