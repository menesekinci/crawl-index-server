from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
import threading
import time
import urllib.error
import urllib.request
import webbrowser

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import api_router
from app.config import get_settings
from app.db.session import create_db_engine, init_db
from app.services.cloudflare import CloudflareCrawlClient
from app.services.embeddings import EmbeddingService
from app.services.jobs import CrawlCoordinator
from app.services.search import SearchService
from app.services.sources import SourceService
from app.services.vector_store import VectorStore
from app.ui.routes import ui_router
from app.workers.scheduler import AppScheduler

UI_READY_TIMEOUT_SECONDS = 15.0
UI_READY_POLL_INTERVAL_SECONDS = 0.25


@dataclass
class ServiceContainer:
    source_service: SourceService
    crawl_coordinator: CrawlCoordinator
    search_service: SearchService
    scheduler: AppScheduler
    vector_store: VectorStore

    def close(self) -> None:
        close = getattr(self.vector_store, "close", None)
        if callable(close):
            close()


def build_container(settings=None) -> ServiceContainer:
    settings = settings or get_settings()
    engine = create_db_engine(settings)
    init_db(engine)
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
    return ServiceContainer(
        source_service=source_service,
        crawl_coordinator=crawl_coordinator,
        search_service=search_service,
        scheduler=scheduler,
        vector_store=vector_store,
    )


def create_app(
    *,
    settings=None,
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


def get_admin_ui_url(settings) -> str:
    return f"http://{settings.app_host}:{settings.app_port}/admin/sources"


def wait_for_ui_ready_and_open(
    url: str,
    *,
    timeout_seconds: float = UI_READY_TIMEOUT_SECONDS,
    poll_interval_seconds: float = UI_READY_POLL_INTERVAL_SECONDS,
    open_browser=webbrowser.open_new_tab,
    urlopen=urllib.request.urlopen,
    sleep=time.sleep,
    monotonic=time.monotonic,
) -> bool:
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


def start_ui_browser_thread(settings) -> threading.Thread:
    url = get_admin_ui_url(settings)
    thread = threading.Thread(
        target=wait_for_ui_ready_and_open,
        kwargs={"url": url},
        name="crawl-index-ui-open",
        daemon=True,
    )
    thread.start()
    return thread


def run() -> None:
    settings = get_settings()
    start_ui_browser_thread(settings)
    uvicorn.run("app.main:app", host=settings.app_host, port=settings.app_port, reload=False)
