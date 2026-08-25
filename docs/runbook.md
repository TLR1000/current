# Deploy- en beheerrunbook — shoebox

## Uitgangspunten

- Repository: `https://github.com/TLR1000/current`
- Deploybranch: `main`
- Host: `jeroen@192.168.178.241`
- Installatiemap: `/home/jeroen/current`
- LAN-poort: `8002`
- Container: `current-api`
- Docker Compose beheert build, herstart en healthcheck.

## Eerste installatie

```bash
ssh jeroen@192.168.178.241
git clone https://github.com/TLR1000/current.git ~/current
cd ~/current
docker compose up -d --build
docker compose ps
curl -fsS http://localhost:8002/ready
```

De service heeft geen secrets of `.env` nodig. Het named volume
`current-data` bevat de gegenereerde dataset, RWS-HW-cache en operationele
vijfminutenresultaten. Verwijder dit volume niet bij een gewone deployment.

De standaard ruimtelijke configuratie gebruikt maximaal vier punten en IDW².
Deze is in Compose zichtbaar als `CURRENT_SPATIAL_POINT_COUNT=4` en
`CURRENT_SPATIAL_POWER=2`. Wijzig deze waarden alleen samen met validatietests;
een wijziging verandert alle ruimtelijk afgeleide resultaten.

## Nieuwe versie deployen

Lokaal:

```powershell
git status --short
python -m pytest -q
git add .
git commit -m "Beschrijving"
git push origin main
```

Op de shoebox:

```bash
cd ~/current
git pull --ff-only
docker compose up -d --build
docker image prune -f
```

## Verificatie

```bash
cd ~/current
docker compose ps
curl -fsS http://localhost:8002/
curl -fsS http://localhost:8002/ready
curl -fsS http://localhost:8002/health
curl -fsS 'http://localhost:8002/v1/sources'
curl -fsS 'http://localhost:8002/v1/coverage?source=diamonds'
curl -fsS 'http://localhost:8002/v1/current?source=diamonds&lat=51.9&lon=3.8&time=2026-08-25T12:00:00Z'
```

Vanaf het LAN hoort `http://192.168.178.241:8002` dezelfde landing te tonen.

## Automatisch starten na reboot

Docker is op de shoebox al als systemd-service actief. De container gebruikt
`restart: unless-stopped` en start daardoor na een normale hostreboot opnieuw.

```bash
systemctl is-enabled docker
systemctl is-active docker
docker compose -f ~/current/docker-compose.yml ps
curl -fsS http://localhost:8002/ready
```

## Diagnose

```bash
cd ~/current
docker compose ps
docker compose logs --tail=200 api
docker inspect --format '{{json .State.Health}}' current-api
ss -ltnp | grep ':8002'
```

Accessrequests worden bewust niet gelogd. Alleen start-, fout- en crashoutput
kan in de begrensde Dockerlogs staan.

`/health` toont onder `calculationCache` het aantal operationele rijen en het
eerste/laatste tijdvak. Een groeiend aantal is normaal wanneer nieuwe race- of
planningsdata wordt bevraagd.

## Herstart en herstel

```bash
cd ~/current
docker compose restart api
curl -fsS http://localhost:8002/ready
```

Wanneer het volume beschadigd blijkt, maak eerst een kopie en bouw het daarna
opnieuw op uit de Git-brondata:

```bash
cd ~/current
docker compose down
docker volume inspect current_current-data
docker run --rm -v current_current-data:/data -v "$PWD:/backup" alpine \
  cp /data/current.sqlite3 /backup/current.sqlite3.backup
docker volume rm current_current-data
docker compose up -d --build
```

## Rollback

```bash
cd ~/current
git log --oneline -n 5
git checkout <vorige-commit>
docker compose up -d --build
```

Na herstel terug naar de deploybranch:

```bash
git checkout main
git pull --ff-only
```
