# Architectuur

```text
TrackSense / SailSense / FleetSense / andere clients
                         |
                  HTTP :8002 (v1)
                         |
                   Current API
                    /        \
          SQLite atlas      RWS DDAPI20
          12 diamanten      officiële HW-extremen
                    \        /
             vector- en tijdinterpolatie
                         |
                uniforme current-response
```

De publieke API is providerbewust via de verplichte `source`-parameter, maar
clients hoeven de opslag of rekenimplementatie niet te kennen. De huidige
provider selecteert het dichtstbijzijnde geldige atlaspunt binnen 15 km.

Requests worden naar het dichtstbijzijnde vijfminutenvak genormaliseerd. De
operationele cachesleutel bestaat uit provider, atlasversie, diamant en tijdvak;
de aangevraagde coördinaten zijn bewust geen onderdeel. SailSense-polls,
TrackSense-planning en FleetSense-tijdreeksen delen daardoor berekeningen zodra
zij bij dezelfde diamant uitkomen.

Bij een cachemiss wordt het relevante officiële HW van de referentiehaven
opgehaald. De RWS-extremen worden per station en kalenderdag persistent in
SQLite opgeslagen en dertig dagen vers gehouden. Bij een tijdelijke storing
mag een ouder gevalideerd record als expliciet `stale` worden gebruikt. Daarna
worden snelheid tussen dood- en springtij en stroomvectoren tussen de omliggende
uurvakken geïnterpoleerd. Vectorinterpolatie voorkomt fouten rond 0/360 graden.
Het eindresultaat wordt persistent in `current_calculations` opgeslagen.

De brondata staat als tekst in Git. Bij processtart wordt zij idempotent naar
SQLite geïmporteerd. Het SQLite-bestand staat in een Docker-volume en is een
runtimeartefact, geen versiebron.

## Operationele keuzes

- Eén FastAPI/Uvicorn-proces is voldoende; SQLite deelt cachedata over herstarts.
- CORS staat open zodat meerdere browserapps op het LAN de API kunnen lezen.
- Alleen `GET` is toegestaan via CORS.
- Er is nog geen authenticatie, rate limiting of applicatielogging.
- Uvicorn-accesslogging is uitgeschakeld.
- Docker bewaart alleen begrensde fout-/procesoutput: 3 bestanden van 5 MB.
- `restart: unless-stopped` en `/ready` ondersteunen automatisch herstel.
