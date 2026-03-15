from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mcp.server.fastmcp import FastMCP

from app.main import ServiceContainer, build_container
from app.config import get_settings


@dataclass
class MCPContainer:
    services: ServiceContainer

    def refresh_jobs(self) -> None:
        self.services.crawl_coordinator.poll_active_jobs()

    def close(self) -> None:
        self.services.close()


class CrawlIndexMCPAdapter:
    def __init__(self, container: MCPContainer):
        self._container = container

    def _poll_before_read(self) -> None:
        self._container.refresh_jobs()

    @staticmethod
    def _iso(value: Any) -> Any:
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return value

    def list_sources(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        self._poll_before_read()
        return [
            {
                "id": source.id,
                "name": source.name,
                "start_url": source.start_url,
                "enabled": source.enabled,
                "cron_expr": source.cron_expr,
                "next_run_at": self._iso(source.next_run_at) if source.next_run_at else None,
                "last_success_at": self._iso(source.last_success_at) if source.last_success_at else None,
            }
            for source in self._container.services.source_service.list_sources(enabled_only=enabled_only)
        ]

    def get_source(self, source_id: str) -> dict[str, Any]:
        self._poll_before_read()
        source = self._container.services.source_service.get_source(source_id)
        if source is None:
            raise ValueError("Source not found.")
        return {
            "id": source.id,
            "name": source.name,
            "start_url": source.start_url,
            "allowed_domains": source.allowed_domains,
            "source_type": source.source_type,
            "cron_expr": source.cron_expr,
            "enabled": source.enabled,
            "crawl_depth": source.crawl_depth,
            "crawl_limit": source.crawl_limit,
            "render": source.render,
            "formats": source.formats,
            "next_run_at": self._iso(source.next_run_at) if source.next_run_at else None,
            "last_success_at": self._iso(source.last_success_at) if source.last_success_at else None,
        }

    def trigger_crawl(self, source_id: str) -> dict[str, Any]:
        job = self._container.services.crawl_coordinator.create_and_submit_job(source_id)
        return {
            "job_id": job.id,
            "provider_job_id": job.provider_job_id,
            "status": job.status,
        }

    def list_jobs(
        self,
        source_id: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        self._poll_before_read()
        return [
            {
                "id": job.id,
                "source_id": job.source_id,
                "status": job.status,
                "provider_job_id": job.provider_job_id,
                "requested_url": job.requested_url,
                "total_records": job.total_records,
                "finished_records": job.finished_records,
                "skipped_records": job.skipped_records,
                "error_text": job.error_text,
                "submitted_at": self._iso(job.submitted_at) if job.submitted_at else None,
                "started_at": self._iso(job.started_at) if job.started_at else None,
                "finished_at": self._iso(job.finished_at) if job.finished_at else None,
            }
            for job in self._container.services.crawl_coordinator.list_jobs(
                source_id=source_id,
                status=status,
                limit=limit,
            )
        ]

    def get_job(self, job_id: str) -> dict[str, Any]:
        self._poll_before_read()
        job = self._container.services.crawl_coordinator.get_job(job_id)
        if job is None:
            raise ValueError("Job not found.")
        return {
            "id": job.id,
            "source_id": job.source_id,
            "status": job.status,
            "provider_job_id": job.provider_job_id,
            "requested_url": job.requested_url,
            "requested_depth": job.requested_depth,
            "requested_limit": job.requested_limit,
            "render": job.render,
            "formats": job.formats,
            "total_records": job.total_records,
            "finished_records": job.finished_records,
            "skipped_records": job.skipped_records,
            "error_text": job.error_text,
            "submitted_at": self._iso(job.submitted_at) if job.submitted_at else None,
            "started_at": self._iso(job.started_at) if job.started_at else None,
            "finished_at": self._iso(job.finished_at) if job.finished_at else None,
        }

    def retry_job(self, job_id: str) -> dict[str, Any]:
        job = self._container.services.crawl_coordinator.retry_job(job_id)
        return {
            "job_id": job.id,
            "provider_job_id": job.provider_job_id,
            "status": job.status,
        }

    def list_documents(self, source_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        self._poll_before_read()
        return [
            {
                "id": document.id,
                "source_id": document.source_id,
                "url": document.url,
                "title": document.title,
                "fetched_at": self._iso(document.fetched_at),
                "status_code": document.status_code,
            }
            for document in self._container.services.crawl_coordinator.list_documents(source_id=source_id, limit=limit)
        ]

    def get_document(
        self,
        document_id: str,
        include_markdown: bool = False,
        max_chars: int = 4000,
    ) -> dict[str, Any]:
        self._poll_before_read()
        if max_chars < 1:
            raise ValueError("max_chars must be at least 1.")
        payload = self._container.services.crawl_coordinator.get_document_payload(
            document_id,
            include_markdown=include_markdown,
            max_chars=max_chars,
        )
        if payload is None:
            raise ValueError("Document not found.")
        return payload

    def search_docs(
        self,
        query: str,
        limit: int = 10,
        source_id: str | None = None,
    ) -> list[dict[str, Any]]:
        self._poll_before_read()
        return self._container.services.search_service.search(query=query, limit=limit, source_id=source_id)


def create_mcp_container() -> MCPContainer:
    return MCPContainer(services=build_container())


def create_mcp_server(container: MCPContainer | None = None) -> FastMCP:
    runtime = container or create_mcp_container()
    adapter = CrawlIndexMCPAdapter(runtime)
    mcp = FastMCP("crawl-index")

    @mcp.tool()
    def list_sources(enabled_only: bool = False) -> list[dict[str, Any]]:
        """List available crawl sources, optionally only enabled ones."""
        return adapter.list_sources(enabled_only=enabled_only)

    @mcp.tool()
    def get_source(source_id: str) -> dict[str, Any]:
        """Get one source with crawl defaults and scheduling metadata."""
        return adapter.get_source(source_id)

    @mcp.tool()
    def trigger_crawl(source_id: str) -> dict[str, Any]:
        """Start a crawl job for a source and return the created local job identifiers."""
        return adapter.trigger_crawl(source_id)

    @mcp.tool()
    def list_jobs(
        source_id: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """List recent crawl jobs, with optional filtering by source and status."""
        return adapter.list_jobs(source_id=source_id, status=status, limit=limit)

    @mcp.tool()
    def get_job(job_id: str) -> dict[str, Any]:
        """Get one crawl job with current progress, timestamps, and error details."""
        return adapter.get_job(job_id)

    @mcp.tool()
    def retry_job(job_id: str) -> dict[str, Any]:
        """Retry a failed job by re-submitting it to the crawl provider."""
        return adapter.retry_job(job_id)

    @mcp.tool()
    def list_documents(source_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """List recently fetched documents, optionally filtered to a single source."""
        return adapter.list_documents(source_id=source_id, limit=limit)

    @mcp.tool()
    def get_document(
        document_id: str,
        include_markdown: bool = False,
        max_chars: int = 4000,
    ) -> dict[str, Any]:
        """Get document metadata and a bounded preview; optionally include truncated markdown."""
        return adapter.get_document(document_id, include_markdown=include_markdown, max_chars=max_chars)

    @mcp.tool()
    def search_docs(query: str, limit: int = 10, source_id: str | None = None) -> list[dict[str, Any]]:
        """Run semantic search over indexed documents and return snippets with source context."""
        return adapter.search_docs(query=query, limit=limit, source_id=source_id)

    @mcp.tool()
    def get_web_ui_info() -> dict[str, str]:
        """Provides the URL and capabilities of the Local Crawl Index Server's Web UI. Call this when the user asks about settings, missing credentials, or wants a visual dashboard."""
        settings = get_settings()
        base_url = f"http://{settings.app_host}:{settings.app_port}"
        return {
            "message": "The Crawl Index Server has a full Web UI running locally.",
            "dashboard_url": f"{base_url}/admin/sources",
            "settings_url": f"{base_url}/admin/settings",
            "capabilities": "Users can visually manage sources, track crawl jobs in real-time, configure Cloudflare API tokens, and perform semantic searches."
        }

    return mcp


def run() -> None:
    server = create_mcp_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    run()
