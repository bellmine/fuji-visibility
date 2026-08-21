# Fuji Visibility Tool — Phase 3 Web Dashboard Implementation Plan

## 0. Objective

Phase 1 and Phase 2 are complete and working.

The next step is to remove the operational friction of:

```text
SSH into VPS
cd into project
run CLI commands
read terminal output
```

Phase 3 adds a lightweight, private web dashboard at:

```text
https://fuji.wangdi.store
```

The dashboard is a **presentation and control layer** over the existing Fuji Visibility codebase.

It must **not** reimplement:

- Open-Meteo fetching logic
- Fuji Proxy Score
- consensus calculation
- forecast stability logic
- decision logic
- SQLite persistence
- model capability handling

The CLI and the web dashboard must call the **same Python service/domain functions** so that:

```text
CLI result == Web result
```

for identical inputs and stored data.

---

# 1. Verified VPS Environment

The target VPS was inspected before writing this specification.

Verified on 2026-08-21:

```text
Nginx Proxy Manager container:
    npm-npm-1

Image:
    jc21/nginx-proxy-manager:latest

NPM build:
    2.14.0

Status:
    running

Published ports:
    80
    81
    443

Docker network:
    npm_default

NPM compose file:
    /home/ubuntu/npm/docker-compose.yml

Architecture:
    arm64
```

The existing NPM compose configuration uses:

```yaml
networks:
  npm_default:
    external: true
```

Therefore the Fuji dashboard should join the existing external Docker network:

```text
npm_default
```

NPM should reverse-proxy to the dashboard using Docker DNS:

```text
http://fuji-dashboard:8000
```

Do **not** use the current NPM container IP as a dependency. Container IP addresses are not stable.

Current VPS resource snapshot:

```text
RAM:
    11 GiB total
    ~2.3 GiB available

Swap:
    none

Disk:
    ~52 GiB available

System already hosts multiple Docker services.
```

Therefore Phase 3 should remain lightweight:

- one Uvicorn worker
- no React runtime
- no Node server
- no frontend build system unless absolutely necessary
- no additional database
- no Redis
- no Celery
- no Kubernetes
- no heavyweight observability stack

---

# 2. Target Architecture

Use:

```text
Browser
   |
   | HTTPS
   v
fuji.wangdi.store
   |
   v
Nginx Proxy Manager
   |
   | Docker network: npm_default
   v
fuji-dashboard:8000
   |
   +--> existing decision.py
   +--> existing consensus.py
   +--> existing stability.py
   +--> existing scoring.py
   +--> existing storage.py
   |
   v
SQLite + raw forecast data
```

Automatic forecast collection:

```text
Open-Meteo
   |
   v
fuji-snapshot-worker
   |
   v
shared /app/data
   |
   +--> SQLite
   +--> raw JSON
```

Both services should use the same project image:

```text
fuji-dashboard
fuji-snapshot-worker
```

and the same persistent bind-mounted data directory.

---

# 3. Technology Stack

Backend:

```text
FastAPI
Uvicorn
Jinja2
```

Frontend:

```text
server-rendered HTML
plain CSS
minimal vanilla JavaScript
inline SVG for simple trend charts
```

Do not use:

```text
React
Vue
Next.js
Nuxt
Node.js application server
Tailwind build pipeline
Webpack
Vite
```

A tiny browser-side JavaScript file is acceptable.

The dashboard should be fully usable without a JavaScript framework.

---

# 4. Project Structure

Add a web package without disrupting the existing CLI layout.

Suggested structure:

```text
src/
└── fuji_visibility/
    ├── cli.py
    ├── open_meteo.py
    ├── storage.py
    ├── scoring.py
    ├── fingerprint.py
    ├── consensus.py
    ├── stability.py
    ├── decision.py
    ├── services.py
    ├── snapshot_worker.py
    └── web/
        ├── __init__.py
        ├── app.py
        ├── routes.py
        ├── schemas.py
        ├── viewmodels.py
        ├── templates/
        │   ├── base.html
        │   ├── dashboard.html
        │   ├── diagnostics.html
        │   └── error.html
        └── static/
            ├── app.css
            └── app.js

Dockerfile
docker-compose.dashboard.yml
.env.example
```

If Phase 1/2 already expose clean service functions, `services.py` may not be necessary.

Do not add an artificial service layer merely for naming consistency.

The real requirement is:

```text
CLI and web routes share the same business functions.
```

---

# 5. Refactoring Rule

Before adding routes, inspect the current CLI.

If `cli.py` contains actual business logic such as:

```text
fetch forecast
write snapshot
compute consensus
compute decision
query trend
```

move that logic into reusable Python functions.

CLI commands should become thin adapters:

```python
def decide_command(...):
    result = decide_service(...)
    render_terminal(result)
```

Web routes should call the same function:

```python
def decision_api(...):
    result = decide_service(...)
    return result
```

Do not have web handlers call CLI commands through:

