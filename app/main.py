"""Service container with improved initialization and graceful shutdown."""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import api_router
from app.config import Settings, get_settings
from app.db.session import create_db_engine, init_db
from app.services.cloudflare import CloudflareCrawlClient
from app.services.embeddings import EmbeddingService
from app.services.jobs import CrawlCoordinator
from app.services.search import SearchService
from app.services.sources import SourceService
from app.services.vector_store import VectorStore
from app.ui.routes import ui_router
from app.workers.scheduler import AppScheduler

logger = logging.getLogger(__name__)

UI_READY_TIMEOUT_SECONDS = 15.0
UI_READY_POLL_INTERVAL_SECONDS = 0.25


@dataclass
class ServiceContainer:
    source_service: SourceService
    crawl_coordinator: CrawlCoordinator
    search_service: SearchService
    scheduler: AppScheduler
    vector_store: VectorStore

    def health_check(self) -> dict[str, bool]:
        """Check health of all services."""
        try:
            return {
                "vector_store": self.vector_store.health_check(),
            }
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {"error": str(e)}

    def close(self) -> None:
        """Gracefully close all services."""
        logger.info("Closing service container...")

        # Close scheduler first
        if hasattr(self, "scheduler") and self.scheduler:
            try:
                self.scheduler.shutdown(wait=True)
                logger.debug("Scheduler shut down")
            except Exception as e:
                logger.error(f"Error shutting down scheduler: {e}")

        # Close vector store
        if hasattr(self, "vector_store") and self.vector_store:
            try:
                self.vector_store.close()
                logger.debug("Vector store closed")
            except Exception as e:
                logger.error(f"Error closing vector store: {e}")


def build_container(
    settings: Settings | None = None,
    max_retries: int = 3,
) -> ServiceContainer:
    """
    Build the service container with retry logic.

    Args:
        settings: Optional settings object
        max_retries: Maximum initialization retry attempts

    Returns:
        Configured ServiceContainer

    Raises:
        RuntimeError: If container cannot be initialized after max_retries
    """
    settings = settings or get_settings()
    last_error = None

    for attempt in range(max_retries):
        try:
            logger.info(f"Building service container (attempt {attempt + 1}/{max_retries})...")

            # Create database engine
            engine = create_db_engine(settings)
            init_db(engine)
            logger.debug("Database initialized")

            # Create services
            vector_store = VectorStore(settings)
            embedding_service = EmbeddingService(settings, vector_store)
            cloudflare_client = CloudflareCrawlClient(settings)
            source_service = SourceService(engine, settings)
            crawl_coordinator = CrawlCoordinator(
                engine=engine,
                settings=settings,
                cloudflare_client=cloudflare_client,
                embedding_service=embedding_service,
                vector_store=vector_store,
            )
            search_service = SearchService(engine, embedding_service, vector_store)
            scheduler = AppScheduler(settings, source_service, crawl_coordinator)

            container = ServiceContainer(
                source_service=source_service,
                crawl_coordinator=crawl_coordinator,
                search_service=search_service,
                scheduler=scheduler,
                vector_store=vector_store,
            )

            # Verify vector store is accessible
            if not vector_store.health_check():
                logger.warning("Vector store health check failed on initialization")

            logger.info("Service container built successfully")
            return container

        except Exception as e:
            last_error = e
            logger.warning(
                f"Container initialization failed (attempt {attempt + 1}/{max_retries}): {e}"
            )
            if attempt < max_retries - 1:
                time.sleep(2**attempt)  # Exponential backoff

    raise RuntimeError(
        f"Failed to initialize service container after {max_retries} attempts: {last_error}"
    )


def create_app(
    *,
    settings: Settings | None = None,
    container: ServiceContainer | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings or get_settings()
        app.state.services = container or build_container(app.state.settings)
        app.state.services.scheduler.start()
        try:
            yield
        finally:
            app.state.services.scheduler.shutdown()
            app.state.services.close()

    fastapi_app = FastAPI(title="Crawl Index Server", lifespan=lifespan)
    fastapi_app.mount("/static", StaticFiles(directory="app/ui/static"), name="static")
    fastapi_app.include_router(api_router)
    fastapi_app.include_router(ui_router)
    return fastapi_app


app = create_app()


def get_admin_ui_url(settings: Settings) -> str:
    return f"http://{settings.app_host}:{settings.app_port}/admin/sources"


def wait_for_ui_ready_and_open(
    url: str,
    *,
    timeout_seconds: float = UI_READY_TIMEOUT_SECONDS,
    poll_interval_seconds: float = UI_READY_POLL_INTERVAL_SECONDS,
    open_browser=None,
    urlopen=None,
    sleep=None,
    monotonic=None,
) -> bool:
    import urllib.error
    import urllib.request
    import webbrowser

    open_browser = open_browser or webbrowser.open_new_tab
    urlopen = urlopen or urllib.request.urlopen
    sleep = sleep or time.sleep
    monotonic = monotonic or time.monotonic

    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        try:
            with urlopen(url, timeout=1.0) as response:
                status_code = getattr(response, "status", 200)
            if status_code < 500:
                open_browser(url)
                return True
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            pass
        sleep(poll_interval_seconds)
    return False


def start_ui_browser_thread(settings: Settings) -> None:
    import threading

    url = get_admin_ui_url(settings)
    thread = threading.Thread(
        target=wait_for_ui_ready_and_open,
        kwargs={"url": url},
        name="crawl-index-ui-open",
        daemon=True,
    )
    thread.start()


def run() -> None:
    settings = get_settings()
    start_ui_browser_thread(settings)
    uvicorn.run("app.main:app", host=settings.app_host, port=settings.app_port, reload=False)
