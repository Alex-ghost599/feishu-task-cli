from __future__ import annotations

import json
import os
import re
import stat
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from feishu_task_cli import __version__
from feishu_task_cli.errors import (
    JournalCorruptError,
    JournalPermissionError,
    ReplayBlockedError,
    UnknownExecutionError,
)
from feishu_task_cli.journal.locking import (
    _fsync_directory,
    default_journal_root,
    plan_execution_lock,
    prepare_private_directory,
)

HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
RECORD_KEYS = {
    "attempt_id",
    "plan_hash",
    "started_at",
    "state",
    "tool_version",
    "updated_at",
}


class ExecutionState(StrEnum):
    STARTED = "started"
    UNKNOWN = "unknown"
    VERIFIED = "verified"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True)
class JournalRecord:
    attempt_id: str
    plan_hash: str
    started_at: datetime
    state: ExecutionState
    tool_version: str
    updated_at: datetime

    def to_json(self) -> dict[str, str]:
        payload = asdict(self)
        payload["state"] = self.state.value
        payload["started_at"] = _format_utc(self.started_at)
        payload["updated_at"] = _format_utc(self.updated_at)
        return payload


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_utc(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("timestamp must use UTC")
    return parsed


class ExecutionAttempt:
    def __init__(self, journal: ExecutionJournal, record: JournalRecord) -> None:
        self._journal = journal
        self._record = record
        self._completed = False
        self._active = True

    @property
    def attempt_id(self) -> str:
        return self._record.attempt_id

    @property
    def completed(self) -> bool:
        return self._completed

    def complete(self, state: ExecutionState) -> None:
        if not self._active:
            raise ReplayBlockedError("execution attempt is outside its active lock scope")
        if self._completed:
            raise ReplayBlockedError("execution attempt already completed")
        if state is ExecutionState.STARTED:
            raise ValueError("started is not a terminal execution state")
        current = self._journal.status(self._record.plan_hash)
        if current is None or current.attempt_id != self._record.attempt_id:
            raise JournalCorruptError("execution attempt no longer owns its journal record")
        if current.state is not ExecutionState.STARTED:
            raise ReplayBlockedError("execution attempt can only complete a started record")
        terminal = JournalRecord(
            attempt_id=current.attempt_id,
            plan_hash=current.plan_hash,
            started_at=current.started_at,
            state=state,
            tool_version=current.tool_version,
            updated_at=datetime.now(UTC),
        )
        self._journal._write(terminal)
        self._completed = True

    def _deactivate(self) -> None:
        self._active = False


class ExecutionJournal:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or default_journal_root()
        self.records_path = self.root / "records"
        self.locks_path = self.root / "locks"
        prepare_private_directory(self.root)
        prepare_private_directory(self.records_path)
        prepare_private_directory(self.locks_path)

    @staticmethod
    def _validate_hash(plan_hash: str) -> None:
        if not HASH_PATTERN.fullmatch(plan_hash):
            raise ValueError("plan_hash must be 64 lowercase hexadecimal characters")

    def _record_path(self, plan_hash: str) -> Path:
        self._validate_hash(plan_hash)
        return self.records_path / f"{plan_hash}.json"

    def status(self, plan_hash: str) -> JournalRecord | None:
        path = self._record_path(plan_hash)
        if not path.exists() and not path.is_symlink():
            return None
        try:
            descriptor = os.open(
                path,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            )
        except OSError as error:
            raise JournalPermissionError("journal record cannot be safely opened") from error
        try:
            details = os.fstat(descriptor)
            if not stat.S_ISREG(details.st_mode):
                raise JournalPermissionError("journal record must be a private regular file")
            if hasattr(os, "getuid") and details.st_uid != os.getuid():
                raise JournalPermissionError("journal record must be owned by the current user")
            if stat.S_IMODE(details.st_mode) & 0o077:
                raise JournalPermissionError("journal record permissions must be 0600 or stricter")
            content = os.read(descriptor, 16_385)
            if len(content) > 16_384:
                raise JournalCorruptError("execution journal record is corrupt")
            payload: Any = json.loads(content.decode("utf-8"))
            if not isinstance(payload, dict) or set(payload) != RECORD_KEYS:
                raise ValueError("record fields do not match the journal contract")
            if payload["plan_hash"] != plan_hash:
                raise ValueError("record plan hash does not match its filename")
            if not isinstance(payload["attempt_id"], str) or not payload["attempt_id"]:
                raise ValueError("attempt_id must be non-empty")
            if not re.fullmatch(r"[0-9a-f]{32}", payload["attempt_id"]):
                raise ValueError("attempt_id must be a UUID hex value")
            if not isinstance(payload["tool_version"], str) or not payload["tool_version"]:
                raise ValueError("tool_version must be non-empty")
            record = JournalRecord(
                attempt_id=payload["attempt_id"],
                plan_hash=payload["plan_hash"],
                started_at=_parse_utc(payload["started_at"]),
                state=ExecutionState(payload["state"]),
                tool_version=payload["tool_version"],
                updated_at=_parse_utc(payload["updated_at"]),
            )
            if record.updated_at < record.started_at:
                raise ValueError("updated_at cannot predate started_at")
            return record
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ) as error:
            raise JournalCorruptError("execution journal record is corrupt") from error
        finally:
            os.close(descriptor)

    def _write(self, record: JournalRecord) -> None:
        path = self._record_path(record.plan_hash)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{record.plan_hash}.", suffix=".tmp", dir=self.records_path
        )
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(record.to_json(), handle, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            _fsync_directory(self.records_path)
        except BaseException:
            with suppress(FileNotFoundError):
                os.unlink(temporary)
            raise

    @contextmanager
    def execution(self, plan_hash: str) -> Iterator[ExecutionAttempt]:
        self._validate_hash(plan_hash)
        with plan_execution_lock(plan_hash, root=self.root):
            existing = self.status(plan_hash)
            if existing is not None:
                if existing.state is ExecutionState.STARTED:
                    orphaned = JournalRecord(
                        attempt_id=existing.attempt_id,
                        plan_hash=existing.plan_hash,
                        started_at=existing.started_at,
                        state=ExecutionState.UNKNOWN,
                        tool_version=existing.tool_version,
                        updated_at=datetime.now(UTC),
                    )
                    self._write(orphaned)
                    raise UnknownExecutionError("orphaned started execution promoted to unknown")
                if existing.state is ExecutionState.UNKNOWN:
                    raise UnknownExecutionError("plan execution outcome is already unknown")
                raise ReplayBlockedError(f"plan execution is already {existing.state.value}")

            now = datetime.now(UTC)
            record = JournalRecord(
                attempt_id=uuid.uuid4().hex,
                plan_hash=plan_hash,
                started_at=now,
                state=ExecutionState.STARTED,
                tool_version=__version__,
                updated_at=now,
            )
            self._write(record)
            attempt = ExecutionAttempt(self, record)
            try:
                try:
                    yield attempt
                except BaseException:
                    raise
                if not attempt.completed:
                    attempt.complete(ExecutionState.UNKNOWN)
                    raise UnknownExecutionError("execution ended without a terminal journal state")
            finally:
                attempt._deactivate()
