from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine, select

from app.config import Settings
from app.db.models import Chunk, CrawlJob, Document, Source
from app.services.cloudflare import CrawlJobResult, CrawlRecord
from app.services.jobs import CrawlCoordinator


class FakeCloudflareClient:
    enabled = True


class FakeEmbeddingService:
    def __init__(self):
        self.calls = 0
        self.model_name = "fake-mini"

    def embed_texts(self, texts):
        self.calls += 1
        return [[0.1, 0.2, 0.3] for _ in texts]

    def vector_size(self):
        return 3


class FakeVectorStore:
    def __init__(self):
        self.upserts = []
        self.deletes = []

    def upsert(self, points, vector_size):
        self.upserts.append((points, vector_size))

    def delete_points(self, point_ids):
        self.deletes.append(point_ids)


def make_coordinator(tmp_path: Path):
    db_path = tmp_path / "app.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    settings = Settings(database_url=f"sqlite:///{db_path}", qdrant_path=str(tmp_path / "qdrant"))
    embedder = FakeEmbeddingService()
    vector_store = FakeVectorStore()
    coordinator = CrawlCoordinator(
        engine=engine,
        settings=settings,
        cloudflare_client=FakeCloudflareClient(),
        embedding_service=embedder,
        vector_store=vector_store,
    )
    with Session(engine) as session:
        source = Source(name="Docs", start_url="https://docs.example.com")
        session.add(source)
        session.commit()
        session.refresh(source)
        job = CrawlJob(source_id=source.id, requested_url=source.start_url)
        session.add(job)
        session.commit()
        session.refresh(job)
    return coordinator, engine, embedder


def test_unchanged_document_skips_reembedding(tmp_path: Path):
    coordinator, engine, embedder = make_coordinator(tmp_path)
    result = CrawlJobResult(
        id="job",
        status="completed",
        total=1,
        finished=1,
        skipped=0,
        records=[
            CrawlRecord(
                url="https://docs.example.com",
                status="completed",
                title="Docs",
                status_code=200,
                markdown="# Intro\nHello",
                metadata={"status": 200, "title": "Docs"},
            )
        ],
    )

    with Session(engine) as session:
        source = session.exec(select(Source)).first()
        assert source is not None
        changed = coordinator._ingest_documents(session, source.id, result)
        assert len(changed) == 1

    coordinator._index_documents([session_document_id(engine)])
    first_calls = embedder.calls

    with Session(engine) as session:
        source = session.exec(select(Source)).first()
        assert source is not None
        changed = coordinator._ingest_documents(session, source.id, result)

    assert changed == []
    assert embedder.calls == first_calls


def session_document_id(engine) -> str:
    with Session(engine) as session:
        document = session.exec(select(Document)).first()
        assert document is not None
        return document.id
