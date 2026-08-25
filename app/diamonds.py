import hashlib
import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


LOCATION_RE = re.compile(
    r"^LOCATIE\s+(?P<number>\d+):(?:\s+"
    r"(?P<lat_deg>\d+)°(?P<lat_min>[\d.]+)'N\s+"
    r"(?P<lon_deg>\d+)°(?P<lon_min>[\d.]+)'E)?"
)
RATE_RE = re.compile(
    r"^(?P<hour>[-+]\d{2})h\s+"
    r"(?P<direction>\d{3})°\s+"
    r"(?P<spring>[\d,]+)\s+kn\s+"
    r"(?P<neap>[\d,]+)\s+kn$"
)
HW_RE = re.compile(
    r"^HW \(High Water\)\s+"
    r"(?P<direction>\d{3})°\s+"
    r"(?P<spring>[\d,]+)\s+kn\s+"
    r"(?P<neap>[\d,]+)\s+kn$"
)


@dataclass(frozen=True)
class DiamondRate:
    hour: int
    direction_deg: float
    spring_speed_knots: float
    neap_speed_knots: float


@dataclass
class DiamondPoint:
    number: int
    lat: float | None
    lon: float | None
    reference_port: str | None = None
    rates: list[DiamondRate] | None = None

    def __post_init__(self):
        if self.rates is None:
            self.rates = []


def _decimal(value: str) -> float:
    return float(value.replace(",", "."))


def _port_code(name: str) -> str:
    codes = {
        "Hoek van Holland": "hoek_van_holland",
        "Vlissingen": "vlissingen",
    }
    if name not in codes:
        raise ValueError(f"Unknown reference port: {name}")
    return codes[name]


def parse_diamonds(path: Path) -> tuple[list[DiamondPoint], list[str]]:
    points: list[DiamondPoint] = []
    warnings: list[str] = []
    current: DiamondPoint | None = None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        location = LOCATION_RE.match(line)
        if location:
            if current is not None:
                points.append(current)
            values = location.groupdict()
            has_coordinates = values["lat_deg"] is not None
            current = DiamondPoint(
                number=int(values["number"]),
                lat=(
                    int(values["lat_deg"]) + float(values["lat_min"]) / 60
                    if has_coordinates
                    else None
                ),
                lon=(
                    int(values["lon_deg"]) + float(values["lon_min"]) / 60
                    if has_coordinates
                    else None
                ),
            )
            continue
        if current is None:
            continue
        if line.startswith("Referentie:"):
            current.reference_port = _port_code(line.split(":", 1)[1].strip())
            continue
        match = HW_RE.match(line) or RATE_RE.match(line)
        if match:
            values = match.groupdict()
            current.rates.append(
                DiamondRate(
                    hour=int(values.get("hour") or 0),
                    direction_deg=float(values["direction"]),
                    spring_speed_knots=_decimal(values["spring"]),
                    neap_speed_knots=_decimal(values["neap"]),
                )
            )

    if current is not None:
        points.append(current)

    valid: list[DiamondPoint] = []
    for point in points:
        if point.lat is None or point.lon is None:
            warnings.append(f"diamond {point.number}: missing_coordinates")
            continue
        hours = sorted(rate.hour for rate in point.rates)
        if hours != list(range(-6, 7)):
            warnings.append(f"diamond {point.number}: incomplete_hourly_rates")
            continue
        if point.reference_port is None:
            warnings.append(f"diamond {point.number}: missing_reference_port")
            continue
        valid.append(point)
    return valid, warnings


