"""Live and historical matching of the public Is It Visible fingerprint."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Iterable, Sequence

from pydantic import ValidationError

from .config import (
    DEFAULT_CLOUD_MAPPINGS,
    DEFAULT_CANDIDATE_MODELS,
    FINGERPRINT_CLOUD_SCALE,
    FINGERPRINT_TEMP_SCALE,
    FINGERPRINT_VISIBILITY_SCALE,
)
from .models import Fingerprint, FingerprintObservation, ForecastResult, HourlyForecast
from .open_meteo import OpenMeteoClient, OpenMeteoError
from .scoring import effective_cloud_pct
from .time_utils import canonical_iso, to_jst

CloudMapping = str


@dataclass(frozen=True)
class FingerprintResidual:
    valid_time: datetime
    temperature: float
    cloud: float
    visibility: float
    point_error: float


@dataclass(frozen=True)
class FingerprintCandidate:
    latitude: float
    longitude: float
    model: str
    cloud_mapping: CloudMapping
    error: float
    residuals: tuple[FingerprintResidual, ...]
    resolved_model: str | None = None
    run: datetime | None = None


@dataclass(frozen=True)
class FingerprintFailure:
    latitude: float
    longitude: float
    model: str
    run: datetime | None
    reason: str


@dataclass(frozen=True)
class FingerprintSearchResult:
    candidates: tuple[FingerprintCandidate, ...]
    failures: tuple[FingerprintFailure, ...]
    attempted_requests: int


def load_fingerprint(path: str | Path) -> Fingerprint:
    file_path = Path(path).expanduser()
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Fingerprint file does not exist: {file_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Fingerprint file is not valid JSON: {exc.msg}") from exc
    if isinstance(payload, list):
        payload = {"observations": payload}
    if not isinstance(payload, dict):
        raise ValueError("Fingerprint JSON must be an object or an observations array.")
    try:
        fingerprint = Fingerprint.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"Fingerprint JSON is malformed: {exc}") from exc
    if not fingerprint.observations:
        raise ValueError("Fingerprint must contain at least one observation.")
    return fingerprint


def coordinate_grid(
    latitude_center: float,
    longitude_center: float,
    radius_deg: float,
    step_deg: float,
) -> list[tuple[float, float]]:
    if radius_deg < 0:
        raise ValueError("coordinate search radius cannot be negative")
    if step_deg <= 0:
        raise ValueError("coordinate search step must be positive")
    count = int(round(radius_deg / step_deg))
    offsets = [round(-radius_deg + index * step_deg, 6) for index in range(2 * count + 1)]
    # Include the exact center when radius is not an integer multiple of step.
    offsets.append(0.0)
    offsets = sorted(set(offsets))
    return [
        (round(latitude_center + lat_offset, 6), round(longitude_center + lon_offset, 6))
        for lat_offset in offsets
        for lon_offset in offsets
    ]


class FingerprintSearcher:
    def __init__(
        self,
        client: OpenMeteoClient,
        *,
        progress: Callable[[str], None] | None = None,
    ) -> None:
        self.client = client
        self.progress = progress

    def search_live(
        self,
        fingerprint: Fingerprint,
        *,
        latitude_center: float,
        longitude_center: float,
        radius_deg: float,
        step_deg: float,
        models: Sequence[str] = DEFAULT_CANDIDATE_MODELS,
        cloud_mappings: Sequence[CloudMapping] = DEFAULT_CLOUD_MAPPINGS,
    ) -> FingerprintSearchResult:
        coordinates = coordinate_grid(
            latitude_center, longitude_center, radius_deg, step_deg
        )
        start_date, end_date = _observation_date_range(fingerprint.observations)
        candidates: list[FingerprintCandidate] = []
        failures: list[FingerprintFailure] = []
        attempted = 0
        for latitude, longitude in coordinates:
            for model in _clean_choices(models):
                attempted += 1
                self._progress(
                    f"fingerprint request {attempted}: {latitude:.3f},{longitude:.3f} {model}"
                )
                try:
                    forecast = self.client.fetch_forecast(
                        latitude,
                        longitude,
                        model=model,
                        start_date=start_date,
                        end_date=end_date,
                    )
                except OpenMeteoError as exc:
                    failures.append(FingerprintFailure(latitude, longitude, model, None, str(exc)))
                    continue
                candidates.extend(
                    _evaluate_forecast(
                        forecast,
                        fingerprint.observations,
                        latitude=latitude,
                        longitude=longitude,
                        model=model,
                        cloud_mappings=cloud_mappings,
                        failures=failures,
                    )
                )
        return FingerprintSearchResult(
            candidates=tuple(sorted(candidates, key=lambda candidate: candidate.error)),
            failures=tuple(failures),
            attempted_requests=attempted,
        )

    def search_history(
        self,
        fingerprint: Fingerprint,
        *,
        runs: Iterable[datetime],
        latitude_center: float,
        longitude_center: float,
        radius_deg: float,
        step_deg: float,
        models: Sequence[str] = DEFAULT_CANDIDATE_MODELS,
        cloud_mappings: Sequence[CloudMapping] = DEFAULT_CLOUD_MAPPINGS,
    ) -> FingerprintSearchResult:
        coordinates = coordinate_grid(
            latitude_center, longitude_center, radius_deg, step_deg
        )
        start_date, end_date = _observation_date_range(fingerprint.observations)
        candidates: list[FingerprintCandidate] = []
        failures: list[FingerprintFailure] = []
        attempted = 0
        for run in runs:
            for latitude, longitude in coordinates:
                for model in _clean_choices(models):
                    attempted += 1
                    try:
                        forecast = self.client.fetch_single_run(
                            latitude,
                            longitude,
                            run,
                            model=model,
                            start_date=start_date,
                            end_date=end_date,
                        )
                    except OpenMeteoError as exc:
                        failures.append(FingerprintFailure(latitude, longitude, model, run, str(exc)))
                        continue
                    candidates.extend(
                        _evaluate_forecast(
                            forecast,
                            fingerprint.observations,
                            latitude=latitude,
                            longitude=longitude,
                            model=model,
                            cloud_mappings=cloud_mappings,
                            failures=failures,
                            run=run,
                        )
                    )
        return FingerprintSearchResult(
            candidates=tuple(sorted(candidates, key=lambda candidate: candidate.error)),
            failures=tuple(failures),
            attempted_requests=attempted,
        )

    def _progress(self, message: str) -> None:
        if self.progress is not None:
            self.progress(message)


def _evaluate_forecast(
    forecast: ForecastResult,
    observations: Sequence[FingerprintObservation],
    *,
    latitude: float,
    longitude: float,
    model: str,
    cloud_mappings: Sequence[CloudMapping],
    failures: list[FingerprintFailure],
    run: datetime | None = None,
) -> list[FingerprintCandidate]:
    by_time = {canonical_iso(hour.valid_time): hour for hour in forecast.hours}
    result: list[FingerprintCandidate] = []
    for mapping in _clean_choices(cloud_mappings):
        residuals: list[FingerprintResidual] = []
        missing: list[str] = []
        for observation in observations:
            key = canonical_iso(observation.valid_time)
            predicted = by_time.get(key)
            if predicted is None:
                missing.append(f"missing valid hour {key}")
                continue
            residual = _residual(predicted, observation, mapping)
            if residual is None:
                missing.append(f"missing source value at {key}")
            else:
                residuals.append(residual)
        if missing:
            failures.append(
                FingerprintFailure(
                    latitude,
                    longitude,
                    model,
                    run,
                    f"cloud mapping {mapping}: " + "; ".join(missing),
                )
            )
            continue
        result.append(
            FingerprintCandidate(
                latitude=latitude,
                longitude=longitude,
                model=model,
                cloud_mapping=mapping,
                error=sum(item.point_error for item in residuals) / len(residuals),
                residuals=tuple(residuals),
                resolved_model=forecast.resolved_model,
                run=run,
            )
        )
    return result


def _residual(
    predicted: HourlyForecast,
    observed: FingerprintObservation,
    mapping: CloudMapping,
) -> FingerprintResidual | None:
    if (
        observed.temperature_c is None
        or observed.displayed_cloud_pct is None
        or observed.visibility_km is None
        or predicted.temperature_c is None
        or predicted.visibility_km is None
    ):
        return None
    cloud = _mapped_cloud(predicted, mapping)
    if cloud is None:
        return None
    temperature_error = abs(predicted.temperature_c - observed.temperature_c) / FINGERPRINT_TEMP_SCALE
    cloud_error = abs(cloud - observed.displayed_cloud_pct) / FINGERPRINT_CLOUD_SCALE
    visibility_error = abs(predicted.visibility_km - observed.visibility_km) / FINGERPRINT_VISIBILITY_SCALE
    point_error = 0.30 * temperature_error + 0.30 * cloud_error + 0.40 * visibility_error
    return FingerprintResidual(
        valid_time=to_jst(predicted.valid_time),
        temperature=predicted.temperature_c - observed.temperature_c,
        cloud=cloud - observed.displayed_cloud_pct,
        visibility=predicted.visibility_km - observed.visibility_km,
        point_error=point_error,
    )


def _mapped_cloud(record: HourlyForecast, mapping: CloudMapping) -> float | None:
    aliases = {
        "low_mid_max": "low_mid_max",
        "low_mid_weighted": "low_mid_weighted",
        "mid_high_weighted": "mid_high_weighted",
    }
    if mapping == "total":
        return record.cloud_total_pct
    if mapping == "mid":
        return record.cloud_mid_pct
    if mapping in aliases:
        return effective_cloud_pct(record, aliases[mapping])
    raise ValueError(
        f"unknown fingerprint cloud mapping {mapping!r}; "
        "choose total, mid, low_mid_max, low_mid_weighted, or mid_high_weighted"
    )


def _observation_date_range(observations: Sequence[FingerprintObservation]) -> tuple[date, date]:
    dates = [to_jst(item.valid_time).date() for item in observations]
    return min(dates), max(dates)


def _clean_choices(values: Sequence[str] | Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        item = str(value).strip()
        if item and item not in result:
            result.append(item)
    return result
