# Roadmap

## Eerstvolgend

- Persistente RWS-cache in SQLite, per station en datum, zodat herstarts geen
  nieuwe upstreamcall veroorzaken en historisch plannen offline kan werken.
- `stale-if-error`: bij een tijdelijke RWS-storing een eerder gevalideerd HW
  retourneren met expliciete stale-markering.
- Cachemetriek op `/health` zonder request- of persoonslogging.
- Contracttests vanuit TrackSense zodra de eerste integratie gereed is.
- Validatie van berekeningen tegen onafhankelijke stroomwaarnemingen.

## Daarna

- Ruimtelijke vectorinterpolatie tussen meerdere geschikte atlaspunten; de
  huidige methode kiest bewust alleen het dichtstbijzijnde punt.
- Meer vaargebieden, diamanten en referentiehavens via hetzelfde importschema.
- Batchendpoint voor routepunten en tijdreeksen om honderden losse calls te
  voorkomen.
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
