from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from app.config import Settings
from app.db.models import CrawlJob, Document, Source
from app.main import ServiceContainer, create_app, run, start_ui_browser_thread, wait_for_ui_ready_and_open
from app.services.jobs import CrawlCoordinator
from app.services.search import SearchService
from app.services.sources import SourceService
from app.workers.scheduler import AppScheduler


class StubCloudflareClient:
    enabled = True

    def submit_crawl(self, **kwargs):
        return "provider-job-1"

    def get_job(self, provider_job_id):
        from app.services.cloudflare import CrawlJobResult, CrawlRecord

        return CrawlJobResult(
            id=provider_job_id,
            status="completed",
            total=1,
            finished=1,
            skipped=0,
            records=[
                CrawlRecord(
                    url="https://docs.example.com/getting-started",
                    status="completed",
                    title="Getting Started",
                    status_code=200,
                    markdown="# Getting Started\nUse an API token for authentication.",
                    metadata={"status": 200, "title": "Getting Started"},
                )
            ],
        )


class StubEmbeddingService:
    model_name = "stub-mini"

    def __init__(self):
        self.calls = 0

    def embed_texts(self, texts):
        self.calls += 1
        return [[0.5, 0.1, 0.9] for _ in texts]

    def embed_query(self, text):
        return [0.5, 0.1, 0.9]

    def vector_size(self):
        return 3


class StubVectorStore:
    def __init__(self):
        self.points = []

    def upsert(self, points, vector_size):
        self.points.extend(points)

    def delete_points(self, point_ids):
        self.points = [point for point in self.points if point[0] not in point_ids]

    def search(self, query_vector, limit=10, source_id=None):
        results = []
        for point_id, _, payload in self.points[:limit]:
            if source_id and payload["source_id"] != source_id:
                continue
            results.append({"id": point_id, "score": 0.99, "payload": payload})
        return results


def build_test_container(tmp_path: Path):
    db_path = tmp_path / "integration.db"
    settings = Settings(
        database_url=f"sqlite:///{db_path}",
        qdrant_path=str(tmp_path / "qdrant"),
        cf_account_id="acc",
        cf_api_token="token",
    )
    engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    vector_store = StubVectorStore()
    embedding_service = StubEmbeddingService()
    source_service = SourceService(engine, settings)
    crawl_coordinator = CrawlCoordinator(
        engine=engine,
        settings=settings,
        cloudflare_client=StubCloudflareClient(),
        embedding_service=embedding_service,
        vector_store=vector_store,
    )
    search_service = SearchService(engine, embedding_service, vector_store)
    scheduler = AppScheduler(settings, source_service, crawl_coordinator)
    return settings, ServiceContainer(source_service, crawl_coordinator, search_service, scheduler, vector_store), engine


def test_source_to_search_flow(tmp_path: Path):
    settings, container, engine = build_test_container(tmp_path)
    with TestClient(create_app(settings=settings, container=container)) as client:
        source_res = client.post(
            "/api/sources",
            json={"name": "Docs", "start_url": "https://docs.example.com", "allowed_domains": ["docs.example.com"]},
        )
        assert source_res.status_code == 200
        source_id = source_res.json()["id"]

        crawl_res = client.post(f"/api/sources/{source_id}/crawl")
        assert crawl_res.status_code == 200
        job_id = crawl_res.json()["id"]

        container.crawl_coordinator.poll_active_jobs()

        with Session(engine) as session:
            assert session.exec(select(CrawlJob).where(CrawlJob.id == job_id)).first().status == "completed"
            assert session.exec(select(Document)).first() is not None

        search_res = client.post("/api/search", json={"query": "API token authentication", "limit": 5})
        assert search_res.status_code == 200
        results = search_res.json()
        assert len(results) == 1
        assert results[0]["title"] == "Getting Started"


class StubResponse:
    def __init__(self, status: int):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_wait_for_ui_ready_and_open_retries_until_ready():
    opened_urls = []
    attempts = {"count": 0}

    def fake_urlopen(url, timeout):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise OSError("not ready")
        return StubResponse(200)

    def fake_open_browser(url):
        opened_urls.append(url)

    result = wait_for_ui_ready_and_open(
        "http://127.0.0.1:8000/admin/sources",
        timeout_seconds=1,
        poll_interval_seconds=0,
        open_browser=fake_open_browser,
        urlopen=fake_urlopen,
        sleep=lambda _: None,
        monotonic=lambda: attempts["count"] / 10,
    )

    assert result is True
    assert opened_urls == ["http://127.0.0.1:8000/admin/sources"]
    assert attempts["count"] == 3


def test_wait_for_ui_ready_and_open_times_out_cleanly():
    opened_urls = []
    tick = {"value": 0}

    def fake_urlopen(url, timeout):
        raise OSError("still starting")

    def fake_open_browser(url):
        opened_urls.append(url)

    def fake_monotonic():
        current = tick["value"]
        tick["value"] += 1
        return current

    result = wait_for_ui_ready_and_open(
        "http://127.0.0.1:8000/admin/sources",
        timeout_seconds=2,
        poll_interval_seconds=0,
        open_browser=fake_open_browser,
        urlopen=fake_urlopen,
        sleep=lambda _: None,
        monotonic=fake_monotonic,
    )

    assert result is False
    assert opened_urls == []


def test_start_ui_browser_thread_uses_admin_url(tmp_path: Path):
    settings, _, _ = build_test_container(tmp_path)
    seen = {}

    def fake_wait_for_ui_ready_and_open(url: str) -> bool:
        seen["url"] = url
        return True

    import app.main as main_module

    original = main_module.wait_for_ui_ready_and_open
    main_module.wait_for_ui_ready_and_open = fake_wait_for_ui_ready_and_open
    try:
        thread = start_ui_browser_thread(settings)
        thread.join(timeout=1)
    finally:
        main_module.wait_for_ui_ready_and_open = original

    assert seen["url"] == f"http://{settings.app_host}:{settings.app_port}/admin/sources"


def test_run_starts_browser_thread_before_uvicorn(monkeypatch, tmp_path: Path):
    settings, _, _ = build_test_container(tmp_path)
    calls = []

    def fake_get_settings():
        return settings

    def fake_start_ui_browser_thread(runtime_settings):
        calls.append(("thread", runtime_settings.app_port))

    def fake_uvicorn_run(app_path, host, port, reload):
        calls.append(("uvicorn", app_path, host, port, reload))

    monkeypatch.setattr("app.main.get_settings", fake_get_settings)
    monkeypatch.setattr("app.main.start_ui_browser_thread", fake_start_ui_browser_thread)
    monkeypatch.setattr("app.main.uvicorn.run", fake_uvicorn_run)

    run()

    assert calls == [
        ("thread", settings.app_port),
        ("uvicorn", "app.main:app", settings.app_host, settings.app_port, False),
    ]
