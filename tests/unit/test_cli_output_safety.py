from __future__ import annotations

import errno
import os
import stat
from collections import Counter
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


def test_atomic_cleanup_retries_interrupted_unlink_and_preserves_primary(
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

    def tracked_close(descriptor: int) -> None:
        close_attempts.append(descriptor)
        real_close(descriptor)

    def interrupt_unlink_once(path: str, *, dir_fd: int | None = None) -> None:
        unlink_attempts.append(path)
        if len(unlink_attempts) == 1:
            raise OSError(errno.EINTR, "interrupted before unlink")
        real_unlink(path, dir_fd=dir_fd)

    def fail_first_fsync(descriptor: int) -> None:
        nonlocal fsync_calls
        fsync_calls += 1
        if fsync_calls == 1:
            raise OSError("primary write failure")
        real_fsync(descriptor)

    monkeypatch.setattr(cli.os, "open", tracked_open)
    monkeypatch.setattr(cli.os, "close", tracked_close)
    monkeypatch.setattr(cli.os, "unlink", interrupt_unlink_once)
    monkeypatch.setattr(cli.os, "fsync", fail_first_fsync)
    monkeypatch.setattr(cli, "_open_output_parent", lambda path: parent_fd)

    with pytest.raises(OSError, match="primary write failure"):
        cli._write_atomic(output, b"synthetic")

    assert sorted(opened) == sorted(close_attempts)
    assert Counter(opened) == Counter(close_attempts)
    assert len(unlink_attempts) == 2
    assert not output.exists()
    assert not list(tmp_path.glob(".*.tmp"))


def test_atomic_cleanup_persistent_unlink_wipes_verified_private_temp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output = tmp_path / "artifact.json"
    artifact = b"sensitive artifact bytes"
    real_open = os.open
    real_close = os.close
    real_fsync = os.fsync
    opened: list[int] = []
    close_attempts: list[int] = []
    unlink_attempts: list[str] = []
    temp_open_flags: list[int] = []
    fsync_calls = 0

    parent_fd = real_open(tmp_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    opened.append(parent_fd)

    def tracked_open(path: str, flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
        descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
        opened.append(descriptor)
        if path.startswith(".artifact.json."):
            temp_open_flags.append(flags)
        return descriptor

    def tracked_close(descriptor: int) -> None:
        close_attempts.append(descriptor)
        real_close(descriptor)

    def fail_unlink_before_delete(path: str, *, dir_fd: int | None = None) -> None:
        del dir_fd
        unlink_attempts.append(path)
        raise OSError(errno.EACCES, "persistent unlink failure")

    primary = OSError("primary write failure")

    def fail_first_fsync(descriptor: int) -> None:
        nonlocal fsync_calls
        fsync_calls += 1
        if fsync_calls == 1:
            raise primary
        real_fsync(descriptor)

    monkeypatch.setattr(cli.os, "open", tracked_open)
    monkeypatch.setattr(cli.os, "close", tracked_close)
    monkeypatch.setattr(cli.os, "unlink", fail_unlink_before_delete)
    monkeypatch.setattr(cli.os, "fsync", fail_first_fsync)
    monkeypatch.setattr(cli, "_open_output_parent", lambda path: parent_fd)

    with pytest.raises(OSError, match="primary write failure") as caught:
        cli._write_atomic(output, artifact)

    assert caught.value is primary
    assert caught.value.output_cleanup_status == "incomplete_wiped"  # type: ignore[attr-defined]
    assert Counter(opened) == Counter(close_attempts)
    assert len(unlink_attempts) == 2
    assert len(temp_open_flags) == 2
    assert temp_open_flags[1] & getattr(os, "O_NOFOLLOW", 0)
    residues = list(tmp_path.glob(".*.tmp"))
    assert len(residues) == 1
    residue = residues[0]
    assert residue.read_bytes() == b""
    assert artifact not in residue.read_bytes()
    assert stat.S_IMODE(residue.stat(follow_symlinks=False).st_mode) == 0o600
    assert not residue.is_symlink()
    assert not output.exists()