```python
subprocess
os.system
shell strings
```

Do not duplicate scoring / consensus / decision code inside the web package.

---

# 6. Dashboard UX Goal

The first screen should answer this question within a few seconds:

> Which upcoming reachable window currently looks best, and how trustworthy is that forecast?

The user should not need to understand every weather variable before seeing the decision state.

The page should progressively reveal technical detail.

Order:

1. data freshness
2. current decision
3. upcoming-day overview
4. reachable hourly forecast
5. model consensus
6. forecast drift
7. model diagnostics

---

# 7. Homepage

Route:

```text
GET /
```

Primary page title:

```text
Mt. Fuji Visibility
```

Suggested top section:

```text
Mt. Fuji Visibility

Last forecast snapshot:
2026-08-21 08:30 JST

Location:
Kawaguchiko

Reachable after:
08:00 JST

[ Refresh forecast ]
```

If the snapshot is old:

```text
Forecast data is 6h 12m old
```

visually mark it as stale.

Suggested thresholds:

```text
fresh:
    <= 4 hours

warning:
    > 4 hours

stale:
    > 8 hours
```

Keep thresholds configurable.

---

# 8. Decision Card

The most prominent card should use the existing Phase 2 `decide` result.

Example:

```text
RECOMMENDED

WED AUG 26

Best reachable window
08:00–10:00

Peak
09:00

Proxy median       86
Model consensus    HIGH
Stability          HIGH
Trend              IMPROVING
```

Then:

```text
Why Wednesday wins

- longer reachable window
- stronger multi-model agreement
- stable recent forecast
- low mid-level cloud
```

This explanation must come from structured decision evidence.

Do not generate vague text based only on the winning date.

---

# 9. No-Decision States

The dashboard must correctly display strict Phase 2 outcomes.

Current live Phase 2 behavior found only:

```text
2 full models
```

because some JMA / ECMWF forecasts lacked required fields.

Therefore the UI must support:

```text
NO QUALIFYING WINDOW
```

and:

```text
NO CLEAR WINNER
```

Example:

```text
NO QUALIFYING WINDOW

Only 2 full forecast models are currently available.

Minimum required:
3 full models

Partial model data is shown below,
but it is not being treated as full consensus.
```

Do not weaken the decision threshold merely to make the dashboard look more decisive.

---

# 10. Upcoming Days Overview

Show the next configurable number of days.

Default:

```text
7 days
```

Example:

```text
Day       Best reachable   Proxy   Consensus   Stability   Trend
Sat 22    none             --      LOW         --          --
Sun 23    08–09            61      MEDIUM      LOW         VOLATILE
Mon 24    08–10            72      MEDIUM      MEDIUM      IMPROVING
Tue 25    08–09            80      HIGH        MEDIUM      STABLE
Wed 26    08–10            86      HIGH        HIGH        IMPROVING
Thu 27    08–11            75      MEDIUM      HIGH        STABLE
```

Use the same reachability rule as Phase 2.

Hours before the configured arrival cutoff must never determine the displayed best window.

---

# 11. Date Selection

The page should not hard-code:

```text
2026-08-25
2026-08-26
```

Those dates are useful for current integration testing only.

The dashboard should show the upcoming forecast period automatically.

Allow the user to select one or more days for detailed comparison.

Recommended implementation:

```text
date chips / checkboxes
```

Store client preference in:

```text
URL query parameters
or
localStorage
```

Do not create an account/profile database for this.

---

# 12. Default Trip Settings

Server defaults:

```text
location:
    kawaguchiko

hours:
    05:00–12:00

arrival_after:
    08:00

timezone:
    Asia/Tokyo

models:
    all configured consensus models
```

Expose a small settings area where the user can temporarily change:

```text
arrival_after
hours
candidate dates
location preset
```

Initial location presets can reuse existing Phase 1 config:

```text
kawaguchiko
oishi
shojiko
```

Do not duplicate preset coordinates in web code.

---

# 13. Hourly Forecast Grid

For selected days, render reachable and unreachable hours.

Example:

```text
WED AUG 26

Time   Reach   Proxy   Mid Cloud   Vis   Rain   Consensus
05:00    no      91        3%      46km   0%      HIGH
06:00    no      94        2%      48km   0%      HIGH
07:00    no      90        4%      45km   0%      HIGH
08:00   yes      84       10%      37km   5%      HIGH
09:00   yes      87        5%      42km   5%      HIGH
10:00   yes      82       14%      35km  10%      MEDIUM
11:00   yes      68       31%      24km  20%      LOW
```

Unreachable rows may be visually muted but remain visible for context.

They must never contribute to recommendation ranking.

---

# 14. Responsive Mobile Design

The primary usage is likely a phone browser.

Requirements:

- no horizontal page overflow at ~360 px width
- decision card visible near the top
- tables may become stacked cards on mobile
- tap targets at least ~40 px
- timestamps always include JST
- technical diagnostics collapsed by default

