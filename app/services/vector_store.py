from __future__ import annotations

from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http import models

from app.config import Settings


class VectorStore:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = QdrantClient(path=str(settings.qdrant_dir))
        self._vector_size: int | None = None

    def ensure_collection(self, vector_size: int) -> None:
        if self._vector_size == vector_size:
            return
        collections = {collection.name for collection in self._client.get_collections().collections}
        if self._settings.collection_name not in collections:
            self._client.create_collection(
                collection_name=self._settings.collection_name,
                vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE),
            )
        self._vector_size = vector_size

    def upsert(
        self,
        points: list[tuple[str, list[float], dict[str, Any]]],
        vector_size: int,
    ) -> None:
        if not points:
            return
        self.ensure_collection(vector_size)
        payload = [
            models.PointStruct(id=point_id, vector=vector, payload=metadata)
            for point_id, vector, metadata in points
        ]
        self._client.upsert(collection_name=self._settings.collection_name, points=payload)

    def delete_points(self, point_ids: list[str]) -> None:
        if not point_ids:
            return
        self._client.delete(
            collection_name=self._settings.collection_name,
            points_selector=models.PointIdsList(points=point_ids),
        )

    def search(
        self,
        query_vector: list[float],
        limit: int = 10,
        source_id: str | None = None,
    ) -> list[dict[str, Any]]:
        collections = {collection.name for collection in self._client.get_collections().collections}
        if self._settings.collection_name not in collections:
            return []
        query_filter = None
        if source_id:
            query_filter = models.Filter(
                must=[models.FieldCondition(key="source_id", match=models.MatchValue(value=source_id))]
            )
        response = self._client.query_points(
            collection_name=self._settings.collection_name,
            query=query_vector,
            limit=limit,
            query_filter=query_filter,
        )
        results = response.points
        return [
            {
                "id": item.id,
                "score": float(item.score),
                "payload": item.payload or {},
            }
            for item in results
        ]

    def close(self) -> None:
        self._client.close()
