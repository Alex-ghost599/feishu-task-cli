#!/usr/bin/env python3
"""Scan tracked content and Git history for private or credential-shaped values."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

Pattern = tuple[str, re.Pattern[str]]

LEGACY_PUBLISHED_IDENTITY_EXCEPTIONS = frozenset({"40005c84301d277b105735e72e7633c90b966e46"})


def _assignment(field: str, value: str) -> re.Pattern[str]:
    return re.compile(rf"(?i)[\"']?{field}[\"']?\s*[:=]\s*[\"']?{value}")


uuid_value = (
    r"(?!00000000-0000-0000-0000-000000000000)"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)

PATTERNS: tuple[Pattern, ...] = (
    (
        "personal_home_path",
        re.compile("/" + r"(?:Users|home)/[A-Za-z0-9._-]+/"),
    ),
    (
        "authorization_value",
        re.compile(
            r"(?i)[\"']?Authorization[\"']?\s*[:=]\s*[\"']?"
            r"(?:Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{8,}"
        ),
    ),
    (
        "secret_assignment",
        re.compile(
            r"(?i)(?:app_secret|user_access_token|refresh_token)\s*[:=]\s*"
            r"['\"]?[A-Za-z0-9._~+/=-]{16,}"
        ),
    ),
    (
        "real_feishu_identifier",
        re.compile(r"\b(?:ou_|on_)[A-Za-z0-9]{20,}\b"),
    ),
    (
        "real_app_id",
        _assignment("app_id", r"(?!cli_(?:test|example|synthetic))cli_[A-Za-z0-9]{16,}"),
    ),
    (
        "real_user_id",
        _assignment(
            "user_id",
            r"(?!(?:test|example|synthetic)(?:\b|_))(?:u_)?[A-Za-z0-9][A-Za-z0-9._-]{15,}",
        ),
    ),
    ("real_task_guid", _assignment("task_guid", uuid_value)),
    ("real_tasklist_guid", _assignment("tasklist_guid", uuid_value)),
    (
        "real_tenant_key",
        _assignment(
            "tenant_key",
            r"(?!(?:tenant_)?(?:test|example|synthetic)(?:\b|_))[A-Za-z0-9._-]{16,}",
        ),
    ),
)


def scan_text(text: str, source: str) -> list[str]:
    """Return stable, redacted finding labels for one text source."""
    return [f"{source}: {name}" for name, pattern in PATTERNS if pattern.search(text)]


def _tracked_files(root: Path) -> list[Path]:
    output = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True
    ).stdout
    return [root / item.decode() for item in output.split(b"\0") if item]


def scan_tree(root: Path) -> list[str]:
    findings: list[str] = []
    for path in _tracked_files(root):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        findings.extend(scan_text(text, path.relative_to(root).as_posix()))
    return findings


def scan_history(root: Path) -> list[str]:
    history = subprocess.run(
        ["git", "log", "-p", "--all", "--no-ext-diff", "--no-textconv"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        errors="ignore",
    ).stdout
    return scan_text(history, "git-history")


def _is_github_noreply(email: str) -> bool:
    return email == "noreply@github.com" or email.endswith("@users.noreply.github.com")


def scan_identity_log(text: str) -> list[str]:
    """Return redacted findings for publishable commit author/committer identities."""
    findings: list[str] = []
    for line in text.splitlines():
        fields = line.split("\t")
        if len(fields) != 3:
            findings.append("git-head-identities: malformed_identity_record")
            continue
        commit_sha, author_email, committer_email = fields
        if commit_sha in LEGACY_PUBLISHED_IDENTITY_EXCEPTIONS:
            continue
        if not _is_github_noreply(author_email):
            findings.append("git-head-identities: non_noreply_author")
        if not _is_github_noreply(committer_email):
            findings.append("git-head-identities: non_noreply_committer")
    return sorted(set(findings))


def scan_head_identities(root: Path) -> list[str]:
    """Scan only commits reachable from publishable HEAD, not retained remote task refs."""
    identity_log = subprocess.run(
        ["git", "log", "HEAD", "--format=%H%x09%ae%x09%ce"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        errors="ignore",
    ).stdout
    return scan_identity_log(identity_log)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", action="store_true")
    args = parser.parse_args()
    root = Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], check=True, capture_output=True, text=True
        ).stdout.strip()
    )
    findings = scan_tree(root)
    if args.history:
        findings.extend(scan_history(root))
        findings.extend(scan_head_identities(root))
    if findings:
        print("Privacy scan failed:")
        for finding in sorted(set(findings)):
            print(f"- {finding}")
        return 1
    print("Privacy scan passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
