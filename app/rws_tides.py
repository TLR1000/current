import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from threading import Lock
from time import monotonic


RWS_ENDPOINT = os.getenv(
    "RWS_WATER_LEVEL_ENDPOINT",
    "https://ddapi20-waterwebservices.rijkswaterstaat.nl/"
    "ONLINEWAARNEMINGENSERVICES/OphalenWaarnemingen",
)

RWS_STATION_CODES = {
    "hoek_van_holland": "hoekvanholland",
    "vlissingen": "vlissingen",
}
RWS_CACHE_TTL_SECONDS = int(os.getenv("CURRENT_RWS_CACHE_TTL_SECONDS", "21600"))
_CACHE: dict[tuple[str, str], tuple[float, list[datetime]]] = {}
_CACHE_LOCK = Lock()


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def extremes_request(station_code: str, at: datetime) -> dict:
    utc_at = at.astimezone(timezone.utc)
    day_start = utc_at.replace(hour=0, minute=0, second=0, microsecond=0)
    return {
        "Locatie": {"Code": station_code},
        "AquoPlusWaarnemingMetadata": {
            "AquoMetadata": {
                "Compartiment": {"Code": "OW"},
                "Grootheid": {"Code": "WATHTE"},
                "Hoedanigheid": {"Code": "NAP"},
                "Groepering": {"Code": "GETETBRKD2"},
            }
        },
        "Periode": {
            "Begindatumtijd": _iso(day_start - timedelta(hours=7)),
            "Einddatumtijd": _iso(day_start + timedelta(days=1, hours=7)),
        },
    }


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_high_waters(response: dict) -> list[datetime]:
    series = response.get("WaarnemingenLijst", [])
    type_series = next(
        (
            item for item in series
            if item.get("AquoMetadata", {}).get("Typering", {}).get("Code") == "GETETTPE"
        ),
        None,
    )
    if type_series is not None:
        result = []
        for measurement in type_series.get("MetingenLijst", []):
            label = str(measurement.get("Meetwaarde", {}).get("Waarde_Alfanumeriek", "")).lower()
            value = str(measurement.get("Tijdstip", ""))
            if "hoog" not in label or not value:
                continue
            try:
                result.append(_parse_time(value))
            except ValueError:
                continue
        if result:
            return sorted(result)

    # GETETBRKD2 may return alternating extrema without an explicit HW/LW label.
    extrema = []
    for item in series:
        metadata = item.get("AquoMetadata", {})
        if metadata.get("Grootheid", {}).get("Code") != "WATHTE":
            continue
        for measurement in item.get("MetingenLijst", []):
            value = measurement.get("Meetwaarde", {}).get("Waarde_Numeriek")
            try:
                extrema.append((_parse_time(str(measurement["Tijdstip"])), float(value)))
            except (KeyError, TypeError, ValueError):
                continue
    extrema.sort(key=lambda row: row[0])
    high_waters = []
    for index, (measured_at, level) in enumerate(extrema):
        previous = extrema[index - 1][1] if index else None
        following = extrema[index + 1][1] if index + 1 < len(extrema) else None
        if previous is None and following is not None and level > following:
            high_waters.append(measured_at)
        elif following is None and previous is not None and level > previous:
            high_waters.append(measured_at)
        elif previous is not None and following is not None and level >= previous and level >= following:
            high_waters.append(measured_at)
    return high_waters


def fetch_nearest_high_water(reference_port: str, at: datetime) -> dict:
    station_code = RWS_STATION_CODES.get(reference_port)
    if station_code is None:
        raise ValueError(f"No RWS station configured for {reference_port}")
    cache_key = (station_code, at.astimezone(timezone.utc).date().isoformat())
    now = monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
    cache_status = "hit" if cached and now - cached[0] < RWS_CACHE_TTL_SECONDS else "miss"
    high_waters = cached[1] if cache_status == "hit" else None
    request = urllib.request.Request(
        RWS_ENDPOINT,
        data=json.dumps(extremes_request(station_code, at)).encode("utf-8"),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    if high_waters is None:
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"RWS WaterWebservices unavailable: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("Succesvol") is not True:
            raise RuntimeError("RWS WaterWebservices returned an invalid response")
        high_waters = parse_high_waters(payload)
        with _CACHE_LOCK:
            _CACHE[cache_key] = (now, high_waters)
    if not high_waters:
        raise RuntimeError(f"RWS returned no high water for {station_code}")
    high_water = min(high_waters, key=lambda value: abs((at - value).total_seconds()))
    return {
        "time": high_water,
        "station_code": station_code,
        "source": "Rijkswaterstaat DDAPI20",
        "dataset": "GETETBRKD2",
        "cache": cache_status,
    }
