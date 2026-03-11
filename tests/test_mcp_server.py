import asyncio
import json
from dataclasses import dataclass

from app.mcp_server import MCPContainer, CrawlIndexMCPAdapter, create_mcp_server


@dataclass
class StubSource:
    id: str
    name: str
    start_url: str
    enabled: bool = True
    cron_expr: str | None = None
    next_run_at: object | None = None
    last_success_at: object | None = None
    allowed_domains: list[str] | None = None
    source_type: str = "docs"
    crawl_depth: int = 1
    crawl_limit: int = 50
    render: bool = False
    formats: list[str] | None = None


@dataclass
class StubJob:
    id: str
    source_id: str
    status: str
    provider_job_id: str | None = None
    requested_url: str = "https://docs.example.com"
    requested_depth: int = 1
    requested_limit: int = 50
    render: bool = False
    formats: list[str] | None = None
    total_records: int = 0
    finished_records: int = 0
    skipped_records: int = 0
    error_text: str | None = None
    submitted_at: object | None = None
    started_at: object | None = None
    finished_at: object | None = None


class StubSourceService:
    def __init__(self):
        self.sources = [
            StubSource(
                id="src-1",
                name="Docs",
                start_url="https://docs.example.com",
                allowed_domains=["docs.example.com"],
                formats=["markdown"],
            )
        ]

    def list_sources(self, enabled_only: bool = False):
        return [source for source in self.sources if source.enabled or not enabled_only]

    def get_source(self, source_id: str):
        return next((source for source in self.sources if source.id == source_id), None)


class StubCoordinator:
    def __init__(self):
        self.poll_calls = 0
        self.jobs = [StubJob(id="job-1", source_id="src-1", status="completed", total_records=1, finished_records=1)]
        self.documents = [
            {
                "id": "doc-1",
                "source_id": "src-1",
                "url": "https://docs.example.com/auth",
                "title": "Auth",
                "fetched_at": "2026-03-12T00:00:00+00:00",
                "status_code": 200,
            }
        ]
        self.document_payload = {
            "id": "doc-1",
            "source_id": "src-1",
            "url": "https://docs.example.com/auth",
            "canonical_url": "https://docs.example.com/auth",
            "title": "Auth",
            "status_code": 200,
            "fetched_at": "2026-03-12T00:00:00+00:00",
            "content_hash": "abc",
            "metadata_json": {"title": "Auth"},
            "preview": "abcd",
            "truncated": True,
            "raw_markdown": "abcd",
        }

    def poll_active_jobs(self):
        self.poll_calls += 1

    def create_and_submit_job(self, source_id: str):
        if source_id == "missing-credentials":
            raise RuntimeError("Cloudflare credentials are missing.")
        return StubJob(id="job-new", source_id=source_id, status="polling", provider_job_id="provider-1")

    def retry_job(self, job_id: str):
        if job_id == "bad-job":
            raise RuntimeError("Cloudflare credentials are missing.")
        return StubJob(id=job_id, source_id="src-1", status="polling", provider_job_id="provider-retry")

    def list_jobs(self, source_id=None, status=None, limit=20):
        return self.jobs[:limit]

    def get_job(self, job_id: str):
        return next((job for job in self.jobs if job.id == job_id), None)

    def list_documents(self, source_id=None, limit=20):
        return [type("Doc", (), document)() for document in self.documents[:limit]]

    def get_document_payload(self, document_id: str, include_markdown: bool = False, max_chars: int = 4000):
        payload = dict(self.document_payload)
        payload["preview"] = payload["preview"][:max_chars]
        if not include_markdown:
            payload.pop("raw_markdown", None)
        else:
            payload["raw_markdown"] = payload["raw_markdown"][:max_chars]
        payload["truncated"] = True
        return payload if document_id == "doc-1" else None


class StubSearchService:
    def search(self, query: str, limit: int = 10, source_id: str | None = None):
        return [
            {
                "document_id": "doc-1",
                "source_id": "src-1",
                "url": "https://docs.example.com/auth",
                "title": "Auth",
                "score": 0.99,
                "snippet": "Use API tokens.",
                "chunk_index": 0,
            }
        ][:limit]


class StubScheduler:
    def start(self):
        return None

    def shutdown(self):
        return None


class StubVectorStore:
    def close(self):
        return None


def make_adapter():
    services = type(
        "StubServices",
        (),
        {
            "source_service": StubSourceService(),
            "crawl_coordinator": StubCoordinator(),
            "search_service": StubSearchService(),
            "scheduler": StubScheduler(),
            "vector_store": StubVectorStore(),
            "close": lambda self: None,
        },
    )()
    return CrawlIndexMCPAdapter(MCPContainer(services=services)), services


def test_get_document_truncates_and_can_include_markdown():
    adapter, _ = make_adapter()

    plain = adapter.get_document("doc-1", include_markdown=False, max_chars=2)
    full = adapter.get_document("doc-1", include_markdown=True, max_chars=3)

    assert plain["preview"] == "ab"
    assert "raw_markdown" not in plain
    assert full["raw_markdown"] == "abc"


def test_read_tools_poll_before_read():
    adapter, services = make_adapter()

    adapter.list_jobs()
    adapter.get_job("job-1")
    adapter.list_documents()
    adapter.search_docs("api token")

    assert services.crawl_coordinator.poll_calls == 4


def test_mutating_tools_surface_credential_errors():
    adapter, _ = make_adapter()

    try:
        adapter.trigger_crawl("missing-credentials")
    except RuntimeError as exc:
        assert "credentials" in str(exc).lower()
    else:
        raise AssertionError("Expected trigger_crawl to fail without credentials")

    try:
        adapter.retry_job("bad-job")
    except RuntimeError as exc:
        assert "credentials" in str(exc).lower()
    else:
        raise AssertionError("Expected retry_job to fail without credentials")


def test_mcp_server_lists_tools_and_handles_call():
    adapter, services = make_adapter()
    server = create_mcp_server(MCPContainer(services=services))

    async def run_checks():
        tools = await server.list_tools()
        names = {tool.name for tool in tools}
        assert {"list_sources", "trigger_crawl", "search_docs", "get_document"} <= names
        result = await server.call_tool("list_sources", {"enabled_only": False})
        payload = result[1]["result"]
        assert payload[0]["id"] == "src-1"

    asyncio.run(run_checks())
