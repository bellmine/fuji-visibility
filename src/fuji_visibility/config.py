"""Configuration shared by the API, storage, scoring, and CLI layers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


TIMEZONE = "Asia/Tokyo"
PROVIDER = "open-meteo"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
SINGLE_RUNS_URL = "https://single-runs-api.open-meteo.com/v1/forecast"
PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_DATABASE_PATH = DATA_DIR / "fuji_forecasts.sqlite"
DEFAULT_RAW_DATA_PATH = DATA_DIR / "raw"


@dataclass(frozen=True)
class LocationPreset:
    name: str
    latitude: float
    longitude: float
    description: str


# These are intentionally editable presets, not claims about the private
# coordinates used by Is It Visible.
LOCATION_PRESETS: dict[str, LocationPreset] = {
    "kawaguchiko": LocationPreset(
        name="kawaguchiko",
        latitude=35.520,
        longitude=138.750,
        description="Lake Kawaguchiko search center",
    ),
    "oishi": LocationPreset(
        name="oishi",
        latitude=35.517,
        longitude=138.745,
        description="Oishi Park area",
    ),
    "shojiko": LocationPreset(
        name="shojiko",
        latitude=35.493,
        longitude=138.665,
        description="Lake Shojiko area",
    ),
}

DEFAULT_LOCATION = "kawaguchiko"

HOURLY_VARIABLES: tuple[str, ...] = (
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation_probability",
    "cloud_cover",
    "cloud_cover_low",
    "cloud_cover_mid",
    "cloud_cover_high",
    "visibility",
    "wind_speed_10m",
    "wind_direction_10m",
)

# Kept separate so pressure diagnostics can be added without changing the
# normalized hourly model or the basic score.
PRESSURE_LEVELS = (700, 600, 500, 400)

# Candidate model names are best-effort. Open-Meteo can add/remove model
# identifiers; consensus and fingerprint search treat unsupported models as
# skippable candidates and print the API's actionable error.
CANDIDATE_MODELS: tuple[str, ...] = (
    "auto",
    "jma_seamless",
    "jma_msm",
    "jma_gsm",
    "gfs_seamless",
    "ecmwf_ifs025",
)

# Backward-compatible name used by the Phase 1 fingerprint command.
DEFAULT_CANDIDATE_MODELS = CANDIDATE_MODELS

MODEL_REQUIRED_VARIABLES: frozenset[str] = frozenset(
    {
        "cloud_cover_mid",
        "relative_humidity_2m",
        "precipitation_probability",
    }
)
MODEL_FULL_VARIABLES: frozenset[str] = frozenset(
    set(MODEL_REQUIRED_VARIABLES) | {"visibility"}
)
MODEL_OPTIONAL_VARIABLES: frozenset[str] = frozenset(
    {"temperature_2m", "cloud_cover_low", "cloud_cover_high"}
)

GOOD_PROXY_THRESHOLD = 75.0
GOOD_MID_CLOUD_THRESHOLD = 25.0
GOOD_VISIBILITY_THRESHOLD_KM = 25.0
GOOD_PRECIP_THRESHOLD = 30.0

CONSENSUS_HIGH_MIN_FULL_MODELS = 4
CONSENSUS_MEDIUM_MIN_FULL_MODELS = 3
CONSENSUS_HIGH_GOOD_RATIO = 0.75
CONSENSUS_MEDIUM_GOOD_RATIO = 0.50
CONSENSUS_HIGH_PROXY_STDDEV = 8.0
CONSENSUS_MEDIUM_PROXY_STDDEV = 15.0
CONSENSUS_HIGH_MID_CLOUD_STDDEV = 15.0

STABILITY_HISTORY_HOURS = (6, 12, 24)
STABILITY_IMPROVING_DELTA = 5.0
STABILITY_WORSENING_DELTA = -5.0
STABILITY_STABLE_STDDEV = 6.0
STABILITY_MEDIUM_STDDEV = 12.0
STABILITY_VOLATILE_STDDEV = 10.0
STABILITY_MID_CLOUD_HIGH_STDDEV = 12.0
STABILITY_LARGE_REVERSAL = 15.0
STABILITY_MIN_SNAPSHOTS = 3
STABILITY_HIGH_MIN_SNAPSHOTS = 4

DECISION_MIN_PROXY_DIFFERENCE = 5.0
DECISION_MIN_WINDOW_HOURS = 2
DECISION_MIN_FULL_MODELS = 3

DEFAULT_CLOUD_MAPPINGS: tuple[str, ...] = (
    "total",
    "mid",
    "low_mid_max",
    "low_mid_weighted",
    "mid_high_weighted",
)

REQUEST_TIMEOUT_SECONDS = 20.0
FINGERPRINT_TEMP_SCALE = 1.0
FINGERPRINT_CLOUD_SCALE = 10.0
FINGERPRINT_VISIBILITY_SCALE = 10.0

SCORE_BREAKPOINTS: dict[str, tuple[tuple[float, float], ...]] = {
    # These are transparent proxy choices, not Is It Visible's undisclosed
    # normalization functions.
    "cloud": ((0, 100), (20, 85), (50, 60), (80, 30), (100, 0)),
    "precipitation": ((0, 100), (10, 90), (30, 65), (60, 30), (100, 0)),
    "humidity": ((30, 100), (40, 90), (60, 70), (80, 35), (100, 0)),
    "visibility": ((0, 0), (10, 25), (20, 45), (30, 65), (40, 82), (50, 95), (60, 100)),
}

PROXY_WEIGHTS: dict[str, float] = {
    "visibility": 0.40,
    "cloud": 0.30,
    "precipitation": 0.20,
    "humidity": 0.10,
}
