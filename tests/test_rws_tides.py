from datetime import datetime, timezone
import json
import sqlite3
import urllib.error

import app.rws_tides as tides
from app.rws_tides import extremes_request, parse_high_waters


def test_extremes_request_uses_official_grouping():
    payload = extremes_request("hoekvanholland", datetime(2026, 8, 25, 12, tzinfo=timezone.utc))
    metadata = payload["AquoPlusWaarnemingMetadata"]["AquoMetadata"]
    assert metadata["Groepering"]["Code"] == "GETETBRKD2"
    assert metadata["Grootheid"]["Code"] == "WATHTE"
    assert payload["Locatie"]["Code"] == "hoekvanholland"


def test_parse_labelled_high_water():
    payload = {"WaarnemingenLijst": [{
        "AquoMetadata": {"Typering": {"Code": "GETETTPE"}},
        "MetingenLijst": [
            {"Tijdstip": "2026-08-25T10:00:00Z", "Meetwaarde": {"Waarde_Alfanumeriek": "hoogwater"}},
            {"Tijdstip": "2026-08-25T16:00:00Z", "Meetwaarde": {"Waarde_Alfanumeriek": "laagwater"}},
        ],
    }]}
    assert parse_high_waters(payload) == [datetime(2026, 8, 25, 10, tzinfo=timezone.utc)]


def test_parse_unlabelled_alternating_extremes():
    payload = {"WaarnemingenLijst": [{
        "AquoMetadata": {"Grootheid": {"Code": "WATHTE"}},
        "MetingenLijst": [
            {"Tijdstip": "2026-08-25T04:00:00Z", "Meetwaarde": {"Waarde_Numeriek": -80}},
            {"Tijdstip": "2026-08-25T10:00:00Z", "Meetwaarde": {"Waarde_Numeriek": 120}},
            {"Tijdstip": "2026-08-25T16:00:00Z", "Meetwaarde": {"Waarde_Numeriek": -70}},
        ],
    }]}
    assert parse_high_waters(payload) == [datetime(2026, 8, 25, 10, tzinfo=timezone.utc)]


def test_persistent_high_water_cache_survives_process_memory(tmp_path, monkeypatch):
    database = tmp_path / "current.sqlite3"
    tides.initialise_rws_cache(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO rws_high_water_cache VALUES (?, ?, ?, ?)",
            (
                "hoekvanholland",
                "2026-08-25",
                json.dumps(["2026-08-25T10:00:00Z"]),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    tides._CACHE.clear()
    monkeypatch.setattr(
        tides.urllib.request,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("upstream must not be called")),
    )
    result = tides.fetch_nearest_high_water(
        "hoek_van_holland",
        datetime(2026, 8, 25, 10, 15, tzinfo=timezone.utc),
        database,
    )
    assert result["time"] == datetime(2026, 8, 25, 10, tzinfo=timezone.utc)
    assert result["cache"] == "persistent-hit"


def test_stale_high_water_is_used_when_rws_is_unavailable(tmp_path, monkeypatch):
    database = tmp_path / "current.sqlite3"
    tides.initialise_rws_cache(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO rws_high_water_cache VALUES (?, ?, ?, ?)",
            (
                "vlissingen",
                "2026-08-25",
                json.dumps(["2026-08-25T11:44:00Z"]),
                "2000-01-01T00:00:00+00:00",
            ),
        )
    tides._CACHE.clear()
    monkeypatch.setattr(
        tides.urllib.request,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(urllib.error.URLError("offline")),
    )
    result = tides.fetch_nearest_high_water(
        "vlissingen",
        datetime(2026, 8, 25, 12, tzinfo=timezone.utc),
        database,
    )
    assert result["time"] == datetime(2026, 8, 25, 11, 44, tzinfo=timezone.utc)
    assert result["cache"] == "stale"
