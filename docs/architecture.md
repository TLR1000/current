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
De rechthoek in `/v1/coverage` beschrijft uitsluitend de puntligging. Effectieve
dekking is de unie van de 15-km-zones rond punten en kan daarom buiten die
rechthoek doorlopen. `/v1/coverage/check` past exact dezelfde selectieregel toe
als de rekenroute.

Requests worden naar het dichtstbijzijnde vijfminutenvak genormaliseerd. De
operationele cachesleutel bestaat uit provider, atlasversie, diamant en tijdvak;
de aangevraagde coördinaten zijn bewust geen onderdeel. SailSense-polls,
TrackSense-planning en FleetSense-tijdreeksen delen daardoor berekeningen zodra
zij bij dezelfde diamant uitkomen.

Voor ruimtelijke afleiding worden maximaal vier punten binnen 15 km geselecteerd.
Hun gewichten zijn omgekeerd evenredig met het kwadraat van de afstand. Ieder
punt wordt eerst zelfstandig voor zijn eigen referentiehaven en HW berekend of
uit de operationele cache gelezen. Daarna worden uitsluitend de `u/v`-vectoren
gewogen gecombineerd. Richting en snelheid worden pas uit de samengestelde
vector afgeleid. Binnen één meter van een diamant wint het bronpunt volledig,
zodat een bekende atlaswaarde niet wordt gladgestreken.

Bij een cachemiss wordt het relevante officiële HW van de referentiehaven
opgehaald. De RWS-extremen worden per station en kalenderdag persistent in
SQLite opgeslagen en dertig dagen vers gehouden. Bij een tijdelijke storing
mag een ouder gevalideerd record als expliciet `stale` worden gebruikt. Daarna
worden snelheid tussen dood- en springtij en stroomvectoren tussen de omliggende
uurvakken geïnterpoleerd. Vectorinterpolatie voorkomt fouten rond 0/360 graden.
Het eindresultaat wordt persistent in `current_calculations` opgeslagen.

De tijdsbron is astronomisch en heeft geen modelrun of forecast-horizon. Het
contract retourneert deze velden expliciet als niet van toepassing en houdt
`validAt` (rekenvak) gescheiden van `generatedAt` (cachemoment).

De brondata staat als tekst in Git. Bij processtart wordt zij idempotent naar
SQLite geïmporteerd. Het SQLite-bestand staat in een Docker-volume en is een
runtimeartefact, geen versiebron.

## Operationele keuzes

- Eén FastAPI/Uvicorn-proces is voldoende; SQLite deelt cachedata over herstarts.
- CORS staat open zodat meerdere browserapps op het LAN de API kunnen lezen.
- Alleen `GET` en de batch-`POST` zijn toegestaan via CORS.
- Er is nog geen authenticatie, rate limiting of applicatielogging.
- Uvicorn-accesslogging is uitgeschakeld.
- Docker bewaart alleen begrensde fout-/procesoutput: 3 bestanden van 5 MB.
- `restart: unless-stopped` en `/ready` ondersteunen automatisch herstel.

## Batchverwerking

De batchroute gebruikt exact hetzelfde rekenpad als de enkelvoudige route en
verwerkt maximaal 100 items in invoervolgorde. Daardoor blijven resultaten en
provenance identiek en werkt de operationele cache ook tussen items binnen
dezelfde request. Een mislukking wordt per item geïsoleerd. De limiet begrenst
CPU-tijd, upstreamwerk en responsegrootte voor het enkele Uvicorn-proces.
