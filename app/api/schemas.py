from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SourceCreate(BaseModel):
    name: str
    start_url: str
    allowed_domains: list[str] = Field(default_factory=list)
    source_type: str = "docs"
    cron_expr: str | None = None
    enabled: bool = True
    crawl_depth: int = 1
    crawl_limit: int = 100
    render: bool = False
    formats: list[str] = Field(default_factory=lambda: ["markdown"])


class SearchRequest(BaseModel):
    query: str
    limit: int = 10
    source_id: str | None = None


class SearchResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: str
    source_id: str
    url: str
    title: str | None
    score: float
    snippet: str
    chunk_index: int


class HealthResponse(BaseModel):
    status: str
    cloudflare_enabled: bool
    embedding_model: str


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_id: str
    status: str
    provider_job_id: str | None
    requested_url: str
    total_records: int
    finished_records: int
    skipped_records: int
    error_text: str | None
    submitted_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_id: str
    url: str
    canonical_url: str | None
    title: str | None
    status_code: int | None
    fetched_at: datetime
    content_hash: str
    raw_markdown: str
    metadata_json: dict[str, Any]
