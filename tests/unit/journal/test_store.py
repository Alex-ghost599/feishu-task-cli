from __future__ import annotations

import json
from pathlib import Path

import pytest
from filelock import Timeout

from feishu_task_cli.errors import (
    JournalCorruptError,
    JournalPermissionError,
    ReplayBlockedError,
    UnknownExecutionError,
)
from feishu_task_cli.journal import locking
from feishu_task_cli.journal.locking import plan_execution_lock
from feishu_task_cli.journal.store import ExecutionJournal, ExecutionState

PLAN_HASH = "a" * 64


@pytest.fixture
def journal(tmp_path: Path) -> ExecutionJournal:
    return ExecutionJournal(tmp_path / "journal")


def test_verified_plan_cannot_be_claimed_twice(journal: ExecutionJournal) -> None:
    with journal.execution(PLAN_HASH) as attempt:
        attempt.complete(ExecutionState.VERIFIED)

    with pytest.raises(ReplayBlockedError), journal.execution(PLAN_HASH):
        pass


def test_record_contains_only_safe_hash_state_and_attempt_metadata(
    journal: ExecutionJournal,
) -> None:
    with journal.execution(PLAN_HASH) as attempt:
        attempt.complete(ExecutionState.PARTIAL)

    record_path = journal.records_path / f"{PLAN_HASH}.json"
    payload = json.loads(record_path.read_text(encoding="utf-8"))
    assert set(payload) == {
        "attempt_id",
        "plan_hash",
        "started_at",
        "state",
        "tool_version",
        "updated_at",
    }
    assert payload["plan_hash"] == PLAN_HASH
    assert payload["state"] == "partial"
    assert record_path.stat().st_mode & 0o777 == 0o600


def test_normal_exit_without_terminal_state_becomes_unknown(
    journal: ExecutionJournal,
) -> None:
    with pytest.raises(UnknownExecutionError, match="terminal"), journal.execution(PLAN_HASH):
        pass

    assert journal.status(PLAN_HASH).state is ExecutionState.UNKNOWN  # type: ignore[union-attr]


def test_exception_leaves_started_for_next_lock_holder_to_promote(
    journal: ExecutionJournal,
) -> None:
    with pytest.raises(RuntimeError, match="synthetic crash"), journal.execution(PLAN_HASH):
        raise RuntimeError("synthetic crash")

    assert journal.status(PLAN_HASH).state is ExecutionState.STARTED  # type: ignore[union-attr]
    with pytest.raises(UnknownExecutionError, match="orphaned"), journal.execution(PLAN_HASH):
        pass
    assert journal.status(PLAN_HASH).state is ExecutionState.UNKNOWN  # type: ignore[union-attr]


def test_corrupt_record_fails_closed(journal: ExecutionJournal) -> None:
    record = journal.records_path / f"{PLAN_HASH}.json"
    record.write_text("{not-json", encoding="utf-8")
    record.chmod(0o600)

    with pytest.raises(JournalCorruptError):
        journal.status(PLAN_HASH)


def test_unsafe_state_directory_permissions_are_rejected(tmp_path: Path) -> None:
    root = tmp_path / "unsafe"
    root.mkdir(mode=0o755)
    root.chmod(0o755)

    with pytest.raises(JournalPermissionError):
        ExecutionJournal(root)


def test_symlinked_journal_directory_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    root = tmp_path / "journal-link"
    root.symlink_to(target, target_is_directory=True)

    with pytest.raises(JournalPermissionError, match="directory"):
        ExecutionJournal(root)


def test_symlinked_record_is_rejected(journal: ExecutionJournal, tmp_path: Path) -> None:
    with journal.execution(PLAN_HASH) as attempt:
        attempt.complete(ExecutionState.VERIFIED)
    record = journal.records_path / f"{PLAN_HASH}.json"
    external = tmp_path / "external-record.json"
    record.replace(external)
    record.symlink_to(external)

    with pytest.raises(JournalPermissionError, match="record"):
        journal.status(PLAN_HASH)


def test_attempt_can_only_complete_once(journal: ExecutionJournal) -> None:
    with journal.execution(PLAN_HASH) as attempt:
        attempt.complete(ExecutionState.FAILED)
        with pytest.raises(ReplayBlockedError, match="already completed"):
            attempt.complete(ExecutionState.VERIFIED)


def test_unknown_state_stays_unknown_on_every_later_attempt(journal: ExecutionJournal) -> None:
    with pytest.raises(UnknownExecutionError, match="terminal"), journal.execution(PLAN_HASH):
        pass
    with (
        pytest.raises(UnknownExecutionError, match="already unknown"),
        journal.execution(PLAN_HASH),
    ):
        raise AssertionError("mutation must not run")


def test_caller_filelock_timeout_is_not_misclassified(journal: ExecutionJournal) -> None:
    with pytest.raises(Timeout, match="synthetic"), journal.execution(PLAN_HASH):
        raise Timeout("synthetic.lock")


def test_escaped_attempt_cannot_overwrite_unknown_after_scope_exit(
    journal: ExecutionJournal,
) -> None:
    escaped = None
    with (
        pytest.raises(RuntimeError, match="synthetic crash"),
        journal.execution(PLAN_HASH) as attempt,
    ):
        escaped = attempt
        raise RuntimeError("synthetic crash")
    assert escaped is not None
    with pytest.raises(UnknownExecutionError, match="orphaned"), journal.execution(PLAN_HASH):
        raise AssertionError("mutation must not run")

    with pytest.raises(ReplayBlockedError, match="active lock scope"):
        escaped.complete(ExecutionState.VERIFIED)
    assert journal.status(PLAN_HASH).state is ExecutionState.UNKNOWN  # type: ignore[union-attr]


def test_public_lock_accepts_plan_hash_and_rejects_path_input(tmp_path: Path) -> None:
    with plan_execution_lock(PLAN_HASH, root=tmp_path):
        pass
    with (
        pytest.raises(ValueError, match="plan_hash"),
        plan_execution_lock("../../outside", root=tmp_path),
    ):
        pass


def test_new_journal_directories_are_fsynced_with_their_parents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "new-journal"
    synced: list[Path] = []
    monkeypatch.setattr(locking, "_fsync_directory", synced.append, raising=False)

    ExecutionJournal(root)

    assert root in synced
    assert root.parent in synced
    assert root / "records" in synced
    assert root / "locks" in synced


def test_journal_states_only_include_post_claim_outcomes() -> None:
    assert set(ExecutionState) == {
        ExecutionState.STARTED,
        ExecutionState.UNKNOWN,
        ExecutionState.VERIFIED,
        ExecutionState.PARTIAL,
        ExecutionState.FAILED,
    }