For hourly data, on narrow screens prefer:

```text
08:00
Proxy 84
Mid 10%
Vis 37 km
Consensus HIGH
```

over a 10-column horizontal table.

Desktop may use the full table.

---

# 15. Forecast Drift Visualization

This is one of the highest-value parts of the dashboard.

For a selected valid hour, show how successive stored forecasts changed.

Example:

```text
WED AUG 26 — 09:00

Proxy median

Aug 21 00:00  72
Aug 21 03:00  77
Aug 21 06:00  83
Aug 21 09:00  86

Trend:
IMPROVING

Stability:
HIGH
```

Add a lightweight trend plot.

Preferred implementation:

```text
inline SVG
```

Do not add a heavy chart framework only for one small line chart.

If a small no-build chart library is already present in the project, reuse it.

Otherwise inline SVG is enough.

---

# 16. Drift Variables

Allow switching the drift plot between:

```text
Proxy median
Mid-level cloud median
Visibility median
```

Optional:

```text
Precipitation probability
```

The visual purpose is to distinguish:

```text
87 after four stable/improving model cycles
```

from:

```text
87 after oscillating between 50 and 90
```

---

# 17. Model Consensus Section

Show a compact summary:

```text
09:00

Full models:
2 / 6

Proxy median:
87

Consensus:
INSUFFICIENT_DATA
```

Then list threshold votes when available:

```text
Good proxy:
2 / 2

Good mid-cloud:
5 / 6

Good visibility:
2 / 2
```

The distinction between:

```text
full model
partial model
```

must remain visible.

---

# 18. Model Diagnostics

Collapsed by default.

Example:

```text
Model            Status     Proxy   Mid Cloud   Visibility   Missing
auto             FULL        87       5%          42 km       -
gfs_seamless     FULL        83       8%          36 km       -
jma_seamless     PARTIAL     --      11%          --          rain, visibility
jma_msm          PARTIAL     --       9%          --          rain, visibility
jma_gsm          PARTIAL     --      16%          --          rain, visibility
ecmwf_ifs025     PARTIAL     --       7%          --          visibility
```

Outliers should be marked.

Do not hide failed models.

---

# 19. Data Freshness

Add a prominent freshness state.

Example:

```text
Last successful snapshot:
08:31 JST

Age:
2h 07m

Status:
FRESH
```

If the latest scheduled refresh failed:

```text
Last successful snapshot:
05:30 JST

Latest refresh attempt:
08:30 JST

Result:
FAILED — Open-Meteo timeout
```

The dashboard should still render old stored data.

A failed weather API request must not make the dashboard unavailable.

---

# 20. Manual Refresh

Button:

```text
Refresh forecast
```

Endpoint:

```text
POST /api/refresh
```

Behavior:

1. acquire refresh lock
2. fetch configured models
3. save snapshots
4. release lock
5. update dashboard status

Do not execute shell commands.

Call the existing Python snapshot service directly.

---

# 21. Refresh Concurrency Protection

The automatic worker and manual button can race.

Use a simple process-independent lock.

Recommended on Linux:

```text
fcntl.flock
```

Lock file:

```text
/app/data/refresh.lock
```

Behavior:

If another refresh is running:

```text
HTTP 409
```

JSON:

```json
{
  "status": "busy",
  "message": "A forecast refresh is already running."
}
```

The UI should show:

```text
Refresh already in progress
```

Do not start two simultaneous multi-model fetch jobs.

---

# 22. Refresh Cooldown

Add configurable minimum manual refresh interval.

Default:

```text
5 minutes
```

If the user manually refreshes again too soon:

```text
HTTP 429
```

Show:

```text
Forecast was refreshed 2 minutes ago.
Try again in 3 minutes.
```

This protects Open-Meteo and avoids accidental repeated clicks.

Scheduled collection is unaffected.

---

# 23. Refresh Execution Model

Do not require a task queue.

Options:

```text
FastAPI BackgroundTasks
```

or:

```text
a small in-process task
```

are sufficient because:

- Uvicorn runs one worker
- a file lock prevents collision
- refresh jobs are short-lived
- there is no need for distributed processing

If reliable job state becomes complicated, a synchronous POST with a loading state is acceptable.

Do not add Celery/Redis.

---

# 24. Automatic Snapshot Worker

Add:

```text
fuji-snapshot-worker
```

as a second Docker service using the same image.

Purpose:

```text
collect forecast snapshots automatically
```

Default interval:

```text
3 hours
```

The worker should run an immediate snapshot on startup, then sleep until the next interval.

Implement as Python, not a shell loop if practical.

Example module:

```text
python -m fuji_visibility.snapshot_worker
```

Behavior:

```text
startup
  -> acquire refresh lock
  -> snapshot --models all
  -> release lock
  -> sleep
  -> repeat
```

If the API call fails:

```text
log error
wait until next scheduled cycle
continue running
```

