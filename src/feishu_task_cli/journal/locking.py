from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from filelock import FileLock, Timeout

from feishu_task_cli.errors import ExecutionInProgressError


@contextmanager
def plan_execution_lock(lock_path: Path) -> Iterator[None]:
    """Acquire a non-blocking OS-backed lock for the full execution scope."""
    lock = FileLock(lock_path, timeout=0)
    try:
        lock.acquire()
    except Timeout as error:
        raise ExecutionInProgressError("execution_in_progress") from error
    try:
        yield
    finally:
        lock.release()
