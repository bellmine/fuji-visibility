# Fuji Visibility Tool — Phase 2 Implementation Plan

## 0. Context

Phase 1 has been completed successfully.

Current implementation already includes:

- Open-Meteo hourly client
- JST-normalized timestamps
- raw JSON preservation
- `forecast`
- `compare`
- `snapshot`
- `trend`
- `fingerprint`
- `fingerprint-history`
- `previous-runs`
- `export`
- SQLite persistence
- SHA-256 raw-response deduplication
- Fuji Proxy Score
- cloud strategy support
- arrival-time cutoff
- best reachable window selection
- coordinate / model / cloud-mapping fingerprint search
- CSV / JSON export
- README and configuration
- offline test suite

Current validation status:

```text
uv run pytest
15 passed
```

Live commands have also been verified.

A recent live comparison returned:

```text
Recommended candidate:
2026-08-26 08:00–09:00 JST

Peak:
2026-08-26 09:00
Fuji Proxy Score: 87
```

Phase 2 should **not** focus on adding a frontend or making the proxy score more elaborate.

The next goal is to answer a more important question:

> Is a high forecast score stable, supported by multiple models, and likely to remain useful by the time the user can actually arrive?

---

# 1. Phase 2 Goals

Implement three capabilities:

1. **Multi-model forecast consensus**
2. **Forecast stability / confidence analysis**
3. **A final `decide` command that combines forecast quality, model agreement, drift, and reachable hours**

Secondary goals:

4. Automate repeated snapshot collection locally
5. Improve diagnostics for forecast instability
6. Prepare architecture for later mountain-aware forecasting

Do not add a web UI in this phase.

---

# 2. Design Principle

Do not collapse every signal into one opaque number.

The tool should keep these dimensions separate:

```text
Forecast quality
Model consensus
Forecast stability
Reachability
Trend direction
Primary weather risk
```

For example:

```text
Proxy Score: 91
Model Consensus: LOW
Stability: LOW
Trend: VOLATILE
```

must be treated as less trustworthy than:

```text
Proxy Score: 84
Model Consensus: HIGH
Stability: HIGH
Trend: STABLE
```

The `decide` command may rank options, but it must also show the component evidence.

---

# 3. Multi-Model Consensus

## 3.1 Purpose

The existing implementation can query Open-Meteo using `auto` or a specific model.

Phase 2 should query several suitable models for the same:

```text
location
valid hour
forecast variables
```

Then compare their agreement.

The purpose is not to identify the one "best model."

The purpose is to detect:

- broad agreement
- split forecasts
- one-model outliers
- uncertainty in cloud / visibility timing

---

## 3.2 Candidate Model Discovery

Do not hard-code stale model identifiers without validation.

Create a model configuration list such as:

```python
CANDIDATE_MODELS = [
    "auto",
    "...",
]
```

At runtime:

1. validate whether the model identifier is accepted by the current Open-Meteo API
2. attempt the required variables
3. record missing fields
4. skip unsuitable models gracefully

A model is eligible for full consensus scoring only if it provides at minimum:

```text
cloud_cover_mid
relative_humidity_2m
precipitation_probability
```

Prefer models that also provide:

```text
visibility
cloud_cover_low
cloud_cover_high
temperature_2m
```

If `visibility` is unavailable, the model may still contribute to a partial cloud consensus, but it must not be treated as equivalent to a full forecast member.

---

## 3.3 Model Metadata

Add a model capability record:

```python
class ModelCapability(BaseModel):
    model: str
    supported: bool
    variables_available: set[str]
    missing_required: set[str]
    missing_optional: set[str]
```

Cache capability checks for the current process.

Do not repeatedly probe the same unsupported model.

---

## 3.4 New CLI Command

Add:

```bash
fuji consensus 2026-08-25 2026-08-26 \
  --location kawaguchiko \
  --hours 5-12 \
  --arrival-after 08:00
```

Optional:

```bash
--models auto,<model1>,<model2>,<model3>
```

If `--models` is omitted, use configured candidates.

---

# 4. Consensus Statistics

For every valid hour, calculate:

```text
model_count
full_model_count
partial_model_count

proxy_median
proxy_min
proxy_max
proxy_stddev

mid_cloud_median
mid_cloud_min
mid_cloud_max
mid_cloud_stddev

visibility_median_km
visibility_min_km
visibility_max_km
visibility_stddev_km

precip_median
humidity_median
```

