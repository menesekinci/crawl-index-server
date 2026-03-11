from __future__ import annotations

from app.config import get_settings
from app.db.session import create_db_engine, init_db
from app.services.embeddings import EmbeddingService
from app.services.vector_store import VectorStore


def main() -> None:
    settings = get_settings()
    engine = create_db_engine(settings)
    init_db(engine)
    vector_store = VectorStore(settings)
    embedding_service = EmbeddingService(settings, vector_store)
    embedding_service.vector_size()
    print("Bootstrap complete.")
    print(f"Database: {settings.database_path}")
    print(f"Qdrant path: {settings.qdrant_dir}")
    print(f"Embedding model: {settings.embedding_model}")


if __name__ == "__main__":
    main()

