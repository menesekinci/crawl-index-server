from __future__ import annotations

import hashlib
from datetime import datetime
from uuid import uuid4

from sqlmodel import Session, delete, select

from app.config import Settings
from app.db.models import Chunk, CrawlJob, Document, JobStatus, Source, utcnow
from app.services.chunking import MarkdownChunker
from app.services.cloudflare import CloudflareCrawlClient, CloudflareNotConfiguredError, CrawlJobResult
from app.services.embeddings import EmbeddingService
from app.services.vector_store import VectorStore


class CrawlCoordinator:
    def __init__(
        self,
        *,
        engine,
        settings: Settings,
        cloudflare_client: CloudflareCrawlClient,
        embedding_service: EmbeddingService,
        vector_store: VectorStore,
    ):
        self._engine = engine
        self._settings = settings
        self._cloudflare_client = cloudflare_client
        self._embedding_service = embedding_service
        self._vector_store = vector_store
        self._chunker = MarkdownChunker(settings.chunk_target_chars, settings.chunk_overlap_chars)

    def list_jobs(
        self,
        source_id: str | None = None,
        status: str | None = None,
        limit: int | None = 20,
    ) -> list[CrawlJob]:
        with Session(self._engine) as session:
            statement = select(CrawlJob).order_by(CrawlJob.created_at.desc())
            if source_id:
                statement = statement.where(CrawlJob.source_id == source_id)
            if status:
                statement = statement.where(CrawlJob.status == status)
            if limit:
                statement = statement.limit(limit)
            return list(session.exec(statement))

    def get_job(self, job_id: str) -> CrawlJob | None:
        with Session(self._engine) as session:
            return session.get(CrawlJob, job_id)

    def list_documents(self, source_id: str | None = None, limit: int | None = 20) -> list[Document]:
        with Session(self._engine) as session:
            statement = select(Document).order_by(Document.fetched_at.desc())
            if source_id:
                statement = statement.where(Document.source_id == source_id)
            if limit:
                statement = statement.limit(limit)
            return list(session.exec(statement))

    def get_document(self, document_id: str) -> Document | None:
        with Session(self._engine) as session:
            return session.get(Document, document_id)

    def get_document_payload(
        self,
        document_id: str,
        *,
        include_markdown: bool = False,
        max_chars: int = 4000,
    ) -> dict | None:
        document = self.get_document(document_id)
        if document is None:
            return None
        preview = document.raw_markdown[:max_chars]
        payload = {
            "id": document.id,
            "source_id": document.source_id,
            "url": document.url,
            "canonical_url": document.canonical_url,
            "title": document.title,
            "status_code": document.status_code,
            "fetched_at": document.fetched_at.isoformat(),
            "content_hash": document.content_hash,
            "metadata_json": document.metadata_json,
            "preview": preview,
            "truncated": len(document.raw_markdown) > max_chars,
        }
        if include_markdown:
            payload["raw_markdown"] = preview
        return payload

    def create_job_for_source(self, source_id: str) -> CrawlJob:
        with Session(self._engine) as session:
            source = session.get(Source, source_id)
            if source is None:
                raise ValueError("Source not found.")
            job = CrawlJob(
                source_id=source.id,
                requested_url=source.start_url,
                requested_depth=source.crawl_depth,
                requested_limit=source.crawl_limit,
                render=source.render,
                formats=source.formats,
            )
            session.add(job)
            session.commit()
            session.refresh(job)
            return job

    def submit_job(self, job_id: str) -> CrawlJob:
        with Session(self._engine) as session:
            job = session.get(CrawlJob, job_id)
            if job is None:
                raise ValueError("Job not found.")
            if job.provider_job_id:
                return job
            try:
                provider_job_id = self._cloudflare_client.submit_crawl(
                    url=job.requested_url,
                    depth=job.requested_depth,
                    limit=job.requested_limit,
                    render=job.render,
                    formats=job.formats,
                )
            except CloudflareNotConfiguredError as exc:
                job.status = JobStatus.failed.value
                job.error_text = str(exc)
                job.finished_at = utcnow()
                session.add(job)
                session.commit()
                raise
            job.provider_job_id = provider_job_id
            job.status = JobStatus.polling.value
            job.submitted_at = utcnow()
            job.started_at = job.started_at or utcnow()
            job.updated_at = utcnow()
            session.add(job)
            session.commit()
            session.refresh(job)
            return job

    def create_and_submit_job(self, source_id: str) -> CrawlJob:
        job = self.create_job_for_source(source_id)
        return self.submit_job(job.id)

    def retry_job(self, job_id: str) -> CrawlJob:
        with Session(self._engine) as session:
            existing = session.get(CrawlJob, job_id)
            if existing is None:
                raise ValueError("Job not found.")
            existing.provider_job_id = None
            existing.status = JobStatus.pending.value
            existing.error_text = None
            existing.submitted_at = None
            existing.started_at = None
            existing.finished_at = None
            existing.updated_at = utcnow()
            session.add(existing)
            session.commit()
        return self.submit_job(job_id)

    def poll_active_jobs(self) -> None:
        with Session(self._engine) as session:
            jobs = list(
                session.exec(
                    select(CrawlJob).where(CrawlJob.status.in_([JobStatus.polling.value, JobStatus.submitted.value]))
                )
            )
        for job in jobs:
            self._poll_single_job(job.id)

    def _poll_single_job(self, job_id: str) -> None:
        with Session(self._engine) as session:
            job = session.get(CrawlJob, job_id)
            if job is None or not job.provider_job_id:
                return
        try:
            result = self._cloudflare_client.get_job(job.provider_job_id)
        except Exception as exc:
            with Session(self._engine) as session:
                job = session.get(CrawlJob, job_id)
                if job:
                    job.error_text = str(exc)
                    job.updated_at = utcnow()
                    session.add(job)
                    session.commit()
            return
        with Session(self._engine) as session:
            job = session.get(CrawlJob, job_id)
            if job is None:
                return
            job.total_records = result.total
            job.finished_records = result.finished
            job.skipped_records = result.skipped
            job.updated_at = utcnow()
            if result.status == "completed":
                changed_documents = self._ingest_documents(session, job.source_id, result)
                session.refresh(job)
                job.status = JobStatus.completed.value
                job.finished_at = utcnow()
                job.error_text = None
                session.add(job)
                source = session.get(Source, job.source_id)
                if source:
                    source.last_run_at = utcnow()
                    source.last_success_at = source.last_run_at
                    source.updated_at = utcnow()
                    session.add(source)
                session.commit()
                if changed_documents:
                    self._index_documents(changed_documents)
            elif result.status in {"failed", "error"}:
                job.status = JobStatus.failed.value
                job.finished_at = utcnow()
                job.error_text = f"Provider reported status={result.status}"
                session.add(job)
                session.commit()
            else:
                job.status = JobStatus.polling.value
                session.add(job)
                session.commit()

    def _ingest_documents(self, session: Session, source_id: str, result: CrawlJobResult) -> list[str]:
        changed_document_ids: list[str] = []
        for record in result.records:
            if not record.markdown.strip():
                continue
            content_hash = hashlib.sha256(record.markdown.encode("utf-8")).hexdigest()
            existing = session.exec(
                select(Document).where(Document.source_id == source_id, Document.url == record.url)
            ).first()
            if existing and existing.content_hash == content_hash:
                existing.fetched_at = utcnow()
                existing.updated_at = utcnow()
                existing.metadata_json = record.metadata
                session.add(existing)
                continue

            if existing:
                self._delete_document_chunks(session, existing.id)
                document = existing
            else:
                document = Document(source_id=source_id, url=record.url, content_hash=content_hash, raw_markdown="")

            document.canonical_url = record.metadata.get("url") or record.url
            document.title = record.title
            document.status_code = record.status_code
            document.content_hash = content_hash
            document.fetched_at = utcnow()
            document.raw_markdown = record.markdown
            document.metadata_json = record.metadata
            document.updated_at = utcnow()
            session.add(document)
            session.flush()
            changed_document_ids.append(document.id)
        session.commit()
        return changed_document_ids

    def _delete_document_chunks(self, session: Session, document_id: str) -> None:
        chunks = list(session.exec(select(Chunk).where(Chunk.document_id == document_id)))
        point_ids = [chunk.vector_point_id for chunk in chunks if chunk.vector_point_id]
        if point_ids:
            self._vector_store.delete_points(point_ids)
        session.exec(delete(Chunk).where(Chunk.document_id == document_id))
        session.commit()

    def _index_documents(self, document_ids: list[str]) -> None:
        with Session(self._engine) as session:
            documents = [session.get(Document, document_id) for document_id in document_ids]
            documents = [document for document in documents if document is not None]
            points = []
            chunks_to_update: list[Chunk] = []
            for document in documents:
                chunks = self._chunker.split(document.raw_markdown)
                texts = [chunk.text for chunk in chunks]
                vectors = self._embedding_service.embed_texts(texts)
                vector_size = len(vectors[0]) if vectors else self._embedding_service.vector_size()
                for chunk_data, vector in zip(chunks, vectors):
                    chunk = Chunk(
                        document_id=document.id,
                        chunk_index=chunk_data.index,
                        text=chunk_data.text,
                        content_hash=hashlib.sha256(chunk_data.text.encode("utf-8")).hexdigest(),
                        token_estimate=chunk_data.token_estimate,
                        embedding_model=self._embedding_service.model_name,
                        embedded_at=utcnow(),
                        vector_point_id=str(uuid4()),
                    )
                    session.add(chunk)
                    session.flush()
                    chunks_to_update.append(chunk)
                    points.append(
                        (
                            chunk.vector_point_id,
                            vector,
                            {
                                "source_id": document.source_id,
                                "document_id": document.id,
                                "chunk_id": chunk.id,
                                "url": document.url,
                                "title": document.title,
                                "chunk_index": chunk.chunk_index,
                                "content_hash": document.content_hash,
                                "fetched_at": document.fetched_at.isoformat(),
                            },
                        )
                    )
                self._vector_store.upsert(points=[point for point in points if point[2]["document_id"] == document.id], vector_size=vector_size)
            for chunk in chunks_to_update:
                chunk.updated_at = utcnow()
                session.add(chunk)
            session.commit()

    def process_due_sources(self) -> None:
        now = utcnow()
        with Session(self._engine) as session:
            due_sources = list(
                session.exec(
                    select(Source).where(
                        Source.enabled.is_(True),
                        Source.cron_expr.is_not(None),
                        Source.next_run_at.is_not(None),
                        Source.next_run_at <= now,
                    )
                )
            )
            active_source_ids = {
                source_id
                for source_id in session.exec(
                    select(CrawlJob.source_id).where(
                        CrawlJob.status.in_([JobStatus.pending.value, JobStatus.submitted.value, JobStatus.polling.value])
                    )
                )
            }
        for source in due_sources:
            if source.id in active_source_ids:
                continue
            try:
                self.create_and_submit_job(source.id)
            finally:
                with Session(self._engine) as session:
                    fresh_source = session.get(Source, source.id)
                    if fresh_source:
                        fresh_source.last_run_at = utcnow()
                        fresh_source.next_run_at = self._compute_next_run(fresh_source.cron_expr, fresh_source.last_run_at)
                        fresh_source.updated_at = utcnow()
                        session.add(fresh_source)
                        session.commit()

    def _compute_next_run(self, cron_expr: str | None, start: datetime | None = None) -> datetime | None:
        from apscheduler.triggers.cron import CronTrigger

        if not cron_expr:
            return None
        trigger = CronTrigger.from_crontab(cron_expr, timezone=datetime.now().astimezone().tzinfo)
        next_fire = trigger.get_next_fire_time(None, start or datetime.now().astimezone())
        return next_fire.astimezone().astimezone(tz=utcnow().tzinfo) if next_fire else None

    def reindex_source(self, source_id: str) -> int:
        with Session(self._engine) as session:
            documents = list(session.exec(select(Document).where(Document.source_id == source_id)))
            for document in documents:
                self._delete_document_chunks(session, document.id)
        self._index_documents([document.id for document in documents])
        return len(documents)
