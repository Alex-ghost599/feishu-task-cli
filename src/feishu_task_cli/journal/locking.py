from __future__ import annotations

import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from filelock import FileLock, Timeout
from platformdirs import user_state_path

from feishu_task_cli.errors import ExecutionInProgressError, JournalPermissionError

HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def default_journal_root() -> Path:
    return user_state_path("feishu-task-cli") / "executions"


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _reject_symlink_ancestors(path: Path) -> None:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current /= component
        if current.is_symlink():
            raise JournalPermissionError("journal path must not contain symlink components")


def _validate_private_directory(path: Path) -> None:
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


def prepare_private_directory(path: Path) -> None:
    """Create a private directory and durably persist each new directory entry."""
    _reject_symlink_ancestors(path)
    missing: list[Path] = []
    cursor = path
    while not cursor.exists() and not cursor.is_symlink():
        missing.append(cursor)
        if cursor.parent == cursor:
            break
        cursor = cursor.parent
    for directory in reversed(missing):
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            pass
        except OSError as error:
            raise JournalPermissionError("journal directory cannot be created") from error
        _validate_private_directory(directory)
        _fsync_directory(directory)
        _fsync_directory(directory.parent)
    _reject_symlink_ancestors(path)
    _validate_private_directory(path)
    _fsync_directory(path)
    _fsync_directory(path.parent)


@contextmanager
def plan_execution_lock(plan_hash: str, *, root: Path | None = None) -> Iterator[None]:
    """Acquire a non-blocking OS-backed lock for the full execution scope."""
    if HASH_PATTERN.fullmatch(plan_hash) is None:
        raise ValueError("plan_hash must be 64 lowercase hexadecimal characters")
    journal_root = root or default_journal_root()
    prepare_private_directory(journal_root)
    locks_path = journal_root / "locks"
    prepare_private_directory(locks_path)
    lock = FileLock(locks_path / f"{plan_hash}.lock", timeout=0, mode=0o600)
    try:
        lock.acquire()
    except Timeout as error:
        raise ExecutionInProgressError("execution_in_progress") from error
    try:
        yield
    finally:
        lock.release()
