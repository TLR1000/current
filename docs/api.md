# API-contract

## Stabiliteit

Routes onder `/v1` zijn het stabiele publieke contract. Velden worden binnen
v1 niet verwijderd of van betekenis veranderd. Nieuwe optionele velden mogen
wel worden toegevoegd; clients moeten onbekende velden daarom negeren.

Alle succesvolle en foutresponses bevatten:

```json
{
  "apiVersion": "1.3.0",
  "requestId": "d8ccf25b-..."
}
```

## Stroming opvragen

```http
GET /v1/current?source=diamonds&lat=51.9&lon=3.8&time=2026-08-25T12:00:00Z
```

Parameters:

| Naam | Verplicht | Betekenis |
|---|---:|---|
| `source` | ja | Expliciete provider; momenteel `diamonds` |
| `lat` | ja | WGS84-breedtegraad, −90 t/m 90 |
| `lon` | ja | WGS84-lengtegraad, −180 t/m 180 |
| `time` | ja | ISO 8601 met tijdzone; intern naar UTC genormaliseerd |

Voorbeeldresponse:

```json
{
  "apiVersion": "1.3.0",
  "requestId": "d8ccf25b-...",
  "source": "diamonds",
  "query": {
    "latitude": 51.9,
    "longitude": 3.8,
    "time": "2026-08-25T12:00:00+00:00"
  },
  "current": {
    "directionDegreesTrue": 38.4,
    "speedKnots": 1.26,
    "speedMetersPerSecond": 0.648,
    "eastwardMetersPerSecond": 0.403,
    "northwardMetersPerSecond": 0.508
  },
  "context": {
    "area": "voordelta",
    "calculationTime": "2026-08-25T12:00:00+00:00",
    "referencePort": "Hoek van Holland",
    "referenceHighWater": "2026-08-25T12:38:00+00:00",
    "hoursFromHighWater": -0.633,
    "springNeapFactor": 0.72,
    "diamond": {
      "number": 3,
      "latitude": 51.8741667,
      "longitude": 3.8998333,
      "distanceKm": 7.41
    },
    "interpolationPoints": [
      {
        "number": 3,
        "latitude": 51.8741667,
        "longitude": 3.8998333,
        "distanceKm": 7.41,
        "weight": 0.54,
        "referencePort": "Hoek van Holland",
        "referenceHighWater": "2026-08-25T12:38:00+00:00",
        "hoursFromHighWater": -0.633,
        "springNeapFactor": 0.72,
        "calculationCache": {"status": "hit"},
        "highWater": {"station": "hoekvanholland", "cache": "persistent-hit"}
      }
    ]
  },
  "quality": {
    "method": "inverse-distance weighted spatial and temporal vector interpolation",
    "spatialInterpolation": true,
    "spatialPointCount": 4,
    "spatialDistancePower": 2.0,
    "temporalResolutionMinutes": 5,
    "maximumTimeOffsetSeconds": 150,
    "estimated": true
  },
  "provenance": {
    "atlas": "tidal-diamonds",
    "highWater": {
      "provider": "Rijkswaterstaat DDAPI20",
      "dataset": "GETETBRKD2",
      "station": "hoekvanholland",
      "cache": "hit"
    },
    "springNeap": "local astronomical calculation",
    "calculationCache": {
      "status": "hit",
      "calculatedAt": "2026-08-20T08:13:22+00:00",
      "ageSeconds": 468398
    }
  }
}
```

Richting is de richting waarheen het water stroomt, in graden waar vanaf het
noorden met de klok mee. `eastwardMetersPerSecond` is positief naar het oosten;
`northwardMetersPerSecond` is positief naar het noorden.

De service rondt `query.time` af naar het dichtstbijzijnde vijfminutenvak in
`context.calculationTime`. De maximale afwijking is 150 seconden. Dit sluit aan
op actuele vijfminutenpolling en zorgt dat route- en tijdreeksclients dezelfde
operationele berekeningen hergebruiken. `calculationCache.status` is `miss` bij
de eerste berekening en `hit` bij hergebruik, ook na een containerherstart.

Ruimtelijk gebruikt de service maximaal vier dichtstbijzijnde atlaspunten
binnen de coverageafstand. Het gewicht is `1 / afstand²`, genormaliseerd over
de geselecteerde punten. De API interpoleert de oost- en noordcomponent en
leidt daaruit richting en snelheid af. Een punt binnen één meter van een
diamant gebruikt uitsluitend die diamant. `context.diamond` blijft voor
compatibiliteit het dichtstbijzijnde punt; `context.interpolationPoints` is de
volledige, gezaghebbende lijst voor de ruimtelijke berekening.

## Fouten

Fouten hebben een stabiele structuur:

```json
{
  "apiVersion": "1.3.0",
  "requestId": "...",
  "error": {
    "code": "not_found",
    "message": "No current data within 15 km ..."
  }
}
```

| HTTP | Code | Betekenis |
|---:|---|---|
| 404 | `not_found` | Punt ligt buiten de toegestane dekking |
| 422 | `invalid_request` | Parameter ontbreekt of is ongeldig |
| 503 | `upstream_unavailable` | Dataset of externe HW-bron niet beschikbaar |

Er is momenteel geen authenticatie en geen rate limiting. Clients moeten een
redelijke timeout gebruiken en 503 tijdelijk behandelen met begrensde retry en
backoff.

## Batchinterface

```http
POST /v1/current/batch
Content-Type: application/json
```

Request:

```json
{
  "source": "diamonds",
  "queries": [
    {"lat": 51.826, "lon": 3.6037, "time": "2026-09-12T12:29:00Z"},
    {"lat": 51.8261, "lon": 3.6038, "time": "2026-09-12T12:31:00Z"},
    {"lat": 0, "lon": 0, "time": "2026-09-12T12:30:00Z"}
  ]
}
```

Regels:

- minimaal 1 en maximaal 100 items;
- resultaten hebben dezelfde volgorde als `queries` en een zero-based `index`;
- `lat` en `lon` worden voor de hele request gevalideerd;
- een ongeldige tijd of inhoudelijke fout wordt per item geretourneerd;
- de HTTP-response blijft 200 wanneer de batch syntactisch geldig is, ook als
  één of meer items falen;
- een structureel ongeldige body of meer dan 100 items geeft HTTP 422;
- clients splitsen grotere tijdreeksen zelf in deterministische blokken van 100.

Ingekort antwoord:

```json
{
  "apiVersion": "1.3.0",
  "requestId": "...",
  "source": "diamonds",
  "summary": {
    "requested": 3,
    "succeeded": 2,
    "failed": 1,
    "calculationPointHits": 4,
    "calculationPointMisses": 4
  },
  "results": [
    {
      "index": 0,
      "status": "ok",
      "source": "diamonds",
      "query": {"latitude": 51.826, "longitude": 3.6037, "time": "..."},
      "current": {},
      "context": {},
      "quality": {},
      "provenance": {}
    },
    {
      "index": 2,
      "status": "error",
      "query": {"latitude": 0, "longitude": 0, "time": "..."},
      "error": {
        "httpStatus": 404,
        "code": "not_found",
        "message": "No current data within 15 km ..."
      }
    }
  ]
}
```

Een succesvol item heeft hetzelfde `source`, `query`, `current`, `context`,
`quality` en `provenance`-contract als `GET /v1/current`. De summary telt
cachehits en -misses op onderliggend diamantniveau, niet alleen per query.
