# feishu-task-cli Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and publicly release `Alex-ghost599/feishu-task-cli` v0.1.0 as an agent-native, review-gated, readback-verified Feishu Task write and assignment CLI.

**Architecture:** Typer exposes non-interactive JSON commands over Pydantic domain artifacts. Application services enforce canonical Plan/Review/Policy validation, AuthContext and precondition checks, a single-consumption execution journal, Feishu mutations, readback reconciliation, and safe Receipt rendering. Feishu HTTP and OAuth remain adapters behind typed interfaces.

**Tech Stack:** Python 3.11+, Typer, Pydantic 2, httpx, keyring, platformdirs, filelock, rfc8785, pytest, respx, Ruff, mypy, build, twine, pip-audit, gitleaks, GitHub Actions, CodeQL.

## Global Constraints

- Repository: `Alex-ghost599/feishu-task-cli`; distribution: `feishu-task-cli`; executable: `feishu-task`; package: `feishu_task_cli`.
- License: MIT.
- No private-source code, fixtures, comments, error text, Git history, personal paths, real profiles, IDs, credentials, tenant data, or business examples may enter the repository.
- `main` contains releases; `develop` is long-lived integration; every post-bootstrap change starts with an Issue and merges by squash PR into `develop`.
- Bugs require Issue → `fix--<slug>` from `develop` → failing regression test → PR to `develop`.
- A release uses `develop` → `main` PR, then an annotated tag whose target equals the release merge commit.
- Do not delete remote branches. Do not use `--delete-branch`.
- Prefix every `gh` command with `GH_PROMPT_DISABLED=1` and pass `--repo Alex-ghost599/feishu-task-cli` whenever the command supports it.
- After each GitHub write, re-read the created or modified resource before continuing.
- Every public push must trigger CI containing quality, tests, build, full-history gitleaks, privacy/provenance, and relevant feature checks.
- All implementation follows red-green-refactor TDD; never add production behavior before a failing test proves the requirement.
- Agent identities are declared audit metadata, not cryptographically verified identities.
- Mutations are never blindly retried after ambiguous transport failure.
- Secrets are not accepted through CLI flags and are never emitted to stdout, stderr, exceptions, traces, artifacts, or receipts.

## File map

```text
.github/
  CODEOWNERS                         repository ownership
  dependabot.yml                     dependency PRs targeting develop
  ISSUE_TEMPLATE/bug.yml             bug workflow template
  ISSUE_TEMPLATE/feature.yml         feature workflow template
  pull_request_template.md           clean-room and verification checklist
  workflows/ci.yml                   all-push quality/test/build/secret/privacy checks
  workflows/codeql.yml               Python CodeQL analysis
  workflows/dependency-review.yml    PR dependency review
  workflows/release.yml              tag/package verification and GitHub release
scripts/
  privacy_scan.py                    tracked-tree and history privacy/provenance scan
docs/
  architecture.md                    public architecture and trust boundaries
  agent-protocol.md                  Plan/Review/Policy/Receipt workflow
  behavior-inventory.md              public-source behavior/provenance ledger
  release-process.md                 develop-to-main release instructions
  superpowers/specs/...              approved design
  superpowers/plans/...              this plan
schemas/
  plan-v1.json                       committed Plan schema
  review-v1.json                     committed Review schema
  policy-v1.json                     committed Policy schema
  receipt-v1.json                    committed Receipt schema
src/feishu_task_cli/
  __init__.py                        package version
  __main__.py                        python -m entry point
  cli.py                             Typer command tree and JSON I/O
  errors.py                          typed errors and stable exit codes
  artifacts/
    base.py                          strict artifact base model
    canonical.py                     RFC 8785 and SHA-256 hashing
    plan.py                          Plan and AuthContext
    review.py                        Review and checked-fact enum
    policy.py                        Policy schema
    receipt.py                       Receipt and outcomes
    schema_export.py                 deterministic JSON Schema export
  application/
    planner.py                       create/update/assign/complete plan construction
    reviewer.py                      Review construction
    policy_engine.py                 review/policy enforcement
    executor.py                      guarded mutation orchestration
    reconcile.py                     requested/observed comparison
  auth/
    config.py                        non-secret config and secure secret inputs
    context.py                       AuthContext fingerprint resolution
    keyring_store.py                 refresh token storage
    oauth.py                         localhost user OAuth flow
  feishu/
    client.py                        redacted HTTP transport
    tasks.py                         narrow task endpoint adapter
  journal/
    store.py                         hash-only state persistence
    locking.py                       plan-scoped OS exclusive locks
  presentation/
    markdown.py                      untrusted-data-safe rendering
    next_actions.py                  typed safe-next-action mapping
tests/
  unit/...                           domain/application/security tests
  contract/...                       CLI and schema contracts
  integration/...                    mocked HTTP and concurrency tests
  golden/...                         canonical hash and Markdown vectors
```

