"""Long-running scheduled snapshot process for the dashboard container."""

from __future__ import annotations

import logging
import time

from .services import DashboardService
from .web.settings import DashboardSettings

logger = logging.getLogger("fuji_visibility.snapshot_worker")


def run() -> None:
    settings = DashboardSettings.from_env()
    service = DashboardService(settings)
    interval_seconds = settings.snapshot_interval_hours * 3600
    logger.info(
        "snapshot worker started: location=%s interval=%sh models=%s",
        settings.default_location,
        settings.snapshot_interval_hours,
        ",".join(settings.configured_models),
    )
    while True:
        try:
            result = service.refresh(manual=False)
            logger.info(
                "scheduled snapshot complete: snapshots=%s successful_models=%s failures=%s",
                len(result.snapshot_ids),
                len(result.successful_models),
                len(result.failures),
            )
        except Exception:
            # A transient provider or SQLite failure must not stop future cycles.
            logger.exception("scheduled snapshot failed; next cycle will retry")
        time.sleep(interval_seconds)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    run()
