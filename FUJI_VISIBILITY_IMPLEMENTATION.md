# Fuji Visibility Reverse-Engineering Tool — Implementation Plan

## 0. Purpose

Build a small Python tool that exposes the **full hourly weather inputs** behind Mt. Fuji visibility decisions instead of relying on the public “Best Viewing Times” Top 3 cards shown by Is It Visible.

The tool must:

1. Pull complete hourly Open-Meteo forecast data for the Kawaguchiko / Fuji Five Lakes side.
2. Show the variables most relevant to whether Mt. Fuji itself is visible:
   - total cloud cover
   - low / mid / high cloud cover
   - meteorological visibility
   - relative humidity
   - precipitation probability
   - temperature
   - optionally wind and pressure-level cloud diagnostics
3. Compare two candidate travel days hour by hour.
4. Support an **arrival cutoff**, because hours before the user can physically arrive are irrelevant.
5. Save every forecast snapshot so forecast drift can be inspected later.
6. Reverse-engineer which Open-Meteo coordinate/model combination best matches public Is It Visible cards.
7. Implement a clearly labeled **Fuji Proxy Score** that approximates Is It Visible’s published methodology without claiming exact parity.

This is primarily a **CLI + SQLite + JSON/CSV** project. Do not spend time on a web UI until the core data pipeline is correct.

---

## 1. Background and Known Facts

### 1.1 Is It Visible uses Open-Meteo

Is It Visible states in its privacy policy that it uses Open-Meteo server-side for fixed geographic coordinates, with “Lake Kawaguchiko” given as the Mt. Fuji example.

Reference:

- https://isitvisible.com/privacy
- https://open-meteo.com/en/docs

### 1.2 Published score structure

Is It Visible publishes the following weighting:

- Visibility distance: **40%**
- Cloud cover: **30%**
- Precipitation probability: **20%**
- Relative humidity: **10%**

It says each component is normalized to 0–100 before weighting.

Reference:

- https://isitvisible.com/methodology

Published quality bands:

Cloud cover:
- 0–20% = Excellent
- 20–50% = Good
- 50–80% = Fair
- 80–100% = Poor

Precipitation probability:
- 0–10% = Excellent
- 10–30% = Good
- 30–60% = Fair
- 60–100% = Poor

Relative humidity:
- 0–40% = Excellent
- 40–60% = Good
- 60–80% = Fair
- 80–100% = Poor

The exact per-component normalization functions are not public, so exact score replication is **not** a requirement.

### 1.3 Relevant Open-Meteo variables

Open-Meteo provides:

```text
temperature_2m
relative_humidity_2m
precipitation_probability
cloud_cover
cloud_cover_low
cloud_cover_mid
cloud_cover_high
visibility
wind_speed_10m
wind_direction_10m
```

Definitions important to this project:

- `cloud_cover_low`: clouds / fog up to ~3 km altitude
- `cloud_cover_mid`: ~3–8 km altitude
- `cloud_cover_high`: above ~8 km
- `visibility`: meteorological viewing distance, returned in meters

Mt. Fuji summit elevation is 3,776 m, so `cloud_cover_mid` is especially important.

Open-Meteo also supports pressure-level variables. Relevant approximate levels:

- 700 hPa ≈ 3.0 km
- 600 hPa ≈ 4.2 km
- 500 hPa ≈ 5.6 km
- 400 hPa ≈ 7.2 km

Pressure-level diagnostics are optional in MVP but should be supported by the architecture.

Reference:

- https://open-meteo.com/en/docs

---

## 2. Current Reverse-Engineering Fingerprint

Use the following public Is It Visible observations as a test fingerprint.

Approximate screenshot capture time:

```text
2026-08-21 07:30 JST
```

Observed cards:

```yaml
observations:
  - valid_time: "2026-08-26T09:00:00+09:00"
    temperature_c: 27.2
    displayed_cloud_pct: 5
    visibility_km: 42.5
    rank: 1
    label: "EXCELLENT"

  - valid_time: "2026-08-26T08:00:00+09:00"
    temperature_c: 25.6
    displayed_cloud_pct: 11
    visibility_km: 37.0
    rank: 2
    label: "GOOD"

  - valid_time: "2026-08-25T10:00:00+09:00"
    temperature_c: 27.8
    displayed_cloud_pct: 21
    visibility_km: 23.5
    rank: 3
    label: "GOOD"
```