---

### Task 1: Bootstrap the public repository with CI before the first push

**Issue/branch:** Bootstrap exception on local `main`; no product implementation and no pre-existing remote branch.

**Files:**
- Create: `pyproject.toml`
- Create: `README.md`
- Create: `LICENSE`
- Create: `CONTRIBUTING.md`
- Create: `SECURITY.md`
- Create: `CODE_OF_CONDUCT.md`
- Create: `CHANGELOG.md`
- Create: `.gitignore`
- Create: `.github/CODEOWNERS`
- Create: `.github/dependabot.yml`
- Create: `.github/ISSUE_TEMPLATE/bug.yml`
- Create: `.github/ISSUE_TEMPLATE/feature.yml`
- Create: `.github/pull_request_template.md`
- Create: `.github/workflows/ci.yml`
- Create: `.github/workflows/codeql.yml`
- Create: `.github/workflows/dependency-review.yml`
- Create: `scripts/privacy_scan.py`
- Create: `src/feishu_task_cli/__init__.py`
- Create: `tests/contract/test_package.py`

**Interfaces:**
- Consumes: approved design commit and repository name.
- Produces: installable empty package, `feishu-task-cli` metadata, baseline CI jobs `quality`, `tests`, `build`, `secrets`, and `privacy`.

- [ ] **Step 1: Write the bootstrap package smoke test**

```python
from feishu_task_cli import __version__


def test_initial_version_is_unreleased() -> None:
    assert __version__ == "0.0.0"
```

- [ ] **Step 2: Run the test and verify red**

Run: `uv run --with pytest pytest tests/contract/test_package.py -v`

Expected: collection fails because `feishu_task_cli` does not exist.

- [ ] **Step 3: Add the minimal package and project metadata**

```python
# src/feishu_task_cli/__init__.py
__version__ = "0.0.0"
```

Use `pyproject.toml` with `setuptools.build_meta`, Python `>=3.11`, the dependency ranges from the header, `feishu-task = "feishu_task_cli.cli:app"`, Ruff line length 100, mypy package checking, and pytest paths `tests`.

- [ ] **Step 4: Add governance and public-boundary documents**

README must label the repository as pre-release and Agent-native. CONTRIBUTING must state Issue → branch → PR → `develop`, squash merge, no automatic branch deletion, and release PR → `main`. SECURITY must direct vulnerability reporters to GitHub private vulnerability reporting and prohibit secrets in public issues. The PR template must include test evidence, clean-room declaration, secret scan, and user-facing behavior checkboxes.

- [ ] **Step 5: Add pinned baseline workflows**

Use these immutable official action commits:

```text
actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683
actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065
gitleaks/gitleaks-action@ff98106e4c7b2bc287b24eaf42907196329070c7
github/codeql-action/*@02c5e83432fe5497fd85b873b6c9f16a8578e1d9
```

`ci.yml` triggers on every branch push and every pull request. It uses `permissions: contents: read`, checkout `fetch-depth: 0`, Python 3.11 and 3.12 tests, Ruff, mypy, pytest, `python -m build`, `twine check`, gitleaks, and `scripts/privacy_scan.py --history`. The scanner detects real personal home-directory paths, token/header shapes, and non-synthetic Feishu identifiers while excluding its own encoded pattern definitions. Job names are exactly `quality`, `tests`, `build`, `secrets`, and `privacy`.

