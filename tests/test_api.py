from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

import app.main as main


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "current.sqlite3")
    monkeypatch.setattr(main, "DIAMONDS_PATH", Path(__file__).parent.parent / "data" / "diamonds.txt")


def high_water_stub(reference_port, at, database=None):
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
    assert payload["apiVersion"] == "1.3.0"
    assert payload["requestId"]
    assert payload["context"]["calculationTime"] == "2026-08-25T12:30:00+00:00"
    assert payload["quality"]["temporalResolutionMinutes"] == 5
    assert payload["provenance"]["calculationCache"]["status"] == "miss"
    assert payload["quality"]["spatialInterpolation"] is False
    assert payload["quality"]["spatialPointCount"] == 1
    assert payload["context"]["interpolationPoints"][0]["weight"] == 1.0


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


def test_nearby_queries_share_operational_calculation(monkeypatch):
    calls = []

    def counted_high_water(reference_port, at, database=None):
        calls.append((reference_port, at))
        return high_water_stub(reference_port, at, database)

    monkeypatch.setattr(main, "fetch_nearest_high_water", counted_high_water)
    common = {"source": "diamonds", "lat": 51.9858, "lon": 3.896}
    with TestClient(main.app) as client:
        first = client.get("/v1/current", params={**common, "time": "2026-08-25T12:29:00Z"})
        second = client.get("/v1/current", params={**common, "time": "2026-08-25T12:31:00Z"})
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["context"]["calculationTime"] == "2026-08-25T12:30:00+00:00"
    assert second.json()["context"]["calculationTime"] == "2026-08-25T12:30:00+00:00"
    assert first.json()["provenance"]["calculationCache"]["status"] == "miss"
    assert second.json()["provenance"]["calculationCache"]["status"] == "hit"
    assert len(calls) == 4


def test_between_diamonds_uses_weighted_spatial_vectors(monkeypatch):
    monkeypatch.setattr(main, "fetch_nearest_high_water", high_water_stub)
    with TestClient(main.app) as client:
        response = client.get("/v1/current", params={
            "source": "diamonds",
            "lat": 51.826,
            "lon": 3.6037,
            "time": "2026-08-25T12:30:00Z",
        })
    assert response.status_code == 200
    payload = response.json()
    points = payload["context"]["interpolationPoints"]
    assert payload["quality"]["spatialInterpolation"] is True
    assert payload["quality"]["spatialPointCount"] == 4
    assert payload["quality"]["spatialDistancePower"] == 2
    assert len(points) == 4
    assert sum(point["weight"] for point in points) == pytest.approx(1, abs=0.00001)
    assert {7, 8}.issubset({point["number"] for point in points})
    assert all(point["distanceKm"] <= main.MAX_DISTANCE_KM for point in points)


def test_spatial_points_keep_their_own_reference_port(monkeypatch):
    calls = []

    def port_aware_high_water(reference_port, at, database=None):
        calls.append(reference_port)
        result = high_water_stub(reference_port, at, database)
        if reference_port == "vlissingen":
            result = {**result, "station_code": "vlissingen"}
        return result

    monkeypatch.setattr(main, "fetch_nearest_high_water", port_aware_high_water)
    with TestClient(main.app) as client:
        response = client.get("/v1/current", params={
            "source": "diamonds", "lat": 51.85, "lon": 3.84,
            "time": "2026-08-25T12:30:00Z",
        })
    assert response.status_code == 200
    points = response.json()["context"]["interpolationPoints"]
    assert {"Hoek van Holland", "Vlissingen"}.issubset(
        {point["referencePort"] for point in points}
    )
    assert {"hoek_van_holland", "vlissingen"}.issubset(set(calls))


def test_batch_preserves_order_shares_cache_and_returns_partial_errors(monkeypatch):
    monkeypatch.setattr(main, "fetch_nearest_high_water", high_water_stub)
    body = {
        "source": "diamonds",
        "queries": [
            {"lat": 51.826, "lon": 3.6037, "time": "2026-08-25T12:29:00Z"},
            {"lat": 51.8261, "lon": 3.6038, "time": "2026-08-25T12:31:00Z"},
            {"lat": 0, "lon": 0, "time": "2026-08-25T12:30:00Z"},
        ],
    }
    with TestClient(main.app) as client:
        response = client.post("/v1/current/batch", json=body)
    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"] == {
        "requested": 3,
        "succeeded": 2,
        "failed": 1,
        "calculationPointHits": 4,
        "calculationPointMisses": 4,
    }
    assert [item["index"] for item in payload["results"]] == [0, 1, 2]
    assert [item["status"] for item in payload["results"]] == ["ok", "ok", "error"]
    assert payload["results"][0]["provenance"]["calculationCache"]["status"] == "miss"
    assert payload["results"][1]["provenance"]["calculationCache"]["status"] == "hit"
    assert payload["results"][2]["error"]["code"] == "not_found"


def test_batch_invalid_time_is_an_item_error(monkeypatch):
    monkeypatch.setattr(main, "fetch_nearest_high_water", high_water_stub)
    with TestClient(main.app) as client:
        response = client.post("/v1/current/batch", json={
            "source": "diamonds",
            "queries": [
                {"lat": 51.825, "lon": 3.6388, "time": "not-a-time"},
                {"lat": 51.825, "lon": 3.6388, "time": "2026-08-25T12:30:00Z"},
            ],
        })
    payload = response.json()
    assert response.status_code == 200
    assert payload["summary"]["failed"] == 1
    assert payload["summary"]["succeeded"] == 1
    assert payload["results"][0]["error"]["code"] == "invalid_request"
    assert payload["results"][1]["status"] == "ok"


def test_batch_rejects_more_than_one_hundred_items():
    query = {"lat": 51.825, "lon": 3.6388, "time": "2026-08-25T12:30:00Z"}
    with TestClient(main.app) as client:
        response = client.post("/v1/current/batch", json={
            "source": "diamonds", "queries": [query] * 101,
        })
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_cors_allows_batch_post():
    with TestClient(main.app) as client:
        response = client.options("/v1/current/batch", headers={
            "Origin": "http://tracksense.local",
            "Access-Control-Request-Method": "POST",
        })
    assert response.status_code == 200
    assert "POST" in response.headers["access-control-allow-methods"]
