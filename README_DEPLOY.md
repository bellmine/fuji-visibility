# Deploying the Phase 3 dashboard

This project ships a small FastAPI dashboard and a separate scheduled snapshot
worker. Both containers use the same image and the same bind-mounted `data/`
directory. The web process reads stored snapshots; only the refresh endpoint and
worker call Open-Meteo.

## VPS prerequisites

- Docker Engine and the Docker Compose plugin
- the existing external Docker network `npm_default`
- an Nginx Proxy Manager instance already attached to `npm_default`
- a checked-out copy of this repository

The compose file intentionally publishes no host port. The dashboard listens on
container port `8000` and is reachable by NPM as `http://fuji-dashboard:8000`.

## First deployment

From the repository directory:

```bash
docker network inspect npm_default >/dev/null
cp .env.example .env
chmod 600 .env
mkdir -p data
# Set FUJI_CONTAINER_UID/GID in .env to the owner of data/ (id -u / id -g).
docker compose -f docker-compose.dashboard.yml config
docker compose -f docker-compose.dashboard.yml up -d --build
docker compose -f docker-compose.dashboard.yml ps
```

The first scheduled worker cycle runs immediately after the worker starts, then
repeats every three hours. A manual dashboard refresh is protected by the
shared `/app/data/refresh.lock` file and the five-minute cooldown in `.env`.

Check the application from inside its container or from another container on
`npm_default`:

```bash
docker exec fuji-dashboard python -c \
  "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health').read().decode())"
docker logs --tail=100 fuji-snapshot-worker
```

The first snapshot may take a little while because each configured model is
requested independently. Partial model failure is recorded and does not stop
the next worker cycle.

## Nginx Proxy Manager

Create or update a Proxy Host manually in NPM:

| Field | Value |
| --- | --- |
| Domain Names | `fuji.wangdi.store` |
| Scheme | `http` |
| Forward Hostname / IP | `fuji-dashboard` |
| Forward Port | `8000` |
| Websockets Support | enabled if needed by the NPM template |

Request a certificate for `fuji.wangdi.store` in the SSL tab and enable the
desired access list/authentication there. This repository does not modify the
existing NPM compose file, container, or proxy database.

After saving the Proxy Host, verify both the public page and the internal
health endpoint. Do not use a container IP as the upstream; Docker DNS for
`fuji-dashboard` is stable across restarts while container IPs are not.

## Updates and rollback

Before an update, back up the persistent data directory. The SQLite database
uses WAL mode, so stop both services first if taking a simple file copy:

```bash
docker compose -f docker-compose.dashboard.yml stop
cp -a data "data.backup.$(date +%Y%m%d-%H%M%S)"
docker compose -f docker-compose.dashboard.yml up -d --build
```

To update from GitHub:

```bash
git pull --ff-only
docker compose -f docker-compose.dashboard.yml up -d --build
docker compose -f docker-compose.dashboard.yml ps
```

If a new image is unhealthy, inspect `docker compose ... logs`, then restore the
previous Git revision and rebuild. Never delete `data/` during an application
rollback; it contains the forecast history and raw responses used by the
dashboard.

## Configuration and privacy

Keep `.env` out of Git. It contains deployment choices and may later contain
private settings. The dashboard is intended to remain private behind NPM's
access controls or an equivalent network restriction. No API key is required
for the current Open-Meteo endpoints, and no credentials belong in this repo.

Useful overrides include `FUJI_MODELS`, `FUJI_DEFAULT_LOCATION`,
`FUJI_UPCOMING_DAYS`, `FUJI_RAW_RETENTION_DAYS`, and
`FUJI_MANUAL_REFRESH_COOLDOWN_SECONDS`. The dashboard common-hours selector
defaults to `08:00–17:00`; set `FUJI_DEFAULT_START_HOUR` and
`FUJI_DEFAULT_END_HOUR` to change that presentation default. Phase 3.1 decision
thresholds can be tuned with `FUJI_MIN_PROXY`, `FUJI_MIN_FULL_PROXY_MODELS`, the two
`FUJI_MAX_PROXY_SPREAD_*` values, and the `FUJI_GOOD_*` field thresholds. The
paths in the compose file are
forced to `/app/data` so the dashboard and worker always share one database and
one lock file.

If the host uses a different non-root ownership policy, keep the directory
writable by the configured non-root `FUJI_CONTAINER_UID/GID` (the Compose
defaults are 1001:1001 and are intended to be adjusted per host). Do not solve
this by publishing port 8000 or by storing the database inside the ephemeral
container filesystem.
