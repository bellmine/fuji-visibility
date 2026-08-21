"""Reusable application services shared by the CLI, web app, and worker."""

from __future__ import annotations

import json
import logging
import time as time_module
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Callable, Sequence
from zoneinfo import ZoneInfo

from . import __version__
from .config import (
    CANDIDATE_MODELS,
    LOCATION_PRESETS,
    REQUEST_TIMEOUT_SECONDS,
    TIMEZONE,
)
from .consensus import (
    ConsensusFailure,
    ConsensusFetcher,
    ConsensusResult,
    build_consensus_from_stored,
)
from .decision import DecisionResult, decide_days
from .models import ModelCapability, StoredForecast
from .open_meteo import OpenMeteoClient, OpenMeteoError
from .storage import ForecastStore, StorageError
from .stability import StabilityMetrics, consensus_stability
from .time_utils import JST, canonical_iso, parse_clock, parse_datetime, to_jst
from .web.refresh import refresh_lock
from .web.settings import DashboardSettings

logger = logging.getLogger(__name__)

LAST_REFRESH_ATTEMPT = "last_refresh_attempt"
LAST_REFRESH_SUCCESS = "last_refresh_success"
LAST_REFRESH_STATUS = "last_refresh_status"
LAST_REFRESH_ERROR = "last_refresh_error"
LAST_REFRESH_FAILURES = "last_refresh_failures"
LAST_MODEL_CAPABILITIES = "last_model_capabilities"
APPLICATION_VERSION = "application_version"


class RefreshCooldownError(RuntimeError):
    """Raised when a manual refresh is requested before the cooldown expires."""

    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = max(1, retry_after_seconds)
        super().__init__(
            f"Forecast was refreshed recently. Try again in {self.retry_after_seconds} seconds."
        )


@dataclass(frozen=True)
class SnapshotRun:
    snapshot_ids: tuple[int, ...]
    successful_models: tuple[str, ...]
    failures: tuple[ConsensusFailure, ...]
    capabilities: tuple[ModelCapability, ...]


@dataclass(frozen=True)
class DashboardData:
    dates: tuple[date, ...]
    daily_results: tuple[tuple[date, ConsensusResult], ...]
    decision: DecisionResult
    stability_by_time: dict[str, StabilityMetrics]
    status: dict[str, object]


def fetch_consensus_days(
    latitude: float,
    longitude: float,
    dates: Sequence[date],
    *,
    models: Sequence[str] = CANDIDATE_MODELS,
    cloud_strategy: str = "mid",
    verbose: bool = False,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
) -> list[tuple[date, ConsensusResult]]:
    """Fetch one date at a time using the same consensus engine as the web layer."""

    results: list[tuple[date, ConsensusResult]] = []
    with OpenMeteoClient(verbose=verbose, timeout=timeout) as client:
        fetcher = ConsensusFetcher(client)
        for target_date in dates:
            result = fetcher.fetch(
                latitude,
                longitude,
                models=models,
                model_kwargs={"start_date": target_date, "end_date": target_date},
                cloud_strategy=cloud_strategy,
            )
            if not result.members:
                detail = "; ".join(
                    f"{failure.model}: {failure.reason}" for failure in result.failures
                )
                raise OpenMeteoError(
                    f"No consensus models succeeded for {target_date}. {detail}"
                )
            results.append((target_date, result))
    return results


