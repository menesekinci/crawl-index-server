"""Qdrant lock manager for exclusive single-process access."""

import logging
import os
import time
from pathlib import Path
from typing import Optional

import portalocker

from app.utils.errors import QdrantLockError

logger = logging.getLogger(__name__)

# Lock file name
LOCK_FILE_NAME = "qdrant.lock"

# Stale lock timeout in seconds (1 hour)
STALE_LOCK_TIMEOUT = 3600


class QdrantLockManager:
    """
    Manages exclusive access to Qdrant storage using file-based locking.

    This ensures only one process can access Qdrant at a time, preventing
    the portalocker.AlreadyLocked errors we saw when multiple processes
    (web server + MCP server) tried to access simultaneously.
    """

    def __init__(self, lock_dir: Path):
        """
        Initialize the lock manager.

        Args:
            lock_dir: Directory where lock file will be created
        """
        self.lock_dir = Path(lock_dir)
        self.lock_file = self.lock_dir / LOCK_FILE_NAME
        self._lock_fd: Optional[int] = None
        self._owns_lock = False

    def _ensure_lock_dir(self) -> None:
        """Ensure the lock directory exists."""
        self.lock_dir.mkdir(parents=True, exist_ok=True)

    def _read_lock_info(self) -> Optional[dict]:
        """Read lock file content to check for stale locks."""
        try:
            if not self.lock_file.exists():
                return None
            with open(self.lock_file, "r") as f:
                content = f.read().strip()
                if not content:
                    return None
                parts = content.split(":")
                if len(parts) >= 2:
                    return {
                        "pid": int(parts[0]),
                        "timestamp": float(parts[1]),
                    }
        except (ValueError, IOError) as e:
            logger.warning(f"Failed to read lock file: {e}")
        return None

    def _write_lock_info(self) -> None:
        """Write our PID and timestamp to lock file."""
        self._ensure_lock_dir()
        with open(self.lock_file, "w") as f:
            f.write(f"{os.getpid()}:{time.time()}")

    def _is_process_running(self, pid: int) -> bool:
        """Check if a process with given PID is running."""
        try:
            # On Unix, signal 0 just checks if process exists
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def _cleanup_stale_locks(self) -> bool:
        """
        Clean up stale lock files from crashed processes.

        Returns True if we cleaned up a stale lock.
        """
        lock_info = self._read_lock_info()
        if lock_info is None:
            return False

        # Check if the process holding the lock is still running
        if self._is_process_running(lock_info["pid"]):
            # Process is alive, lock might be valid
            # But check if it's older than stale timeout
            age = time.time() - lock_info["timestamp"]
            if age < STALE_LOCK_TIMEOUT:
                return False

        # Process is dead OR lock is too old - clean it up
        logger.warning(
            f"Cleaning up stale lock: pid={lock_info['pid']}, "
            f"age={time.time() - lock_info['timestamp']:.0f}s"
        )
        try:
            self.lock_file.unlink(missing_ok=True)
            return True
        except OSError as e:
            logger.error(f"Failed to remove stale lock file: {e}")
        return False

    def acquire(self, timeout: float = 30.0) -> bool:
        """
        Acquire exclusive lock with timeout.

        Args:
            timeout: Maximum time to wait for lock in seconds

        Returns:
            True if lock acquired, False otherwise
        """
        self._ensure_lock_dir()

        # First, clean up any stale locks
        self._cleanup_stale_locks()

        start_time = time.time()

        while True:
            try:
                # Open lock file (create if doesn't exist)
                self._lock_fd = os.open(
                    str(self.lock_file),
                    os.O_CREAT | os.O_RDWR,
                )

                # Try to acquire exclusive lock (non-blocking first)
                portalocker.lock(
                    self._lock_fd,
                    portalocker.LOCK_EX | portalocker.LOCK_NB,
                )

                # Success! Write our info
                self._write_lock_info()
                self._owns_lock = True
                logger.debug(f"Acquired Qdrant lock (pid={os.getpid()})")
                return True

            except portalocker.AlreadyLocked:
                # Another process holds the lock
                if self._lock_fd is not None:
                    try:
                        os.close(self._lock_fd)
                    except OSError:
                        pass
                    self._lock_fd = None

                # Check if we've timed out
                elapsed = time.time() - start_time
                if elapsed >= timeout:
                    logger.error(
                        f"Failed to acquire Qdrant lock after {timeout}s"
                    )
                    return False

                # Wait a bit before retrying
                time.sleep(0.5)

            except OSError as e:
                logger.error(f"OS error while acquiring lock: {e}")
                if self._lock_fd is not None:
                    try:
                        os.close(self._lock_fd)
                    except OSError:
                        pass
                    self._lock_fd = None
                raise QdrantLockError(f"Failed to acquire lock: {e}") from e

    def release(self) -> None:
        """Release the lock if we own it."""
        if self._owns_lock and self._lock_fd is not None:
            try:
                portalocker.lock(
                    self._lock_fd,
                    portalocker.LOCK_UN,
                )
                os.close(self._lock_fd)
                logger.debug(f"Released Qdrant lock (pid={os.getpid()})")
            except OSError as e:
                logger.error(f"Error releasing lock: {e}")
            finally:
                self._lock_fd = None
                self._owns_lock = False

    def is_locked(self) -> bool:
        """Check if the lock is currently held by any process."""
        # Try to clean up stale locks first
        self._cleanup_stale_locks()

        # Check if lock file exists and is held by another process
        if not self.lock_file.exists():
            return False

        lock_info = self._read_lock_info()
        if lock_info is None:
            return False

        # Check if the process is still running
        if not self._is_process_running(lock_info["pid"]):
            # Process is dead, lock is stale (should have been cleaned up)
            return False

        return True

    def __enter__(self) -> "QdrantLockManager":
        """Context manager entry."""
        if not self.acquire():
            raise QdrantLockError("Failed to acquire Qdrant lock")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.release()


# Global lock manager instance (lazy initialization)
_lock_manager: Optional[QdrantLockManager] = None


def get_lock_manager(lock_dir: Path) -> QdrantLockManager:
    """Get or create the global lock manager instance."""
    global _lock_manager
    if _lock_manager is None:
        _lock_manager = QdrantLockManager(lock_dir)
    return _lock_manager


def qdrant_lock(lock_dir: Path):
    """
    Context manager for Qdrant lock.

    Usage:
        with qdrant_lock(Path(".data/qdrant")):
            # Qdrant operations here
            pass
    """
    return QdrantLockManager(lock_dir)
