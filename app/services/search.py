from __future__ import annotations

from sqlmodel import Session

from app.db.models import Chunk, Document
from app.services.embeddings import EmbeddingService
from app.services.vector_store import VectorStore


class SearchService:
    def __init__(self, engine, embedding_service: EmbeddingService, vector_store: VectorStore):
        self._engine = engine
        self._embedding_service = embedding_service
        self._vector_store = vector_store

    def search(self, query: str, limit: int = 10, source_id: str | None = None) -> list[dict]:
        vector = self._embedding_service.embed_query(query)
        raw_results = self._vector_store.search(vector, limit=limit, source_id=source_id)
        hydrated: list[dict] = []
        with Session(self._engine) as session:
            for item in raw_results:
                payload = item["payload"]
                document = session.get(Document, payload.get("document_id"))
                chunk = session.get(Chunk, payload.get("chunk_id"))
                if not document or not chunk:
                    continue
                hydrated.append(
                    {
                        "document_id": document.id,
                        "source_id": document.source_id,
                        "url": document.url,
                        "title": document.title,
                        "score": item["score"],
                        "snippet": chunk.text[:320],
                        "chunk_index": chunk.chunk_index,
                    }
                )
        return hydrated

