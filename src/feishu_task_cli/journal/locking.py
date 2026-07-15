from __future__ import annotations

import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

from filelock import FileLock, Timeout
from platformdirs import user_state_path

from feishu_task_cli.errors import ExecutionInProgressError, JournalPermissionError

HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def default_journal_root() -> Path:
    return user_state_path("feishu-task-cli") / "executions"


def _prepare_private_directory(path: Path) -> None:
    with suppress(OSError):
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        details = path.lstat()
    except OSError as error:
        raise JournalPermissionError(
            "journal lock directory cannot be created or inspected"
        ) from error
    if stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode):
        raise JournalPermissionError("journal lock path must be a private directory")
    if hasattr(os, "getuid") and details.st_uid != os.getuid():
        raise JournalPermissionError("journal lock directory must be owned by the current user")
    if stat.S_IMODE(details.st_mode) & 0o077:
        raise JournalPermissionError("journal lock directory permissions must be 0700 or stricter")


@contextmanager
def plan_execution_lock(plan_hash: str, *, root: Path | None = None) -> Iterator[None]:
    """Acquire a non-blocking OS-backed lock for the full execution scope."""
    if HASH_PATTERN.fullmatch(plan_hash) is None:
        raise ValueError("plan_hash must be 64 lowercase hexadecimal characters")
    journal_root = root or default_journal_root()
    _prepare_private_directory(journal_root)
    locks_path = journal_root / "locks"
    _prepare_private_directory(locks_path)
    lock = FileLock(locks_path / f"{plan_hash}.lock", timeout=0, mode=0o600)
    try:
        lock.acquire()
    except Timeout as error:
        raise ExecutionInProgressError("execution_in_progress") from error
    try:
        yield
    finally:
        lock.release()