- [ ] **Step 6: Run bootstrap verification locally**

Run:

```bash
uv sync --extra test
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest -v
uv build
uv run twine check dist/*
gitleaks git --redact --no-banner
git diff --check
```

Expected: all commands pass; test count is at least 1; both wheel and sdist pass `twine check`.

- [ ] **Step 7: Amend the unpublished bootstrap commit**

Run:

```bash
git add .
git commit --amend --no-edit
git show --check --stat HEAD
```

Expected: one root commit remains on local `main`; it contains design, plan, governance, package smoke, and CI but no product behavior.

- [ ] **Step 8: Create and verify the public repository**

Run:

```bash
GH_PROMPT_DISABLED=1 gh repo create Alex-ghost599/feishu-task-cli --public --source=. --remote=origin --description "Agent-native, review-gated Feishu Task CLI"
git push -u origin main
GH_PROMPT_DISABLED=1 gh repo view Alex-ghost599/feishu-task-cli --json nameWithOwner,isPrivate,defaultBranchRef,url --repo Alex-ghost599/feishu-task-cli
GH_PROMPT_DISABLED=1 gh run list --branch main --limit 10 --repo Alex-ghost599/feishu-task-cli
```

Expected: repository is public, default branch is `main`, and first-push workflows exist. Wait for required jobs and verify each conclusion with `gh run view`.

- [ ] **Step 9: Create `develop`, then configure and verify rulesets**

Run:

```bash
git branch develop main
git push -u origin develop
GH_PROMPT_DISABLED=1 gh api repos/Alex-ghost599/feishu-task-cli/branches/develop --repo Alex-ghost599/feishu-task-cli
```

Create active branch rulesets through `gh api` for `main` and `develop`: required PRs, required checks `quality`, `tests`, `build`, `secrets`, `privacy`, resolved conversations, deletion protection, and non-fast-forward protection; approval count stays zero because the authenticated author cannot approve their own PR. Re-read both rulesets with `gh api repos/Alex-ghost599/feishu-task-cli/rulesets` and verify exact targets and required contexts.

---

### Task 2: Canonical artifacts and committed JSON Schemas

**Issue/branch:** Create Issue “Implement canonical agent artifacts”; branch `feat--canonical-artifacts` from `develop`; PR to `develop`.

**Files:**
- Create: `src/feishu_task_cli/errors.py`
- Create: `src/feishu_task_cli/artifacts/base.py`
- Create: `src/feishu_task_cli/artifacts/canonical.py`
- Create: `src/feishu_task_cli/artifacts/plan.py`
- Create: `src/feishu_task_cli/artifacts/review.py`
- Create: `src/feishu_task_cli/artifacts/policy.py`
- Create: `src/feishu_task_cli/artifacts/receipt.py`
- Create: `src/feishu_task_cli/artifacts/schema_export.py`
- Create: `schemas/plan-v1.json`
- Create: `schemas/review-v1.json`
- Create: `schemas/policy-v1.json`
- Create: `schemas/receipt-v1.json`
- Create: `tests/golden/hash-vectors.json`
- Test: `tests/unit/artifacts/test_canonical.py`
- Test: `tests/unit/artifacts/test_models.py`
- Test: `tests/contract/test_schemas.py`

**Interfaces:**
- Consumes: `rfc8785.dumps(value) -> bytes`.
- Produces: `canonical_bytes(value) -> bytes`, `artifact_hash(value) -> str`, strict `PlanV1`, `ReviewV1`, `PolicyV1`, `ReceiptV1`, `CheckedFact`, `Outcome`, and `export_schemas(path)`.

- [ ] **Step 1: Open and verify the GitHub Issue and branch**

Run `GH_PROMPT_DISABLED=1 gh issue create --title "Implement canonical agent artifacts" --body "Implement strict v1 Plan, Review, Policy, Receipt, RFC 8785 canonicalization, SHA-256 hashes, committed JSON Schemas, and golden vectors. Acceptance: tests first, no private-source code or identifiers, all CI gates pass." --repo Alex-ghost599/feishu-task-cli`, extract the returned Issue number, re-read it with `gh issue view <number>`, then create `feat--canonical-artifacts` from synchronized `develop`.

