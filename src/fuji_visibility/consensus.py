"""Multi-model forecast fetching and transparent consensus statistics."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from statistics import median, pstdev
from typing import Iterable, Sequence

from .config import (
    CANDIDATE_MODELS,
    CONSENSUS_HIGH_GOOD_RATIO,
    CONSENSUS_HIGH_MIN_FULL_MODELS,
    CONSENSUS_HIGH_MID_CLOUD_STDDEV,
    CONSENSUS_HIGH_PROXY_STDDEV,
    CONSENSUS_MEDIUM_GOOD_RATIO,
    CONSENSUS_MEDIUM_MIN_FULL_MODELS,
    CONSENSUS_MEDIUM_PROXY_STDDEV,
    FIELD_SUPPORT_MODERATE_GOOD_RATIO,
    FIELD_SUPPORT_MODERATE_MIN_MODELS,
    FIELD_SUPPORT_STRONG_GOOD_RATIO,
    FIELD_SUPPORT_STRONG_MIN_MODELS,
    GOOD_HUMIDITY_MAX,
    GOOD_MID_CLOUD_MAX,
    GOOD_PRECIP_MAX,
    GOOD_VISIBILITY_MIN_KM,
    MAX_PROXY_SPREAD_FOR_STRONG_SUPPORT,
    MAX_PROXY_SPREAD_FOR_WEAK_SUPPORT,
    MIN_FULL_PROXY_MODELS,
    MIN_PROXY,
    MODEL_OPTIONAL_VARIABLES,
    MODEL_REQUIRED_VARIABLES,
)
from .models import (
    ForecastResult,
    HourlyForecast,
    ModelCapability,
    ProxyScore,
    StoredForecast,
)
from .open_meteo import OpenMeteoClient, OpenMeteoError
from .scoring import proxy_score
from .time_utils import canonical_iso, to_jst


@dataclass(frozen=True)
class ConsensusFailure:
    model: str
    reason: str


@dataclass(frozen=True)
class ForecastMember:
    model: str
    forecast: ForecastResult
    capability: ModelCapability

    @property
    def full_forecast(self) -> bool:
        return self.capability.full_forecast_available


@dataclass(frozen=True)
class ConsensusMemberValue:
    model: str
    record: HourlyForecast
    proxy: ProxyScore
    full_model: bool
    outlier: bool = False
    capability_status: str = "PARTIAL_USEFUL"
    supports: dict[str, bool] = field(default_factory=dict)


@dataclass(frozen=True)
class FieldConsensus:
    """Evidence and voting summary for one normalized forecast field."""

    field: str
    model_count: int = 0
    values: tuple[float, ...] = ()
    median: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    stddev: float | None = None
    good_votes: int = 0
    support: str = "INSUFFICIENT"
    good_threshold: float = 0.0
    good_when: str = "below_or_equal"

    @property
    def min(self) -> float | None:  # noqa: A003 - public diagnostic field name
        return self.minimum

    @property
    def max(self) -> float | None:  # noqa: A003 - public diagnostic field name
        return self.maximum

    @property
    def good_ratio(self) -> float | None:
        return None if not self.model_count else self.good_votes / self.model_count

    def payload(self) -> dict[str, object]:
        return {
            "model_count": self.model_count,
            "values": list(self.values),
            "median": self.median,
            "min": self.minimum,
            "max": self.maximum,
            "stddev": self.stddev,
            "good_votes": self.good_votes,
            "good_ratio": self.good_ratio,
            "support": self.support,
            "good_threshold": self.good_threshold,
            "good_when": self.good_when,
        }


@dataclass(frozen=True)
class ConsensusHour:
    valid_time: datetime
    model_count: int
    full_model_count: int
    partial_model_count: int
    proxy_median: float | None
    proxy_min: float | None
    proxy_max: float | None
    proxy_stddev: float | None
    mid_cloud_median: float | None
    mid_cloud_min: float | None
    mid_cloud_max: float | None
    mid_cloud_stddev: float | None
    visibility_median_km: float | None
    visibility_min_km: float | None
    visibility_max_km: float | None
    visibility_stddev_km: float | None
    precip_median: float | None
    humidity_median: float | None
    models_good_proxy: int
    models_good_mid_cloud: int
    models_good_visibility: int
    consensus_label: str
    outlier_models: tuple[str, ...]
    members: tuple[ConsensusMemberValue, ...]
    models_good_precip: int = 0
    # Phase 3.1 field-level evidence.  Defaults keep Phase 2 callers that
    # construct ConsensusHour directly source-compatible.
    full_proxy_model_count: int | None = None
    proxy_values: tuple[float, ...] = ()
    proxy_spread: float | None = None
    proxy_agreement: str = "INSUFFICIENT"
    mid_cloud_model_count: int = 0
    mid_cloud_values: tuple[float, ...] = ()
    mid_cloud_good_votes: int = 0
    visibility_model_count: int = 0
    visibility_values_km: tuple[float, ...] = ()
    visibility_good_votes: int = 0
    precip_model_count: int = 0
    precip_values: tuple[float, ...] = ()
    precip_max: float | None = None
    precip_good_votes: int = 0
    humidity_model_count: int = 0
    humidity_values: tuple[float, ...] = ()
    humidity_max: float | None = None
    humidity_good_votes: int = 0
    field_consensus: dict[str, FieldConsensus] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.full_proxy_model_count is None:
            object.__setattr__(self, "full_proxy_model_count", self.full_model_count)
        if self.proxy_spread is None and self.proxy_min is not None and self.proxy_max is not None:
            object.__setattr__(self, "proxy_spread", self.proxy_max - self.proxy_min)
        if self.proxy_agreement == "INSUFFICIENT" and self.proxy_spread is not None:
            object.__setattr__(self, "proxy_agreement", _proxy_agreement(self.proxy_spread, self.full_proxy_model_count or 0))

    @property
    def proxy_range(self) -> tuple[float | None, float | None]:
        return self.proxy_min, self.proxy_max

    @property
    def field_consensus_summary(self) -> dict[str, dict[str, object]]:
        return {name: evidence.payload() for name, evidence in self.field_consensus.items()}

    @property
    def proxy_payload(self) -> dict[str, object]:
        return {
            "model_count": self.full_proxy_model_count or 0,
            "values": list(self.proxy_values),
            "median": self.proxy_median,
            "min": self.proxy_min,
            "max": self.proxy_max,
            "spread": self.proxy_spread,
            "stddev": self.proxy_stddev,
            "agreement": self.proxy_agreement,
        }

    @property
    def reachable(self) -> bool:
        # Kept as a convenience for callers that have already filtered hours;
        # actual reachability is a user-specific decision and is calculated by
        # the CLI/decision layer.
        return True


@dataclass(frozen=True)
class ConsensusResult:
    requested_models: tuple[str, ...]
    members: tuple[ForecastMember, ...]
    failures: tuple[ConsensusFailure, ...]
    hours: tuple[ConsensusHour, ...]
    requested_lat: float
    requested_lon: float

    @property
    def model_count(self) -> int:
        return len(self.members)

    def hour_map(self) -> dict[str, ConsensusHour]:
        return {canonical_iso(hour.valid_time): hour for hour in self.hours}


class ModelCapabilityCache:
    """Process-local cache for accepted/unsupported model probes."""

    def __init__(self) -> None:
        self._items: dict[str, ModelCapability] = {}

    def get(self, model: str) -> ModelCapability | None:
        return self._items.get(model)

    def put(self, capability: ModelCapability) -> None:
        self._items[capability.model] = capability

    def clear(self) -> None:
        self._items.clear()


def capability_from_forecast(result: ForecastResult) -> ModelCapability:
    """Inspect a successful response without issuing a second probe request."""

    hourly = result.raw_payload.get("hourly", {})
    available: set[str] = set()
    if isinstance(hourly, dict):
        for variable, values in hourly.items():
            if variable == "time":
                continue
            if isinstance(values, list) and any(value is not None for value in values):
                available.add(variable)
    missing_required = set(MODEL_REQUIRED_VARIABLES - available)
    missing_optional = set(MODEL_OPTIONAL_VARIABLES - available)
    # Visibility is needed for a complete Fuji Proxy member but remains an
    # optional capability field so the model can still support cloud-only
    # consensus when it is absent.
    if "visibility" not in available:
        missing_optional.add("visibility")
    return ModelCapability(
        model=result.model,
        supported=True,
        variables_available=available,
        missing_required=missing_required,
        missing_optional=missing_optional,
    )


def unsupported_capability(model: str, reason: str) -> ModelCapability:
    return ModelCapability(model=model, supported=False, error=reason)


class ConsensusFetcher:
    """Fetch each configured model once and derive hourly consensus."""

    def __init__(
        self,
        client: OpenMeteoClient,
        *,
        capability_cache: ModelCapabilityCache | None = None,
    ) -> None:
        self.client = client
        self.capability_cache = capability_cache or ModelCapabilityCache()

    def fetch(
        self,
        latitude: float,
        longitude: float,
        *,
        models: Sequence[str] = CANDIDATE_MODELS,
        model_kwargs: dict[str, object] | None = None,
        cloud_strategy: str = "mid",
    ) -> ConsensusResult:
        kwargs = dict(model_kwargs or {})
        requested = _unique_models(models)
        members: list[ForecastMember] = []
        failures: list[ConsensusFailure] = []
        for model in requested:
            cached = self.capability_cache.get(model)
            if cached is not None and not cached.supported:
                failures.append(ConsensusFailure(model, cached.error or "model is unsupported"))
                continue
            try:
                forecast = self.client.fetch_forecast(
                    latitude,
                    longitude,
                    model=model,
                    **kwargs,
                )
            except OpenMeteoError as exc:
                capability = unsupported_capability(model, str(exc))
                self.capability_cache.put(capability)
                failures.append(ConsensusFailure(model, str(exc)))
                continue
            capability = capability_from_forecast(forecast)
            self.capability_cache.put(capability)
            members.append(ForecastMember(model=model, forecast=forecast, capability=capability))
        return build_consensus(
            members,
            requested_models=requested,
            failures=failures,
            latitude=latitude,
            longitude=longitude,
            cloud_strategy=cloud_strategy,
        )


def build_consensus(
    members: Sequence[ForecastMember],
    *,
    requested_models: Sequence[str] | None = None,
    failures: Sequence[ConsensusFailure] = (),
    latitude: float = 0.0,
    longitude: float = 0.0,
    cloud_strategy: str = "mid",
    good_mid_cloud_max: float = GOOD_MID_CLOUD_MAX,
    good_visibility_min_km: float = GOOD_VISIBILITY_MIN_KM,
    good_precip_max: float = GOOD_PRECIP_MAX,
    good_humidity_max: float = GOOD_HUMIDITY_MAX,
) -> ConsensusResult:
    """Calculate medians/ranges from successful model members only."""

    times: set[str] = set()
    by_model: dict[str, dict[str, HourlyForecast]] = {}
    for member in members:
        rows = {canonical_iso(row.valid_time): row for row in member.forecast.hours}
        by_model[member.model] = rows
        times.update(rows)

    hours: list[ConsensusHour] = []
    for key in sorted(times):
        rows: list[ConsensusMemberValue] = []
        for member in members:
            record = by_model[member.model].get(key)
            if record is None:
                continue
            rows.append(
                ConsensusMemberValue(
                    model=member.model,
                    record=record,
                    proxy=proxy_score(record, cloud_strategy),
                    full_model=member.full_forecast,
                    capability_status=member.capability.status,
                    supports=member.capability.supports,
                )
            )
        hours.append(
            _build_hour(
                rows,
                key,
                good_mid_cloud_max=good_mid_cloud_max,
                good_visibility_min_km=good_visibility_min_km,
                good_precip_max=good_precip_max,
                good_humidity_max=good_humidity_max,
            )
        )
    return ConsensusResult(
        requested_models=tuple(requested_models or _unique_models(member.model for member in members)),
        members=tuple(members),
        failures=tuple(failures),
        hours=tuple(hours),
        requested_lat=latitude,
        requested_lon=longitude,
    )


def build_consensus_from_stored(
    rows: Iterable[StoredForecast],
    *,
    requested_models: Sequence[str] = CANDIDATE_MODELS,
    failures: Sequence[ConsensusFailure] = (),
    latitude: float | None = None,
    longitude: float | None = None,
    cloud_strategy: str = "mid",
    good_mid_cloud_max: float = GOOD_MID_CLOUD_MAX,
    good_visibility_min_km: float = GOOD_VISIBILITY_MIN_KM,
    good_precip_max: float = GOOD_PRECIP_MAX,
    good_humidity_max: float = GOOD_HUMIDITY_MAX,
) -> ConsensusResult:
    """Derive the same consensus statistics from persisted model snapshots.

    The web dashboard intentionally reads stored snapshots instead of calling
    Open-Meteo on every page request. Capability metadata is reconstructed from
    the normalized rows, while the calculation itself remains ``build_consensus``.
    """

    grouped: dict[str, list[StoredForecast]] = {}
    materialized = list(rows)
    for row in materialized:
        grouped.setdefault(row.model, []).append(row)
    members: list[ForecastMember] = []
    for model, model_rows in grouped.items():
        capability = _capability_from_stored(model, model_rows)
        first = model_rows[0]
        members.append(
            ForecastMember(
                model=model,
                forecast=ForecastResult(
                    model=model,
                    resolved_model=model,
                    requested_lat=first.requested_lat,
                    requested_lon=first.requested_lon,
                    timezone="Asia/Tokyo",
                    retrieved_at=max(row.retrieved_at for row in model_rows),
                    hours=list(model_rows),
                    raw_payload={"hourly": {}},
                ),
                capability=capability,
            )
        )
    if latitude is None:
        latitude = materialized[0].requested_lat if materialized else 0.0
    if longitude is None:
        longitude = materialized[0].requested_lon if materialized else 0.0
    return build_consensus(
        members,
        requested_models=requested_models,
        failures=failures,
        latitude=latitude,
        longitude=longitude,
        cloud_strategy=cloud_strategy,
        good_mid_cloud_max=good_mid_cloud_max,
        good_visibility_min_km=good_visibility_min_km,
        good_precip_max=good_precip_max,
        good_humidity_max=good_humidity_max,
    )


def _capability_from_stored(model: str, rows: Sequence[StoredForecast]) -> ModelCapability:
    available: set[str] = set()
    if any(row.cloud_mid_pct is not None for row in rows):
        available.add("cloud_cover_mid")
    if any(row.relative_humidity_pct is not None for row in rows):
        available.add("relative_humidity_2m")
    if any(row.precipitation_probability_pct is not None for row in rows):
        available.add("precipitation_probability")
    if any(row.visibility_m is not None for row in rows):
        available.add("visibility")
    if any(row.temperature_c is not None for row in rows):
        available.add("temperature_2m")
    if any(row.cloud_low_pct is not None for row in rows):
        available.add("cloud_cover_low")
    if any(row.cloud_high_pct is not None for row in rows):
        available.add("cloud_cover_high")
    return ModelCapability(
        model=model,
        supported=True,
        variables_available=available,
        missing_required=set(MODEL_REQUIRED_VARIABLES - available),
        missing_optional=set(MODEL_OPTIONAL_VARIABLES - available)
        | ({"visibility"} if "visibility" not in available else set()),
    )


def _build_hour(
    rows: Sequence[ConsensusMemberValue],
    key: str,
    *,
    good_mid_cloud_max: float,
    good_visibility_min_km: float,
    good_precip_max: float,
    good_humidity_max: float,
) -> ConsensusHour:
    proxy_values = [row.proxy.score for row in rows if row.full_model and row.proxy.score is not None]
    mid_values = [row.record.cloud_mid_pct for row in rows if row.record.cloud_mid_pct is not None]
    visibility_values = [
        row.record.visibility_km
        for row in rows
        if row.record.visibility_km is not None
    ]
    precip_values = [
        row.record.precipitation_probability_pct
        for row in rows
        if row.record.precipitation_probability_pct is not None
    ]
    humidity_values = [
        row.record.relative_humidity_pct for row in rows if row.record.relative_humidity_pct is not None
    ]
    outliers = _proxy_outliers(rows, proxy_values)
    marked_rows = tuple(
        ConsensusMemberValue(
            model=row.model,
            record=row.record,
            proxy=row.proxy,
            full_model=row.full_model,
            outlier=row.model in outliers,
            capability_status=row.capability_status,
            supports=row.supports,
        )
        for row in rows
    )
    full_count = sum(1 for row in rows if row.full_model and row.proxy.score is not None)
    model_count = len(rows)
    proxy_stddev = _stddev(proxy_values)
    mid_stddev = _stddev(mid_values)
    proxy_min = min(proxy_values) if proxy_values else None
    proxy_max = max(proxy_values) if proxy_values else None
    proxy_spread = None if proxy_min is None or proxy_max is None else proxy_max - proxy_min
    field_consensus = {
        "mid_cloud": _field_consensus(
            "mid_cloud",
            mid_values,
            good_votes=sum(value <= good_mid_cloud_max for value in mid_values),
            good_threshold=good_mid_cloud_max,
            good_when="below_or_equal",
        ),
        "visibility": _field_consensus(
            "visibility",
            visibility_values,
            good_votes=sum(value >= good_visibility_min_km for value in visibility_values),
            good_threshold=good_visibility_min_km,
            good_when="above_or_equal",
        ),
        "precipitation": _field_consensus(
            "precipitation",
            precip_values,
            good_votes=sum(value <= good_precip_max for value in precip_values),
            good_threshold=good_precip_max,
            good_when="below_or_equal",
        ),
        "humidity": _field_consensus(
            "humidity",
            humidity_values,
            good_votes=sum(value <= good_humidity_max for value in humidity_values),
            good_threshold=good_humidity_max,
            good_when="below_or_equal",
        ),
    }
    return ConsensusHour(
        valid_time=to_jst(datetime.fromisoformat(key)),
        model_count=model_count,
        full_model_count=full_count,
        partial_model_count=model_count - full_count,
        proxy_median=_median(proxy_values),
        proxy_min=min(proxy_values) if proxy_values else None,
        proxy_max=max(proxy_values) if proxy_values else None,
        proxy_stddev=proxy_stddev,
        mid_cloud_median=_median(mid_values),
        mid_cloud_min=min(mid_values) if mid_values else None,
        mid_cloud_max=max(mid_values) if mid_values else None,
        mid_cloud_stddev=mid_stddev,
        visibility_median_km=_median(visibility_values),
        visibility_min_km=min(visibility_values) if visibility_values else None,
        visibility_max_km=max(visibility_values) if visibility_values else None,
        visibility_stddev_km=_stddev(visibility_values),
        precip_median=_median(precip_values),
        humidity_median=_median(humidity_values),
        models_good_proxy=sum(value >= MIN_PROXY for value in proxy_values),
        models_good_mid_cloud=field_consensus["mid_cloud"].good_votes,
        models_good_visibility=field_consensus["visibility"].good_votes,
        models_good_precip=field_consensus["precipitation"].good_votes,
        consensus_label=_consensus_label(
            full_count,
            proxy_values,
            proxy_stddev,
            mid_stddev,
            field_consensus,
        ),
        outlier_models=tuple(sorted(outliers)),
        members=marked_rows,
        full_proxy_model_count=full_count,
        proxy_values=tuple(proxy_values),
        proxy_spread=proxy_spread,
        proxy_agreement=_proxy_agreement(proxy_spread, full_count),
        mid_cloud_model_count=field_consensus["mid_cloud"].model_count,
        mid_cloud_values=tuple(mid_values),
        mid_cloud_good_votes=field_consensus["mid_cloud"].good_votes,
        visibility_model_count=field_consensus["visibility"].model_count,
        visibility_values_km=tuple(visibility_values),
        visibility_good_votes=field_consensus["visibility"].good_votes,
        precip_model_count=field_consensus["precipitation"].model_count,
        precip_values=tuple(precip_values),
        precip_max=max(precip_values) if precip_values else None,
        precip_good_votes=field_consensus["precipitation"].good_votes,
        humidity_model_count=field_consensus["humidity"].model_count,
        humidity_values=tuple(humidity_values),
        humidity_max=max(humidity_values) if humidity_values else None,
        humidity_good_votes=field_consensus["humidity"].good_votes,
        field_consensus=field_consensus,
    )


def _consensus_label(
    full_count: int,
    proxy_values: Sequence[float],
    proxy_stddev: float | None,
    mid_stddev: float | None,
    field_consensus: dict[str, FieldConsensus] | None = None,
) -> str:
    if full_count < MIN_FULL_PROXY_MODELS:
        return "INSUFFICIENT_DATA"
    good_ratio = sum(value >= MIN_PROXY for value in proxy_values) / full_count
    field_consensus = field_consensus or {}
    mid_support = field_consensus.get("mid_cloud")
    precip_support = field_consensus.get("precipitation")
    if mid_support is not None and mid_support.support == "OPPOSED":
        return "LOW"
    if precip_support is not None and precip_support.support == "OPPOSED":
        return "LOW"
    if (
        full_count >= CONSENSUS_HIGH_MIN_FULL_MODELS
        and good_ratio >= CONSENSUS_HIGH_GOOD_RATIO
        and (proxy_stddev is not None and proxy_stddev <= CONSENSUS_HIGH_PROXY_STDDEV)
        and (mid_stddev is not None and mid_stddev <= CONSENSUS_HIGH_MID_CLOUD_STDDEV)
        and (mid_support is None or mid_support.support in {"STRONG_SUPPORT", "MODERATE_SUPPORT"})
    ):
        return "HIGH"
    if (
        full_count >= MIN_FULL_PROXY_MODELS
        and good_ratio >= CONSENSUS_MEDIUM_GOOD_RATIO
        and (proxy_stddev is not None and proxy_stddev <= CONSENSUS_MEDIUM_PROXY_STDDEV)
    ):
        return "MEDIUM"
    return "LOW"


def _field_consensus(
    name: str,
    values: Sequence[float],
    *,
    good_votes: int,
    good_threshold: float,
    good_when: str,
) -> FieldConsensus:
    count = len(values)
    ratio = good_votes / count if count else 0.0
    if count < FIELD_SUPPORT_MODERATE_MIN_MODELS:
        support = "INSUFFICIENT"
    elif count >= FIELD_SUPPORT_STRONG_MIN_MODELS and ratio >= FIELD_SUPPORT_STRONG_GOOD_RATIO:
        support = "STRONG_SUPPORT"
    elif ratio >= FIELD_SUPPORT_MODERATE_GOOD_RATIO:
        support = "MODERATE_SUPPORT"
    elif ratio < 0.5:
        support = "OPPOSED"
    else:
        support = "MIXED"
    return FieldConsensus(
        field=name,
        model_count=count,
        values=tuple(float(value) for value in values),
        median=_median(values),
        minimum=min(values) if values else None,
        maximum=max(values) if values else None,
        stddev=_stddev(values),
        good_votes=good_votes,
        support=support,
        good_threshold=good_threshold,
        good_when=good_when,
    )


def _proxy_agreement(spread: float | None, model_count: int) -> str:
    if model_count < MIN_FULL_PROXY_MODELS or spread is None:
        return "INSUFFICIENT"
    if spread <= MAX_PROXY_SPREAD_FOR_STRONG_SUPPORT:
        return "GOOD"
    if spread <= MAX_PROXY_SPREAD_FOR_WEAK_SUPPORT:
        return "MIXED"
    return "SEVERE"


def _proxy_outliers(rows: Sequence[ConsensusMemberValue], values: Sequence[float]) -> set[str]:
    if len(values) < 4:
        return set()
    center = median(values)
    deviations = [abs(value - center) for value in values]
    mad = median(deviations)
    threshold = max(10.0, 3.0 * mad)
    return {
        row.model
        for row in rows
        if row.proxy.score is not None and abs(row.proxy.score - center) > threshold
    }


def _median(values: Sequence[float]) -> float | None:
    return None if not values else float(median(values))


def _stddev(values: Sequence[float]) -> float | None:
    return None if not values else float(pstdev(values))


def _unique_models(models: Iterable[str]) -> list[str]:
    result: list[str] = []
    for model in models:
        value = str(model).strip()
        if value and value not in result:
            result.append(value)
    return result


def consensus_hour_for(
    result: ConsensusResult,
    valid_time: datetime,
) -> ConsensusHour | None:
    return result.hour_map().get(canonical_iso(valid_time))
