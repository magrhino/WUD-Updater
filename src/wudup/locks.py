"""Directory-based WUD file locks.

The shell scripts use ``mkdir path.lock`` as the lock primitive.
These helpers intentionally mirror that behavior for Python and Bash parity.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

_SECONDS_RE = re.compile(r"^\d+$", re.ASCII)


class WudLockError(RuntimeError):
    """Raised when a WUD lock cannot be used."""


class WudLockTimeout(WudLockError):
    """Raised when acquiring a WUD lock times out."""


def lock_dir_for(path: str | Path) -> Path:
    """Return the lock directory path used by the shell scripts."""

    return Path(f"{Path(path)}.lock")


def parse_lock_timeout(value: int | str) -> int:
    """Parse a shell-compatible lock timeout value."""

    if isinstance(value, int) and not isinstance(value, bool):
        if value >= 0:
            return value
        raise WudLockError("WUD_LOCK_TIMEOUT must be an integer number of seconds")

    text = str(value)
    if _SECONDS_RE.fullmatch(text) is None:
        raise WudLockError("WUD_LOCK_TIMEOUT must be an integer number of seconds")
    return int(text, 10)


def expect_parent_wud_lock(path: str | Path) -> None:
    """Verify that a parent process already holds the WUD lock."""

    lock_dir = lock_dir_for(path)
    if not lock_dir.is_dir():
        raise WudLockError(f"Expected WUD file lock to be held: {lock_dir}")


def release_parent_wud_lock(path: str | Path) -> None:
    """Release a parent-held WUD lock, ignoring missing lock directories."""

    try:
        os.rmdir(lock_dir_for(path))
    except OSError:
        pass


@dataclass
class DirectoryLock:
    """Directory lock with shell-compatible timeout and parent reuse behavior."""

    path: str | Path
    timeout_seconds: int | str = 30
    parent_held: bool = False
    sleep: Callable[[float], None] = time.sleep
    _held: bool = field(default=False, init=False)

    @property
    def lock_dir(self) -> Path:
        return lock_dir_for(self.path)

    @property
    def held(self) -> bool:
        return self._held

    def acquire(self) -> None:
        timeout = parse_lock_timeout(self.timeout_seconds)

        if self.parent_held:
            expect_parent_wud_lock(self.path)
            return

        if self._held:
            return

        waited = 0
        last_error: OSError | None = None
        while True:
            try:
                os.mkdir(self.lock_dir)
            except OSError as exc:
                last_error = exc
                if waited >= timeout:
                    raise WudLockTimeout(
                        f"Timed out waiting for WUD file lock: {self.lock_dir}"
                    ) from last_error
                self.sleep(1)
                waited += 1
                continue

            self._held = True
            return

    def release(self) -> None:
        if not self._held:
            return
        try:
            os.rmdir(self.lock_dir)
        except OSError:
            pass
        self._held = False

    def release_parent(self) -> None:
        if not self.parent_held:
            return
        release_parent_wud_lock(self.path)
        self.parent_held = False

    def close(self) -> None:
        self.release()
        self.release_parent()

    def __enter__(self) -> DirectoryLock:
        self.acquire()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