- [ ] **Step 2: Write failing canonicalization tests**

```python
def test_hash_uses_rfc8785_and_excludes_hash_field() -> None:
    value = {"schema_version": "1", "name": "任务", "plan_hash": "ignored"}
    assert artifact_hash(value, hash_field="plan_hash") == artifact_hash(
        {"name": "任务", "schema_version": "1"}, hash_field="plan_hash"
    )


def test_float_is_rejected() -> None:
    with pytest.raises(ArtifactIntegrityError, match="floating-point"):
        canonical_bytes({"value": 1.5})
```

- [ ] **Step 3: Run the focused tests and verify red**

Run: `uv run pytest tests/unit/artifacts/test_canonical.py -v`

Expected: import failure for missing artifact modules.

- [ ] **Step 4: Implement canonical serialization and strict models**

Implement recursive float rejection, RFC 8785 serialization, SHA-256 hexadecimal hashes, UTC datetime validation, `extra="forbid"`, and the exact artifact fields from the approved design. `ReviewV1` contains `reviewer_id` and optional `intended_executor_id`, but no review-mode input. `AuthContext` stores full domain-separated fingerprints and separate display fingerprints.

- [ ] **Step 5: Write and run schema/golden tests**

Tests must prove deterministic schema export, unknown-field rejection, stable enum values, a changed AuthContext changing `plan_hash`, and golden vectors loading identically on Python 3.11 and 3.12.

Run: `uv run pytest tests/unit/artifacts tests/contract/test_schemas.py -v`

Expected: PASS.

- [ ] **Step 6: Export schemas and run the full local gate**

Run: `uv run python -m feishu_task_cli.artifacts.schema_export schemas && uv run pytest -v && uv run ruff check . && uv run mypy src && git diff --check`.

Expected: generated schemas match tracked files and all gates pass.

- [ ] **Step 7: Commit, push, open PR, verify checks, and squash merge**

Commit `feat: add canonical agent artifacts`; push the branch; open a PR referencing the Issue and clean-room declaration; re-read the PR; verify all required checks and mergeability; squash merge into `develop` without deleting the branch; re-read PR, Issue, and remote `develop`.

---

### Task 3: Review policy and agent-facing CLI contracts

**Issue/branch:** Issue “Enforce declared agent review policy”; branch `feat--agent-review-policy`; PR to `develop`.

**Files:**
- Create: `src/feishu_task_cli/application/reviewer.py`
- Create: `src/feishu_task_cli/application/policy_engine.py`
- Create: `src/feishu_task_cli/cli.py`
- Create: `src/feishu_task_cli/__main__.py`
- Test: `tests/unit/application/test_policy_engine.py`
- Test: `tests/contract/test_cli_review.py`

**Interfaces:**
- Consumes: `PlanV1`, `ReviewV1`, `PolicyV1`, `CheckedFact`.
- Produces: `build_review(plan, reviewer_id, intended_executor_id, verdict, checked_facts, ...) -> ReviewV1`; `validate_execution_review(plan, review, policy, executor_id) -> DeclaredReviewRelationship`; Typer commands `review` and `schema show`.

- [ ] **Step 1: Create and verify the Issue and task branch**

Use `gh issue create`, re-read it, and branch from current `develop` only.

- [ ] **Step 2: Write failing policy tests**

```python
def test_same_declared_identity_derives_self_reviewed() -> None:
    result = validate_execution_review(plan, review(reviewer_id="agent-a"), neutral_policy, "agent-a")
    assert result == DeclaredReviewRelationship.SELF_REVIEWED


def test_independent_policy_rejects_same_declared_identity() -> None:
    with pytest.raises(PolicyRejectedError, match="different declared identities"):
        validate_execution_review(plan, review(reviewer_id="agent-a"), strict_policy, "agent-a")
```

Also test missing executor ID, intended-executor mismatch, expired Review, changed Plan hash, unknown checked fact, rejected verdict, and missing action-specific checked facts.

- [ ] **Step 3: Verify red, implement minimally, then verify green**

