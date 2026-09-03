"""
🏛️ PRV CAPITAL | OS-LEVEL SINGLE-INSTANCE PROCESS MUTEX
Prevents multiple concurrent PRV trading engines or background daemons from running simultaneously.
Uses POSIX fcntl.flock(LOCK_EX | LOCK_NB) on a dedicated lockfile.
"""
import os
import sys
import fcntl
import atexit
import logging
from typing import Optional

logger = logging.getLogger("single_instance_lock")

DEFAULT_LOCK_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "prv_trading_engine.lock"
)


class SingleInstanceLock:
    def __init__(self, lock_file: str = DEFAULT_LOCK_FILE):
        self.lock_file = lock_file
        self.fd: Optional[int] = None
        self.is_locked: bool = False

    def acquire(self) -> bool:
        """
        Attempts non-blocking exclusive advisory lock.
        Returns True if acquired, False if already held by another process.
        """
        os.makedirs(os.path.dirname(self.lock_file), exist_ok=True)
        try:
            self.fd = os.open(self.lock_file, os.O_CREAT | os.O_RDWR, 0o644)
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.ftruncate(self.fd, 0)
            payload = f"PID={os.getpid()}\nSTART_TIME={os.times()[4]}\n"
            os.write(self.fd, payload.encode("utf-8"))
            os.fsync(self.fd)
            self.is_locked = True
            atexit.register(self.release)
            return True
        except (BlockingIOError, OSError) as e:
            if self.fd is not None:
                try:
                    os.close(self.fd)
                except Exception:
                    pass
                self.fd = None
            self.is_locked = False
            return False

    def release(self):
        """Releases the lock and closes file descriptor."""
        if self.is_locked and self.fd is not None:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
                os.close(self.fd)
            except Exception:
                pass
            self.fd = None
            self.is_locked = False

    def get_lock_holder_pid(self) -> Optional[int]:
        """Reads PID from lockfile if available."""
        if not os.path.exists(self.lock_file):
            return None
        try:
            with open(self.lock_file, "r") as f:
                content = f.read()
                for line in content.splitlines():
                    if line.startswith("PID="):
                        return int(line.split("=")[1])
        except Exception:
            return None
        return None


single_instance_lock = SingleInstanceLock()
