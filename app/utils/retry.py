"""Retry utilities with exponential backoff."""

import logging
import time
from functools import wraps
from typing import Callable, Optional, Type, Tuple

from app.utils.errors import CrawlIndexError

logger = logging.getLogger(__name__)


def with_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    multiplier: float = 2.0,
    retry_on: Optional[Tuple[Type[Exception], ...]] = None,
    on_retry: Optional[Callable[[Exception, int, float], None]] = None,
):
    """
    Decorator that retries a function with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay between retries
        multiplier: Exponential multiplier for delay
        retry_on: Tuple of exception types to retry on (None = all except CrawlIndexError)
        on_retry: Optional callback function(exception, retry_count, delay)
    """

    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if retry_on is None:
                # Default: retry on一切 except CrawlIndexError and its subclasses
                _retry_on: Tuple[Type[Exception], ...] = (
                    Exception,
                )
            else:
                _retry_on = retry_on

            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except _retry_on as e:
                    last_exception = e

                    # Don't retry if it's a CrawlIndexError (considered fatal)
                    if attempt >= max_retries:
                        logger.error(
                            f"{func.__name__} failed after {max_retries} retries: {e}"
                        )
                        raise

                    delay = min(base_delay * (multiplier**attempt), max_delay)

                    if on_retry:
                        on_retry(e, attempt, delay)
                    else:
                        logger.warning(
                            f"{func.__name__} failed (attempt {attempt + 1}/{max_retries + 1}), "
                            f"retrying in {delay:.1f}s: {e}"
                        )

                    time.sleep(delay)

            # This shouldn't happen, but just in case
            if last_exception:
                raise last_exception

        return wrapper

    return decorator


def async_with_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    multiplier: float = 2.0,
    retry_on: Optional[Tuple[Type[Exception], ...]] = None,
    on_retry: Optional[Callable[[Exception, int, float], None]] = None,
):
    """
    Async version of with_retry decorator.
    """

    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            if retry_on is None:
                _retry_on: Tuple[Type[Exception], ...] = (Exception,)
            else:
                _retry_on = retry_on

            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except _retry_on as e:
                    last_exception = e

                    if attempt >= max_retries:
                        logger.error(
                            f"{func.__name__} failed after {max_retries} retries: {e}"
                        )
                        raise

                    delay = min(base_delay * (multiplier**attempt), max_delay)

                    if on_retry:
                        on_retry(e, attempt, delay)
                    else:
                        logger.warning(
                            f"{func.__name__} failed (attempt {attempt + 1}/{max_retries + 1}), "
                            f"retrying in {delay:.1f}s: {e}"
                        )

                    import asyncio

                    await asyncio.sleep(delay)

            if last_exception:
                raise last_exception

        return wrapper

    return decorator