Also calculate threshold agreement.

Example default thresholds:

```text
GOOD_PROXY_THRESHOLD = 75
GOOD_MID_CLOUD_THRESHOLD = 25%
GOOD_VISIBILITY_THRESHOLD_KM = 25
GOOD_PRECIP_THRESHOLD = 30%
```

Then expose:

```text
models_good_proxy / full_model_count
models_good_mid_cloud / model_count
models_good_visibility / full_model_count
```

Example:

```text
4/5 models have Proxy >= 75
5/5 models have mid cloud <= 25%
3/5 models have visibility >= 25 km
```

---

# 5. Consensus Labels

Add a transparent consensus classification.

Suggested initial heuristic:

## HIGH

```text
at least 4 full models
>= 75% of full models have Proxy >= threshold
proxy stddev <= 8
mid-cloud stddev <= 15 percentage points
```

## MEDIUM

```text
at least 3 full models
>= 50% of full models have Proxy >= threshold
proxy stddev <= 15
```

## LOW

Everything else.

Also support:

```text
INSUFFICIENT_DATA
```

when fewer than 3 full models are available.

Keep these thresholds in configuration.

Do not bury them in CLI code.

---

# 6. Outlier Detection

A single model may produce an extreme result.

For each hour:

- calculate median proxy
- calculate median absolute deviation if enough models exist
- flag large outliers

Example:

```text
Model A  84
Model B  82
Model C  81
Model D  79
Model E  43  <- OUTLIER
```

Do not let one outlier dominate the consensus summary.

Still display it.

Never silently delete forecast members.

---

# 7. Consensus Output

Example:

```text
WED 2026-08-26

Time   Reach  Models  Proxy Median  Range   Mid Cloud  Visibility  Consensus
08:00   yes     5        83        78–88      11%       35 km       HIGH
09:00   yes     5        86        81–91       7%       39 km       HIGH
10:00   yes     5        79        61–86      18%       30 km       MEDIUM
11:00   yes     5        63        42–76      35%       21 km       LOW
```

Optional detail mode:

```bash
--show-models
```

Output:

```text
09:00

auto          Proxy 87  Mid 5%   Vis 42 km
model_a       Proxy 84  Mid 8%   Vis 39 km
model_b       Proxy 88  Mid 6%   Vis 44 km
model_c       Proxy 81  Mid 12%  Vis 35 km
model_d       Proxy 85  Mid 9%   Vis 38 km
```

---

# 8. Snapshot Collection

## 8.1 Purpose

The main value of the existing `snapshot` command is not archival.

It is to answer:

> Is the forecast converging or oscillating?

The tool should make repeated snapshot collection easy.

---

## 8.2 New CLI Option

Extend:

```bash
fuji snapshot
```

to support:

```bash
fuji snapshot \
  --location kawaguchiko \
  --days 7 \
  --models all
```

Where `all` means all configured valid consensus models.

Persist each model as an independent forecast snapshot.

---

## 8.3 Local Repeated Collection

Add documentation for using:

```text
cron
systemd timer
launchd
Windows Task Scheduler
```

Do not build a daemon into the application yet.

Recommended collection interval for the current use case:

```text
every 3 hours
```

Reason:

- frequent enough to observe model-run changes
- not excessively noisy
- underlying NWP models do not meaningfully refresh every few minutes

Example cron entry:

```cron
0 */3 * * * cd /path/to/fuji-visibility && uv run fuji snapshot --location kawaguchiko --days 7 --models all
```

Document that local scheduling is optional.

---

# 9. Forecast Stability Analysis

## 9.1 Purpose

A forecast can be good but unstable.

The tool should distinguish:

```text
high and stable
high but volatile
medium and improving
medium and worsening
```

Stability should be calculated independently from Proxy Score.

---

## 9.2 Required Historical Series

For each tuple:

```text
location
model
valid_time
```

load recent saved snapshots ordered by:

```text
retrieved_at
```

Default history windows:

```text
6 hours
12 hours
24 hours
```

---

# 10. Stability Metrics

For each valid hour and model:

```text
latest_proxy
previous_proxy
delta_last_snapshot

delta_6h
delta_12h
delta_24h

recent_proxy_mean
recent_proxy_stddev

recent_mid_cloud_mean
recent_mid_cloud_stddev

recent_visibility_mean
recent_visibility_stddev

consecutive_improving
consecutive_worsening
```

At consensus level also compute the same metrics for:

```text
proxy median
mid-cloud median
visibility median
```

Consensus-level drift is more important than a single-model drift.

---

# 11. Trend Labels

Suggested initial classification.

## IMPROVING

Example rule:

```text
latest proxy median >= previous
and
delta_6h >= +5
and
no large volatility
```

## WORSENING

```text
delta_6h <= -5
and
no large volatility
```

## STABLE

```text
abs(delta_6h) < 5
and
recent proxy stddev <= 6
```

## VOLATILE

```text
recent proxy stddev > 10
or
alternating large positive / negative forecast changes
```

## UNKNOWN

Insufficient snapshot history.

These values must be configurable.

---

# 12. Stability Confidence

Add:

```text
HIGH
MEDIUM
LOW
UNKNOWN
```

Suggested heuristic:

## HIGH

```text
>= 4 recent snapshots
proxy stddev <= 6
mid-cloud stddev <= 12
no large forecast reversal
```

## MEDIUM

```text
>= 3 recent snapshots
proxy stddev <= 12
```

## LOW

```text
>= 3 snapshots
but volatility exceeds MEDIUM threshold
```

## UNKNOWN

Too little history.

Do not call this "forecast accuracy."

Call it:

```text
Forecast Stability
```

or:

```text
Stability Confidence
```

It measures consistency of successive forecasts, not truth.

---

# 13. Enhanced `trend` Command

Extend:

```bash
fuji trend 2026-08-26 \
  --hour 09:00 \
  --location kawaguchiko
```

to optionally aggregate models:

```bash
--consensus
```

Example:

```text
Valid time: 2026-08-26 09:00 JST

Retrieved        Proxy Median  Mid Cloud  Vis km  Models
Aug 21 08:00        76            18%      30       5
Aug 21 11:00        80            14%      33       5
Aug 21 14:00        83            11%      36       5
Aug 21 17:00        86             8%      39       5

Trend: IMPROVING
Stability: HIGH
6h delta: +6
12h delta: +10
```

Add optional ASCII sparkline only if trivial.

Do not make charting a dependency.

---

# 14. `decide` Command

This is the primary Phase 2 user-facing feature.

Add:

```bash
fuji decide \
  --dates 2026-08-25,2026-08-26 \
  --location kawaguchiko \
  --hours 5-12 \
  --arrival-after 08:00
```

Optional:

```bash
--models all
--min-window-hours 2
--good-proxy 75
--json
```

---

# 15. Decision Inputs

For every reachable hour calculate / gather:

```text
proxy median
proxy range
model consensus label
forecast stability label
trend label
mid-cloud median
visibility median
precipitation median
```

Then identify contiguous candidate windows.

Do not rank unreachable hours.

---

# 16. Candidate Window Construction

For each day:

1. remove hours before `arrival_after`
2. find hours where:
   - proxy median >= configured minimum
   - consensus is not LOW
3. group adjacent qualifying hours
4. calculate window statistics

Window statistics:

```text
start
end
duration
peak hour
peak proxy median
window mean proxy
minimum proxy
consensus distribution
stability
trend
mid-cloud maximum
visibility minimum
```

A 2-hour stable window should normally beat one isolated excellent hour.

---

# 17. Decision Ranking

Do not create one hidden magical score unless necessary.

Prefer lexicographic / rules-based ranking.

Suggested priority:

1. reachable window exists
2. consensus quality
3. stability confidence
4. window duration
5. proxy median
6. trend direction
7. precipitation / cloud risk

Example conceptual ranking:

```text
HIGH consensus + HIGH stability + 2h window
>
HIGH consensus + LOW stability + 1h peak
>
MEDIUM consensus + HIGH stability + 2h window
```

If an internal composite is used, expose its components and formula.

---

# 18. `decide` Output

Desired output:

```text
Mt Fuji Decision
Location: Kawaguchiko
Reachable from: 08:00 JST

RECOMMENDED: WED 2026-08-26

Best reachable window:
08:00–10:00 JST

Peak:
09:00
Proxy median: 86
Model consensus: HIGH
Forecast stability: HIGH
Trend: IMPROVING

Model agreement:
4/5 models rate 09:00 >= 75
Proxy range: 81–91

Weather:
Mid cloud median: 7%
Visibility median: 39 km
Rain median: 5%

Main risk:
Mid-level cloud increases rapidly after 10:00.

TUE 2026-08-25

Best reachable window:
08:00–09:00 JST

Peak proxy median: 82
Model consensus: MEDIUM
Forecast stability: LOW
Trend: VOLATILE

Why Wednesday wins:
- longer reachable window
- stronger multi-model agreement
- more stable recent forecast
- similar peak quality
```

---

# 19. Decision Ambiguity

The tool must be allowed to return:

```text
NO CLEAR WINNER
```

Example:

```text
Tuesday and Wednesday are too close to distinguish reliably.

Tuesday:
Proxy median 84
Consensus HIGH
Stability MEDIUM

Wednesday:
Proxy median 85
Consensus HIGH
Stability MEDIUM

Difference is below configured decision threshold.
Recheck after the next model cycle.
```

This is preferable to false precision.

---

# 20. Decision Thresholds

Add config:

```text
DECISION_MIN_PROXY_DIFFERENCE = 5
DECISION_MIN_WINDOW_HOURS = 2
DECISION_MIN_FULL_MODELS = 3
```

If differences are below the threshold, return:

```text
NO CLEAR WINNER
```

unless one day has materially better stability / consensus.

---

# 21. Reachability

Existing arrival cutoff should remain a hard constraint.

Example:

```text
--arrival-after 08:00
```

Hours:

```text
05:00
06:00
07:00
```

may be displayed for context but must never influence:

```text
best reachable hour
best reachable window
day recommendation
```

This requirement is important.

---

# 22. Separate Forecast Quality from Confidence

Avoid output such as:

```text
Score 90 = highly confident
```

Instead:

```text
Forecast Quality: EXCELLENT
Proxy: 90

Model Consensus: LOW
Forecast Stability: LOW
```

This communicates:

```text
the weather forecast is excellent if correct,
but the forecast itself is not stable.
```

---

# 23. Database Changes

Current schema can likely be reused if snapshots already store model identity.

If not, ensure `model` is indexed.

Recommended indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_snapshots_model
ON forecast_snapshots(model);

CREATE INDEX IF NOT EXISTS idx_hourly_snapshot_time
ON hourly_forecasts(snapshot_id, valid_time);
```

For trend queries:

```sql
CREATE INDEX IF NOT EXISTS idx_snapshot_location_model_time
ON forecast_snapshots(requested_lat, requested_lon, model, retrieved_at);
```

Do not introduce a new database unless necessary.

---

# 24. Consensus Persistence

Do not store consensus rows as source-of-truth data.

Consensus is derived from underlying model snapshots.

It can be recalculated.

If caching is later needed, create an explicit derived cache table, but not in Phase 2 unless performance requires it.

---

# 25. API Failure Handling

Consensus must tolerate partial model failure.

Example:

```text
Requested 6 models

5 successful
1 unavailable

Consensus calculated from 5 models.
```

If fewer than 3 full models succeed:

```text
Consensus: INSUFFICIENT_DATA
```

The command may still display the available forecasts.

It must not silently treat one model as a consensus.

---

# 26. Model Weighting

MVP Phase 2 should use equal weighting.

Do not assign subjective model weights yet.

Future versions may learn empirical model performance from webcam observations.

For now:

```text
one model = one vote
```

Exception:

`auto` may overlap conceptually with individual Open-Meteo models.

Document this.

Optionally provide:

```bash
--exclude-auto-from-voting
```

but this is not required for initial Phase 2.

---

# 27. Raw Diagnostic Export

Extend export support.

Example:

```bash
fuji export consensus \
  2026-08-25 2026-08-26 \
  --hours 5-12 \
  --format csv
```

Columns should include:

```text
valid_time
model
proxy
cloud_mid
visibility_km
precip_probability
humidity
reachable
```

Also support consensus aggregate JSON.

This will make later debugging and manual analysis easier.

---

# 28. Mountain-Aware Forecasting — Future Architecture

Do not fully implement this in Phase 2.

Prepare interfaces so the forecast target is not permanently assumed to be one point.

Future concept:

```text
observer point:
    Oishi Park
    Shojiko