Do not crash-loop because Open-Meteo is temporarily unavailable.

---

# 25. SQLite Concurrency

Web reads and worker writes will occur concurrently.

Ensure SQLite is configured for:

```text
WAL mode
```

and a reasonable busy timeout.

Example:

```sql
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;
```

Keep write transactions short.

Do not hold a SQLite write transaction during network requests.

Correct order:

```text
fetch remote data
normalize
open transaction
write snapshot
commit
```

Not:

```text
open transaction
fetch Open-Meteo
wait
write
commit
```

Existing Phase 1/2 database history must remain usable.

---

# 26. API Endpoints

Minimum API:

```text
GET  /health
GET  /api/status
GET  /api/days
GET  /api/forecast
GET  /api/consensus
GET  /api/trend
GET  /api/decision
POST /api/refresh
```

These endpoints are for the dashboard itself and debugging.

Do not treat this as a public API product.

---

# 27. `GET /health`

Must be cheap and must not call Open-Meteo.

Example:

```json
{
  "status": "ok",
  "database": "ok",
  "last_snapshot": "2026-08-21T08:31:00+09:00"
}
```

If database access fails:

```text
HTTP 503
```

The Docker healthcheck should call this endpoint.

---

# 28. `GET /api/status`

Example:

```json
{
  "timezone": "Asia/Tokyo",
  "location": "kawaguchiko",
  "arrival_after": "08:00",
  "last_successful_snapshot": "...",
  "last_refresh_attempt": "...",
  "last_refresh_status": "success",
  "full_models": 2,
  "configured_models": 6,
  "data_age_seconds": 7200
}
```

---

# 29. `GET /api/decision`

Inputs:

```text
dates
arrival_after
hours
location
```

Example:

```text
/api/decision?dates=2026-08-25,2026-08-26&arrival_after=08:00
```

Return the existing structured Phase 2 decision object.

If current code only produces terminal text, refactor it so the domain function returns structured data and the CLI formatter renders text separately.

---

# 30. Error Handling in Web UI

Never display a Python traceback to the browser.

User-facing errors should look like:

```text
Forecast data could not be loaded.

Stored data is still available.
```

Technical details belong in logs.

For API endpoints return structured JSON:

```json
{
  "error": "insufficient_data",
  "message": "Only 2 full models are available."
}
```

---

# 31. Logging

Use normal Python logging.

Log:

```text
dashboard start
snapshot worker start
manual refresh
scheduled refresh
refresh duration
model success/failure
database write result
decision request errors
```

Do not log:

```text
Basic Auth credentials
cookies
authorization headers
```

NPM handles authentication outside the application.

---

# 32. Authentication and Exposure

The dashboard should not implement its own login system.

Use Nginx Proxy Manager.

Recommended:

```text
NPM Access List
```

with Basic Auth for this private dashboard.

The application itself should assume it is behind a trusted reverse proxy.

Do not expose the dashboard container directly to the public internet.

---

# 33. Docker Networking

The dashboard container must join:

```text
npm_default
```

which already exists as an external Docker network.

Compose:

```yaml
networks:
  npm_default:
    external: true
```

The dashboard service should use:

```yaml
networks:
  - npm_default
```

NPM will resolve:

```text
fuji-dashboard
```

through Docker DNS.

Do not forward to a hard-coded container IP.

---

# 34. No Host Port Publication

For the dashboard:

Use:

```yaml
expose:
  - "8000"
```

Do not use:

```yaml
ports:
  - "8000:8000"
```

unless a temporary local debugging reason is explicitly documented.

The expected production path is:

```text
Internet
-> NPM 443
-> npm_default
-> fuji-dashboard:8000
```

---

# 35. Docker Compose

Create:

```text
docker-compose.dashboard.yml
```

Conceptual structure:

```yaml
services:
  fuji-dashboard:
    build: .
    container_name: fuji-dashboard
    restart: unless-stopped
    command:
      - uvicorn
      - fuji_visibility.web.app:app
      - --host
      - 0.0.0.0
      - --port
      - "8000"
      - --workers
      - "1"
    expose:
      - "8000"
    env_file:
      - .env
    volumes:
      - ./data:/app/data
    networks:
      - npm_default
    healthcheck:
      ...

  fuji-snapshot-worker:
    build: .
    container_name: fuji-snapshot-worker
    restart: unless-stopped
    command:
      - python
      - -m
      - fuji_visibility.snapshot_worker
    env_file:
      - .env
    volumes:
      - ./data:/app/data
    networks:
      - npm_default

networks:
  npm_default:
    external: true
```

The exact compose syntax may be adjusted to fit the existing project.

---

# 36. Dockerfile

Requirements:

- compatible with arm64
- Python 3.12+
- small base image
- install project dependencies reproducibly
- no development dependencies in production
- run as a non-root application user if practical
- `/app/data` writable by application user

Recommended base:

```text
python:3.12-slim
```

