from __future__ import annotations

import subprocess
from pathlib import Path

import scripts.privacy_scan as privacy_scan
from scripts.privacy_scan import scan_history, scan_text, scan_tree

ROOT = Path(__file__).resolve().parents[2]
PUBLIC_DOCS = (
    ROOT / "README.md",
    ROOT / "docs/architecture.md",
    ROOT / "docs/agent-protocol.md",
    ROOT / "docs/behavior-inventory.md",
    ROOT / "docs/release-process.md",
)


def test_public_documentation_exposes_agent_native_safety_boundaries() -> None:
    documentation = "\n".join(path.read_text(encoding="utf-8") for path in PUBLIC_DOCS)

    for required_statement in (
        "A Plan is not an executed Task",
        "declared identity",
        "single host",
        "unknown",
        "typed assignee",
        "self-review",
        "JSON",
        "Markdown",
        "no default profiles",
        "no live-tenant validation",
    ):
        assert required_statement.casefold() in documentation.casefold()


def test_public_oauth_setup_documents_registered_redirect_and_permissions() -> None:
    documentation = "\n".join(path.read_text(encoding="utf-8") for path in PUBLIC_DOCS)

    for required_statement in (
        "http://127.0.0.1:8765/callback",
        "FEISHU_OAUTH_REDIRECT_URI",
        "task:task:read",
        "task:task:write",
        "publish the Feishu application",
        "--no-browser",
    ):
        assert required_statement.casefold() in documentation.casefold()


def test_release_docs_match_complete_local_gate_and_history_boundary() -> None:
    release_process = (ROOT / "docs/release-process.md").read_text(encoding="utf-8")

    for command in (
        "uv run pip-audit",
        "uv build --clear",
        "uv venv",
        'feishu-task" --help',
        "feishu_task_cli.__version__",
    ):
        assert command in release_process
    assert "retained remote task branches" in release_process.casefold()
    assert "not a clean-all-refs claim" in release_process.casefold()


def test_behavior_inventory_uses_only_public_feishu_sources() -> None:
    inventory = (ROOT / "docs/behavior-inventory.md").read_text(encoding="utf-8")
    links = [part.split(")", 1)[0] for part in inventory.split("(")[1:] if ")" in part]

    assert links
    assert all(link.startswith("https://open.feishu.cn/") for link in links)
    assert "private predecessor" not in inventory.casefold()
    assert "source code comparison" not in inventory.casefold()


def test_public_docs_contain_no_private_or_credential_shaped_values() -> None:
    findings: list[str] = []
    for path in PUBLIC_DOCS:
        findings.extend(scan_text(path.read_text(encoding="utf-8"), path.name))

    assert findings == []


def test_tracked_tree_and_git_history_pass_the_public_boundary_scan() -> None:
    subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=ROOT, check=True)

    assert scan_tree(ROOT) == []
    assert scan_history(ROOT) == []


def test_history_identity_scanner_rejects_non_github_noreply_metadata() -> None:
    scanner = getattr(privacy_scan, "scan_identity_log", None)

    assert callable(scanner)
    assert scanner("f" * 40 + "\tmaintainer@example.invalid\tnoreply@github.com\n") == [
        "git-head-identities: non_noreply_author"
    ]


def test_publishable_head_commit_identities_are_safe_or_legacy_sha() -> None:
    scanner = getattr(privacy_scan, "scan_head_identities", None)

    assert callable(scanner)
    assert scanner(ROOT) == []