mountain / sightline points:
    north slope
    summit vicinity
    intermediate line-of-sight sample points
```

Potential inputs:

```text
surface low/mid/high cloud
pressure-level RH
pressure-level cloud cover
wind direction
wind speed
temperature
dew point
```

Possible pressure levels:

```text
700 hPa
600 hPa
500 hPa
400 hPa
```

No Phase 2 decision logic should depend on this yet.

---

# 29. Optional Webcam Validation Roadmap

Do not implement automated image analysis now.

But document a future validation dataset:

```text
timestamp
observer location
actual Fuji visibility
clear / partial / hidden
manual confidence
photo / webcam source
```

Eventually compare forecast variables against actual visibility.

This would allow:

- evaluating which model performs best
- tuning the Fuji Proxy Score
- testing whether mid-cloud is actually the best cloud variable
- learning optimal thresholds

For now, keep this as a future roadmap item.

---

# 30. Tests

Add offline unit tests for:

- consensus median / range
- consensus label thresholds
- insufficient model data
- outlier detection
- stability metrics
- improving classification
- worsening classification
- volatile classification
- candidate window grouping
- arrival cutoff
- `NO CLEAR WINNER`
- decision ranking
- partial API failure
- model capability handling

Synthetic forecast sequences should be used.

Do not make tests depend on live weather.

---

# 31. Suggested Test Fixtures

Create synthetic cases.

## Stable excellent

```text
snapshots:
82, 84, 85, 86

models:
84, 85, 86, 87, 84
```

Expected:

```text
Consensus HIGH
Stability HIGH
Trend IMPROVING
```

## Volatile excellent

```text
snapshots:
55, 91, 60, 90

models:
89, 91, 42, 88, 50
```

Expected:

```text
Consensus LOW or MEDIUM
Stability LOW
Trend VOLATILE
```

## Stable medium

```text
snapshots:
70, 71, 70, 72

models:
69, 71, 72, 70
```

Expected:

```text
Stability HIGH
```

## Arrival cutoff

```text
07:00 Proxy 96
08:00 Proxy 82
09:00 Proxy 80
arrival_after = 08:00
```

Expected:

```text
07:00 never selected
best reachable window starts at 08:00
```

---

# 32. CLI Backward Compatibility

Existing commands must continue to work.

Do not break:

```text
forecast
compare
snapshot
trend
fingerprint
fingerprint-history
previous-runs
export
```

If data models are changed, add migrations or backward-compatible reads for the current SQLite database.

Do not require the user to delete existing forecast history.

---

# 33. README Changes

Add a section:

```text
## How to use this tool for a real trip decision
```

Suggested workflow:

```bash
# Start collecting forecasts several days in advance
fuji snapshot --location kawaguchiko --days 7 --models all

# Repeat roughly every 3 hours

# Compare candidate days
fuji consensus 2026-08-25 2026-08-26 \
  --hours 5-12 \
  --arrival-after 08:00

# Inspect forecast drift
fuji trend 2026-08-26 \
  --hour 09:00 \
  --consensus

# Make the final comparison
fuji decide \
  --dates 2026-08-25,2026-08-26 \
  --hours 5-12 \
  --arrival-after 08:00