Using `uv` inside the image is acceptable if the repository already uses it.

Do not introduce a Node image.

---

# 37. Persistent Data

Use a bind mount:

```text
./data:/app/data
```

Benefits:

- existing SQLite DB can be copied in
- raw JSON remains inspectable
- backups are easy
- container replacement does not lose forecast history

Expected layout:

```text
data/
├── fuji_forecasts.sqlite
├── raw/
└── refresh.lock
```

If the existing application uses different paths, expose them through environment variables rather than duplicating data.

---

# 38. Environment Configuration

Create `.env.example`.

Suggested settings:

```text
FUJI_TIMEZONE=Asia/Tokyo

FUJI_DEFAULT_LOCATION=kawaguchiko

FUJI_DEFAULT_START_HOUR=5
FUJI_DEFAULT_END_HOUR=12
FUJI_DEFAULT_ARRIVAL_AFTER=08:00

FUJI_SNAPSHOT_INTERVAL_HOURS=3
FUJI_MANUAL_REFRESH_COOLDOWN_SECONDS=300

FUJI_DB_PATH=/app/data/fuji_forecasts.sqlite
FUJI_RAW_DATA_DIR=/app/data/raw
FUJI_REFRESH_LOCK_PATH=/app/data/refresh.lock

FUJI_WEB_HOST=0.0.0.0
FUJI_WEB_PORT=8000

FUJI_UPCOMING_DAYS=7
```

Reuse Phase 1/2 model configuration rather than defining a second web-only model list.

---

# 39. Nginx Proxy Manager Configuration

Production hostname:

```text
fuji.wangdi.store
```

Before NPM setup, DNS must resolve this hostname to the VPS.

NPM Proxy Host:

```text
Domain Names:
    fuji.wangdi.store

Scheme:
    http

Forward Hostname / IP:
    fuji-dashboard

Forward Port:
    8000

Block Common Exploits:
    enabled

Websockets Support:
    disabled
```

No WebSocket support is required in Phase 3.

---

# 40. NPM SSL

Configure:

```text
Request a new SSL Certificate
Force SSL
HTTP/2 Support
```

Use Let's Encrypt through the existing NPM installation.

Expected final URL:

```text
https://fuji.wangdi.store
```

---

# 41. NPM Access List

Recommended for a private personal dashboard.

Create an NPM Access List and attach it to:

```text
fuji.wangdi.store
```

Do not store those credentials in the Fuji project repository.

Authentication should remain entirely in NPM.

---

# 42. Reverse Proxy Headers

FastAPI should behave correctly behind NPM.

Trust forwarded proxy headers only in the deployment context.

Ensure URLs generated by the application respect:

```text
X-Forwarded-Proto: https
Host: fuji.wangdi.store
```

Do not hard-code `http://localhost:8000` into templates or JavaScript.

Use relative URLs:

```text
/api/status
/api/refresh
```

---

# 43. Manual NPM Acceptance Test

After deploying the dashboard container, verify network connectivity before configuring the public domain.

From the NPM container/network, confirm:

```text
http://fuji-dashboard:8000/health
```

returns:

```json
{
  "status": "ok"
}
```

Then configure the NPM Proxy Host.

---

# 44. Dashboard Healthcheck

Docker healthcheck should test:

```text
http://127.0.0.1:8000/health
```

Do not require `curl` if it is not installed in the final image.

A Python stdlib healthcheck is acceptable.

Container status should become:

```text
healthy
```

---

# 45. Resource Constraints

Because the VPS currently has no swap and ~2.3 GiB available memory, keep runtime footprint low.

Requirements:

```text
Uvicorn workers:
    1

Database:
    existing SQLite

Frontend:
    server-rendered

Background worker:
    one lightweight Python process
```

Do not add:

```text
PostgreSQL
Redis
Node runtime
browser automation
```

for Phase 3.

---

# 46. Static Assets

Serve small CSS / JS assets directly from FastAPI.

No CDN dependency is required.

Advantages:

- dashboard remains self-contained
- no third-party script availability dependency
- easier Content Security Policy later

If using inline SVG charts, no chart library is needed.

---

# 47. Visual Design

Keep it functional rather than decorative.

Primary states should have clear visual hierarchy:

```text
RECOMMENDED
NO CLEAR WINNER
NO QUALIFYING WINDOW
STALE DATA
REFRESH FAILED
```

Do not rely only on color.

Always include text labels.

Examples:

```text
Consensus: HIGH
Stability: LOW
Trend: VOLATILE
```

---

# 48. Staleness and Decision Safety

If data is older than the configured stale threshold, the dashboard must not present a recommendation as if it were fresh.

Example:

```text
WEDNESDAY RECOMMENDED

Warning:
Forecast data is 9 hours old.
Refresh before making a travel decision.
```

Do not silently hide the age.

---

# 49. Refresh State Persistence

At minimum persist:

```text
last_refresh_attempt
last_refresh_success
last_refresh_error
```

