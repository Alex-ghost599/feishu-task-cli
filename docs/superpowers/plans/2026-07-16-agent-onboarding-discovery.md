# Agent Onboarding and Repository Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give any AI Agent a copy-paste, safety-bounded v0.1.2 installation and Task execution entry point, then publish accurate GitHub About, Homepage, and Topics metadata.

**Architecture:** Treat the prompts as versioned public contracts, not marketing copy. Contract tests parse the README, installation guide, root Agent entry point, package version, and tracked metadata manifest before documentation is written; GitHub metadata remains an external deployment step performed only after the same content and v0.1.2 Release reach `main`.

**Tech Stack:** Markdown, Python 3.11+, pytest, Pydantic CLI schemas, GitHub Actions, GitHub REST API, `gh`.

## Global Constraints

- All install commands pin annotated tag `v0.1.2`; never use `@main`, `@develop`, or an unpinned Git URL.
- Installer network activity is limited to GitHub/package reads and isolated `uv tool` writes.
- Installer never uses `sudo`, changes system Python, opens a browser, runs OAuth, calls Task APIs, or asks for/prints credentials.
- Installer stops with `blocked` when Python 3.11+ or `uv` is absent.
- Installer final output is only the exact JSON report contract in the approved design.
- Usage follows Plan -> Review -> Execute -> readback -> Receipt -> Render; `partial` and `unknown` are never replayed or reported as success.
- README badges and statements must be backed by current tests or GitHub state; no production-ready, live-tenant, download, or compatibility claim.
- GitHub description is at most 160 characters; Topics are unique normalized names and at most 20.
- Issues #54 and #55 remain open until v0.1.2 Release and GitHub metadata readback succeed.

---

### Task 1: Add failing onboarding and metadata contracts

**Files:**
- Create: `tests/contract/test_agent_onboarding.py`
- Read: `pyproject.toml`
- Read: `README.md`

**Interfaces:**
- Consumes: package version from `pyproject.toml`
- Produces: executable contract for the README marker blocks, installation report shape, repository metadata values, and local Markdown links

- [ ] **Step 1: Write the failing tests**

Create tests that extract fenced blocks between stable headings and assert:

```python
INSTALL_REF = "v0.1.2"
REPORT_KEYS = {
    "status", "package", "requested_ref", "installed_version", "executable",
    "checks", "auth_attempted", "browser_opened", "task_write_attempted",
    "warnings", "errors",
}
CHECK_KEYS = {"python", "uv", "version", "help", "schemas"}
FORBIDDEN_INSTALL_TEXT = (
    "@main", "@develop", "sudo ", "curl | sh", "auth login", "feishu-task execute",
    "--app-secret", "--token",
)
```

The tests must verify: README links to `docs/agent-installation.md`; all five local document links exist; the pinned ref equals `v` plus `project.version`; Plan/Review/Policy/Receipt schemas are named; the report example has exactly the reviewed keys and false mutation booleans; metadata description length is at most 160; Topics match `^[a-z0-9]+(?:-[a-z0-9]+)*$`, are unique, and total at most 20.

- [ ] **Step 2: Run RED**

Run: `uv run pytest -q tests/contract/test_agent_onboarding.py`

Expected: FAIL because `docs/agent-installation.md`, `AGENTS.md`, and `docs/repository-metadata.md` do not exist and README has no copy-to-Agent block.

- [ ] **Step 3: Commit the RED contract**

```bash
git add tests/contract/test_agent_onboarding.py
git diff --cached --check
git commit -m "test: define agent onboarding contracts"
```

---

### Task 2: Implement the safe Agent installation and usage entry points

**Files:**
- Create: `docs/agent-installation.md`
- Create: `AGENTS.md`
- Modify: `README.md`
- Test: `tests/contract/test_agent_onboarding.py`

**Interfaces:**
- Consumes: v0.1.2 version and existing commands in `docs/agent-protocol.md`
- Produces: copyable installer prompt, deterministic install report, copyable Task execution prompt, and generic cloned-repository Agent router

- [ ] **Step 1: Write the installation guide**

The installer prompt must instruct the receiving Agent to:

```text
1. Verify Python >=3.11 and uv; report blocked and stop if absent.
2. Install or upgrade only the isolated uv tool from the pinned v0.1.2 Git tag.
3. Resolve the absolute feishu-task executable and verify installed package version 0.1.2.
4. Run --help and schema show for plan, review, policy, and receipt.
5. Do not authenticate, open a browser, call Feishu APIs, or execute a Task write.
6. Return only the reviewed JSON report and never include secrets or business data.
```

The separate Task prompt must require explicit IDs and write authorization, prefer independent review, retain declared self-review when unavoidable, render a user handoff, and stop without replay on `partial` or `unknown`.

- [ ] **Step 2: Add the short repository Agent router**

`AGENTS.md` must remain under 100 lines and route Agents to:

```markdown
- Installation and copyable prompts: `docs/agent-installation.md`
- Runtime artifact and outcome rules: `docs/agent-protocol.md`
- Public architecture and trust boundaries: `docs/architecture.md`
- Contributions and Git workflow: `CONTRIBUTING.md`
```

It must prohibit local absolute paths, implicit profiles, credentials, and live writes during install verification.

- [ ] **Step 3: Put the short copy block near the README top**

The README block links to the complete guide and preserves the same v0.1.2 pin and install-only boundaries. It must not duplicate the entire protocol.

- [ ] **Step 4: Run GREEN**