```

Explain that:

- forecasts 4–5 days out are useful for identifying candidate days
- exact hourly ranking should not be trusted too early
- stability and model agreement matter more as the trip approaches
- final departure should still be checked against short-term weather and live webcams

---

# 34. Implementation Order

## Milestone 1 — Multi-model query layer

Deliver:

- model capability validation
- multiple-model fetch
- graceful field / model failure handling

Acceptance:

```bash
fuji consensus <date>
```

can successfully query multiple models.

---

## Milestone 2 — Consensus statistics

Deliver:

- medians
- ranges
- stddev
- threshold agreement
- consensus labels
- outlier flags

Acceptance:

Hourly consensus table is meaningful and covered by tests.

---

## Milestone 3 — Multi-model snapshots

Deliver:

```bash
fuji snapshot --models all
```

Acceptance:

SQLite stores separate model snapshots without breaking current history.

---

## Milestone 4 — Stability metrics

Deliver:

- 6h / 12h / 24h drift
- standard deviation
- improving / worsening / volatile labels
- stability confidence

Acceptance:

Synthetic trend tests pass.

---

## Milestone 5 — Consensus trend

Deliver:

```bash
fuji trend <date> --hour <time> --consensus
```

Acceptance:

Displays evolution of median model forecast across snapshots.

---

## Milestone 6 — `decide`

Deliver:

```bash
fuji decide
```

Acceptance:

- respects arrival cutoff
- prefers stable multi-hour windows
- compares candidate days
- can return `NO CLEAR WINNER`
- explains recommendation

---

## Milestone 7 — Documentation / exports

Deliver:

- README real-trip workflow
- consensus CSV / JSON export
- scheduler examples

---

# 35. Definition of Done

Phase 2 is complete when:

- [ ] Multiple forecast models can be queried for the same hour.
- [ ] Unsupported / incomplete models are skipped gracefully.
- [ ] Consensus median / range / stddev are available.
- [ ] Consensus quality is labeled separately from forecast quality.
- [ ] Multi-model snapshots are persisted.
- [ ] Forecast drift can be calculated across saved snapshots.
- [ ] Trend is labeled STABLE / IMPROVING / WORSENING / VOLATILE.
- [ ] Stability confidence is available.
- [ ] Reachability remains a hard constraint.
- [ ] Candidate multi-hour windows can be found.
- [ ] `decide` compares candidate days.
- [ ] `decide` explains why one day wins.
- [ ] `decide` can return NO CLEAR WINNER.
- [ ] Existing CLI commands remain backward-compatible.
- [ ] Existing SQLite history remains usable.
- [ ] New functionality is covered by offline tests.
- [ ] README documents repeated snapshot collection.
- [ ] No frontend is required.
- [ ] No output conflates stability with actual forecast accuracy.

---

# 36. Codex Working Instructions

When implementing this Phase 2 specification:

1. Read the existing implementation before changing architecture.
2. Preserve the current working CLI.
3. Do not rewrite Phase 1 unless necessary.
4. Reuse existing forecast models, storage, scoring, and formatting code.
5. Make database changes backward-compatible.
6. Implement milestones in order.
7. Keep consensus, stability, and weather quality as separate concepts.
8. Avoid hidden composite heuristics.
9. Keep thresholds configurable.
10. Use offline synthetic tests for decision logic.
11. Do not add a web frontend.
12. Do not add automated Is It Visible scraping.
13. Do not spend Phase 2 time tuning the Proxy Score against one forecast snapshot.
14. Document any Open-Meteo model/API differences discovered during implementation.
15. At completion run:
    - full test suite
    - one live `consensus`
    - one `snapshot --models all`
    - one `trend --consensus`
    - one `decide`
16. Report:
    - files modified
    - schema changes
    - model list used
    - skipped / unsupported models
    - test results
    - live command results
    - unresolved limitations

---

# 37. Suggested Validation Scenario

Use the current candidate dates as a real integration scenario:

```text
2026-08-25
2026-08-26
```

Assume:

```text
earliest realistic useful arrival:
08:00 JST
```

Run:

```bash
fuji snapshot \
  --location kawaguchiko \
  --days 7 \
  --models all
```

Then:

```bash
fuji consensus 2026-08-25 2026-08-26 \
  --location kawaguchiko \
  --hours 5-12 \
  --arrival-after 08:00
```

Then:

```bash
fuji decide \
  --dates 2026-08-25,2026-08-26 \
  --location kawaguchiko \
  --hours 5-12 \
  --arrival-after 08:00
```

The tool should not assume the previously observed:

```text
2026-08-26 09:00 Proxy 87
```

is still correct.

It must use the latest data and saved forecast history.

---

# 38. Expected End State

After Phase 2, the tool should be able to answer:

```text
Which day has the best weather?
```

and, more importantly:

```text
Which reachable day has the best combination of:
- visibility forecast
- cloud conditions
- multi-model agreement
- forecast stability
- usable window length?
```

The output should make it obvious when:

```text
a high score is trustworthy
```

versus:

```text
a high score is only one unstable model run.
```

That distinction is the primary objective of Phase 2.