This can be:

- a small metadata table in SQLite
- or an existing application metadata mechanism

Prefer SQLite so the state survives container restarts.

Do not create a second state database.

---

# 50. Automatic Cleanup

Raw Open-Meteo JSON can accumulate over time.

Add optional retention configuration:

```text
FUJI_RAW_RETENTION_DAYS=30
```

The snapshot worker may perform a lightweight daily cleanup.

Do not delete normalized SQLite forecast history by default.

Forecast drift history is valuable.

---

# 51. Diagnostics Page

Route:

```text
GET /diagnostics
```

Show:

```text
configured models
model capabilities
last model errors
database path
snapshot count
last successful snapshot
worker freshness
application version
```

Do not expose:

```text
environment secrets
NPM credentials
authorization headers
full system environment
```

This page remains behind NPM authentication.

---

# 52. Version Display

Show the application version in the footer or diagnostics page.

Example:

```text
Fuji Visibility v0.3.0
```

If Git commit SHA is available at build time, optionally show:

```text
v0.3.0 (abc1234)
```

This helps diagnose whether the VPS is running the expected build.

---

# 53. API JSON Contract

The page should consume structured JSON internally where useful.

Do not parse human CLI text in JavaScript.

For example:

```json
{
  "decision": "recommended",
  "date": "2026-08-26",
  "window": {
    "start": "08:00",
    "end": "10:00",
    "peak": "09:00"
  },
  "proxy_median": 86,
  "consensus": "HIGH",
  "stability": "HIGH",
  "trend": "IMPROVING"
}
```

Existing Phase 2 `decide --json` output should be reused where practical.

---

# 54. Server-Side Rendering vs API Fetch

Preferred pattern:

Initial request:

```text
GET /
```

server-renders enough data to display immediately.

JavaScript is used for:

```text
manual refresh
changing selected days
loading trend details
updating diagnostics
```

Do not make the entire initial page depend on multiple browser-side API calls.

---

# 55. Testing

Add offline tests for:

- homepage renders with stored fixture data
- recommendation state
- `NO CLEAR WINNER`
- `NO QUALIFYING WINDOW`
- stale-data warning
- partial-model diagnostics
- health endpoint
- status endpoint
- decision endpoint
- refresh cooldown
- refresh lock contention
- refresh API failure
- SQLite WAL compatibility
- arrival cutoff remains enforced in web view
- mobile-relevant template output contains required fields

Use FastAPI TestClient or equivalent.

No test should require NPM.

No normal unit test should require live Open-Meteo.

---

# 56. Integration Tests

Optional integration tests may cover:

```text
live Open-Meteo refresh
Docker healthcheck
```

Mark them separately.

Do not include the public production domain in tests that run by default.

---

# 57. Docker Deployment Validation

Before public NPM configuration, validate:

```text
docker compose -f docker-compose.dashboard.yml build
docker compose -f docker-compose.dashboard.yml up -d
```

Then verify:

```text
fuji-dashboard:
    running / healthy

fuji-snapshot-worker:
    running
```

Check that no host port `8000` is published.

---

# 58. Data Migration

If an existing Phase 1/2 SQLite database is available, use it.

Do not create a blank production database and discard forecast history.

Deployment documentation should explain how to place the existing data directory at:

```text
./data
```

before starting containers.

Schema migrations must remain backward-compatible.

---

# 59. Backup

Document a simple backup command for:

```text
data/fuji_forecasts.sqlite
```

Because WAL mode is enabled, use a safe SQLite backup method if backing up while services are running.

A brief README note is enough.

Do not build a backup subsystem in Phase 3.

---

# 60. Security Requirements

Production requirements:

- only NPM publishes 80/443
- dashboard does not publish 8000 on host
- NPM provides HTTPS
- NPM Access List recommended
- POST is required for refresh
- manual refresh uses cooldown
- no arbitrary command execution
- no shell interpolation
- no filesystem browser
- no environment dump endpoint
- no raw SQL endpoint
- no user-controlled model string passed unsafely into shell commands

This dashboard does not require a custom account system.

---

# 61. Phase 3 Non-Goals

Do not implement:

- public user registration
- password database
- OAuth
- multi-user profiles
- notifications
- PWA
- mobile native app
- React SPA
- map view
- route planning
- webcam computer vision
- mountain sightline physics
- pressure-level score tuning
- automatic leave-day booking
- automated NPM administration through code

Those can be separate future phases if useful.

---

# 62. Deployment Documentation

Add:

```text
README_DEPLOY.md
```

It should contain:

1. VPS prerequisites
2. Docker build
3. data directory setup
4. `.env` creation
5. `npm_default` network verification
6. compose startup
7. local Docker health test
8. NPM proxy host configuration
9. NPM SSL configuration
10. optional Access List configuration
11. final HTTPS validation
12. upgrade procedure
13. rollback procedure

Use:

