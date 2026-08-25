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
