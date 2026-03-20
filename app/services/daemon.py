"""Daemon lock mechanism for single-instance MCP server."""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Lock file name
DAEMON_LOCK_FILE = ".data/crawl-index-daemon.lock"


class DaemonLock:
    """
    Daemon lock to ensure only one MCP server instance runs at a time.

    Inspired by ai-consultation-mcp's daemon.lock pattern.
    """

    def __init__(self, lock_file: str = DAEMON_LOCK_FILE):
        self.lock_file = Path(lock_file)
        self._acquired = False
        self._pid: Optional[int] = None

    def acquire(self, timeout: float = 30.0) -> bool:
        """
        Acquire the daemon lock.

        Args:
            timeout: Maximum time to wait for lock in seconds

        Returns:
            True if lock acquired, False if another instance is running
        """
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)

        start_time = time.time()

        while True:
            # Check if another process holds the lock
            if self.lock_file.exists():
                try:
                    with open(self.lock_file, "r") as f:
                        lock_data = json.load(f)
                        existing_pid = lock_data.get("pid")

                    # Check if that process is still running
                    if existing_pid and self._is_process_running(existing_pid):
                        elapsed = time.time() - start_time
                        if elapsed >= timeout:
                            logger.error(
                                f"Failed to acquire daemon lock after {timeout}s "
                                f"(another instance running as pid={existing_pid})"
                            )
                            return False

                        # Wait and retry
                        time.sleep(0.5)
                        continue

                    # Process is dead, stale lock - we'll remove it
                    logger.warning(
                        f"Removing stale daemon lock from dead process pid={existing_pid}"
                    )
                    try:
                        self.lock_file.unlink(missing_ok=True)
                    except OSError:
                        pass

                except (json.JSONDecodeError, IOError) as e:
                    # Corrupted lock file, remove it
                    logger.warning(f"Removing corrupted lock file: {e}")
                    try:
                        self.lock_file.unlink(missing_ok=True)
                    except OSError:
                        pass

            # Try to acquire the lock
            try:
                with open(self.lock_file, "w") as f:
                    json.dump(
                        {
                            "pid": os.getpid(),
                            "started_at": time.time(),
                        },
                        f,
                    )
                    f.flush()
                    os.fsync(f.fileno())

                self._acquired = True
                self._pid = os.getpid()
                logger.info(f"Daemon lock acquired (pid={os.getpid()})")
                return True

            except OSError as e:
                logger.error(f"Failed to create lock file: {e}")
                return False

    def release(self) -> None:
        """Release the daemon lock if we own it."""
        if self._acquired and self.lock_file.exists():
            try:
                self.lock_file.unlink(missing_ok=True)
                logger.info(f"Daemon lock released (pid={os.getpid()})")
            except OSError as e:
                logger.error(f"Failed to remove lock file: {e}")
            finally:
                self._acquired = False

    def is_running(self) -> bool:
        """Check if another instance is already running."""
        if not self.lock_file.exists():
            return False

        try:
            with open(self.lock_file, "r") as f:
                lock_data = json.load(f)
                existing_pid = lock_data.get("pid")

            if existing_pid and self._is_process_running(existing_pid):
                return True

        except (json.JSONDecodeError, IOError):
            pass

        return False

    @staticmethod
    def _is_process_running(pid: int) -> bool:
        """Check if a process with given PID is running."""
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def __enter__(self) -> "DaemonLock":
        """Context manager entry."""
        if not self.acquire():
            raise RuntimeError("Failed to acquire daemon lock")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.release()


def setup_logging(level: int = logging.INFO) -> None:
    """Setup logging for MCP server."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stderr)],
    )


def register_shutdown_handler(cleanup_fn=None) -> None:
    """Register signal handlers for graceful shutdown."""

    def shutdown_handler(signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        if cleanup_fn:
            cleanup_fn()
        sys.exit(0)

    import signal

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)
