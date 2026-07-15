from __future__ import annotations

import os
from pathlib import Path

import pytest

import feishu_task_cli.cli as cli


def test_parent_walk_closes_new_fd_when_old_close_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    nested = tmp_path / "one" / "two"
    nested.mkdir(parents=True)
    real_open = os.open
    real_close = os.close
    opened: list[int] = []
    close_attempts: list[int] = []

    def tracked_open(*args: object, **kwargs: object) -> int:
        descriptor = real_open(*args, **kwargs)  # type: ignore[arg-type]
        opened.append(descriptor)
        return descriptor

    def close_then_fail_once(descriptor: int) -> None:
        close_attempts.append(descriptor)
        real_close(descriptor)
        if len(close_attempts) == 1:
            raise OSError("primary close failure")

    monkeypatch.setattr(cli.os, "open", tracked_open)
    monkeypatch.setattr(cli.os, "close", close_then_fail_once)

    with pytest.raises(OSError, match="primary close failure"):
        cli._open_output_parent(nested / "artifact.json")

    assert sorted(opened) == sorted(close_attempts)
    assert len(close_attempts) == len(set(close_attempts))


def test_atomic_cleanup_preserves_primary_and_attempts_every_resource_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output = tmp_path / "artifact.json"
    real_close = os.close
    real_unlink = os.unlink
    real_fsync = os.fsync
    opened: list[int] = []
    close_attempts: list[int] = []
    unlink_attempts: list[str] = []
    fsync_calls = 0

    real_open = os.open
    parent_fd = real_open(tmp_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    opened.append(parent_fd)

    def tracked_open(*args: object, **kwargs: object) -> int:
        descriptor = real_open(*args, **kwargs)  # type: ignore[arg-type]
        opened.append(descriptor)
        return descriptor

    def close_then_report_cleanup_failure(descriptor: int) -> None:
        close_attempts.append(descriptor)
        real_close(descriptor)
        raise OSError("secondary close failure")

    def unlink_then_report_cleanup_failure(path: str, *, dir_fd: int | None = None) -> None:
        unlink_attempts.append(path)
        real_unlink(path, dir_fd=dir_fd)
        raise OSError("secondary unlink failure")

    def fail_first_fsync(descriptor: int) -> None:
        nonlocal fsync_calls
        fsync_calls += 1
        if fsync_calls == 1:
            raise OSError("primary write failure")
        real_fsync(descriptor)

    monkeypatch.setattr(cli.os, "open", tracked_open)
    monkeypatch.setattr(cli.os, "close", close_then_report_cleanup_failure)
    monkeypatch.setattr(cli.os, "unlink", unlink_then_report_cleanup_failure)
    monkeypatch.setattr(cli.os, "fsync", fail_first_fsync)
    monkeypatch.setattr(cli, "_open_output_parent", lambda path: parent_fd)

    with pytest.raises(OSError, match="primary write failure"):
        cli._write_atomic(output, b"synthetic")

    assert sorted(opened) == sorted(close_attempts)
    assert len(close_attempts) == len(set(close_attempts))
    assert len(unlink_attempts) == 1
    assert not output.exists()
    assert not list(tmp_path.glob(".*.tmp"))
