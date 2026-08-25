from datetime import datetime, timezone

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
