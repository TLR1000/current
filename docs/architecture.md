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

Per request wordt het relevante officiële HW van de bij het atlaspunt horende
referentiehaven opgehaald. Deze astronomische RWS-extremen worden zes uur in het
procesgeheugen gecachet. Daarna worden eerst snelheid tussen dood- en springtij
en vervolgens stroomvectoren tussen de omliggende uurvakken geïnterpoleerd.
Vectorinterpolatie voorkomt fouten rond 0/360 graden.

De brondata staat als tekst in Git. Bij processtart wordt zij idempotent naar
SQLite geïmporteerd. Het SQLite-bestand staat in een Docker-volume en is een
runtimeartefact, geen versiebron.

## Operationele keuzes

- Eén FastAPI/Uvicorn-proces is voldoende voor het huidige gebied en verkeer.
- CORS staat open zodat meerdere browserapps op het LAN de API kunnen lezen.
- Alleen `GET` is toegestaan via CORS.
- Er is nog geen authenticatie, rate limiting of applicatielogging.
- Uvicorn-accesslogging is uitgeschakeld.
- Docker bewaart alleen begrensde fout-/procesoutput: 3 bestanden van 5 MB.
- `restart: unless-stopped` en `/ready` ondersteunen automatisch herstel.