Important:

- These values are a snapshot of a forecast state, not timeless truth.
- Live Open-Meteo values may no longer match by the time the tool is implemented.
- Fingerprinting therefore needs two modes:
  1. **live match** against the current forecast
  2. **historical run search** using Open-Meteo Single Runs API around the screenshot capture time

Do not hard-code an assumption that Is It Visible’s displayed `Clouds` value equals `cloud_cover_mid`. Test multiple interpretations.

---

## 3. Project Scope

### 3.1 In scope

- Open-Meteo Forecast API client
- Hourly weather table
- Multi-day comparison
- Arrival-time filtering
- Snapshot persistence
- Forecast drift analysis
- Is It Visible fingerprint matching
- Candidate coordinate/model search
- Approximate Fuji visibility score
- CSV / JSON export
- Automated tests
- Clear CLI output

### 3.2 Out of scope for MVP

- Web frontend
- Mobile app
- Automated browser scraping of Is It Visible
- Image recognition / OCR of screenshots
- Claiming exact reproduction of proprietary scoring logic
- Route planning / Google Maps integration
- Notifications / scheduled background jobs
- Live webcam image analysis

---

## 4. Technology Choices

Use:

```text
Python >= 3.12
```

Recommended dependencies:

```text
httpx
typer
rich
pydantic
```

Use the Python standard library for:

```text
sqlite3
datetime
zoneinfo
json
csv
statistics
math
```

Optional:

```text
pandas
```

Do not make pandas mandatory unless it materially simplifies comparison/export logic.

Testing:

```text
pytest
pytest-httpx
```

Package management can be either `uv` or `pip`, but document the chosen method.

---

## 5. Suggested Repository Layout

```text
fuji-visibility/
├── README.md
├── pyproject.toml
├── data/
│   ├── fuji_forecasts.sqlite
│   ├── raw/
│   └── fingerprints/
│       └── isitvisible_2026-08-21_0730_jst.json
├── src/
│   └── fuji_visibility/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── models.py
│       ├── open_meteo.py
│       ├── scoring.py
│       ├── fingerprint.py
│       ├── storage.py
│       ├── comparison.py
│       └── formatting.py
└── tests/
    ├── test_open_meteo.py
    ├── test_scoring.py
    ├── test_fingerprint.py
    ├── test_storage.py
    └── fixtures/
```

---

## 6. Data Source Implementation

### 6.1 Forecast API

Base endpoint:

```text
https://api.open-meteo.com/v1/forecast
```

Minimum request:

```text
latitude=<lat>
longitude=<lon>
timezone=Asia/Tokyo
hourly=temperature_2m,relative_humidity_2m,precipitation_probability,cloud_cover,cloud_cover_low,cloud_cover_mid,cloud_cover_high,visibility,wind_speed_10m,wind_direction_10m
```

Prefer explicit `start_date` / `end_date` or `start_hour` / `end_hour` when querying a narrow period.

All application-level timestamps must be normalized to:

```text
Asia/Tokyo
```

Do not use naive datetimes internally.

### 6.2 Open-Meteo model behavior

Default Open-Meteo behavior selects / combines the best suitable models automatically.

The API also accepts an explicit `models` parameter.

The implementation must support:

```text
--model auto
--model <explicit-model>
```

`auto` means omit the `models` parameter.

Do not assume that one model provides all variables. If an explicit model returns missing fields, record that and skip it for fingerprint matching where necessary.

### 6.3 Raw response preservation

Every successful API request must optionally save the exact raw JSON response under:

```text
data/raw/
```

Suggested file name:

```text
2026-08-21T073500+0900__35.52_138.75__auto.json
```

Also store a SHA-256 hash in SQLite so duplicate snapshots can be detected.

---

## 7. Location Handling

### 7.1 Default target

The public Is It Visible privacy text says it uses fixed coordinates and gives **Lake Kawaguchiko** as the Mt. Fuji example, but does not publish exact coordinates.

Therefore:

- do not treat any single hand-picked point as authoritative
- make coordinates configurable
- implement a coordinate-search grid for fingerprint matching

