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

from app.diamonds import calculate_diamond_current, import_diamonds, moon_spring_neap_factor
from app.rws_tides import fetch_nearest_high_water


API_VERSION = "1.0.0"
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("CURRENT_DB", BASE_DIR / "current.sqlite3"))
DIAMONDS_PATH = Path(os.getenv("CURRENT_DIAMONDS_FILE", BASE_DIR / "data" / "diamonds.txt"))
MAX_DISTANCE_KM = float(os.getenv("CURRENT_MAX_POINT_DISTANCE_KM", "15"))


def initialise_data() -> dict:
    if not DIAMONDS_PATH.exists():
        raise RuntimeError(f"Diamond source file not found: {DIAMONDS_PATH}")
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return import_diamonds(DB_PATH, DIAMONDS_PATH)


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
    allow_methods=["GET"],
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


def find_nearest_diamond(lat: float, lon: float):
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
    if not rows:
        return None
    point = min(rows, key=lambda row: haversine_km(lat, lon, row["lat"], row["lon"]))
    result = dict(point)
    result["distance_km"] = round(haversine_km(lat, lon, point["lat"], point["lon"]), 3)
    return result


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
        },
    )


@app.get("/health")
def health(request: Request):
    return envelope(request, status="ok" if database_ready() else "degraded", service="current-api")


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
    )


@app.get("/v1/current")
def get_current(
    request: Request,
    source: Literal["diamonds"] = Query(...),
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    time: str = Query(...),
):
    at = parse_time(time)
    point = find_nearest_diamond(lat, lon)
    if point is None:
        raise HTTPException(503, "Current dataset is unavailable")
    if point["distance_km"] > MAX_DISTANCE_KM:
        raise HTTPException(
            404,
            f"No current data within {MAX_DISTANCE_KM:g} km; nearest diamond is "
            f"{point['distance_km']:.3f} km away",
        )
    try:
        high_water = fetch_nearest_high_water(point["reference_port_code"], at)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(503, str(exc)) from exc
    hours_from_high_water = (at - high_water["time"]).total_seconds() / 3600
    spring_neap_factor = moon_spring_neap_factor(at)
    try:
        current = calculate_diamond_current(
            load_rates(point["point_id"]), hours_from_high_water, spring_neap_factor
        )
    except ValueError as exc:
        raise HTTPException(503, str(exc)) from exc
    return envelope(
        request,
        source=source,
        query={"latitude": lat, "longitude": lon, "time": at.isoformat()},
        current={
            "directionDegreesTrue": current["direction_deg"],
            "speedKnots": current["speed_knots"],
            "speedMetersPerSecond": current["speed_mps"],
            "eastwardMetersPerSecond": current["u"],
            "northwardMetersPerSecond": current["v"],
        },
        context={
            "area": point["area_code"],
            "referencePort": point["reference_port"],
            "referenceHighWater": high_water["time"].isoformat(),
            "hoursFromHighWater": round(hours_from_high_water, 3),
            "springNeapFactor": round(spring_neap_factor, 4),
            "diamond": {
                "number": point["diamond_number"],
                "latitude": point["lat"], "longitude": point["lon"],
                "distanceKm": point["distance_km"],
            },
        },
        quality={
            "method": "nearest-point temporal vector interpolation",
            "spatialInterpolation": False,
            "estimated": True,
        },
        provenance={
            "atlas": "tidal-diamonds",
            "highWater": {
                "provider": high_water["source"],
                "dataset": high_water["dataset"],
                "station": high_water["station_code"],
                "cache": high_water.get("cache", "none"),
            },
            "springNeap": "local astronomical calculation",
        },
    )
