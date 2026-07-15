from __future__ import annotations

import re
import tomllib
from pathlib import Path

import yaml

from feishu_task_cli import __version__

ROOT = Path(__file__).resolve().parents[2]
RELEASE_VERSION = "0.1.2"


def test_release_version_is_consistent_across_public_metadata() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    release_match = re.search(
        rf"(?ms)^## \[{re.escape(RELEASE_VERSION)}\].*?(?=^## \[|\Z)",
        changelog,
    )

    assert project["version"] == RELEASE_VERSION
    assert "Development Status :: 3 - Alpha" in project["classifiers"]
    assert __version__ == RELEASE_VERSION
    assert f"## [{RELEASE_VERSION}]" in changelog
    assert "v0.1.0` tag workflow failed before the build step" in changelog
    assert "created no GitHub Release or release assets" in changelog
    assert "`v0.1.1` is the first complete release candidate" in changelog
    assert "v0.1.1` automated release and attestations succeeded" in changelog
    assert "public `SHA256SUMS` paths" in changelog
    assert "could not be verified directly" in changelog
    assert release_match is not None
    release_notes = release_match.group()
    assert "copyable install-only Agent prompt" in release_notes
    assert "authorized Task workflow prompt" in release_notes
    assert "reviewed source of truth for GitHub About metadata" in release_notes
    assert "synthetic mocked responses" in release_notes
    assert "no live-tenant validation" in release_notes
    assert (
        "metadata deployment remains gated until the annotated `v0.1.2` GitHub Release succeeds"
        in release_notes
    )
    assert not re.search(
        r"(?:applied|configured|deployed|published) GitHub About metadata",
        release_notes,
        flags=re.IGNORECASE,
    )