Default search center:

```text
lat ≈ 35.52
lon ≈ 138.75
```

Initial search grid:

```text
lat: center ± 0.04 degrees
lon: center ± 0.04 degrees
step: 0.005 or 0.01 degrees
```

CLI must also permit arbitrary coordinates:

```bash
fuji forecast --lat 35.52 --lon 138.75 ...
```

### 7.2 Named presets

Provide editable presets in `config.py`, for example:

```text
kawaguchiko
oishi
shojiko
```

Exact preset coordinates should be stored as data/config, not scattered through application logic.

The fingerprint search should primarily target the Kawaguchiko area because that is the location Is It Visible publicly mentions.

---

## 8. Core Data Model

Define a normalized hourly record.

Example Pydantic model:

```python
class HourlyForecast(BaseModel):
    provider: str = "open-meteo"
    model: str
    requested_lat: float
    requested_lon: float
    returned_lat: float | None
    returned_lon: float | None
    elevation_m: float | None

    retrieved_at: datetime
    valid_time: datetime

    temperature_c: float | None
    relative_humidity_pct: float | None
    precipitation_probability_pct: float | None

    cloud_total_pct: float | None
    cloud_low_pct: float | None
    cloud_mid_pct: float | None
    cloud_high_pct: float | None

    visibility_m: float | None

    wind_speed_kmh: float | None
    wind_direction_deg: float | None
```

Computed property:

```python
visibility_km = visibility_m / 1000
```

Never store displayed rounded values only. Preserve original numeric values.

---

## 9. SQLite Schema

### 9.1 `forecast_snapshots`

```sql
CREATE TABLE forecast_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    retrieved_at TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    requested_lat REAL NOT NULL,
    requested_lon REAL NOT NULL,
    returned_lat REAL,
    returned_lon REAL,
    elevation_m REAL,
    raw_json_path TEXT,
    raw_sha256 TEXT
);
```

### 9.2 `hourly_forecasts`

```sql
CREATE TABLE hourly_forecasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL,
    valid_time TEXT NOT NULL,

    temperature_c REAL,
    relative_humidity_pct REAL,
    precipitation_probability_pct REAL,

    cloud_total_pct REAL,
    cloud_low_pct REAL,
    cloud_mid_pct REAL,
    cloud_high_pct REAL,

    visibility_m REAL,

    wind_speed_kmh REAL,
    wind_direction_deg REAL,

    FOREIGN KEY(snapshot_id) REFERENCES forecast_snapshots(id)
);
```

Indexes:

```sql
CREATE INDEX idx_hourly_valid_time
ON hourly_forecasts(valid_time);

CREATE INDEX idx_snapshot_retrieved
ON forecast_snapshots(retrieved_at);
```

### 9.3 `fingerprint_observations`

```sql
CREATE TABLE fingerprint_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    observed_at TEXT,
    valid_time TEXT NOT NULL,

    temperature_c REAL,
    displayed_cloud_pct REAL,
    visibility_km REAL,

    rank INTEGER,
    label TEXT,
    notes TEXT
);
```

---

## 10. CLI Requirements

CLI executable:

```text
fuji
```

### 10.1 Forecast table

```bash
fuji forecast 2026-08-25 \
  --location kawaguchiko \
  --hours 5-12
```

Expected table columns:

```text
Time
Temp °C
Cloud Total %
Cloud Low %
Cloud Mid %
Cloud High %
Visibility km
RH %
Rain %
Wind km/h
Proxy Score
```

### 10.2 Compare days

```bash
fuji compare 2026-08-25 2026-08-26 \
  --location kawaguchiko \
  --hours 5-12
```

Support:

```bash
--arrival-after 08:00
```

With this option:

- still display all requested hours if desired
- visually mark hours before arrival as unreachable
- exclude unreachable hours from “best reachable window” ranking

### 10.3 Save snapshot

```bash
fuji snapshot \
  --location kawaguchiko \
  --days 7
```

Behavior:

- fetch live forecast
- save raw JSON
- normalize hourly rows
- persist to SQLite

### 10.4 Trend

```bash
fuji trend 2026-08-26 \
  --hour 09:00 \
  --location kawaguchiko
```

Output example:

