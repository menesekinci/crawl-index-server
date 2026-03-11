from __future__ import annotations

import os
from typing import Iterable

from app.config import Settings
from app.services.vector_store import VectorStore


class EmbeddingService:
    def __init__(self, settings: Settings, vector_store: VectorStore):
        self._settings = settings
        self._vector_store = vector_store
        self._model = None
        self._vector_size: int | None = None

    @property
    def model_name(self) -> str:
        return self._settings.embedding_model

    def _load_model(self):
        if self._model is None:
            os.environ.setdefault("HF_HOME", str(self._settings.embedding_cache_path))
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(
                self._settings.embedding_model,
                cache_folder=str(self._settings.embedding_cache_path),
            )
        return self._model

    def _ensure_vector_size(self) -> int:
        if self._vector_size is None:
            vector = self.embed_texts(["dimension probe"])[0]
            self._vector_size = len(vector)
            self._vector_store.ensure_collection(self._vector_size)
        return self._vector_size

    def embed_texts(self, texts: Iterable[str]) -> list[list[float]]:
        materialized = list(texts)
        if not materialized:
            return []
        model = self._load_model()
        vectors = model.encode(materialized, convert_to_numpy=True, show_progress_bar=False, batch_size=8)
        return [vector.tolist() for vector in vectors]

    def embed_query(self, text: str) -> list[float]:
        self._ensure_vector_size()
        return self.embed_texts([text])[0]

    def vector_size(self) -> int:
        return self._ensure_vector_size()

