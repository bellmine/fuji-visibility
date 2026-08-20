"""Multi-model forecast fetching and transparent consensus statistics."""

from __future__ import annotations

from dataclasses import dataclass
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
    GOOD_MID_CLOUD_THRESHOLD,
    GOOD_PRECIP_THRESHOLD,
    GOOD_PROXY_THRESHOLD,
    GOOD_VISIBILITY_THRESHOLD_KM,
    MODEL_OPTIONAL_VARIABLES,
    MODEL_REQUIRED_VARIABLES,
)
from .models import (
    ForecastResult,
    HourlyForecast,
    ModelCapability,
    ProxyScore,
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

    @property
    def proxy_range(self) -> tuple[float | None, float | None]:
        return self.proxy_min, self.proxy_max

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
                )
            )
        hours.append(_build_hour(rows, key))
    return ConsensusResult(
        requested_models=tuple(requested_models or _unique_models(member.model for member in members)),
        members=tuple(members),
        failures=tuple(failures),
        hours=tuple(hours),
        requested_lat=latitude,
        requested_lon=longitude,
    )


def _build_hour(rows: Sequence[ConsensusMemberValue], key: str) -> ConsensusHour:
    proxy_values = [row.proxy.score for row in rows if row.full_model and row.proxy.score is not None]
    mid_values = [row.record.cloud_mid_pct for row in rows if row.record.cloud_mid_pct is not None]
    visibility_values = [
        row.record.visibility_km
        for row in rows
        if row.full_model and row.record.visibility_km is not None
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
        )
        for row in rows
    )
    full_count = sum(1 for row in rows if row.full_model and row.proxy.score is not None)
    model_count = len(rows)
    proxy_stddev = _stddev(proxy_values)
    mid_stddev = _stddev(mid_values)
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
        models_good_proxy=sum(value >= GOOD_PROXY_THRESHOLD for value in proxy_values),
        models_good_mid_cloud=sum(value <= GOOD_MID_CLOUD_THRESHOLD for value in mid_values),
        models_good_visibility=sum(value >= GOOD_VISIBILITY_THRESHOLD_KM for value in visibility_values),
        models_good_precip=sum(value <= GOOD_PRECIP_THRESHOLD for value in precip_values),
        consensus_label=_consensus_label(
            full_count,
            proxy_values,
            proxy_stddev,
            mid_stddev,
        ),
        outlier_models=tuple(sorted(outliers)),
        members=marked_rows,
    )


def _consensus_label(
    full_count: int,
    proxy_values: Sequence[float],
    proxy_stddev: float | None,
    mid_stddev: float | None,
) -> str:
    if full_count < CONSENSUS_MEDIUM_MIN_FULL_MODELS:
        return "INSUFFICIENT_DATA"
    good_ratio = sum(value >= GOOD_PROXY_THRESHOLD for value in proxy_values) / full_count
    if (
        full_count >= CONSENSUS_HIGH_MIN_FULL_MODELS
        and good_ratio >= CONSENSUS_HIGH_GOOD_RATIO
        and (proxy_stddev is not None and proxy_stddev <= CONSENSUS_HIGH_PROXY_STDDEV)
        and (mid_stddev is not None and mid_stddev <= CONSENSUS_HIGH_MID_CLOUD_STDDEV)
    ):
        return "HIGH"
    if (
        full_count >= CONSENSUS_MEDIUM_MIN_FULL_MODELS
        and good_ratio >= CONSENSUS_MEDIUM_GOOD_RATIO
        and (proxy_stddev is not None and proxy_stddev <= CONSENSUS_MEDIUM_PROXY_STDDEV)
    ):
        return "MEDIUM"
    return "LOW"


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