```text
fuji.wangdi.store
```

as the production example throughout.

---

# 63. Upgrade Procedure

Document an upgrade flow such as:

```text
git pull
docker compose -f docker-compose.dashboard.yml build
docker compose -f docker-compose.dashboard.yml up -d
```

Existing bind-mounted data must survive.

After upgrade:

```text
check /health
check dashboard version
check latest snapshot
```

---

# 64. Rollback

At minimum document:

```text
git checkout previous known-good commit
rebuild dashboard image
restart compose
```

Database migrations introduced in Phase 3 must be backward-compatible enough not to make basic rollback impossible.

Avoid destructive migrations.

---

# 65. Current Model Availability Must Be Visible

Current Phase 2 live validation found configured models:

```text
auto
jma_seamless
jma_msm
jma_gsm
gfs_seamless
ecmwf_ifs025
```

At that check:

```text
JMA models:
    missing precipitation_probability and/or visibility

ECMWF:
    missing visibility

Only 2 models qualified as full models.
```

This condition may change with Open-Meteo.

The dashboard must use runtime capability checks and display current status.

Do not hard-code the above as permanent model facts.

---

# 66. Recommended Homepage Layout

Desktop concept:

```text
+------------------------------------------------------+
| Mt. Fuji Visibility             Updated 08:31 JST    |
| Kawaguchiko | Reachable 08:00+      [Refresh]        |
+------------------------------------------------------+

+------------------------------------------------------+
| CURRENT DECISION                                     |
|                                                      |
| WED AUG 26                                           |
| 08:00–10:00                                         |
| Peak 09:00                                          |
|                                                      |
| Proxy 86 | Consensus HIGH | Stability HIGH          |
| Trend IMPROVING                                     |
+------------------------------------------------------+

+------------------------------------------------------+
| NEXT 7 DAYS                                          |
| Sat | Sun | Mon | Tue | Wed | Thu | Fri              |
+------------------------------------------------------+

+------------------------------------------------------+
| HOURLY — WED AUG 26                                  |
| 08 | 09 | 10 | 11                                   |
| ...                                                  |
+------------------------------------------------------+

+--------------------------+---------------------------+
| FORECAST DRIFT           | MODEL CONSENSUS           |
| small SVG chart          | 2 full / 6 configured     |
+--------------------------+---------------------------+

+------------------------------------------------------+
| MODEL DIAGNOSTICS                         [expand]    |
+------------------------------------------------------+
```

Mobile order:

```text
freshness
decision
days
hourly
drift
consensus
diagnostics
```

---

# 67. Suggested Status Terminology

Use the existing domain terminology consistently.

Decision:

```text
RECOMMENDED
NO CLEAR WINNER
NO QUALIFYING WINDOW
```

Consensus:

```text
HIGH
MEDIUM
LOW
INSUFFICIENT_DATA
```

Trend:

```text
IMPROVING
WORSENING
STABLE
VOLATILE
UNKNOWN
```

Stability:

```text
HIGH
MEDIUM
LOW
UNKNOWN
```

Do not invent slightly different web-only labels for the same states.

---

# 68. Milestone 1 — Shared Service Interface

Deliver:

- inspect existing CLI
- extract reusable service functions where needed
- ensure structured return values
- no CLI regression

Acceptance:

```text
existing 25 tests still pass
```

and CLI output remains functional.

---

# 69. Milestone 2 — FastAPI Skeleton

Deliver:

```text
FastAPI app
Jinja templates
static assets
/health
/api/status
/
```

Acceptance:

Dashboard renders from fixture SQLite data without live internet.

---

# 70. Milestone 3 — Decision / Forecast Views

Deliver:

- decision card
- next-days overview
- hourly grid
- reachability styling
- no-decision states

Acceptance:

Web recommendation matches CLI `decide --json` for the same input.

---

# 71. Milestone 4 — Consensus / Drift Views

Deliver:

- consensus summary
- model diagnostics
- trend history
- inline SVG drift chart

Acceptance:

Displayed statistics match Phase 2 domain functions.

---

# 72. Milestone 5 — Refresh Control

Deliver:

- `POST /api/refresh`
- file lock
- cooldown
- refresh status persistence
- graceful API failure

Acceptance:

Two simultaneous refresh attempts cannot run at once.

---

# 73. Milestone 6 — Snapshot Worker

Deliver:

```text
fuji-snapshot-worker
```

with configurable interval.

Acceptance:

Two scheduled cycles produce additional persisted snapshots without manual SSH commands.

---

# 74. Milestone 7 — Docker Deployment

Deliver:

```text
Dockerfile
docker-compose.dashboard.yml
.env.example
healthcheck
```

Acceptance:

Both services run correctly on arm64.

Dashboard has no published host port.

Dashboard joins:

```text
npm_default
```

---

# 75. Milestone 8 — NPM Production Setup

Production target:

```text
fuji.wangdi.store
```

