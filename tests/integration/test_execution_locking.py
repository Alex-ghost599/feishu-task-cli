from __future__ import annotations

import multiprocessing
import os
from multiprocessing.synchronize import Event
from pathlib import Path

import pytest

from feishu_task_cli.errors import ExecutionInProgressError, UnknownExecutionError
from feishu_task_cli.journal.store import ExecutionJournal, ExecutionState

PLAN_HASH = "b" * 64


def _holder(root: str, acquired: Event, release: Event, results: multiprocessing.Queue) -> None:
    journal = ExecutionJournal(Path(root))
    with journal.execution(PLAN_HASH) as attempt:
        acquired.set()
        release.wait(timeout=10)
        attempt.complete(ExecutionState.VERIFIED)
    results.put("holder_verified")


def _contender(root: str, results: multiprocessing.Queue) -> None:
    journal = ExecutionJournal(Path(root))
    try:
        with journal.execution(PLAN_HASH):
            results.put("mutation_submitted")
    except ExecutionInProgressError:
        results.put("execution_in_progress")


def _crasher(root: str, acquired: Event) -> None:
    journal = ExecutionJournal(Path(root))
    with journal.execution(PLAN_HASH):
        acquired.set()
        os._exit(17)


def test_active_executor_blocks_second_process_without_mutation(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    acquired = context.Event()
    release = context.Event()
    results = context.Queue()
    root = str(tmp_path / "journal")
    holder = context.Process(target=_holder, args=(root, acquired, release, results))
    holder.start()
    assert acquired.wait(timeout=10)

    contender = context.Process(target=_contender, args=(root, results))
    contender.start()
    contender.join(timeout=10)
    assert contender.exitcode == 0
    assert results.get(timeout=2) == "execution_in_progress"
    assert ExecutionJournal(Path(root)).status(PLAN_HASH).state is ExecutionState.STARTED  # type: ignore[union-attr]

    release.set()
    holder.join(timeout=10)
    assert holder.exitcode == 0
    assert results.get(timeout=2) == "holder_verified"
    assert ExecutionJournal(Path(root)).status(PLAN_HASH).state is ExecutionState.VERIFIED  # type: ignore[union-attr]


def test_crashed_executor_is_promoted_to_unknown_and_never_replayed(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    acquired = context.Event()
    root = str(tmp_path / "journal")
    crasher = context.Process(target=_crasher, args=(root, acquired))
    crasher.start()
    assert acquired.wait(timeout=10)
    crasher.join(timeout=10)
    assert crasher.exitcode == 17

    journal = ExecutionJournal(Path(root))
    with pytest.raises(UnknownExecutionError, match="orphaned"), journal.execution(PLAN_HASH):
        raise AssertionError("mutation must not run")
    assert journal.status(PLAN_HASH).state is ExecutionState.UNKNOWN  # type: ignore[union-attr]
