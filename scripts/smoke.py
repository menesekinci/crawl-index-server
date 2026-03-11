from __future__ import annotations

from app.config import get_settings
from app.services.embeddings import EmbeddingService
from app.services.vector_store import VectorStore


def main() -> None:
    settings = get_settings()
    vector_store = VectorStore(settings)
    embedding_service = EmbeddingService(settings, vector_store)
    vector = embedding_service.embed_query("How do I authenticate API requests?")
    print({"model": settings.embedding_model, "vector_size": len(vector), "preview": vector[:5]})


if __name__ == "__main__":
    main()