Configure manually in the existing NPM instance:

```text
http://fuji-dashboard:8000
```

Enable:

```text
SSL
Force SSL
HTTP/2
Block Common Exploits
```

Recommended:

```text
NPM Access List
```

Acceptance:

```text
https://fuji.wangdi.store
```

loads the dashboard over a valid certificate.

---

# 76. Milestone 9 — Documentation and Tests

Deliver:

```text
README updates
README_DEPLOY.md
web tests
Docker deployment instructions
upgrade / rollback instructions
```

Acceptance:

Full offline test suite passes.

---

# 77. Definition of Done

Phase 3 is complete when:

- [ ] Existing CLI remains functional.
- [ ] Existing forecast / consensus / decision logic is reused, not reimplemented.
- [ ] Dashboard is available through FastAPI.
- [ ] Homepage shows forecast freshness.
- [ ] Homepage shows the current decision state.
- [ ] `NO CLEAR WINNER` is supported.
- [ ] `NO QUALIFYING WINDOW` is supported.
- [ ] Next 7 days are visible.
- [ ] Reachability cutoff is enforced.
- [ ] Hourly data is visible.
- [ ] Consensus is visible.
- [ ] Full vs partial models are visible.
- [ ] Forecast drift is visible.
- [ ] Stability and trend are visible.
- [ ] Manual refresh works.
- [ ] Refresh locking works.
- [ ] Refresh cooldown works.
- [ ] Scheduled snapshot collection works.
- [ ] SQLite WAL / concurrent reads and writes are safe.
- [ ] Failed Open-Meteo refresh does not break the dashboard.
- [ ] Raw forecast data and existing DB history remain persistent.
- [ ] Docker image works on arm64.
- [ ] Dashboard container does not publish port 8000 publicly.
- [ ] Dashboard joins existing external `npm_default`.
- [ ] NPM can resolve `fuji-dashboard:8000`.
- [ ] `https://fuji.wangdi.store` works through NPM.
- [ ] SSL is valid.
- [ ] Authentication is handled by NPM if enabled.
- [ ] Production deployment documentation exists.
- [ ] Offline tests pass.

---

# 78. Codex Working Instructions

When implementing this specification:

1. Read the existing Phase 1/2 code before writing the web layer.
2. Preserve all existing CLI behavior.
3. Do not duplicate decision, consensus, stability, or scoring logic.
4. Return structured domain objects from reusable functions where necessary.
5. Build the web layer on those objects.
6. Keep the frontend lightweight.
7. Do not add a Node runtime.
8. Use one Uvicorn worker.
9. Use the existing SQLite database.
10. Enable safe web-read / worker-write concurrency.
11. Implement refresh locking before enabling manual refresh.
12. Use the existing runtime model capability system.
13. Treat partial models honestly.
14. Do not loosen decision thresholds to force a recommendation.
15. Do not expose port 8000 on the VPS.
16. Join the existing external Docker network `npm_default`.
17. Use `fuji-dashboard` as the production Docker service/container DNS name.
18. Use `fuji.wangdi.store` as the production hostname.
19. Keep NPM authentication outside application code.
20. Do not modify the existing NPM compose stack unless required.
21. If a change to NPM itself appears necessary, stop and document why instead of automatically changing it.
22. Ensure the image builds on arm64.
23. At completion, report:
    - files added / modified
    - refactors performed
    - tests run
    - Docker image build result
    - container health
    - exposed/published ports
    - Docker networks
    - dashboard URL
    - NPM settings still requiring manual user action
    - any unresolved limitations

---

# 79. Required Final Validation

After implementation:

1. Run the full existing/offline test suite.
2. Build the Docker image.
3. Start `fuji-dashboard` and `fuji-snapshot-worker`.
4. Verify `fuji-dashboard` becomes healthy.
5. Verify `fuji-snapshot-worker` remains running.
6. Verify `fuji-dashboard` joins `npm_default`.
7. Verify port 8000 is **not** published on the host.
8. Verify the NPM network can resolve and reach:

```text
http://fuji-dashboard:8000/health
```

9. Configure NPM for:

```text
fuji.wangdi.store
```

10. Verify:

```text
https://fuji.wangdi.store
```

with a valid certificate.
11. Verify normal viewing requires no SSH.

---

# 80. Expected Phase 3 End State

Normal daily usage should become:

```text
open phone browser
    ->
https://fuji.wangdi.store
    ->
see current recommendation and forecast confidence
```

No SSH is required for normal viewing.

The dashboard should immediately answer:

```text
Which upcoming day currently looks best?

Can I physically reach the good window?

How many models agree?

Has the forecast been stable?

Is it improving or deteriorating?

How fresh is the data?
```

Technical investigation remains available below the main decision:

```text
hourly variables
model diagnostics
forecast drift
partial model availability
```

Phase 3 succeeds when the dashboard makes the existing Phase 1/2 engine convenient to use without weakening its decision discipline.