```text
Retrieved at        Mid cloud  Visibility  RH   Rain  Proxy
2026-08-21 01:00       18%       27 km     82%   20%   55
2026-08-21 04:00       11%       34 km     76%   10%   70
2026-08-21 07:00        5%       42 km     70%    5%   84
```

This command is critical. The purpose is to show forecast stability / drift.

### 10.5 Fingerprint

```bash
fuji fingerprint \
  --input data/fingerprints/isitvisible_2026-08-21_0730_jst.json
```

Optional search controls:

```bash
--lat-center 35.52
--lon-center 138.75
--radius-deg 0.04
--step-deg 0.01
--models auto,jma_seamless,jma_msm,jma_gsm,gfs_seamless,...
```

The exact model identifiers must be validated against the current Open-Meteo API. Unsupported identifiers should be reported and skipped, not crash the whole search.

Output:

```text
Rank  Coord              Model      Cloud mapping   Error
1     35.520,138.750     auto       total           0.42
2     35.515,138.755     ...        mid             0.71
3     ...
```

Then show per-point residuals.

---

## 11. Fingerprint Matching Design

### 11.1 Unknowns to infer

We do not know:

1. exact latitude / longitude used by Is It Visible
2. whether Open-Meteo default auto/best-match is used
3. whether an explicit model is used
4. what `Clouds` on the card represents
5. whether Is It Visible post-processes Open-Meteo values

Therefore search over these dimensions.

### 11.2 Candidate cloud mappings

For each Open-Meteo candidate, evaluate at least:

```text
total:
    cloud_cover

mid:
    cloud_cover_mid

low_mid_max:
    max(cloud_cover_low, cloud_cover_mid)

low_mid_weighted:
    0.35 * cloud_cover_low + 0.65 * cloud_cover_mid

mid_high_weighted:
    0.75 * cloud_cover_mid + 0.25 * cloud_cover_high
```

Do not assume one is correct.

### 11.3 Error function

Start with normalized absolute error.

Example:

```python
temp_err = abs(pred_temp - obs_temp) / 1.0
cloud_err = abs(pred_cloud - obs_cloud) / 10.0
vis_err = abs(pred_vis_km - obs_vis_km) / 10.0

point_error = (
    0.30 * temp_err +
    0.30 * cloud_err +
    0.40 * vis_err
)
```

Final candidate error:

```text
mean(point_error for all observed cards)
```

Also report raw residuals. Never hide mismatch behind one aggregate score.

### 11.4 Exact-match tolerances

Useful debugging tolerances:

```text
temperature: ±0.3 °C
cloud: ±2 percentage points
visibility: ±1.0 km
```

A strong match across all three observed hours is much more meaningful than matching only one.

---

## 12. Historical Run Matching

Live matching may fail because the screenshot captured a forecast state that has already been superseded.

Use Open-Meteo Single Runs API.

Reference:

- https://open-meteo.com/en/docs/single-runs-api

Endpoint:

```text
https://single-runs-api.open-meteo.com/v1/forecast
```

It accepts the same general forecast parameters plus:

```text
run=<UTC initialization datetime>
```

Example conceptually:

```text
run=2026-08-20T18:00
```

Implementation command:

```bash
fuji fingerprint-history \
  --input data/fingerprints/isitvisible_2026-08-21_0730_jst.json \
  --search-from "2026-08-20T00:00:00Z" \
  --search-to   "2026-08-20T23:59:59Z"
```

Search plausible model initialization times before the screenshot.

Important:

- `run` is model initialization time, not public availability time.
- a model run can become available several hours after initialization
- do not assume the latest UTC initialization was available at screenshot capture time

The command should rank:

```text
coordinate
model
run initialization
cloud mapping
error
```

This is the preferred route if live fingerprinting does not match.

---

## 13. Previous Runs API

Also support Open-Meteo Previous Runs API for lead-time / forecast drift analysis.

Reference:

- https://open-meteo.com/en/docs/previous-runs-api

This API exposes values that were predicted a fixed number of days before valid time.

Use it mainly for research / validation, not as the primary live forecast endpoint.

Optional command:

```bash
fuji previous-runs 2026-08-26 \
  --hour 09:00 \
  --model <model>
```

Display:

```text
current
previous_day1
previous_day2
previous_day3
...
```

