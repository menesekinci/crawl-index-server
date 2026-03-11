from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import Settings
from app.services.jobs import CrawlCoordinator
from app.services.sources import SourceService


class AppScheduler:
    def __init__(self, settings: Settings, source_service: SourceService, crawl_coordinator: CrawlCoordinator):
        self._settings = settings
        self._source_service = source_service
        self._crawl_coordinator = crawl_coordinator
        self._scheduler = BackgroundScheduler(timezone=None)
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._scheduler.add_job(
            self._crawl_coordinator.process_due_sources,
            "interval",
            seconds=self._settings.scheduler_interval_seconds,
            id="scan_due_sources",
            replace_existing=True,
        )
        self._scheduler.add_job(
            self._crawl_coordinator.poll_active_jobs,
            "interval",
            seconds=self._settings.poll_interval_seconds,
            id="poll_active_jobs",
            replace_existing=True,
        )
        self._scheduler.start()
        self._started = True

    def shutdown(self) -> None:
        if self._started:
            self._scheduler.shutdown(wait=False)
            self._started = False