def _release_workflow() -> dict[str, object]:
    loaded = yaml.load(
        (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    assert isinstance(loaded, dict)
    return loaded


def _job(workflow: dict[str, object], name: str) -> dict[str, object]:
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    job = jobs[name]
    assert isinstance(job, dict)
    return job


def _steps(job: dict[str, object]) -> list[dict[str, str]]:
    steps = job["steps"]
    assert isinstance(steps, list)
    assert all(isinstance(step, dict) for step in steps)
    return steps  # type: ignore[return-value]


def test_release_workflow_is_tag_only_with_least_permissions() -> None:
    workflow = _release_workflow()

    assert workflow["on"] == {"push": {"tags": ["v*"]}}
    assert workflow["permissions"] == {"contents": "read"}
    assert _job(workflow, "release")["permissions"] == {
        "attestations": "write",
        "contents": "write",
        "id-token": "write",
    }
    assert _job(workflow, "publish-pypi")["permissions"] == {
        "contents": "read",
        "id-token": "write",
    }


def test_release_lock_check_precedes_every_project_uv_command() -> None:
    release_steps = _steps(_job(_release_workflow(), "release"))
    setup_index = next(
        i for i, step in enumerate(release_steps) if "setup-uv@" in step.get("uses", "")
    )
    runs_after_setup = [step["run"] for step in release_steps[setup_index + 1 :] if "run" in step]

    first_uv_script = next(
        script for script in runs_after_setup if re.search(r"(?m)^\s*uv ", script)
    )
    assert first_uv_script.splitlines()[0].strip() == "uv lock --check"
    assert all(
        "uv run --locked" in line
        for script in runs_after_setup
        for line in script.splitlines()
        if "uv run " in line
    )
    assert any(
        "uv build --clear --out-dir release/packages" in script for script in runs_after_setup
    )
    assert all("uv build --locked" not in script for script in runs_after_setup)


def test_release_artifact_has_one_validated_producer_and_no_pypi_rebuild() -> None:
    workflow = _release_workflow()
    release_steps = _steps(_job(workflow, "release"))
    publish_steps = _steps(_job(workflow, "publish-pypi"))
    release_text = "\n".join(step.get("run", "") for step in release_steps)
    publish_text = "\n".join(step.get("run", "") for step in publish_steps)
    upload = next(step for step in release_steps if "upload-artifact@" in step.get("uses", ""))
    download = next(step for step in publish_steps if "download-artifact@" in step.get("uses", ""))
    attest = next(
        step for step in release_steps if "attest-build-provenance@" in step.get("uses", "")
    )
    pypi = next(step for step in publish_steps if "gh-action-pypi-publish@" in step.get("uses", ""))
    upload_index = release_steps.index(upload)
    download_index = publish_steps.index(download)
    pypi_index = publish_steps.index(pypi)

    assert upload["with"]["name"] == "release-distributions"  # type: ignore[index]
    assert upload["with"]["path"] == "release/"  # type: ignore[index]
    assert download["with"]["name"] == "release-distributions"  # type: ignore[index]
    assert download["with"]["path"] == "release"  # type: ignore[index]
    assert pypi["with"]["packages-dir"] == "release/packages"  # type: ignore[index]
    assert "release/packages/*.whl" in attest["with"]["subject-path"]  # type: ignore[index]
    assert "release/SHA256SUMS" in attest["with"]["subject-path"]  # type: ignore[index]
    assert "uv build --clear --out-dir release/packages" in release_text
    assert "twine check release/packages/*.whl release/packages/*.tar.gz" in release_text
    assert '"$SMOKE_ENV/bin/feishu-task" --help' in release_text
    assert "sha256sum" in release_text
    assert "cd release/packages" in publish_text
    assert "sha256sum -c ../SHA256SUMS" in publish_text
    assert "twine check" in publish_text
    assert "uv build" not in publish_text
    assert not any("checkout@" in step.get("uses", "") for step in publish_steps)
    assert any(
        "gh release create" in step.get("run", "")
        and "release/packages/* release/SHA256SUMS" in step.get("run", "")
        for step in release_steps
    )
    assert upload_index > next(
        i for i, step in enumerate(release_steps) if "uv build --clear" in step.get("run", "")
    )
    assert (
        download_index
        < next(i for i, step in enumerate(publish_steps) if "sha256sum -c" in step.get("run", ""))
        < pypi_index
    )


def test_release_tag_and_version_checks_are_executable_steps() -> None:
    release_steps = _steps(_job(_release_workflow(), "release"))
    release_text = "\n".join(step.get("run", "") for step in release_steps)
    verifier = (ROOT / "scripts/verify_release_tag.sh").read_text(encoding="utf-8")

    verify_index = next(
        i
        for i, step in enumerate(release_steps)
        if step.get("run", "").strip() == "bash scripts/verify_release_tag.sh"
    )
    setup_uv_index = next(
        i for i, step in enumerate(release_steps) if "setup-uv@" in step.get("uses", "")
    )

    assert verify_index < setup_uv_index
    assert "git cat-file -t" in verifier
    assert "GITHUB_SHA" in verifier
    assert "HEAD^{commit}" in verifier
    assert "${tag_ref}^{commit}" in verifier
    assert "refs/remotes/origin/main" in verifier
    assert "tomllib" in release_text


def test_readme_install_does_not_assume_pypi_publishing() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert f"git+https://github.com/Alex-ghost599/feishu-task-cli@v{RELEASE_VERSION}" in readme
    assert "`uv tool install feishu-task-cli`" not in readme


def test_release_process_forbids_reusing_failed_tags() -> None:
    process = (ROOT / "docs/release-process.md").read_text(encoding="utf-8")

    assert "Never move, delete, or reuse a failed release tag" in process
    assert "use the next patch" in process


def test_release_process_requires_ancestry_only_main_sync() -> None:
    process = " ".join((ROOT / "docs/release-process.md").read_text(encoding="utf-8").split())

    assert "zero-file ancestry-only" in process
    assert "`main` → `develop`" in process
    assert "validation-approved normal merge" in process
    assert "Product, documentation, and bug-fix PRs remain squash-merged" in process
    assert "Never substitute marker commits" in process
    assert "force-pushes" in process
    assert "moved tags" in process


def test_release_process_requires_a_fail_safe_ancestry_sync_window() -> None:
    process = " ".join((ROOT / "docs/release-process.md").read_text(encoding="utf-8").split())

    # The approval must bind both policy and object identity before any setting changes.
    assert "machine-readable repository settings snapshot" in process
    assert "machine-readable branch-protection snapshots" in process
    assert "exact `main`, `develop`, and PR head commit IDs" in process
    assert "exact tree IDs" in process

    # The exception is deliberately two switches wide; every other guard stays fixed.
    assert "`allow_merge_commit=true`" in process
    assert "`develop.required_linear_history=false`" in process
    assert "required checks and strictness" in process
    assert "PR review requirements" in process
    assert "administrator enforcement" in process
    assert "conversation resolution" in process
    assert "force-push and deletion protection" in process
    assert "all `main` protection" in process

    # Restore happens before success/failure handling can leave the window open.
    assert "restore-first" in process
    assert "success, failure, or timeout" in process
    assert "trap/finally" in process
    assert "`allow_merge_commit=false`" in process
    assert "`develop.required_linear_history=true`" in process

    # Readback and graph/tree postconditions close the exception.
    assert "read back the complete repository and branch-protection snapshots" in process
    assert "zero changed files" in process
    assert "unchanged tree ID" in process
    assert "both pre-window commits are ancestors" in process
    assert "remote task branch remains present" in process

    # This cannot become a general-purpose escape hatch or overlap later work.
    assert "validation-approved, zero-file ancestry PR" in process
    assert "Product, documentation, and bug-fix PRs remain squash-merged" in process
    assert "delete branches" in process
    assert "No later release or bug-fix work may begin" in process


def test_release_workflow_pins_every_action_to_an_immutable_sha() -> None:
    jobs = _release_workflow()["jobs"]
    assert isinstance(jobs, dict)
    action_refs = [
        step["uses"]
        for job in jobs.values()
        if isinstance(job, dict)
        for step in _steps(job)
        if "uses" in step
    ]

    assert action_refs
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", ref) for ref in action_refs)
