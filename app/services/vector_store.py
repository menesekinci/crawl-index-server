"""Vector store with error handling, retries, and health checks."""

from __future__ import annotations

import logging
from typing import Any, Optional

from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.exceptions import UnexpectedResponse

from app.config import Settings
from app.services.lock_manager import get_lock_manager, QdrantLockManager
from app.utils.errors import (
    CircuitBreakerError,
    VectorStoreError,
    QdrantLockError,
)
from app.utils.retry import with_retry

logger = logging.getLogger(__name__)

# Circuit breaker settings
CIRCUIT_BREAKER_FAILURE_THRESHOLD = 5
CIRCUIT_BREAKER_RESET_TIMEOUT = 30.0  # seconds


class VectorStore:
    """
    Vector store with error handling, retries, and circuit breaker.

    Features:
    - Exclusive lock management for Qdrant access (file-based storage)
    - HTTP transport support for remote Qdrant server
    - Retry with exponential backoff on transient errors
    - Circuit breaker pattern to prevent cascade failures
    - Health check for dependency monitoring
    - Graceful degradation on failures
    """

    def __init__(self, settings: Settings):
        self._settings = settings
        self._vector_size: int | None = None
        self._lock_manager: Optional[QdrantLockManager] = None

        # Use HTTP transport if URL is provided, otherwise use file-based
        if settings.qdrant_url:
            self._client = QdrantClient(url=settings.qdrant_url)
        else:
            self._client = QdrantClient(path=str(settings.qdrant_dir))

        # Circuit breaker state
        self._failure_count = 0
        self._circuit_open_at: Optional[float] = None
        self._available = True

    @property
    def lock_manager(self) -> Optional[QdrantLockManager]:
        """Get the lock manager, creating it if needed (file-based only)."""
        if self._settings.qdrant_url:
            return None  # HTTP transport doesn't need file locking
        if self._lock_manager is None:
            self._lock_manager = get_lock_manager(self._settings.qdrant_dir)
        return self._lock_manager

    def _record_success(self) -> None:
        """Record a successful operation, reset circuit breaker."""
        self._failure_count = 0
        self._circuit_open_at = None
        self._available = True

    def _record_failure(self) -> None:
        """Record a failed operation, potentially open the circuit."""
        self._failure_count += 1
        if self._failure_count >= CIRCUIT_BREAKER_FAILURE_THRESHOLD:
            self._circuit_open_at = __import__("time").time()
            self._available = False
            logger.warning(
                f"Circuit breaker opened after {self._failure_count} failures"
            )

    def _is_circuit_open(self) -> bool:
        """Check if circuit breaker is open."""
        if self._circuit_open_at is None:
            return False

        import time

        elapsed = time.time() - self._circuit_open_at
        if elapsed >= CIRCUIT_BREAKER_RESET_TIMEOUT:
            # Try to close the circuit
            logger.info("Circuit breaker reset timeout passed, attempting reset")
            self._failure_count = 0
            self._circuit_open_at = None
            self._available = True
            return False

        return True

    def _check_health(self) -> bool:
        """Check if Qdrant is accessible."""
        try:
            self._client.get_collections()
            return True
        except Exception as e:
            logger.debug(f"Health check failed: {e}")
            return False

    def health_check(self) -> bool:
        """
        Public health check method.

        Returns True if vector store is operational, False otherwise.
        """
        if self._is_circuit_open():
            return False
        return self._check_health()

    def _execute_with_lock(
        self,
        operation: callable,
        *args,
        **kwargs,
    ) -> Any:
        """
        Execute an operation with exclusive lock and error handling.

        For file-based storage, uses lock_manager to prevent concurrent access.
        For HTTP transport, no locking needed (server handles concurrency).

        Args:
            operation: The operation to execute
            *args, **kwargs: Arguments to pass to the operation

        Returns:
            Result of the operation

        Raises:
            VectorStoreError: If operation fails after retries
        """
        if self._is_circuit_open():
            raise CircuitBreakerError(
                "Circuit breaker is open, vector store unavailable"
            )

        lock_mgr = self.lock_manager
        if lock_mgr is None:
            # HTTP transport - no locking needed
            try:
                result = operation(*args, **kwargs)
                self._record_success()
                return result
            except Exception as e:
                self._record_failure()
                raise VectorStoreError(f"Operation failed: {e}") from e

        try:
            with lock_mgr:
                result = operation(*args, **kwargs)
                self._record_success()
                return result
        except QdrantLockError as e:
            self._record_failure()
            raise VectorStoreError(f"Lock acquisition failed: {e}") from e
        except Exception as e:
            self._record_failure()
            raise VectorStoreError(f"Operation failed: {e}") from e

    @with_retry(max_retries=3, base_delay=0.5, retry_on=(Exception,))
    def _upsert_with_retry(self, points: list, vector_size: int) -> None:
        """Internal upsert with retry."""
        self.ensure_collection(vector_size)
        self._client.upsert(
            collection_name=self._settings.collection_name,
            points=points,
        )

    def ensure_collection(self, vector_size: int) -> None:
        """Ensure the collection exists with the given vector size."""
        if self._vector_size == vector_size:
            return

        try:
            collections = {
                c.name
                for c in self._client.get_collections().collections
            }
            if self._settings.collection_name not in collections:
                self._client.create_collection(
                    collection_name=self._settings.collection_name,
                    vectors_config=models.VectorParams(
                        size=vector_size,
                        distance=models.Distance.COSINE,
                    ),
                )
                logger.info(
                    f"Created collection '{self._settings.collection_name}' "
                    f"with vector_size={vector_size}"
                )
            self._vector_size = vector_size
        except Exception as e:
            self._record_failure()
            raise VectorStoreError(f"Failed to ensure collection: {e}") from e

    def upsert(
        self,
        points: list[tuple[str, list[float], dict[str, Any]]],
        vector_size: int,
    ) -> None:
        """
        Insert or update points in the vector store.

        Args:
            points: List of (id, vector, metadata) tuples
            vector_size: Dimensionality of the vectors

        Raises:
            VectorStoreError: If operation fails after retries
        """
        if not points:
            return

        if self._is_circuit_open():
            raise CircuitBreakerError(
                "Circuit breaker is open, skipping upsert"
            )

        try:
            payload = [
                models.PointStruct(id=point_id, vector=vector, payload=metadata)
                for point_id, vector, metadata in points
            ]

            def _do_upsert():
                self.ensure_collection(vector_size)
                self._client.upsert(
                    collection_name=self._settings.collection_name,
                    points=payload,
                )

            lock_mgr = self.lock_manager
            if lock_mgr:
                with lock_mgr:
                    _do_upsert()
            else:
                _do_upsert()

            self._record_success()
            logger.debug(f"Upserted {len(points)} points")

        except QdrantLockError as e:
            self._record_failure()
            # Fallback: try with retry
            try:
                self._upsert_with_retry(payload, vector_size)
                self._record_success()
            except Exception as retry_e:
                self._record_failure()
                raise VectorStoreError(
                    f"Upsert failed after lock error and retry: {retry_e}"
                ) from retry_e
        except Exception as e:
            self._record_failure()
            raise VectorStoreError(f"Upsert failed: {e}") from e

    def delete_points(self, point_ids: list[str]) -> None:
        """
        Delete points from the vector store.

        Args:
            point_ids: List of point IDs to delete

        Raises:
            VectorStoreError: If operation fails
        """
        if not point_ids:
            return

        if self._is_circuit_open():
            logger.warning(
                "Circuit breaker open, skipping delete"
            )
            return

        try:
            lock_mgr = self.lock_manager
            if lock_mgr:
                with lock_mgr:
                    self._client.delete(
                        collection_name=self._settings.collection_name,
                        points_selector=models.PointIdsList(points=point_ids),
                    )
            else:
                self._client.delete(
                    collection_name=self._settings.collection_name,
                    points_selector=models.PointIdsList(points=point_ids),
                )
            self._record_success()
            logger.debug(f"Deleted {len(point_ids)} points")
        except Exception as e:
            self._record_failure()
            raise VectorStoreError(f"Delete failed: {e}") from e

    def search(
        self,
        query_vector: list[float],
        limit: int = 10,
        source_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Search for similar vectors.

        Args:
            query_vector: The vector to search for
            limit: Maximum number of results
            source_id: Optional filter by source ID

        Returns:
            List of search results with id, score, and payload

        Raises:
            VectorStoreError: If search fails
        """
        if self._is_circuit_open():
            # Return empty results instead of raising
            logger.warning("Circuit breaker open, returning empty search results")
            return []

        try:
            lock_mgr = self.lock_manager

            def _do_search():
                collections = {
                    c.name
                    for c in self._client.get_collections().collections
                }
                if self._settings.collection_name not in collections:
                    return []

                query_filter = None
                if source_id:
                    query_filter = models.Filter(
                        must=[
                            models.FieldCondition(
                                key="source_id",
                                match=models.MatchValue(value=source_id),
                            )
                        ]
                    )

                return self._client.search(
                    collection_name=self._settings.collection_name,
                    query_vector=query_vector,
                    query_filter=query_filter,
                    limit=limit,
                    with_payload=True,
                )

            if lock_mgr:
                with lock_mgr:
                    response = _do_search()
            else:
                response = _do_search()

            self._record_success()
            if not response:
                return []
            return [
                {
                    "id": item.id,
                    "score": float(item.score),
                    "payload": item.payload or {},
                }
                for item in response
            ]

        except Exception as e:
            self._record_failure()
            # Return empty results instead of raising for search
            logger.error(f"Search failed: {e}")
            return []

    def close(self) -> None:
        """Close the vector store connection."""
        try:
            self._client.close()
        except Exception as e:
            logger.error(f"Error closing vector store: {e}")
