"""MCP server with health checks, graceful errors, and daemon mode."""

from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass
from typing import Any

from mcp.server.fastmcp import FastMCP

from app.main import ServiceContainer, build_container
from app.config import get_settings
from app.services.daemon import DaemonLock, setup_logging, register_shutdown_handler

logger = logging.getLogger(__name__)


@dataclass
class MCPContainer:
    services: ServiceContainer

    def refresh_jobs(self) -> None:
        try:
            self.services.crawl_coordinator.poll_active_jobs()
        except Exception as e:
            logger.warning(f"refresh_jobs failed: {e}")

    def health_check(self) -> dict[str, bool]:
        """Check health of all services."""
        return {
            "vector_store": self.services.vector_store.health_check(),
        }

    def close(self) -> None:
        self.services.close()


class CrawlIndexMCPAdapter:
    def __init__(self, container: MCPContainer):
        self._container = container

    def _poll_before_read(self) -> None:
        """Poll active jobs with error handling."""
        try:
            self._container.refresh_jobs()
        except Exception as e:
            logger.warning(f"Poll before read failed: {e}")
            # Continue anyway - don't block reads

    def _health_check(self) -> dict[str, bool]:
        """Get health status of all services."""
        return self._container.health_check()

    @staticmethod
    def _iso(value: Any) -> Any:
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return value

    def list_sources(self, enabled_only: bool = False) -> dict[str, Any]:
        """
        List available crawl sources.

        Returns:
            Dict with 'sources' key containing list of sources, or 'error' key on failure.
        """
        try:
            self._poll_before_read()
            sources = self._container.services.source_service.list_sources(enabled_only=enabled_only)
            return {
                "sources": [
                    {
                        "id": source.id,
                        "name": source.name,
                        "start_url": source.start_url,
                        "enabled": source.enabled,
                        "cron_expr": source.cron_expr,
                        "next_run_at": self._iso(source.next_run_at) if source.next_run_at else None,
                        "last_success_at": self._iso(source.last_success_at) if source.last_success_at else None,
                    }
                    for source in sources
                ]
            }
        except Exception as e:
            logger.error(f"list_sources failed: {e}")
            return {"error": str(e), "sources": []}

    def get_source(self, source_id: str) -> dict[str, Any]:
        """Get one source with crawl defaults and scheduling metadata."""
        try:
            self._poll_before_read()
            source = self._container.services.source_service.get_source(source_id)
            if source is None:
                return {"error": "Source not found", "source_id": source_id}
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
        except Exception as e:
            logger.error(f"get_source failed: {e}")
            return {"error": str(e), "source_id": source_id}

    def trigger_crawl(self, source_id: str) -> dict[str, Any]:
        """Start a crawl job for a source and return the created local job identifiers."""
        try:
            job = self._container.services.crawl_coordinator.create_and_submit_job(source_id)
            return {
                "job_id": job.id,
                "provider_job_id": job.provider_job_id,
                "status": job.status,
            }
        except ValueError as e:
            return {"error": str(e), "source_id": source_id}
        except Exception as e:
            logger.error(f"trigger_crawl failed: {e}")
            return {"error": str(e), "source_id": source_id}

    def list_jobs(
        self,
        source_id: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """List recent crawl jobs, with optional filtering by source and status."""
        try:
            self._poll_before_read()
            jobs = self._container.services.crawl_coordinator.list_jobs(
                source_id=source_id,
                status=status,
                limit=limit,
            )
            return {
                "jobs": [
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
                    for job in jobs
                ]
            }
        except Exception as e:
            logger.error(f"list_jobs failed: {e}")
            return {"error": str(e), "jobs": []}

    def get_job(self, job_id: str) -> dict[str, Any]:
        """Get one crawl job with current progress, timestamps, and error details."""
        try:
            self._poll_before_read()
            job = self._container.services.crawl_coordinator.get_job(job_id)
            if job is None:
                return {"error": "Job not found", "job_id": job_id}
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
        except Exception as e:
            logger.error(f"get_job failed: {e}")
            return {"error": str(e), "job_id": job_id}

    def retry_job(self, job_id: str) -> dict[str, Any]:
        """Retry a failed job by re-submitting it to the crawl provider."""
        try:
            job = self._container.services.crawl_coordinator.retry_job(job_id)
            return {
                "job_id": job.id,
                "provider_job_id": job.provider_job_id,
                "status": job.status,
            }
        except ValueError as e:
            return {"error": str(e), "job_id": job_id}
        except Exception as e:
            logger.error(f"retry_job failed: {e}")
            return {"error": str(e), "job_id": job_id}

    def list_documents(self, source_id: str | None = None, limit: int = 20) -> dict[str, Any]:
        """List recently fetched documents, optionally filtered to a single source."""
        try:
            self._poll_before_read()
            documents = self._container.services.crawl_coordinator.list_documents(
                source_id=source_id,
                limit=limit,
            )
            return {
                "documents": [
                    {
                        "id": document.id,
                        "source_id": document.source_id,
                        "url": document.url,
                        "title": document.title,
                        "fetched_at": self._iso(document.fetched_at),
                        "status_code": document.status_code,
                    }
                    for document in documents
                ]
            }
        except Exception as e:
            logger.error(f"list_documents failed: {e}")
            return {"error": str(e), "documents": []}

    def get_document(
        self,
        document_id: str,
        include_markdown: bool = False,
        max_chars: int = 4000,
    ) -> dict[str, Any]:
        """Get document metadata and a bounded preview; optionally include truncated markdown."""
        try:
            self._poll_before_read()
            if max_chars < 1:
                return {"error": "max_chars must be at least 1", "document_id": document_id}
            payload = self._container.services.crawl_coordinator.get_document_payload(
                document_id,
                include_markdown=include_markdown,
                max_chars=max_chars,
            )
            if payload is None:
                return {"error": "Document not found", "document_id": document_id}
            return payload
        except Exception as e:
            logger.error(f"get_document failed: {e}")
            return {"error": str(e), "document_id": document_id}

    def search_docs(
        self,
        query: str,
        limit: int = 10,
        source_id: str | None = None,
    ) -> dict[str, Any]:
        """Run semantic search over indexed documents and return snippets with source context."""
        try:
            self._poll_before_read()
            results = self._container.services.search_service.search(
                query=query,
                limit=limit,
                source_id=source_id,
            )
            return {"results": results}
        except Exception as e:
            logger.error(f"search_docs failed: {e}")
            return {"error": str(e), "results": []}

    def create_source(
        self,
        name: str,
        start_url: str,
        allowed_domains: list[str],
        source_type: str = "docs",
        crawl_depth: int = 2,
        crawl_limit: int = 50,
        render: bool = False,
        formats: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a new crawl source."""
        if formats is None:
            formats = ["markdown"]
        try:
            payload = {
                "name": name,
                "start_url": start_url,
                "allowed_domains": allowed_domains,
                "source_type": source_type,
                "crawl_depth": crawl_depth,
                "crawl_limit": crawl_limit,
                "render": render,
                "formats": formats,
            }
            source = self._container.services.source_service.create_source(payload)
            return {
                "source_id": source.id,
                "name": source.name,
                "start_url": source.start_url,
                "enabled": source.enabled,
            }
        except Exception as e:
            logger.error(f"create_source failed: {e}")
            return {"error": str(e)}

    def reindex_source(self, source_id: str) -> dict[str, Any]:
        """Re-index all documents for a source (useful after content updates)."""
        try:
            count = self._container.services.crawl_coordinator.reindex_source(source_id)
            return {
                "source_id": source_id,
                "documents_reindexed": count,
            }
        except Exception as e:
            logger.error(f"reindex_source failed: {e}")
            return {"error": str(e), "source_id": source_id}

    def get_health_status(self) -> dict[str, Any]:
        """Get health status of all services."""
        try:
            health = self._health_check()
            return {
                "healthy": all(health.values()) if health else False,
                "services": health,
            }
        except Exception as e:
            logger.error(f"health_check failed: {e}")
            return {"healthy": False, "error": str(e)}


def create_mcp_container(max_retries: int = 3) -> MCPContainer:
    """Create MCP container with retry logic for initialization."""
    last_error = None

    for attempt in range(max_retries):
        try:
            container = MCPContainer(services=build_container())
            # Quick health check to verify initialization
            container.health_check()
            logger.info(f"MCP container initialized (attempt {attempt + 1})")
            return container
        except Exception as e:
            last_error = e
            logger.warning(
                f"Container initialization failed (attempt {attempt + 1}/{max_retries}): {e}"
            )
            if attempt < max_retries - 1:
                time.sleep(2**attempt)  # Exponential backoff

    raise RuntimeError(f"Failed to initialize container after {max_retries} attempts: {last_error}")


def create_mcp_server(container: MCPContainer | None = None) -> FastMCP:
    runtime = container or create_mcp_container()
    adapter = CrawlIndexMCPAdapter(runtime)
    mcp = FastMCP("crawl-index")

    @mcp.tool()
    def list_sources(enabled_only: bool = False) -> dict[str, Any]:
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
    ) -> dict[str, Any]:
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
    def list_documents(source_id: str | None = None, limit: int = 20) -> dict[str, Any]:
        """List recently fetched documents, optionally filtered to a single source."""
        return adapter.list_documents(source_id=source_id, limit=limit)

    @mcp.tool()
    def get_document(
        document_id: str,
        include_markdown: bool = False,
        max_chars: int = 4000,
    ) -> dict[str, Any]:
        """Get document metadata and a bounded preview; optionally include truncated markdown."""
        return adapter.get_document(
            document_id,
            include_markdown=include_markdown,
            max_chars=max_chars,
        )

    @mcp.tool()
    def search_docs(query: str, limit: int = 10, source_id: str | None = None) -> dict[str, Any]:
        """Run semantic search over indexed documents and return snippets with source context."""
        return adapter.search_docs(query=query, limit=limit, source_id=source_id)

    @mcp.tool()
    def get_web_ui_info() -> dict[str, str]:
        """Provides the URL and capabilities of the Local Crawl Index Server's Web UI."""
        settings = get_settings()
        base_url = f"http://{settings.app_host}:{settings.app_port}"
        return {
            "message": "The Crawl Index Server has a full Web UI running locally.",
            "dashboard_url": f"{base_url}/admin/sources",
            "settings_url": f"{base_url}/admin/settings",
            "capabilities": "Users can visually manage sources, track crawl jobs in real-time, configure Cloudflare API tokens, and perform semantic searches.",
        }

    @mcp.tool()
    def health_check() -> dict[str, Any]:
        """Get health status of all services (vector store, etc.)."""
        return adapter.get_health_status()

    @mcp.tool()
    def create_source(
        name: str,
        start_url: str,
        allowed_domains: list[str],
        source_type: str = "docs",
        crawl_depth: int = 2,
        crawl_limit: int = 50,
        render: bool = False,
        formats: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a new crawl source for indexing."""
        return adapter.create_source(
            name=name,
            start_url=start_url,
            allowed_domains=allowed_domains,
            source_type=source_type,
            crawl_depth=crawl_depth,
            crawl_limit=crawl_limit,
            render=render,
            formats=formats,
        )

    @mcp.tool()
    def reindex_source(source_id: str) -> dict[str, Any]:
        """Re-index all documents for a source (useful after content updates)."""
        return adapter.reindex_source(source_id)

    return mcp


def run() -> None:
    """Run the MCP server with daemon lock."""
    setup_logging()
    logger.info("Starting crawl-index MCP server...")

    # Try to acquire daemon lock
    daemon_lock = DaemonLock()
    if not daemon_lock.acquire(timeout=5.0):
        print("ERROR: Another MCP server instance is already running", file=sys.stderr)
        sys.exit(1)

    try:
        # Register cleanup
        container = None

        def cleanup():
            nonlocal container
            logger.info("Cleaning up...")
            if container:
                try:
                    container.close()
                except Exception as e:
                    logger.error(f"Error during cleanup: {e}")
            daemon_lock.release()

        register_shutdown_handler(cleanup)

        # Create and run server
        container = create_mcp_container()
        mcp_server = create_mcp_server(container)

        logger.info("MCP server running (stdio transport)")
        mcp_server.run(transport="stdio")

    except Exception as e:
        logger.error(f"MCP server failed: {e}")
        sys.exit(1)
    finally:
        daemon_lock.release()


if __name__ == "__main__":
    run()