Run focused tests before and after implementation. The neutral policy requires an approved unexpired Review; strict policy additionally requires different declared IDs and an action-specific checked-fact set. No code accepts a caller-supplied relationship mode.

- [ ] **Step 4: Add JSON stdin/stdout contract tests**

Tests use Typer's `CliRunner` to prove `review --plan -` consumes stdin, writes one JSON artifact to stdout, keeps diagnostics on stderr, and `--output review.json` writes atomically while stdout returns a JSON result envelope.

- [ ] **Step 5: Run all local gates and complete the PR flow**

Run full tests, Ruff, mypy, build, gitleaks, and diff check. Commit `feat: enforce declared agent review policy`; push, open/re-read PR, wait for checks, squash merge to `develop`, and re-read merge and Issue state without deleting the branch.

---

### Task 4: Single-consumption execution journal and active-process locking

**Issue/branch:** Issue “Prevent replay and concurrent execution”; branch `feat--execution-journal`; PR to `develop`.

**Files:**
- Create: `src/feishu_task_cli/journal/store.py`
- Create: `src/feishu_task_cli/journal/locking.py`
- Test: `tests/unit/journal/test_store.py`
- Test: `tests/integration/test_execution_locking.py`

**Interfaces:**
- Produces: `ExecutionState`, `ExecutionJournal.execution(plan_hash) -> ContextManager[ExecutionAttempt]`, `ExecutionAttempt.complete(state) -> None`, `ExecutionJournal.status(plan_hash) -> JournalRecord | None`, and `plan_execution_lock(plan_hash) -> ContextManager[None]`.
- Contract: the exclusive OS lock is held from claim through caller mutation/readback and terminal update.

- [ ] **Step 1: Create Issue/branch and write failing state tests**

```python
def test_verified_plan_cannot_be_claimed_twice(journal: ExecutionJournal) -> None:
    with journal.execution("a" * 64) as attempt:
        attempt.complete(ExecutionState.VERIFIED)
    with pytest.raises(ReplayBlockedError):
        with journal.execution("a" * 64):
            pass
```

- [ ] **Step 2: Write the failing active-executor concurrency test**

Use two spawned processes and synchronization events. Process A acquires the lock and waits. Process B attempts the same `plan_hash` and must return `execution_in_progress`, never call the mutation spy, and never change A's `started` state. Release A and assert it records `verified`.

- [ ] **Step 3: Implement hash-only atomic journal storage**

Use `platformdirs.user_state_path("feishu-task-cli")`, JSON records containing only plan hash, state, attempt ID, tool version, and timestamps, temp-file plus `os.replace` updates, and `filelock.FileLock` per plan hash. Reject corrupt or permission-unsafe journal paths.

- [ ] **Step 4: Implement orphaned-started handling**

Only a process that successfully acquires the OS lock may convert an existing `started` to `unknown`. It must then raise `UnknownExecutionError`; it must not call the mutation callback.

- [ ] **Step 5: Run focused failure matrix and full gate**

Run: `uv run pytest tests/unit/journal tests/integration/test_execution_locking.py -v`.

Expected: replay, live concurrency, crash residue, corrupt journal, and terminal-state tests all pass.

- [ ] **Step 6: Complete Issue/PR workflow**

Commit `feat: prevent plan replay and concurrent execution`; push, open/re-read PR, verify checks, squash merge into `develop`, and re-read all remote state without deleting the branch.

---

### Task 5: Secure OAuth, AuthContext, and redacted Feishu transport

**Issue/branch:** Issue “Add secure Feishu auth context”; branch `feat--secure-auth-context`; PR to `develop`.

**Files:**
- Create: `src/feishu_task_cli/auth/config.py`
- Create: `src/feishu_task_cli/auth/context.py`
- Create: `src/feishu_task_cli/auth/keyring_store.py`
- Create: `src/feishu_task_cli/auth/oauth.py`
- Create: `src/feishu_task_cli/feishu/client.py`
- Test: `tests/unit/auth/test_config.py`
- Test: `tests/unit/auth/test_context.py`
- Test: `tests/unit/auth/test_keyring_store.py`
- Test: `tests/integration/test_oauth.py`
- Test: `tests/integration/test_redaction.py`

