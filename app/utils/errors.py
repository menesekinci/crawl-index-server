"""Custom exception hierarchy for crawl-index-server."""


class CrawlIndexError(Exception):
    """Base exception for all crawl-index-server errors."""

    pass


class VectorStoreError(CrawlIndexError):
    """Raised when vector store operations fail."""

    pass


class QdrantLockError(VectorStoreError):
    """Raised when Qdrant lock cannot be acquired."""

    pass


class ServiceUnavailableError(CrawlIndexError):
    """Raised when a required service is unavailable."""

    pass


class CircuitBreakerError(CrawlIndexError):
    """Raised when circuit breaker is open."""

    pass


class ConfigurationError(CrawlIndexError):
    """Raised when configuration is invalid."""

    pass


class CloudflareError(CrawlIndexError):
    """Raised when Cloudflare API operations fail."""

    pass


class DatabaseError(CrawlIndexError):
    """Raised when database operations fail."""

    pass