---

## 14. Fuji Proxy Score

### 14.1 Naming

Call it exactly:

```text
Fuji Proxy Score
```

Do **not** call it:

```text
Is It Visible Score
Official Fuji Visibility Score
```

### 14.2 Weighting

Use the published Is It Visible weights:

```text
visibility      40%
cloud           30%
precipitation   20%
humidity        10%
```

### 14.3 Cloud component

Default proxy should emphasize mountain-intersecting cloud.

Recommended initial implementation:

```python
effective_cloud = max(
    cloud_mid_pct,
    0.5 * cloud_low_pct
)
```

Also allow strategies:

```text
--cloud-strategy total
--cloud-strategy mid
--cloud-strategy low-mid-max
--cloud-strategy weighted
```

Default strategy:

```text
mid
```

Reason: Fuji summit elevation intersects Open-Meteo’s 3–8 km mid-cloud band.

### 14.4 Normalization

Do not pretend the hidden normalization is known.

Implement transparent piecewise-linear functions.

Example cloud score:

```text
0%   -> 100
20%  -> 85
50%  -> 60
80%  -> 30
100% -> 0
```

Example precipitation score:

```text
0%   -> 100
10%  -> 90
30%  -> 65
60%  -> 30
100% -> 0
```

Example humidity score:

```text
30%  -> 100
40%  -> 90
60%  -> 70
80%  -> 35
100% -> 0
```

Example visibility score:

```text
0 km   -> 0
10 km  -> 25
20 km  -> 45
30 km  -> 65
40 km  -> 82
50 km  -> 95
60+ km -> 100
```

Use linear interpolation between breakpoints.

These breakpoints are our own approximation and must be documented in code.

### 14.5 Final formula

```python
proxy = (
    visibility_score * 0.40
    + cloud_score * 0.30
    + precipitation_score * 0.20
    + humidity_score * 0.10
)
```

Round only for display.

Persist the unrounded score if stored.

---

## 15. Best Reachable Window

This is a first-class feature.

Given:

```text
arrival_after = 08:00
```

The tool should ignore 05:00–07:00 when selecting the best window.

Algorithm:

1. filter to reachable hours
2. calculate proxy score
3. find the maximum
4. find adjacent hours within configurable tolerance, e.g. 10 score points
5. report a window rather than one single hour where appropriate

Example:

```text
Best reachable window:
Wed Aug 26, 08:00–10:00 JST

Peak:
09:00 — Proxy 87

Why:
- mid cloud 5%
- visibility 42.5 km
- rain probability 5%
- humidity moderate

Confidence:
Forecast has improved in 2 of the last 3 saved snapshots.
```

---

## 16. Forecast Drift Metrics

For each valid hour, calculate from saved snapshots:

```text
latest proxy
previous proxy
delta since previous snapshot
delta over 6h
delta over 12h
number of consecutive improving snapshots
number of consecutive worsening snapshots
standard deviation of recent predictions
```

Also track raw variables:

```text
visibility_km trend
mid cloud trend
precip probability trend
```

The tool should distinguish:

```text
high score, stable
high score, rapidly worsening
medium score, steadily improving
unstable
```

Suggested heuristic labels:

```text
STABLE
IMPROVING
WORSENING
VOLATILE
```

Keep heuristics simple and documented.

---

## 17. Output Example

Command:

```bash
fuji compare 2026-08-25 2026-08-26 \
  --hours 5-12 \
  --arrival-after 08:00
```

Desired style:

```text
Mt Fuji Visibility — Kawaguchiko
Retrieved: 2026-08-21 07:35 JST
Source: Open-Meteo
Model: auto

TUE 2026-08-25

Time   Reach  Temp  Low  Mid  High  Vis     RH   Rain  Proxy
05:00    no    ...   ...  ...   ...   ...     ...  ...    ...
06:00    no    ...   ...  ...   ...   ...     ...  ...    ...
07:00    no    ...   ...  ...   ...   ...     ...  ...    ...
08:00   yes    ...   ...  ...   ...   ...     ...  ...    78
09:00   yes    ...   ...  ...   ...   ...     ...  ...    81
10:00   yes   27.8   ...  ...   ...  23.5km   ...  ...    76
11:00   yes    ...   ...  ...   ...   ...     ...  ...    61

WED 2026-08-26

Time   Reach  Temp  Low  Mid  High  Vis     RH   Rain  Proxy
08:00   yes   25.6   ...  ...   ...  37.0km   ...  ...    85
09:00   yes   27.2   ...  ...   ...  42.5km   ...  ...    91
10:00   yes    ...    ...  ...   ...   ...      ...  ...    86

Best reachable day: WED
Best reachable window: 08:00–10:00
Peak hour: 09:00
```