**Interfaces:**
- Produces: `Settings.load(...)`, `TokenStore`, `OAuthClient`, `build_auth_context(api_origin, app_id, tenant_id, account_id, actor_id) -> AuthContext`, `resolve_auth_context(client) -> AuthContext`, and `FeishuClient.request(...)`.
- Secrets accepted only from keyring, process environment, or explicit current-user `0600` config.

- [ ] **Step 1: Create Issue/branch and write secret-boundary tests**

Tests prove there are no `--app-secret` or `--access-token` CLI options, `0644` secret config fails, environment secrets never appear in exceptions, and Authorization headers are redacted from request/response logs.

- [ ] **Step 2: Implement secure configuration and keyring storage**

Separate non-secret settings from secret resolution. Validate regular-file ownership and exact `0600` mode before reading an app secret. Keyring service name is `feishu-task-cli`; usernames are safe app/account fingerprints rather than profiles.

- [ ] **Step 3: Write failing AuthContext tests**

```python
def test_different_actor_changes_context() -> None:
    first = build_auth_context(api_origin=ORIGIN, app_id="cli_a", tenant_id="t", account_id="a", actor_id="ou_1")
    second = build_auth_context(api_origin=ORIGIN, app_id="cli_a", tenant_id="t", account_id="a", actor_id="ou_2")
    assert first.actor_fingerprint != second.actor_fingerprint
    assert first != second
```

Also prove domain separation prevents identical raw strings in different fields from sharing fingerprints and safe display values do not expose raw identifiers.

- [ ] **Step 4: Implement OAuth setup and AuthContext resolution**

Implement explicit localhost callback login, token refresh, status, and logout. `auth status` returns safe app/tenant/account/actor fingerprints. Headless execution may use `FEISHU_USER_ACCESS_TOKEN`; OAuth setup may open a browser, but core commands never prompt.

- [ ] **Step 5: Implement redacted HTTP transport and bounded idempotent retry**

Use `httpx.Client`, structured typed API errors, request IDs only when safe, bounded retry only for GET/token refresh, and one-attempt mutation transport. Redact secret-shaped strings recursively from JSON, text, exceptions, and debug hooks.

- [ ] **Step 6: Run tests/gates and complete PR workflow**

Run all auth/redaction tests, full suite, quality, build, gitleaks, and privacy scan. Commit `feat: add secure Feishu auth context`; push, open/re-read PR, verify checks, squash merge to `develop`, and re-read remote state.

---

### Task 6: Task planning, guarded execution, and readback reconciliation

**Issue/branch:** Issue “Implement verified Task mutations”; branch `feat--verified-task-mutations`; PR to `develop`.

**Files:**
- Create: `src/feishu_task_cli/feishu/tasks.py`
- Create: `src/feishu_task_cli/application/planner.py`
- Create: `src/feishu_task_cli/application/reconcile.py`
- Create: `src/feishu_task_cli/application/executor.py`
- Test: `tests/unit/application/test_planner.py`
- Test: `tests/unit/application/test_reconcile.py`
- Test: `tests/integration/test_task_get.py`
- Test: `tests/integration/test_task_mutations.py`
- Test: `tests/integration/test_execution_failures.py`

**Interfaces:**
- Produces: `TaskGateway.get/create/update/assign/complete`, `Planner.create/update/assign/complete`, `reconcile(requested, observed)`, and `Executor.execute(plan, review, policy, executor_id) -> ReceiptV1`.

- [ ] **Step 1: Create Issue/branch and write failing Plan tests**

Tests prove typed assignees accept only `open_id:`, `user_id:`, or `union_id:`; names fail closed; update/assign/complete Plans include observed-before and precondition fingerprint; create Plans bind AuthContext and have no remote precondition.

- [ ] **Step 2: Implement the narrow Task gateway and planner**

Map only get/create/update/assign/complete endpoints. Keep raw Feishu payloads inside the adapter. Planner normalizes timestamps and fields, obtains AuthContext, reads existing Tasks where required, and hashes the completed Plan.

- [ ] **Step 3: Write failing executor safety tests**

