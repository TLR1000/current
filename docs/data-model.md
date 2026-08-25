# Datamodel

## Versiebron

`data/diamonds.txt` is de menselijke en Git-versiebeheerde bron. Iedere locatie
bevat coördinaten, een referentiehaven en dertien tabellen van `HW−6` tot
`HW+6`, met richting en snelheid bij spring- en doodtij. Locatie 13 mist
coördinaten en wordt gecontroleerd overgeslagen; de runtime bevat 12 punten.

## SQLite

Bij opstart worden vier tabellen opgebouwd:

- `reference_ports` — code en naam van de HW-referentiehaven;
- `diamond_sources` — gebied, bronpad, SHA-256 en importtijd;
- `diamond_points` — nummer, WGS84-positie en referentiehaven;
- `diamond_hourly_rates` — uur t.o.v. HW, richting, spring- en doodtijsnelheid.

Iedere geldige diamant moet exact dertien unieke uurregels hebben. Een nieuwe
bronhash vormt een nieuwe herleidbare dataset; de nieuwste geïmporteerde dataset
is actief.

## Operationele gegevens

`rws_high_water_cache` bewaart gevalideerde HW-extremen per RWS-station en
UTC-kalenderdag. Naast de tijden wordt `fetched_at` opgeslagen voor freshness en
`stale-if-error`.

`current_calculations` bewaart het berekende resultaat per:

- provider;
- intern diamantpunt;
- SHA-256 van de atlasversie;
- UTC-vijfminutenvak.

De atlas-hash voorkomt dat resultaten van een oude dataset na een datawijziging
worden hergebruikt. De cache is on-demand: er worden alleen rijen aangemaakt
voor daadwerkelijk opgevraagde race- of actuele tijdvakken. Bij 12 diamanten
zijn maximaal 3.456 rijen per volledig bevraagde dag nodig.
