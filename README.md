# Current API

Current API is een zelfstandige backendservice voor berekende getijstroom. De
service is bedoeld als gedeelde bron voor meerdere nautische apps en draait op
de shoebox via Docker Compose.

## Endpoint

```http
GET /v1/current?source=diamonds&lat=51.9&lon=3.8&time=2026-08-25T12:00:00Z
```

`source` is bewust verplicht. De huidige beschikbare bron is `diamonds` voor de
Voordelta. Richting is graden waar, snelheid wordt geleverd in knopen en m/s en
de oost-/noordcomponenten worden eveneens in m/s geretourneerd.

Handige routes:

- `GET /` — browser- en machinevriendelijke servicelanding;
- `GET /health` — processtatus;
- `GET /ready` — dataset gereed voor verkeer;
- `GET /v1/sources` — beschikbare databronnen;
- `GET /v1/coverage?source=diamonds` — dekking en begrenzing;
- `GET /v1/coverage/check?source=diamonds&lat=...&lon=...` — effectieve afstandsdekking;
- `POST /v1/current/batch` — maximaal 100 geordende positie/tijd-queries;
- `GET /docs` — interactieve OpenAPI-documentatie.

Zie [API-contract](docs/api.md), [architectuur](docs/architecture.md),
[datamodel](docs/data-model.md), [runbook](docs/runbook.md) en
[roadmap](docs/roadmap.md).

## Lokaal starten

```powershell
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8002 --no-access-log
```

Of met dezelfde containeropzet als live:

```powershell
docker compose up -d --build
```

Open daarna `http://localhost:8002` of `http://localhost:8002/docs`.

## Testen

```powershell
python -m pytest -q
```

## Live

- LAN: `http://192.168.178.241:8002`
- Container: `current-api`
- Deploybranch: `main`
- Authenticatie: nog niet ingeschakeld
- Access logging: uitgeschakeld

De service retourneert wel een `requestId`, maar bewaart die niet. Een client
mag zelf `X-Request-ID` meesturen voor correlatie binnen de eigen app.

## Caching

De service heeft twee persistente cachelagen in het Docker-volume:

- officiële RWS-HW-extremen per station en kalenderdag;
- operationele stroomresultaten per diamant en vijfminutenvak.

Verschillende apps en coördinaten die dezelfde diamant en hetzelfde tijdvak
gebruiken delen daarmee één berekening. De response vermeldt het exacte
`calculationTime` en de hit/miss-status. Het gevraagde tijdstip wordt naar het
dichtstbijzijnde vijfminutenvak afgerond, met maximaal 150 seconden verschil.

Voor een locatie tussen atlaspunten combineert de API maximaal vier geschikte
diamanten met inverse-distance-squared gewichten. De interpolatie gebeurt op de
oost-/noordvectoren. Exact op een diamant blijft de oorspronkelijke atlaswaarde
behouden. Alle gebruikte punten, afstanden, gewichten en referentiehavens staan
in `context.interpolationPoints`.

## Batch

Voor routeplanning en tijdreeksen accepteert de API maximaal 100 items per
request:

```json
{
  "source": "diamonds",
  "queries": [
    {"lat": 51.826, "lon": 3.6037, "time": "2026-09-12T12:30:00Z"},
    {"lat": 51.840, "lon": 3.6500, "time": "2026-09-12T12:35:00Z"}
  ]
}
```

De resultaten behouden de invoervolgorde. Een fout voor één item wordt in dat
item geretourneerd en breekt de overige berekeningen niet af. Grotere reeksen
moeten door de client in stabiele blokken van 100 worden verstuurd.

## Coverage en tijdssemantiek

De bounds van `/v1/coverage` zijn de uiterste atlaspuntcoördinaten, geen harde
API-grens. Een locatie is gedekt wanneer ten minste één diamant binnen 15 km
ligt. Stellendam (`51.83284, 4.03820`) ligt buiten de atlaspunt-bounds maar is
wel gedekt door drie punten. Gebruik `/v1/coverage/check` voor een eenduidige
voorafcontrole.

Diamonds is een astronomische getijatlas, geen forecastmodel. Responses maken
dit expliciet met `isForecastModel=false`; `modelRunAt`, forecast-horizon en
vaste `validFrom`/`validUntil` zijn daarom `null`, niet ontbrekend.