Never fabricate a “reason” if one of the source variables is missing.

---

## 18. Optional Pressure-Level Diagnostics

Add after MVP works.

Request cloud cover / RH at pressure levels around Mt. Fuji summit elevation if supported by the selected Open-Meteo model.

Priority levels:

```text
700 hPa ~ 3.0 km
600 hPa ~ 4.2 km
500 hPa ~ 5.6 km
400 hPa ~ 7.2 km
```

Purpose:

- determine whether cloud is specifically concentrated around summit altitude
- distinguish broad mid-cloud percentage from mountain-level obstruction risk

Do not put pressure-level data into the Proxy Score until basic validation shows it improves correspondence with Is It Visible or observed webcam outcomes.

---

## 19. Testing Requirements

### 19.1 Unit tests

Test:

- timezone conversion
- visibility meter → km conversion
- missing/null API fields
- score normalization
- cloud strategies
- arrival filtering
- comparison ranking
- trend calculation
- SQLite persistence
- duplicate raw response detection

### 19.2 API parsing tests

Use fixed JSON fixtures.

Do not make unit tests depend on live Open-Meteo availability.

### 19.3 Integration test

One optional integration test may call live Open-Meteo and should be marked:

```text
@pytest.mark.integration
```

Do not run it in the default unit-test suite.

### 19.4 Fingerprint test

Use a synthetic fixture where the correct coordinate/model/cloud-mapping combination is known.

Verify the search algorithm ranks it first.

Do not create a brittle test that expects live Open-Meteo to continue matching the Aug 21 screenshot.

---

## 20. Error Handling

Handle:

- network timeout
- HTTP 4xx / 5xx
- unsupported model
- requested variable unavailable for model
- missing valid hour
- DST/timezone mistakes
- malformed fingerprint JSON
- database locked
- duplicate snapshot
- partial Open-Meteo response

CLI errors must be actionable.

Bad:

```text
ValueError
```

Good:

```text
Model 'jma_msm' did not return visibility for this request.
Skipping it for fingerprint matching because visibility is required.
```

---

## 21. Logging

Support:

```bash
--verbose
```

Normal mode:

- minimal user-facing messages

Verbose mode:

- final API URL without secrets
- response model metadata
- returned coordinates/elevation
- missing variables
- fingerprint candidate progress
- database writes

No API keys should be required for normal non-commercial Open-Meteo use.

---

## 22. Configuration

Use one config file or Python config module for:

```text
timezone
default location
named presets
default hourly fields
candidate models
score breakpoints
fingerprint weights
coordinate search radius
coordinate step
request timeout
database path
raw data path
```

Do not bury these values in individual command functions.

---

## 23. Implementation Order

### Milestone 1 — Open-Meteo hourly client

Deliver:

- request builder
- hourly parsing
- JST-safe timestamps
- `fuji forecast`
- Rich table

Acceptance:

```bash
fuji forecast 2026-08-25 --hours 5-12
```

works and displays all required fields.

### Milestone 2 — comparison + arrival cutoff

Deliver:

- `fuji compare`
- `--arrival-after`
- best reachable hour/window

Acceptance:

```bash
fuji compare 2026-08-25 2026-08-26 \
  --hours 5-12 \
  --arrival-after 08:00
```

produces a useful recommendation without using unreachable hours.

### Milestone 3 — persistence + trend

Deliver:

- SQLite schema
- raw JSON saving
- `fuji snapshot`
- `fuji trend`

Acceptance:

Run snapshot twice and verify the trend command shows two forecast states for the same valid time.

### Milestone 4 — proxy score

Deliver:

- normalization functions
- cloud strategy selection
- proxy score in tables

Acceptance:

