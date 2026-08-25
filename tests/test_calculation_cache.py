from datetime import datetime, timezone

from app.calculation_cache import (
    five_minute_bucket,
    initialise_calculation_cache,
    load_calculation,
    store_calculation,
)


def test_five_minute_bucket_uses_nearest_interval():
    assert five_minute_bucket(datetime(2026, 8, 25, 12, 27, 29, tzinfo=timezone.utc)).minute == 25
    assert five_minute_bucket(datetime(2026, 8, 25, 12, 27, 30, tzinfo=timezone.utc)).minute == 30


def test_calculation_survives_new_database_connection(tmp_path):
    database = tmp_path / "current.sqlite3"
    initialise_calculation_cache(database)
    bucket = datetime(2026, 8, 25, 12, 30, tzinfo=timezone.utc)
    store_calculation(
        database,
        source="diamonds",
        point_id=7,
        atlas_sha256="abc",
        bucket=bucket,
        payload={"current": {"speed_knots": 1.2}},
    )
    loaded = load_calculation(
        database,
        source="diamonds",
        point_id=7,
        atlas_sha256="abc",
        bucket=bucket,
    )
    assert loaded["payload"]["current"]["speed_knots"] == 1.2
