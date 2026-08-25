import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def initialise_calculation_cache(database: Path) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS current_calculations (
                source TEXT NOT NULL,
                point_id INTEGER NOT NULL,
                atlas_sha256 TEXT NOT NULL,
                bucket_utc TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                calculated_at TEXT NOT NULL,
                PRIMARY KEY (source, point_id, atlas_sha256, bucket_utc)
            )
            """
        )


def five_minute_bucket(at: datetime) -> datetime:
    utc = at.astimezone(timezone.utc)
    seconds = int(utc.timestamp())
    bucket_seconds = ((seconds + 150) // 300) * 300
    return datetime.fromtimestamp(bucket_seconds, tz=timezone.utc)


def load_calculation(
    database: Path,
    *,
    source: str,
    point_id: int,
    atlas_sha256: str,
    bucket: datetime,
) -> dict | None:
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            """
            SELECT payload_json, calculated_at
            FROM current_calculations
            WHERE source=? AND point_id=? AND atlas_sha256=? AND bucket_utc=?
            """,
            (source, point_id, atlas_sha256, bucket.isoformat()),
        ).fetchone()
    if row is None:
        return None
    return {"payload": json.loads(row[0]), "calculated_at": row[1]}


def store_calculation(
    database: Path,
    *,
    source: str,
    point_id: int,
    atlas_sha256: str,
    bucket: datetime,
    payload: dict,
) -> str:
    calculated_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO current_calculations (
                source, point_id, atlas_sha256, bucket_utc,
                payload_json, calculated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, point_id, atlas_sha256, bucket_utc)
            DO UPDATE SET payload_json=excluded.payload_json,
                          calculated_at=excluded.calculated_at
            """,
            (
                source,
                point_id,
                atlas_sha256,
                bucket.isoformat(),
                json.dumps(payload, separators=(",", ":")),
                calculated_at,
            ),
        )
    return calculated_at


def calculation_cache_status(database: Path) -> dict:
    try:
        with sqlite3.connect(database) as connection:
            row = connection.execute(
                """
                SELECT COUNT(*), MIN(bucket_utc), MAX(bucket_utc),
                       MAX(calculated_at) FROM current_calculations
                """
            ).fetchone()
    except sqlite3.DatabaseError:
        return {"entries": 0, "firstBucket": None, "lastBucket": None, "lastCalculatedAt": None}
    return {
        "entries": row[0],
        "firstBucket": row[1],
        "lastBucket": row[2],
        "lastCalculatedAt": row[3],
    }
