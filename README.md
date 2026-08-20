# Fuji Visibility

`fuji` is a small CLI for inspecting the hourly Open-Meteo inputs that matter
for Mt. Fuji visibility around the Fuji Five Lakes area. It is deliberately a
CLI + SQLite + JSON/CSV-style data pipeline; it does not scrape Is It Visible
or claim to reproduce its private score.

## Highlights

- Hourly forecasts normalized to JST with raw API responses retained locally.
- Transparent Fuji Proxy Score based on visibility, cloud, precipitation, and
  humidity inputs.
- Multi-model consensus with partial-model diagnostics, threshold agreement,
  standard deviation, and outlier flags.
- Forecast stability across repeated snapshots, including trend and confidence
  labels.
- A rules-based `decide` command that respects arrival time and prefers usable
  multi-hour windows.

The project intentionally has no web frontend, background daemon, webcam
scraper, or claim of forecast accuracy. Consensus uses equal model votes, and
stability measures consistency between forecast runs rather than truth.

## Setup

This project uses `uv` and requires Python 3.12 or newer.

```bash
uv sync --extra dev
uv run fuji locations
```

If the default uv cache is not writable in a managed environment, set a
task-local cache directory, for example:

```bash
UV_CACHE_DIR=/tmp/fuji-visibility-uv-cache uv sync --extra dev
```

## Commands

Display all required hourly inputs for a day:

```bash
uv run fuji forecast 2026-08-25 \
  --location kawaguchiko \
  --hours 5-12
```

Compare days while excluding pre-arrival hours from the recommendation:

```bash
uv run fuji compare 2026-08-25 2026-08-26 \
  --location kawaguchiko \
  --hours 5-12 \
  --arrival-after 08:00
```

Use arbitrary coordinates with `--lat` and `--lon` together. Named presets
are editable in `src/fuji_visibility/config.py`.

Save a live forecast and its exact response body, then inspect drift after a
second snapshot:

```bash
uv run fuji snapshot --location kawaguchiko --days 7
uv run fuji snapshot --location kawaguchiko --days 7
uv run fuji trend 2026-08-26 --hour 09:00 --location kawaguchiko
```

The default SQLite database is `data/fuji_forecasts.sqlite`; raw responses are
stored in `data/raw/`. Override both with global `--db-path` and `--raw-dir`.

Export normalized rows (including the unrounded Proxy Score) as CSV or JSON:

```bash
uv run fuji export 2026-08-25 --hours 5-12 --format csv --output forecast.csv
uv run fuji export 2026-08-25 --hours 5-12 --format json --output forecast.json
```

Try the supplied public screenshot fingerprint against the current forecast:

```bash
uv run fuji fingerprint \
  --input data/fingerprints/isitvisible_2026-08-21_0730_jst.json \
  --radius-deg 0.01 \
  --step-deg 0.01 \
  --models auto
```

The full default grid/model search can make many API requests. Narrow the
radius, step, or model list while experimenting. Unsupported model identifiers
are reported and skipped. To search archived model initializations:

```bash
uv run fuji fingerprint-history \
  --input data/fingerprints/isitvisible_2026-08-21_0730_jst.json \
  --search-from 2026-08-20T00:00:00Z \
  --search-to 2026-08-20T23:59:59Z \
  --radius-deg 0.01 \
  --step-deg 0.01 \
  --models auto
```

`previous-runs` exposes fixed lead-time values where the selected Open-Meteo
model has archived them:

```bash
uv run fuji previous-runs 2026-08-26 --hour 09:00 --model auto
```

Add `--verbose` before the command for request parameters, response metadata,
and fingerprint progress.

## How to use this tool for a real trip decision

Collect independent model snapshots roughly every three hours while a trip is
approaching:

```bash
uv run fuji snapshot --location kawaguchiko --days 7 --models all
```

The configured model list is validated by attempting the requested hourly
variables. Unsupported models and models with incomplete fields are retained as
diagnostics but are not silently counted as full consensus members.

Compare the current multi-model view:

```bash
uv run fuji consensus 2026-08-25 2026-08-26 \
  --location kawaguchiko \
  --hours 5-12 \
  --arrival-after 08:00 \
  --show-models
```

Inspect the saved consensus drift for one hour:

```bash
uv run fuji trend 2026-08-26 --hour 09:00 \
  --location kawaguchiko --consensus
```

Make the final rules-based comparison:

```bash
uv run fuji decide \
  --dates 2026-08-25,2026-08-26 \
  --location kawaguchiko \
  --hours 5-12 \
  --arrival-after 08:00
```

`decide` keeps these dimensions separate: Proxy quality, model consensus,
forecast stability, trend direction, reachability, and usable window length.
It can return `NO CLEAR WINNER`; a high Proxy value is not treated as high
confidence by itself. Use `--json` for machine-readable decision evidence.

Consensus diagnostics can also be exported:

```bash
uv run fuji export consensus 2026-08-25 2026-08-26 \
  --hours 5-12 --format csv --output consensus.csv
```

Consensus uses equal model votes. The configured `auto` member may overlap
conceptually with an explicit provider model, so it is evidence of the current
Open-Meteo best-match forecast, not an independent physical model.

Local scheduling is intentionally outside the application. For example, a
Unix cron entry can collect every three hours:

```cron
0 */3 * * * cd /path/to/fuji-visibility && uv run fuji snapshot --location kawaguchiko --days 7 --models all
```

Equivalent local schedulers can invoke the same command:

- `systemd --user`: put the command in `fuji-snapshot.service` and trigger it
  from a `fuji-snapshot.timer` with `OnCalendar=*:0/3`.
- `launchd`: use a LaunchAgent with `StartInterval` set to `10800` seconds and
  `ProgramArguments` containing `uv`, `run`, `fuji`, `snapshot`, and the same
  options.
- Windows Task Scheduler: create a task running `uv.exe run fuji snapshot
  --location kawaguchiko --days 7 --models all`, repeating every 3 hours.

These schedulers are examples only; the application itself does not run a
background daemon.

Forecast stability measures consistency between successive saved forecasts,
not forecast accuracy. As the trip approaches, check short-term weather and
live webcams as well.

## Fuji Proxy Score

The displayed score is explicitly named **Fuji Proxy Score**. It uses the
published Is It Visible component weights—visibility 40%, cloud 30%,
precipitation 20%, humidity 10%—but uses transparent piecewise-linear
breakpoints defined in `config.py`, because the original normalization
functions are not public. The default cloud strategy is `mid`, reflecting the
fact that Fuji's summit is near the lower part of Open-Meteo's mid-cloud band.

Choose another interpretation with `--cloud-strategy total`, `mid`,
`low_mid_max`, `low_mid_weighted`, or `mid_high_weighted`. A missing required
input produces an unavailable score rather than an implicit substitute.

## Tests

The default suite is offline and uses fixed response fixtures:

```bash
uv run pytest
```

Any live test is marked `integration` and is not part of the default suite.

## Data-source notes

The forecast client follows the current Open-Meteo Forecast API request shape
and preserves all raw JSON for later inspection. The Single Runs and Previous
Runs clients use their dedicated current API hosts. See the official
[Forecast API documentation](https://open-meteo.com/en/docs),
[Single Runs API documentation](https://open-meteo.com/en/docs/single-runs-api),
and [Previous Runs API documentation](https://open-meteo.com/en/docs/previous-runs-api)
for model availability and archive limits.
