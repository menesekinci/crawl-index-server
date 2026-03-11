from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Column, Text
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobStatus(StrEnum):
    pending = "pending"
    submitted = "submitted"
    polling = "polling"
    completed = "completed"
    failed = "failed"


class SourceBase(SQLModel):
    name: str
    start_url: str
    allowed_domains: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    source_type: str = "docs"
    cron_expr: str | None = None
    enabled: bool = True
    crawl_depth: int = 1
    crawl_limit: int = 50
    render: bool = False
    formats: list[str] = Field(default_factory=lambda: ["markdown"], sa_column=Column(JSON))


class Source(SourceBase, table=True):
    __tablename__ = "sources"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    last_run_at: datetime | None = None
    last_success_at: datetime | None = None
    next_run_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class CrawlJob(SQLModel, table=True):
    __tablename__ = "crawl_jobs"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    source_id: str = Field(index=True, foreign_key="sources.id")
    provider: str = "cloudflare"
    provider_job_id: str | None = None
    status: str = Field(default=JobStatus.pending.value, index=True)
    requested_url: str
    requested_depth: int = 1
    requested_limit: int = 50
    render: bool = False
    formats: list[str] = Field(default_factory=lambda: ["markdown"], sa_column=Column(JSON))
    submitted_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_text: str | None = Field(default=None, sa_column=Column(Text))
    total_records: int = 0
    finished_records: int = 0
    skipped_records: int = 0
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Document(SQLModel, table=True):
    __tablename__ = "documents"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    source_id: str = Field(index=True, foreign_key="sources.id")
    url: str = Field(index=True)
    canonical_url: str | None = None
    title: str | None = None
    status_code: int | None = None
    content_hash: str = Field(index=True)
    fetched_at: datetime = Field(default_factory=utcnow)
    raw_markdown: str = Field(sa_column=Column(Text))
    metadata_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Chunk(SQLModel, table=True):
    __tablename__ = "chunks"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    document_id: str = Field(index=True, foreign_key="documents.id")
    chunk_index: int = Field(index=True)
    text: str = Field(sa_column=Column(Text))
    content_hash: str = Field(index=True)
    token_estimate: int = 0
    embedding_model: str | None = None
    embedded_at: datetime | None = None
    vector_point_id: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class AppSetting(SQLModel, table=True):
    __tablename__ = "app_settings"

    key: str = Field(primary_key=True)
    value: str
    updated_at: datetime = Field(default_factory=utcnow)

