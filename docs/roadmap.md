# Roadmap

## Gereed

- Persistente RWS-cache per station en datum, inclusief `stale-if-error`.
- Persistente operationele resultaatcache per diamant en vijfminutenvak.
- Cacheomvang en tijdsbereik op `/health`, zonder request- of persoonslogging.

## Eerstvolgend

- Retentiebeleid voor oude operationele tijdvakken, met behoud van relevante
  racedata en een expliciete beheeropdracht voor opruimen.
- Optionele cachewarming voor een racedatum en selectie van diamanten.
- Contracttests vanuit TrackSense zodra de eerste integratie gereed is.
- Validatie van berekeningen tegen onafhankelijke stroomwaarnemingen.

## Daarna

- Ruimtelijke vectorinterpolatie tussen meerdere geschikte atlaspunten; de
  huidige methode kiest bewust alleen het dichtstbijzijnde punt.
- Meer vaargebieden, diamanten en referentiehavens via hetzelfde importschema.
- Batchendpoint voor FleetSense-routepunten en tijdreeksen om honderden losse
  HTTP-calls te voorkomen en cachewarming in één request mogelijk te maken.
- ETags en HTTP-cacheheaders voor bronnen- en coverage-endpoints.
- Expliciete providerstatus en circuit breaker voor externe bronnen.
- Versiebeleid en deprecatieheaders voor een toekomstige `/v2`.

## Beveiliging en beheer

Wanneer de service buiten de beperkte vertrouwde kring beschikbaar wordt:

- authenticatie of netwerktoegangscontrole;
- rate limiting en requestlimieten;
- gestructureerde, privacybewuste operationele logging;
- dashboards en alerts op beschikbaarheid/upstreamfouten;
- TLS via reverse proxy of een private tunnel;
- dependency- en container-scanning in CI.