All scoring unit tests pass and the CLI clearly labels it as a proxy.

### Milestone 5 — fingerprint live search

Deliver:

- fingerprint JSON parser
- coordinate grid search
- model iteration
- cloud mapping iteration
- ranked candidate output

Acceptance:

Synthetic fingerprint test identifies the known best candidate.

### Milestone 6 — historical run fingerprint

Deliver:

- Single Runs API client
- run-time search
- candidate ranking

Acceptance:

Can search around an observed screenshot timestamp without relying on current live forecast state.

### Milestone 7 — Previous Runs / diagnostics

Optional after core tool is reliable.

---

## 24. Definition of Done

The project is complete when all of the following are true:

- [ ] All timestamps are timezone-aware and displayed in JST.
- [ ] Any day can be displayed hour-by-hour.
- [ ] Low / mid / high cloud are separate columns.
- [ ] Visibility is displayed in km but raw meters are preserved.
- [ ] Two dates can be compared side by side / sequentially.
- [ ] `--arrival-after` affects ranking.
- [ ] Every forecast can be persisted to SQLite.
- [ ] Raw Open-Meteo JSON can be retained.
- [ ] Forecast drift can be inspected for a valid hour.
- [ ] A Fuji Proxy Score is available and explicitly labeled approximate.
- [ ] Is It Visible fingerprint data can be loaded from JSON.
- [ ] Candidate coordinate/model/cloud mappings can be ranked.
- [ ] Historical Single Runs can be searched when live data no longer matches a screenshot.
- [ ] Unit tests pass without internet access.
- [ ] README contains runnable examples.
- [ ] No output claims exact reproduction of Is It Visible unless independently proven.

---

## 25. Codex Working Instructions

When implementing this specification:

1. Start by reading this document fully.
2. Implement milestones in order.
3. Keep commits / changes logically separated by milestone where possible.
4. Prefer simple, inspectable code over excessive abstraction.
5. Do not build a UI before Milestones 1–6 work.
6. Do not scrape Is It Visible unless explicitly requested later.
7. Do not silently substitute missing weather fields.
8. Preserve raw source data so mismatches can be debugged.
9. Make all reverse-engineering assumptions explicit in code comments / README.
10. If current Open-Meteo parameter names differ from examples here, follow the current official API docs and document the adjustment.
11. At the end, run:
    - unit tests
    - one live forecast command
    - one compare command
    - one snapshot/trend cycle
    - fingerprint against a synthetic fixture
12. Report:
    - files created/modified
    - commands run
    - test results
    - any unresolved mismatch with Is It Visible

---

## 26. Suggested First Commands After Implementation

```bash
# Save a live forecast snapshot
fuji snapshot --location kawaguchiko --days 7

# Inspect Tuesday
fuji forecast 2026-08-25 \
  --location kawaguchiko \
  --hours 5-12

# Compare Tuesday vs Wednesday using a realistic arrival cutoff
fuji compare 2026-08-25 2026-08-26 \
  --location kawaguchiko \
  --hours 5-12 \
  --arrival-after 08:00

# Inspect how Wednesday 09:00 has changed across snapshots
fuji trend 2026-08-26 \
  --hour 09:00 \
  --location kawaguchiko

# Attempt to match the captured Is It Visible cards
fuji fingerprint \
  --input data/fingerprints/isitvisible_2026-08-21_0730_jst.json
```

---

## 27. References

Is It Visible:

- Methodology: https://isitvisible.com/methodology
- Privacy / Open-Meteo disclosure: https://isitvisible.com/privacy

Open-Meteo:

- Forecast API: https://open-meteo.com/en/docs
- Single Runs API: https://open-meteo.com/en/docs/single-runs-api
- Previous Runs API: https://open-meteo.com/en/docs/previous-runs-api

Key Open-Meteo implementation facts to verify against current docs during coding:

- Forecast endpoint supports explicit lat/lon and hourly variables.
- `timezone=Asia/Tokyo` should be used.
- `cloud_cover_low`, `cloud_cover_mid`, and `cloud_cover_high` are separate fields.
- `visibility` is returned in meters.
- explicit models can be selected, while the default uses Open-Meteo’s best-match behavior.
- Single Runs API can retrieve a particular model initialization using `run=...`.