def snapshot_all_models(
    latitude: float,
    longitude: float,
    *,
    days: int,
    models: Sequence[str] = CANDIDATE_MODELS,
    database_path: str | Path,
    raw_directory: str | Path,
    verbose: bool = False,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
) -> SnapshotRun:
    """Fetch and persist each model independently without holding a DB write open."""

    with OpenMeteoClient(verbose=verbose, timeout=timeout) as client:
        fetcher = ConsensusFetcher(client)
        result = fetcher.fetch(
            latitude,
            longitude,
            models=models,
            model_kwargs={"forecast_days": days},
        )
    if not result.members:
        detail = "; ".join(f"{failure.model}: {failure.reason}" for failure in result.failures)
        raise OpenMeteoError(f"No requested snapshot model succeeded. {detail}")
    snapshot_ids: list[int] = []
    with ForecastStore(database_path) as store:
        for member in result.members:
            snapshot_ids.append(
                store.save_forecast(
                    member.forecast,
                    raw_directory=raw_directory,
                    save_raw=True,
                )
            )
    return SnapshotRun(
        snapshot_ids=tuple(snapshot_ids),
        successful_models=tuple(member.model for member in result.members),
        failures=result.failures,
        capabilities=tuple(member.capability for member in result.members)
        + tuple(
            ModelCapability(
                model=failure.model,
                supported=False,
                error=failure.reason,
            )
            for failure in result.failures
        ),
    )