def import_diamonds(database: Path, source_path: Path, area_code="voordelta") -> dict:
    points, warnings = parse_diamonds(source_path)
    source_bytes = source_path.read_bytes()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    imported_at = datetime.now(timezone.utc).isoformat()

    with sqlite3.connect(database) as conn:
        conn.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE IF NOT EXISTS reference_ports (
                id INTEGER PRIMARY KEY,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                lat REAL,
                lon REAL
            );
            CREATE TABLE IF NOT EXISTS diamond_sources (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                area_code TEXT NOT NULL,
                source_path TEXT NOT NULL,
                source_sha256 TEXT NOT NULL UNIQUE,
                imported_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS diamond_points (
                id INTEGER PRIMARY KEY,
                source_id INTEGER NOT NULL REFERENCES diamond_sources(id),
                diamond_number INTEGER NOT NULL,
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                reference_port_id INTEGER NOT NULL REFERENCES reference_ports(id),
                UNIQUE(source_id, diamond_number)
            );
            CREATE TABLE IF NOT EXISTS diamond_hourly_rates (
                diamond_point_id INTEGER NOT NULL REFERENCES diamond_points(id),
                hours_from_high_water INTEGER NOT NULL CHECK(hours_from_high_water BETWEEN -6 AND 6),
                direction_deg REAL NOT NULL CHECK(direction_deg >= 0 AND direction_deg < 360),
                spring_speed_knots REAL NOT NULL CHECK(spring_speed_knots >= 0),
                neap_speed_knots REAL NOT NULL CHECK(neap_speed_knots >= 0),
                PRIMARY KEY(diamond_point_id, hours_from_high_water)
            );
            """
        )
        for code, name in (
            ("hoek_van_holland", "Hoek van Holland"),
            ("vlissingen", "Vlissingen"),
        ):
            conn.execute(
                "INSERT INTO reference_ports(code, name) VALUES (?, ?) "
                "ON CONFLICT(code) DO UPDATE SET name=excluded.name",
                (code, name),
            )
        conn.execute(
            "INSERT INTO diamond_sources(name, area_code, source_path, source_sha256, imported_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(source_sha256) DO UPDATE SET imported_at=excluded.imported_at",
            ("Kaartdiamanten", area_code, str(source_path), source_sha256, imported_at),
        )
        source_id = conn.execute(
            "SELECT id FROM diamond_sources WHERE source_sha256=?", (source_sha256,)
        ).fetchone()[0]
        for point in points:
            port_id = conn.execute(
                "SELECT id FROM reference_ports WHERE code=?", (point.reference_port,)
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO diamond_points(source_id, diamond_number, lat, lon, reference_port_id) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(source_id, diamond_number) DO UPDATE SET "
                "lat=excluded.lat, lon=excluded.lon, reference_port_id=excluded.reference_port_id",
                (source_id, point.number, point.lat, point.lon, port_id),
            )
            point_id = conn.execute(
                "SELECT id FROM diamond_points WHERE source_id=? AND diamond_number=?",
                (source_id, point.number),
            ).fetchone()[0]
            for rate in point.rates:
                conn.execute(
                    "INSERT INTO diamond_hourly_rates VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(diamond_point_id, hours_from_high_water) DO UPDATE SET "
                    "direction_deg=excluded.direction_deg, spring_speed_knots=excluded.spring_speed_knots, "
                    "neap_speed_knots=excluded.neap_speed_knots",
                    (point_id, rate.hour, rate.direction_deg, rate.spring_speed_knots, rate.neap_speed_knots),
                )
    return {"imported_points": len(points), "warnings": warnings, "source_sha256": source_sha256}


def moon_spring_neap_factor(at: datetime) -> float:
    # Astronomical approximation: spring at new/full moon, neap at quarter moon.
    known_new_moon = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)
    synodic_month_days = 29.530588853
    age_days = ((at.astimezone(timezone.utc) - known_new_moon).total_seconds() / 86400) % synodic_month_days
    return abs(math.cos(2 * math.pi * age_days / synodic_month_days))


def calculate_diamond_current(rates, hours_from_hw: float, spring_neap_factor: float) -> dict:
    if not -6 <= hours_from_hw <= 6:
        raise ValueError("high_water must be within 6 hours of time")
    lower_hour = math.floor(hours_from_hw)
    upper_hour = math.ceil(hours_from_hw)
    fraction = hours_from_hw - lower_hour
    by_hour = {row["hours_from_high_water"]: row for row in rates}

    def vector(hour):
        row = by_hour[hour]
        speed = row["neap_speed_knots"] + spring_neap_factor * (
            row["spring_speed_knots"] - row["neap_speed_knots"]
        )
        radians = math.radians(row["direction_deg"])
        return speed * math.sin(radians), speed * math.cos(radians)

    u0, v0 = vector(lower_hour)
    u1, v1 = vector(upper_hour)
    u_knots = u0 + fraction * (u1 - u0)
    v_knots = v0 + fraction * (v1 - v0)
    speed_knots = math.hypot(u_knots, v_knots)
    direction_deg = math.degrees(math.atan2(u_knots, v_knots)) % 360
    rounded_direction = round(direction_deg, 3) % 360
    knots_to_mps = 0.514444
    return {
        "direction_deg": rounded_direction,
        "speed_knots": round(speed_knots, 3),
        "speed_mps": round(speed_knots * knots_to_mps, 3),
        "u": round(u_knots * knots_to_mps, 3),
        "v": round(v_knots * knots_to_mps, 3),
    }