Cover tampered Plan, changed Review, AuthContext mismatch, precondition drift, rejected policy, replay, live concurrent execution, definitive API failure, mutation timeout after send, readback mismatch, and complete verified flow.

- [ ] **Step 4: Implement guarded execution in the specified order**

The exact order is artifact validation → declared review relationship → token/AuthContext → existing-task precondition GET → full-duration plan lock/journal claim → single mutation → returned-GUID GET → reconciliation → terminal journal update → Receipt. Do not catch and convert `BaseException`; preserve interrupts while leaving `started` for orphan detection.

- [ ] **Step 5: Verify outcome mapping**

Assert `verified` exits 0, policy rejection exits 4, definitive API error exits 5, ambiguous mutation exits 6 with journal `unknown`, and readback mismatch exits 7 with `partial`. A second execute never sends another mutation.

- [ ] **Step 6: Run full gate and complete PR workflow**

Commit `feat: add verified task mutations`; push, open/re-read PR, verify required jobs and mergeability, squash merge to `develop`, and re-read Issue/PR/branch state.

---

### Task 7: Safe user presentation and complete Agent CLI

**Issue/branch:** Issue “Add safe Agent result presentation”; branch `feat--agent-presentation`; PR to `develop`.

**Files:**
- Create: `src/feishu_task_cli/presentation/markdown.py`
- Create: `src/feishu_task_cli/presentation/next_actions.py`
- Modify: `src/feishu_task_cli/cli.py`
- Test: `tests/golden/receipt-verified.md`
- Test: `tests/golden/receipt-partial.md`
- Test: `tests/contract/test_cli_end_to_end.py`
- Test: `tests/unit/presentation/test_markdown.py`

**Interfaces:**
- Produces: `render_markdown(artifact) -> str`, typed next-action mapping, and complete commands `auth`, `task get`, `plan`, `review`, `execute`, `execution status`, `render`, and `schema show`.

- [ ] **Step 1: Create Issue/branch and write malicious-content renderer tests**

Fixtures include task text such as `<script>`, Markdown links to attacker domains, control characters, and “ignore previous instructions”. Tests assert raw HTML is escaped, arbitrary links are not clickable, control characters are removed, content is length-bounded, and all business text is labelled untrusted data.

- [ ] **Step 2: Implement pure Markdown rendering and typed next actions**

Renderer has no network imports. Next actions come only from a versioned mapping of outcome/error code, for example `unknown -> investigate_remote_state_without_replay` and `partial -> inspect_mismatched_fields`.

- [ ] **Step 3: Write and implement end-to-end CLI contract tests**

Use mocked auth and Task gateway. Prove an Agent can plan, review, execute, read back, receive JSON, and render Markdown without prompts. Prove `--output path` leaves a JSON result envelope on stdout and all diagnostics on stderr.

- [ ] **Step 4: Run full gate and complete PR workflow**

Commit `feat: add safe agent result presentation`; push, open/re-read PR, verify required checks, squash merge into `develop`, and re-read remote state.

---

### Task 8: Documentation, security hardening, and v0.1.0 release

**Issue/branch:** Issue “Prepare v0.1.0 public release”; branch `release--v0-1-0` from `develop`; documentation/hardening PR to `develop`, followed by release PR `develop` → `main`.

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `src/feishu_task_cli/__init__.py`
- Modify: `pyproject.toml`
- Create: `docs/architecture.md`
- Create: `docs/agent-protocol.md`
- Create: `docs/behavior-inventory.md`
- Create: `docs/release-process.md`
- Create: `.github/workflows/release.yml`
- Test: `tests/contract/test_public_boundary.py`
- Test: `tests/contract/test_release_metadata.py`

**Interfaces:**
- Produces: public documentation, provenance evidence, version `0.1.0`, release workflow, and GitHub Release `v0.1.0`.

- [ ] **Step 1: Create and verify the release-preparation Issue and branch**

Issue acceptance criteria include all design requirements, no live-tenant claim, clean-room scan, independent validation, package smoke, release PR, annotated tag, and GitHub release notes.

- [ ] **Step 2: Write failing public-boundary and metadata tests**