Run: `uv run pytest -q tests/contract/test_agent_onboarding.py`

Expected: PASS for installer safety, report shape, link existence, and version pin.

- [ ] **Step 5: Commit**

```bash
git add README.md AGENTS.md docs/agent-installation.md
git diff --cached --check
git commit -m "docs: add copyable agent installation prompts"
```

---

### Task 3: Expand factual README content and track repository metadata

**Files:**
- Modify: `README.md`
- Create: `docs/repository-metadata.md`
- Test: `tests/contract/test_agent_onboarding.py`

**Interfaces:**
- Consumes: current CI workflow names, Agent protocol outcomes, receipt renderer behavior
- Produces: search-readable project explanation and exact deployable GitHub metadata

- [ ] **Step 1: Add only factual badges and structured sections**

README must add badges for CI, CodeQL, latest Release, Python 3.11+, and MIT; plus concise sections named `Why this exists`, `Use cases`, `Agent contract`, `Example user handoff`, `Troubleshooting`, and `Documentation`.

The example handoff must show a synthetic `verified` result without token, account, tenant, real Task ID, or unsupported live-tenant claim.

- [ ] **Step 2: Add the metadata manifest**

`docs/repository-metadata.md` must record exactly:

```text
Description: Agent-first CLI for safe Feishu/Lark Task writes: review artifacts, dry-run plans, API readback, execution journals, and machine-readable receipts.
Homepage: https://github.com/Alex-ghost599/feishu-task-cli/blob/main/docs/agent-installation.md
Topics: feishu, lark, larksuite, cli, python, ai-agent, agent-tools, agentic-ai, task-management, workflow-automation, oauth2, api-client, dry-run, developer-tools, automation
```

It must also state that the file is the reviewed source of truth and GitHub API readback is deployment evidence.

- [ ] **Step 3: Run contracts and documentation checks**

Run:

```bash
uv run pytest -q tests/contract/test_agent_onboarding.py tests/contract/test_release_metadata.py
uv run ruff format --check .
uv run ruff check .
git diff --check
```

Expected: all pass with no broken local links or metadata contract failures.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/repository-metadata.md
git diff --cached --check
git commit -m "docs: improve repository discovery metadata"
```

---

### Task 4: Validate and merge the docs package to develop

**Files:**
- Modify only if a test or reviewer identifies a concrete defect
- Write ignored reports under `.superpowers/sdd/`

**Interfaces:**
- Consumes: Tasks 1-3 commits
- Produces: reviewed PR into `develop`

- [ ] **Step 1: Run the full local gate**

```bash
uv sync --locked --extra test
uv run ruff format --check .
uv run ruff check .
uv run mypy src scripts
uv run pytest -q --cov=feishu_task_cli --cov-fail-under=90
uv build --clear
uv run twine check dist/*
uv run pip-audit
uv run python scripts/privacy_scan.py --history
git diff --check
```

Expected: all pass; no real credentials, profiles, IDs, or home paths appear.

- [ ] **Step 2: Independent validation-only review**

Reviewer must validate prompt safety, JSON contract, actual CLI command availability, version pin, capability claims, link integrity, keyword relevance, and metadata limits. Any Blocker or Important finding fails the gate.

- [ ] **Step 3: Push and create one PR**

Push `docs--agent-onboarding-discovery` and create a PR to `develop` whose body links `Refs #54` and `Refs #55` but does not close them yet.

- [ ] **Step 4: Wait for all required checks and squash merge**

Require quality, tests, compatibility, build, dependencies, secrets, privacy, CodeQL, and dependency review to pass. Squash merge without deleting the task branch; read back PR, `develop`, and retained branch.

---

### Task 5: Release v0.1.2 and deploy GitHub metadata

**Files:**
- No new product files unless release validation exposes a tracked bug
- Update local ignored release and control-plane evidence

**Interfaces:**
- Consumes: updated `develop`, v0.1.2 release workflow, `docs/repository-metadata.md`
- Produces: public stable Agent prompt and GitHub discovery metadata

- [ ] **Step 1: Promote develop to main**

Open a coherent `develop` to `main` v0.1.2 PR, require all checks, independently review, and squash merge. Do not close #50, #54, or #55 yet.

- [ ] **Step 2: Create and push annotated v0.1.2**

Guard that local HEAD, `origin/main`, tag peeled commit, and release workflow `GITHUB_SHA` are the same. Never move or overwrite an existing tag.

- [ ] **Step 3: Verify the real Release**

Download wheel, sdist, and `SHA256SUMS` flat into one directory; run `sha256sum -c SHA256SUMS`; verify attestations; install the downloaded wheel in a clean environment; verify CLI help and version. PyPI remains skipped unless explicitly enabled.

- [ ] **Step 4: Perform mandatory post-release ancestry sync**

Follow the restore-first runbook in `docs/release-process.md`: validation-approved zero-file PR, exact guards, only two temporary settings, normal merge, restore before postchecks, full readback, unchanged tree, both ancestors, retained branch.

- [ ] **Step 5: Apply GitHub metadata only after main has the docs**

Use `gh repo edit` or the REST API to set the exact description, homepage, and Topics from the tracked manifest. Re-read all values and compare exact description/homepage and sorted Topic sets.

- [ ] **Step 6: Close the three Issues and task control plane**

Close #50, #54, and #55 only after Release, public checksum, attestation, prompt URL, metadata, and ancestry readbacks pass. Update the task note and board, run `check-task-ids.sh`, and obtain final validation-only PASS.
