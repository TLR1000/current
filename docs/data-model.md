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

HW-tijden worden niet blijvend opgeslagen. De huidige procescache is tijdelijk
en wordt bij een containerherstart geleegd. Zie de roadmap voor persistente en
gedeelde caching.