Scan tracked content and Git history for personal absolute paths, internal profile names, token/header patterns, real-looking identifiers, private business fixtures, and inconsistent versions. Assert distribution metadata, `__version__`, changelog, and intended tag are all `0.1.0`.

- [ ] **Step 3: Complete public documentation and behavior inventory**

README begins with Agent-native examples and explicitly distinguishes Plan from executed Task. Document declared identity limits, single-host journal guarantees, OAuth setup, no-replay unknown recovery, typed assignees, JSON/Markdown handoff, Issue/PR workflow, and no default profiles. Behavior inventory cites only public Feishu API documentation and abstract behavior names; it contains no private path or code comparison.

- [ ] **Step 4: Add the release workflow**

Trigger only on tags matching `v*`. Verify tag is annotated, tag commit equals `origin/main` HEAD, version equals tag, full CI passes, build wheel/sdist, run `twine check`, generate artifact attestations where available, and create the GitHub Release. Publishing to PyPI remains environment-gated and is skipped unless trusted publishing is configured.

- [ ] **Step 5: Run the complete local release gate**

Run:

```bash
uv sync --extra test
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest -v --cov=feishu_task_cli --cov-fail-under=90
uv build
uv run twine check dist/*
gitleaks git --redact --no-banner
uv run python scripts/privacy_scan.py --history
git diff --check
```

Expected: every gate passes, coverage is at least 90%, build artifacts validate, and scans find no forbidden tracked content.

- [ ] **Step 6: Obtain independent validation-only review**

Reviewer checks goal, Agent UX, owner boundaries, clean-room evidence, replay/AuthContext/review-policy/TOCTOU safety, secret handling, CI, GitHub history, branch rules, failure modes, docs accuracy, and whether claims can be over-applied. Resolve every P0/P1 through the same Issue/branch/PR flow before release.

- [ ] **Step 7: Merge release-preparation PR into `develop`**

Commit `release: prepare v0.1.0`; push; open and re-read PR; verify all required checks and mergeability; squash merge into `develop`; re-read PR, Issue, and `develop`; retain the remote branch.

- [ ] **Step 8: Open, verify, and merge `develop` to `main`**

Open a PR with head `develop`, base `main`, release notes, included Issues/PRs, validation verdict, and exact verification commands. Re-read it, wait for all checks, verify mergeability, then squash merge. Re-read the merged PR and query `main` SHA.

- [ ] **Step 9: Create and verify annotated tag and GitHub Release**

Run:

```bash
git fetch origin main develop --tags
git switch main
git pull --ff-only origin main
git tag -a v0.1.0 -m "feishu-task-cli v0.1.0"
test "$(git rev-list -n 1 v0.1.0)" = "$(git rev-parse origin/main)"
git push origin v0.1.0
GH_PROMPT_DISABLED=1 gh release view v0.1.0 --repo Alex-ghost599/feishu-task-cli
GH_PROMPT_DISABLED=1 gh run list --branch v0.1.0 --limit 10 --repo Alex-ghost599/feishu-task-cli
```

Expected: annotated tag targets exact `main` HEAD, release workflow passes, and the GitHub Release is public with correct assets and notes.

- [ ] **Step 10: Final repository and task-control verification**

Verify repository visibility/default branch, `main` and `develop` rulesets, open Issues/PRs, all retained task branches, release/tag equality, CI history, secret scanning settings, package install smoke, task note, board card, and `bash 10-Agent-Ops/scripts/check-task-ids.sh`. Record any absent GitHub feature as a bounded residual risk rather than claiming it is active.

## Plan self-review checklist

- [x] Every design section maps to at least one task above.
- [x] All product behavior begins with a failing test.
- [x] Each remote write is followed by a readback.
- [x] No task deletes a remote branch.
- [x] Bootstrap is the only direct-main exception and contains CI before first public push.
- [x] Every post-bootstrap change enters `develop` through Issue/branch/PR.
- [x] Release is `develop` → `main` → annotated tag from exact merge commit.
- [x] Plan contains no real credentials, profiles, account IDs, Task IDs, tenant IDs, personal paths, or private source content.
