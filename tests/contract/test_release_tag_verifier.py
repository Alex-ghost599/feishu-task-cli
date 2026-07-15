from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VERIFIER = ROOT / "scripts/verify_release_tag.sh"


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )


def _release_remote(tmp_path: Path, tag_kind: str) -> tuple[Path, str]:
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    checkout = tmp_path / "checkout"
    tag_name = "v0.1.1"

    _git(tmp_path, "init", "--bare", str(remote))
    _git(tmp_path, "init", "--initial-branch=main", str(seed))
    _git(seed, "config", "user.name", "Release Test")
    _git(seed, "config", "user.email", "release-test@users.noreply.github.com")
    (seed / "payload.txt").write_text("first\n", encoding="utf-8")
    _git(seed, "add", "payload.txt")
    _git(seed, "commit", "-m", "first")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "origin", "main")

    if tag_kind == "annotated" or tag_kind == "wrong-main":
        _git(seed, "tag", "-a", tag_name, "-m", tag_name)
        _git(seed, "push", "origin", f"refs/tags/{tag_name}")
    elif tag_kind == "lightweight":
        _git(seed, "tag", tag_name)
        _git(seed, "push", "origin", f"refs/tags/{tag_name}")
    elif tag_kind != "missing":
        raise AssertionError(f"unknown tag kind: {tag_kind}")

    if tag_kind == "wrong-main":
        (seed / "payload.txt").write_text("second\n", encoding="utf-8")
        _git(seed, "add", "payload.txt")
        _git(seed, "commit", "-m", "second")
        _git(seed, "push", "origin", "main")

    _git(tmp_path, "init", str(checkout))
    _git(checkout, "remote", "add", "origin", str(remote))
    _git(checkout, "fetch", "--no-tags", "origin", "refs/heads/main")
    _git(checkout, "checkout", "--detach", "FETCH_HEAD")
    return checkout, tag_name


def _verify(
    checkout: Path,
    tag_name: str,
    github_sha: str | None = "HEAD",
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["GITHUB_REF_NAME"] = tag_name
    env.pop("GITHUB_SHA", None)
    if github_sha == "HEAD":
        env["GITHUB_SHA"] = _git(checkout, "rev-parse", "HEAD").stdout.strip()
    elif github_sha is not None:
        env["GITHUB_SHA"] = github_sha
    return subprocess.run(
        ["bash", str(VERIFIER)],
        cwd=checkout,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def test_fetches_annotated_tag_object_when_checkout_only_has_peeled_commit(
    tmp_path: Path,
) -> None:
    checkout, tag_name = _release_remote(tmp_path, "annotated")

    assert (
        _git(
            checkout, "rev-parse", "--quiet", "--verify", f"refs/tags/{tag_name}", check=False
        ).returncode
        != 0
    )
    assert _git(checkout, "cat-file", "-t", tag_name, check=False).returncode != 0
    assert VERIFIER.is_file()

    result = _verify(checkout, tag_name)

    assert result.returncode == 0, result.stderr
    assert _git(checkout, "cat-file", "-t", f"refs/tags/{tag_name}").stdout.strip() == "tag"


@pytest.mark.parametrize("tag_kind", ["lightweight", "wrong-main", "missing"])
def test_rejects_invalid_release_tag_state(tmp_path: Path, tag_kind: str) -> None:
    checkout, tag_name = _release_remote(tmp_path, tag_kind)

    result = _verify(checkout, tag_name)

    assert result.returncode != 0


def test_rejects_remote_tag_and_main_moving_after_event_checkout(tmp_path: Path) -> None:
    checkout, tag_name = _release_remote(tmp_path, "annotated")
    seed = tmp_path / "seed"
    event_sha = _git(checkout, "rev-parse", "HEAD").stdout.strip()
    (seed / "payload.txt").write_text("moved after event\n", encoding="utf-8")
    _git(seed, "add", "payload.txt")
    _git(seed, "commit", "-m", "move remote after event")
    _git(seed, "push", "origin", "main")
    _git(seed, "tag", "--force", "--annotate", tag_name, "--message", "moved tag")
    _git(seed, "push", "--force", "origin", f"refs/tags/{tag_name}")

    result = _verify(checkout, tag_name, github_sha=event_sha)

    assert result.returncode != 0
    assert _git(checkout, "rev-parse", "HEAD").stdout.strip() == event_sha


@pytest.mark.parametrize(
    "github_sha",
    [None, "not-a-sha", "0" * 40],
    ids=["missing", "non-40-hex", "unknown-object"],
)
def test_rejects_invalid_github_event_sha(tmp_path: Path, github_sha: str | None) -> None:
    checkout, tag_name = _release_remote(tmp_path, "annotated")

    result = _verify(checkout, tag_name, github_sha=github_sha)

    assert result.returncode != 0
    assert "invalid GITHUB_SHA commit" in result.stderr


def test_rejects_github_event_sha_that_names_a_tag_object(tmp_path: Path) -> None:
    checkout, tag_name = _release_remote(tmp_path, "annotated")
    _git(
        checkout,
        "fetch",
        "--no-tags",
        "origin",
        f"refs/tags/{tag_name}:refs/tags/{tag_name}",
    )
    tag_object = _git(checkout, "rev-parse", f"refs/tags/{tag_name}").stdout.strip()
    assert _git(checkout, "cat-file", "-t", tag_object).stdout.strip() == "tag"

    result = _verify(checkout, tag_name, github_sha=tag_object)

    assert result.returncode != 0
    assert "invalid GITHUB_SHA commit" in result.stderr


def test_rejects_github_event_sha_that_does_not_match_checkout(tmp_path: Path) -> None:
    checkout, tag_name = _release_remote(tmp_path, "annotated")
    (checkout / "local.txt").write_text("different local commit\n", encoding="utf-8")
    _git(checkout, "config", "user.name", "Release Test")
    _git(checkout, "config", "user.email", "release-test@users.noreply.github.com")
    _git(checkout, "add", "local.txt")
    _git(checkout, "commit", "-m", "different local commit")
    other_commit = _git(checkout, "rev-parse", "HEAD^").stdout.strip()

    result = _verify(checkout, tag_name, github_sha=other_commit)

    assert result.returncode != 0
    assert "release commits must match" in result.stderr


@pytest.mark.parametrize("tag_name", ["", "release-0.1.1", "v0.1.1^{}", "../v0.1.1"])
def test_rejects_unsafe_or_non_release_ref_names(tmp_path: Path, tag_name: str) -> None:
    checkout, _ = _release_remote(tmp_path, "annotated")

    result = _verify(checkout, tag_name)

    assert result.returncode != 0
    assert "invalid release tag name" in result.stderr