class DashboardService:
    """Read dashboard state and run refreshes without invoking the CLI."""

    def __init__(
        self,
        settings: DashboardSettings | None = None,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings or DashboardSettings.from_env()
        self._now = now or (lambda: datetime.now(ZoneInfo(self.settings.timezone)))

    @property
    def location(self):
        return self.settings.location_preset

    def location_for(self, location_name: str | None = None):
        if not location_name:
            return self.location
        try:
            return LOCATION_PRESETS[location_name.lower()]
        except KeyError as exc:
            raise ValueError(f"unknown location: {location_name}") from exc

    def upcoming_dates(self, count: int | None = None) -> tuple[date, ...]:
        total = count or self.settings.upcoming_days
        today = to_jst(self._now()).date()
        return tuple(today + timedelta(days=offset) for offset in range(max(1, total)))

    def dashboard_data(
        self,
        *,
        dates: Sequence[date] | None = None,
        arrival_after: time | str | None = None,
        hours: tuple[int, int] | None = None,
        location: str | None = None,
    ) -> DashboardData:
        selected_dates = tuple(dict.fromkeys(dates or self.upcoming_dates()))
        if not selected_dates:
            selected_dates = self.upcoming_dates(1)
        selected_hours = hours or self.settings.hours
        arrival = (
            parse_clock(arrival_after) if isinstance(arrival_after, str) else arrival_after
        ) or self.settings.default_arrival_after
        preset = self.location_for(location)
        start = datetime.combine(min(selected_dates), time.min, tzinfo=JST)
        end = datetime.combine(max(selected_dates), time(23, 59, 59), tzinfo=JST)
        with ForecastStore(self.settings.database_path) as store:
            rows = store.latest_rows(
                canonical_iso(start),
                canonical_iso(end),
                latitude=preset.latitude,
                longitude=preset.longitude,
                models=self.settings.configured_models,
            )
            failures = _metadata_failures(store.get_metadata(LAST_REFRESH_FAILURES))
            daily_results: list[tuple[date, ConsensusResult]] = []
            for target_date in selected_dates:
                day_rows = [
                    row for row in rows if to_jst(row.valid_time).date() == target_date
                ]
                daily_results.append(
                    (
                        target_date,
                        build_consensus_from_stored(
                            day_rows,
                            requested_models=self.settings.configured_models,
                            failures=failures,
                            latitude=preset.latitude,
                            longitude=preset.longitude,
                            cloud_strategy=self.settings.cloud_strategy,
                            good_mid_cloud_max=self.settings.good_mid_cloud_max,
                            good_visibility_min_km=self.settings.good_visibility_min_km,
                            good_precip_max=self.settings.good_precip_max,
                            good_humidity_max=self.settings.good_humidity_max,
                        ),
                    )
                )
            stability_by_time: dict[str, StabilityMetrics] = {}
            for _, result in daily_results:
                for hour in result.hours:
                    history = store.trend(
                        hour.valid_time.isoformat(),
                        latitude=preset.latitude,
                        longitude=preset.longitude,
                    )
                    stability_by_time[canonical_iso(hour.valid_time)] = consensus_stability(
                        history,
                        cloud_strategy=self.settings.cloud_strategy,
                    )
            status = self._status_from_store(
                store,
                preset.latitude,
                preset.longitude,
                location_name=preset.name,
            )
        decision = decide_days(
            daily_results,
            arrival_after=arrival,
            hours=selected_hours,
            stability_by_time=stability_by_time,
            min_proxy=self.settings.min_proxy,
            min_window_hours=self.settings.min_window_hours,
            min_full_proxy_models=self.settings.min_full_proxy_models,
            max_proxy_spread_strong=self.settings.max_proxy_spread_strong,
            max_proxy_spread_weak=self.settings.max_proxy_spread_weak,
            good_mid_cloud_max=self.settings.good_mid_cloud_max,
            good_visibility_min_km=self.settings.good_visibility_min_km,
            good_precip_max=self.settings.good_precip_max,
            good_humidity_max=self.settings.good_humidity_max,
        )
        return DashboardData(
            dates=selected_dates,
            daily_results=tuple(daily_results),
            decision=decision,
            stability_by_time=stability_by_time,
            status=status,
        )

    def status(self) -> dict[str, object]:
        preset = self.location
        with ForecastStore(self.settings.database_path) as store:
            return self._status_from_store(
                store,
                preset.latitude,
                preset.longitude,
                location_name=preset.name,
            )

    def health(self) -> dict[str, object]:
        with ForecastStore(self.settings.database_path) as store:
            return {
                "status": "ok",
                "database": "ok",
                "last_snapshot": store.latest_snapshot_at(
                    latitude=self.location.latitude,
                    longitude=self.location.longitude,
                ),
            }

    def diagnostics(self) -> dict[str, object]:
        preset = self.location
        with ForecastStore(self.settings.database_path) as store:
            metadata = store.get_metadata_map()
            status = self._status_from_store(store, preset.latitude, preset.longitude)
            capabilities = _metadata_capabilities(metadata.get(LAST_MODEL_CAPABILITIES))
            if not capabilities or any(
                "status" not in item or "supports" not in item for item in capabilities
            ):
                # Rebuild capability diagnostics from the latest normalized
                # rows so Phase 2 databases remain readable before the next
                # network refresh writes new metadata.
                start = datetime.combine(
                    to_jst(self._now()).date(), time.min, tzinfo=JST
                )
                end = datetime.combine(
                    to_jst(self._now()).date() + timedelta(days=self.settings.upcoming_days),
                    time(23, 59, 59),
                    tzinfo=JST,
                )
                stored_rows = store.latest_rows(
                    canonical_iso(start),
                    canonical_iso(end),
                    latitude=preset.latitude,
                    longitude=preset.longitude,
                    models=self.settings.configured_models,
                )
                rebuilt = build_consensus_from_stored(
                    stored_rows,
                    requested_models=self.settings.configured_models,
                    latitude=preset.latitude,
                    longitude=preset.longitude,
                )
                by_model = {
                    member.model: _capability_payload(member.capability)
                    for member in rebuilt.members
                }
                for model in self.settings.configured_models:
                    by_model.setdefault(
                        model,
                        _capability_payload(
                            ModelCapability(
                                model=model,
                                supported=False,
                                error="暂无已保存的预报数据",
                            )
                        ),
                    )
                capabilities = [by_model[model] for model in self.settings.configured_models]
            failures = _metadata_failures(metadata.get(LAST_REFRESH_FAILURES))
            return {
                "version": __version__,
                "database_path": str(self.settings.database_path),
                "raw_data_dir": str(self.settings.raw_data_dir),
                "location": self.settings.default_location,
                "configured_models": list(self.settings.configured_models),
                "capabilities": capabilities,
                "failures": [failure.__dict__ for failure in failures],
                "snapshot_count": store.snapshot_count(),
                "hourly_count": store.hourly_count(),
                "status": status,
            }

    def refresh(self, *, manual: bool = True) -> SnapshotRun:
        """Run a guarded multi-model refresh; scheduled calls bypass cooldown."""

        with refresh_lock(self.settings.refresh_lock_path):
            now = self._now()
            with ForecastStore(self.settings.database_path) as store:
                metadata = store.get_metadata_map()
                if manual:
                    retry_after = _cooldown_remaining(
                        metadata.get(LAST_REFRESH_ATTEMPT),
                        now,
                        self.settings.manual_refresh_cooldown_seconds,
                    )
                    if retry_after > 0:
                        raise RefreshCooldownError(retry_after)
                store.set_metadata(LAST_REFRESH_ATTEMPT, canonical_iso(now))
                store.set_metadata(APPLICATION_VERSION, __version__)
            logger.info("%s refresh started", "manual" if manual else "scheduled")
            started = time_module.monotonic()
            try:
                result = snapshot_all_models(
                    self.location.latitude,
                    self.location.longitude,
                    days=self.settings.upcoming_days,
                    models=self.settings.configured_models,
                    database_path=self.settings.database_path,
                    raw_directory=self.settings.raw_data_dir,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
                status = "partial" if result.failures else "success"
                failures_json = json.dumps(
                    [failure.__dict__ for failure in result.failures], ensure_ascii=False
                )
                capabilities_json = json.dumps(
                    [_capability_payload(capability) for capability in result.capabilities],
                    ensure_ascii=False,
                )
                with ForecastStore(self.settings.database_path) as store:
                    store.set_metadata(LAST_REFRESH_SUCCESS, canonical_iso(self._now()))
                    store.set_metadata(LAST_REFRESH_STATUS, status)
                    store.set_metadata(LAST_REFRESH_ERROR, failures_json if result.failures else "")
                    store.set_metadata(LAST_REFRESH_FAILURES, failures_json)
                    store.set_metadata(LAST_MODEL_CAPABILITIES, capabilities_json)
                    store.set_metadata(APPLICATION_VERSION, __version__)
                self.cleanup_raw()
                logger.info(
                    "refresh completed status=%s models=%s duration=%.2fs",
                    status,
                    len(result.successful_models),
                    time_module.monotonic() - started,
                )
                return result
            except Exception as exc:
                logger.exception("refresh failed after %.2fs", time_module.monotonic() - started)
                with ForecastStore(self.settings.database_path) as store:
                    store.set_metadata(LAST_REFRESH_STATUS, "failed")
                    store.set_metadata(LAST_REFRESH_ERROR, str(exc))
                raise

    def cleanup_raw(self) -> int:
        if self.settings.raw_retention_days <= 0:
            return 0
        cutoff = self._now().timestamp() - self.settings.raw_retention_days * 86400
        removed = 0
        raw_dir = Path(self.settings.raw_data_dir)
        if not raw_dir.exists():
            return 0
        for path in raw_dir.glob("*.json"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            except OSError:
                logger.warning("could not remove old raw forecast %s", path, exc_info=True)
        return removed

    def _status_from_store(
        self,
        store: ForecastStore,
        latitude: float,
        longitude: float,
        *,
        location_name: str | None = None,
    ) -> dict[str, object]:
        metadata = store.get_metadata_map()
        latest = store.latest_snapshot_at(latitude=latitude, longitude=longitude)
        last_success = metadata.get(LAST_REFRESH_SUCCESS) or latest
        age = _age_seconds(last_success, self._now())
        capabilities = _metadata_capabilities(metadata.get(LAST_MODEL_CAPABILITIES))
        full_models = sum(
            1
            for item in capabilities
            if item.get("status") == "FULL_PROXY" or item.get("full_forecast_available")
        )
        partial_models = sum(1 for item in capabilities if item.get("status") == "PARTIAL_USEFUL")
        if not capabilities:
            # Phase 1/2 databases predate app_metadata. Infer the count from
            # the latest usable rows so existing history remains informative.
            today = to_jst(self._now()).date()
            legacy_start = datetime.combine(today, time.min, tzinfo=JST)
            legacy_end = datetime.combine(
                today + timedelta(days=self.settings.upcoming_days),
                time(23, 59, 59),
                tzinfo=JST,
            )
            legacy_rows = store.latest_rows(
                canonical_iso(legacy_start),
                canonical_iso(legacy_end),
                latitude=latitude,
                longitude=longitude,
                models=self.settings.configured_models,
            )
            by_model: dict[str, list[StoredForecast]] = {}
            for row in legacy_rows:
                by_model.setdefault(row.model, []).append(row)
            full_models = sum(1 for rows in by_model.values() if _stored_model_is_full(rows))
            partial_models = max(0, len(by_model) - full_models)
        return {
            "version": __version__,
            "timezone": self.settings.timezone,
            "location": location_name or self.settings.default_location,
            "arrival_after": self.settings.default_arrival_after.strftime("%H:%M"),
            "hours": {
                "start": self.settings.hours[0],
                "end": self.settings.hours[1],
            },
            "configured_models": len(self.settings.configured_models),
            "full_models": full_models,
            "partial_models": partial_models,
            "last_successful_snapshot": last_success,
            "last_refresh_attempt": metadata.get(LAST_REFRESH_ATTEMPT),
            "last_refresh_status": metadata.get(LAST_REFRESH_STATUS, "unknown"),
            "last_refresh_error": metadata.get(LAST_REFRESH_ERROR) or None,
            "data_age_seconds": age,
            "snapshot_count": store.snapshot_count(),
            "freshness": _freshness(age),
        }


def _capability_payload(capability: ModelCapability) -> dict[str, object]:
    return {
        "model": capability.model,
        "status": capability.status,
        "supports": capability.supports,
        "usable_fields": list(capability.usable_fields),
        "supported": capability.supported,
        "variables_available": sorted(capability.variables_available),
        "missing_required": sorted(capability.missing_required),
        "missing_optional": sorted(capability.missing_optional),
        "error": capability.error,
        "full_forecast_available": capability.full_forecast_available,
    }


def _metadata_capabilities(value: str | None) -> list[dict[str, object]]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _metadata_failures(value: str | None) -> tuple[ConsensusFailure, ...]:
    if not value:
        return ()
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return ()
    if not isinstance(parsed, list):
        return ()
    return tuple(
        ConsensusFailure(str(item.get("model", "unknown")), str(item.get("reason", "unknown")))
        for item in parsed
        if isinstance(item, dict)
    )


def _stored_model_is_full(rows: Sequence[StoredForecast]) -> bool:
    return all(
        any(getattr(row, field) is not None for row in rows)
        for field in (
            "cloud_mid_pct",
            "relative_humidity_pct",
            "precipitation_probability_pct",
            "visibility_m",
        )
    )


def _cooldown_remaining(value: str | None, now: datetime, cooldown: int) -> int:
    if not value or cooldown <= 0:
        return 0
    try:
        elapsed = (now - parse_datetime(value)).total_seconds()
    except ValueError:
        return 0
    return max(0, int(cooldown - elapsed + 0.999))


def _age_seconds(value: str | None, now: datetime) -> int | None:
    if not value:
        return None
    try:
        return max(0, int((now - parse_datetime(value)).total_seconds()))
    except ValueError:
        return None


def _freshness(age_seconds: int | None) -> str:
    if age_seconds is None:
        return "UNKNOWN"
    if age_seconds <= 4 * 3600:
        return "FRESH"
    if age_seconds <= 8 * 3600:
        return "WARNING"
    return "STALE"
