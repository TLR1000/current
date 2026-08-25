from datetime import datetime, timezone

from fastapi.testclient import TestClient

import app.main as main


def high_water_stub(reference_port, at):
    return {
        "time": datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc),
        "station_code": "hoekvanholland",
        "source": "Rijkswaterstaat DDAPI20",
        "dataset": "GETETBRKD2",
        "cache": "hit",
    }


def test_root_is_useful_in_a_browser():
    with TestClient(main.app) as client:
        response = client.get("/")
    assert response.status_code == 200
    payload = response.json()
    assert payload["service"] == "current-api"
    assert payload["status"] == "ok"
    assert payload["links"]["documentation"] == "/docs"
    assert payload["message"].startswith("Fair winds")


def test_health_ready_sources_and_coverage():
    with TestClient(main.app) as client:
        assert client.get("/health").json()["status"] == "ok"
        assert client.get("/ready").json()["status"] == "ready"
        sources = client.get("/v1/sources").json()["sources"]
        coverage = client.get("/v1/coverage", params={"source": "diamonds"}).json()
    assert sources == [{"id": "diamonds", "name": "Tidal diamonds", "area": "voordelta", "status": "available"}]
    assert coverage["pointCount"] == 12
    assert coverage["bounds"]["north"] > coverage["bounds"]["south"]


def test_current_response_contract(monkeypatch):
    monkeypatch.setattr(main, "fetch_nearest_high_water", high_water_stub)
    with TestClient(main.app) as client:
        response = client.get("/v1/current", params={
            "source": "diamonds",
            "lat": 51.9858333333,
            "lon": 3.896,
            "time": "2026-08-25T12:30:00Z",
        })
    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "diamonds"
    assert payload["current"]["speedKnots"] > 0
    assert payload["current"]["directionDegreesTrue"] >= 0
    assert payload["context"]["diamond"]["number"] == 1
    assert payload["context"]["hoursFromHighWater"] == 0.5
    assert payload["quality"]["estimated"] is True
    assert payload["provenance"]["highWater"]["cache"] == "hit"
    assert payload["apiVersion"] == "1.0.0"
    assert payload["requestId"]


def test_source_is_explicit_and_errors_are_stable():
    with TestClient(main.app) as client:
        response = client.get("/v1/current", params={
            "lat": 51.9, "lon": 3.8, "time": "2026-08-25T12:00:00Z"
        })
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert "source" in response.json()["error"]["fields"]


def test_outside_coverage_is_404(monkeypatch):
    monkeypatch.setattr(main, "fetch_nearest_high_water", high_water_stub)
    with TestClient(main.app) as client:
        response = client.get("/v1/current", params={
            "source": "diamonds", "lat": 0, "lon": 0,
            "time": "2026-08-25T12:00:00Z",
        })
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
