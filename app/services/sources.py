from __future__ import annotations

from datetime import datetime, timezone

from apscheduler.triggers.cron import CronTrigger
from sqlmodel import Session, select

from app.config import Settings
from app.db.models import Source, utcnow


class SourceService:
    def __init__(self, engine, settings: Settings):
        self._engine = engine
        self._settings = settings

    def list_sources(self, enabled_only: bool = False) -> list[Source]:
        with Session(self._engine) as session:
            statement = select(Source).order_by(Source.created_at.desc())
            if enabled_only:
                statement = statement.where(Source.enabled.is_(True))
            return list(session.exec(statement))

    def get_source(self, source_id: str) -> Source | None:
        with Session(self._engine) as session:
            return session.get(Source, source_id)

    def create_source(self, payload: dict) -> Source:
        source = Source(**payload)
        source.next_run_at = self.compute_next_run(source.cron_expr)
        with Session(self._engine) as session:
            session.add(source)
            session.commit()
            session.refresh(source)
            return source

    def due_sources(self) -> list[Source]:
        now = utcnow()
        with Session(self._engine) as session:
            statement = select(Source).where(
                Source.enabled.is_(True),
                Source.cron_expr.is_not(None),
                Source.next_run_at.is_not(None),
                Source.next_run_at <= now,
            )
            return list(session.exec(statement))

    def mark_source_run(self, source_id: str, success: bool = False) -> None:
        with Session(self._engine) as session:
            source = session.get(Source, source_id)
            if source is None:
                return
            source.last_run_at = utcnow()
            if success:
                source.last_success_at = source.last_run_at
            source.next_run_at = self.compute_next_run(source.cron_expr, source.last_run_at)
            source.updated_at = utcnow()
            session.add(source)
            session.commit()

    def compute_next_run(self, cron_expr: str | None, start: datetime | None = None) -> datetime | None:
        if not cron_expr:
            return None
        trigger = CronTrigger.from_crontab(cron_expr, timezone=datetime.now().astimezone().tzinfo)
        next_fire = trigger.get_next_fire_time(None, start or datetime.now().astimezone())
        if next_fire is None:
            return None
        return next_fire.astimezone(timezone.utc)
