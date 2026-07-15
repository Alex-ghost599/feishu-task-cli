# feishu-task-cli Design

Date: 2026-07-15

## 1. Product intent

`feishu-task-cli` is an agent-native CLI for safely creating, updating, assigning, completing, and verifying Feishu Tasks. Its primary consumers are coding agents, workflow agents, and orchestration systems. Human users receive concise plans and receipts rendered by those agents; they are not expected to operate an interactive confirmation flow.

The product wedge is a verifiable write protocol:

1. a planner agent creates a deterministic plan;
2. a reviewer agent records a machine-readable verdict;
3. an executor validates that review against policy and performs the write;
4. the CLI reads the returned task back and reconciles requested versus observed state;
5. agents can render the receipt as a user-facing Markdown summary.

The repository and Python distribution are named `feishu-task-cli`. The executable is `feishu-task`. The project uses the MIT license.

## 2. Goals

- Provide stable JSON interfaces suitable for agents and automation.
- Make every mutation traceable through Plan, Review, and Receipt artifacts.
- Fail closed on ambiguous assignees, modified plans, missing review, expired review, and unresolved validation errors.
- Distinguish self-review from independent review without overstating identity guarantees.
- Verify successful writes through API readback using the returned Task GUID.
- Make results easy for agents to present to users without exposing credentials or raw HTTP traffic.
- Ship as a small, well-tested public repository with no internal profiles, identifiers, paths, or private workflow defaults.

## 3. Non-goals for v0.1

- Tasklist, section, custom-field, subtask, document, calendar, Base, or messaging management.
- Fuzzy person lookup or assignment by display name.
- Multiple named authentication profiles.
- A general Feishu API wrapper or SDK replacement.
- Cryptographic proof that reviewer and executor identities belong to different real agents.
- A hosted service, GUI, MCP server, or long-running daemon.
- Persistence of business audit logs by default.

## 4. Architecture

The Python package is `feishu_task_cli` and targets Python 3.11 or later.

### 4.1 `cli`

Typer commands parse arguments, accept JSON from stdin, select output format, and map domain errors to stable exit codes. Machine commands write exactly one JSON document to stdout. Diagnostics go to stderr.

### 4.2 `application`

Application services build plans, validate reviews and policies, execute mutations, perform readback, reconcile state, and build receipts. This layer depends on domain interfaces rather than HTTP details.

### 4.3 `domain`

Pydantic models define versioned `Plan`, `Review`, `Policy`, and `Receipt` schemas, task inputs, assignee identifiers, reconciliation results, and typed errors. Canonical JSON serialization is centralized here so hashes remain stable.

### 4.4 `feishu`

An `httpx` adapter implements Feishu OAuth and the narrowly required Task endpoints. Request and response payloads are converted at the adapter boundary. The rest of the application does not depend on raw Feishu payloads.

### 4.5 `security`

This layer resolves credentials, redacts secrets, enforces review policy, calculates artifact hashes, bounds artifact lifetime, and rejects unsafe output or configuration fallbacks.

### 4.6 `presentation`

A pure renderer converts Plan, Review, and Receipt JSON into concise Markdown suitable for an agent to show a user. Rendering never triggers network or mutation operations.

### 4.7 `journal`

A local execution journal gives each `plan_hash` single-consumption semantics. It stores only hashes, timestamps, tool version, and `started`, `unknown`, `verified`, or `failed` state; it never stores task titles, descriptions, assignee identifiers, tokens, or raw API payloads. An OS-level exclusive lock for the `plan_hash` is held from claim through mutation, readback, and terminal journal update. A competing process that cannot acquire the lock returns `execution_in_progress` without submitting a mutation or changing journal state.

## 5. Command surface

Authentication commands:

```text
feishu-task auth login
feishu-task auth status
feishu-task auth logout
```

Read command:

```text
feishu-task task get --task-guid <guid>
```

Planning commands:

```text
feishu-task plan create --summary <text> [task fields]
feishu-task plan update --task-guid <guid> [task fields]
feishu-task plan assign --task-guid <guid> --assignee <type:value>
feishu-task plan complete --task-guid <guid>
```

Review and execution:

```text
feishu-task review --plan <path|-> --reviewer-id <id> --verdict <approve|reject> [review fields]
feishu-task execute --plan <path|-> --review <path> --executor-id <id> [--policy <path>]
feishu-task execution status --plan-hash <sha256>
```

Presentation:

```text
feishu-task render --artifact <path|-> --format markdown
feishu-task schema show --artifact <plan|review|policy|receipt>
```

Every artifact-producing command supports `--output <path|->`. `-` means stdout or stdin as appropriate. With `--output -`, stdout is the artifact JSON. With a file path, the artifact is written atomically and stdout is a JSON result envelope containing the path, artifact type, and artifact hash. Human-readable tables are not part of the machine contract in v0.1.

## 6. Artifact protocol

All artifacts include:

- `schema_version`;
- `artifact_type`;
- UTC `created_at`;
- a tool version;
- canonical content that excludes its own hash field.

Artifact hashes use SHA-256 over UTF-8 JSON Canonicalization Scheme (RFC 8785) bytes. Hash fields are excluded from their own canonical input. Domain schemas use RFC 3339 UTC timestamps and integers rather than floating-point values. Unknown fields are rejected for the current schema version. The repository includes golden canonicalization and hash vectors to prevent cross-version drift.

### 6.1 Plan

A Plan contains a unique `plan_id`, action, normalized target, requested fields, assignees, validation findings, required scopes, expected `AuthContext`, expiry, and `plan_hash`. It contains no access token, app secret, Authorization header, or raw HTTP headers.

`AuthContext` contains the API origin plus SHA-256 fingerprints of the app ID, tenant, authenticated account, and acting user. Fingerprints are domain-separated and truncated only for display, while the full hash participates in `plan_hash`. `auth status` exposes these safe fingerprints so a planner agent can choose and display the intended context without using a named profile.

Plans for update, assign, and complete also contain `observed_before` and a canonical precondition fingerprint derived from the current Task state. Planning these actions therefore performs a read. Immediately before mutation, execute reads the Task again and fails closed if the precondition fingerprint changed. Create Plans have no remote Task precondition.

Assignees use exact typed identifiers:

```text
open_id:ou_xxx
user_id:xxx
union_id:on_xxx
```

Display names are allowed only as non-authoritative presentation labels supplied by the caller. They are never used to choose the assignee.

### 6.2 Review

A Review binds to `plan_hash` and contains reviewer ID, optional intended executor ID, verdict, checked facts, warnings, reasons, creation time, expiry, and `review_hash`. It does not allow the caller to assert a review mode.

`execute --executor-id` supplies the declared executor identity. The executor derives `declared_self_reviewed` or `declared_independently_reviewed` by comparing reviewer and executor IDs, and verifies an intended executor when the Review contains one. Agent identity remains self-asserted in v0.1, and documentation must not describe a declared identity relationship as cryptographically verified.

Checked facts are a versioned enum with defined semantics: `action_checked`, `target_identity_checked`, `assignees_checked`, `schedule_checked`, `auth_context_checked`, and `precondition_checked`. A policy selects the required set per action. Unknown values and missing required facts fail closed.

### 6.3 Policy

Policy is an optional local JSON or YAML document. With no file supplied, a built-in neutral policy requires an approved, unexpired Review and permits either review mode. It contains no tenant, member, task, or profile defaults.

A stricter policy may require:

- independent review;
- different declared reviewer and executor IDs;
- a maximum plan or review age;
- approved actions;
- required checked facts;
- rejection of warnings;
- an allowed assignee identifier type.

### 6.4 Receipt

A Receipt contains action, Plan and Review hashes, the derived declared review relationship, declared agent identities, AuthContext fingerprints, task GUID, requested state, observed state, mismatches, omitted fields, API request ID when safe, timestamps, and an outcome:

- `verified`: write succeeded and required fields match readback;
- `partial`: write returned success but required fields do not fully match;
- `unknown`: transport failure leaves mutation outcome uncertain;
- `failed`: no successful mutation is known;
- `rejected`: policy or review blocked execution.

A Plan that has not been executed is not a Receipt and does not use a success outcome.

## 7. Execution and reconciliation

Execution follows this fixed sequence:

1. parse and validate Plan, Review, and Policy;
2. recalculate canonical hashes;
3. verify expiry, verdict, checked facts, declared identity policy, and action policy;
4. acquire or refresh the user access token and resolve actual AuthContext;
5. require exact equality between actual and planned AuthContext;
6. for existing Tasks, read current state and require the precondition fingerprint to match;
7. atomically claim the unused `plan_hash` in the local execution journal as `started`;
8. submit one mutation request;
9. capture the returned Task GUID and safe request metadata;
10. read the Task back using that GUID;
11. normalize the observed response;
12. reconcile all required requested fields;
13. atomically record the terminal journal state and emit a redacted Receipt.

Each Plan is single-consumption. A Plan already journaled as `started`, `unknown`, `verified`, or `failed` is rejected on a later execute call; a new Plan is required for any later attempt. An active executor holds the OS lock, so another invocation reports `execution_in_progress` and cannot reinterpret `started`. If the executor crashes, the OS releases the lock; only a later lock holder may then promote the orphaned `started` state to `unknown` and block replay. The journal provides a single-host safety boundary only and is not described as distributed exactly-once execution.

Read operations and token refresh may use bounded retry with exponential backoff. Mutating requests are never blindly retried after an ambiguous transport failure. When the server may have accepted a mutation but no definitive response was received, the CLI records and emits `unknown` with a non-zero exit code. Recovery is investigation-only in v0.1: an agent may inspect journal status and query Feishu, but cannot replay the same Plan. Remote idempotency is not assumed unless a future endpoint-specific implementation proves and tests a documented idempotency contract.

## 8. Authentication and configuration

The primary flow uses Feishu user OAuth with a localhost callback and refreshable user access token. `auth login` is an explicit one-time setup operation that may require a human to complete browser authorization; plan, review, execute, readback, and render remain non-interactive. The app ID and app secret must be supplied explicitly by environment variables or a user-selected configuration file.

Tokens are stored in the operating-system keyring. If keyring storage is unavailable, login fails with actionable instructions; the CLI does not silently write plaintext tokens. Headless agents may inject `FEISHU_USER_ACCESS_TOKEN` explicitly for the current process. Secrets are never accepted as command-line flags. An explicit configuration file containing an app secret must be a regular file owned by the current user with mode `0600`; broader permissions fail closed. Exception messages, debug logs, and HTTP tracing pass through the same redaction layer.

Configuration precedence is:

1. command flags;
2. environment variables;
3. explicitly selected config file;
4. non-sensitive protocol defaults such as API base URL and timeout.

There is no implicit user config profile, active account, tenant, tasklist, member, or task target.

## 9. Agent and user interaction

JSON is the stable agent contract. Agents can pass artifacts through files or stdin/stdout without parsing terminal prose. Each artifact has a JSON Schema available through `schema show` and committed under `schemas/`.

The Markdown renderer produces short sections:

- intended action;
- review verdict and whether it was self or independent;
- execution outcome;
- task identifier and link when derivable without private defaults;
- requested versus observed fields;
- warnings, mismatches, and unknowns;
- a safe next action selected from a versioned mapping keyed by outcome and typed error code.

Task titles, descriptions, remote errors, and other business-controlled text are untrusted data. The renderer strips disallowed control characters, escapes Markdown and raw HTML, limits length, and places untrusted values in clearly labelled quoted or code-formatted data blocks. It does not emit arbitrary clickable links from untrusted fields. Agents are instructed to treat rendered business content as data rather than instructions.

The renderer never calls the API, infers missing success, invents a next action, or hides `partial` and `unknown` outcomes. Agents should paste or summarize this Markdown to users instead of exposing raw debug output.

## 10. Errors and exit codes

- `0`: requested read, plan, review, render, or verified execution completed successfully;
- `2`: invalid input or schema;
- `3`: configuration or authentication failure;
- `4`: review or policy rejection;
- `5`: Feishu returned a definitive API failure;
- `6`: execution outcome is unknown;
- `7`: readback completed but reconciliation is partial;
- `8`: artifact integrity or version failure.

Errors use a stable JSON envelope when JSON output is requested. It includes a code, category, safe message, retryability, and redacted details.

## 11. Privacy, provenance, and clean-room boundary

The implementation may use the private predecessor only to identify proven behaviors and test scenarios. It must not copy that repository wholesale, preserve its Git history, disclose its filesystem location, or import its profile/config files.

Before publication, automated and manual scans must check for:

- app IDs and secrets;
- tokens and Authorization headers;
- real open IDs, union IDs, user IDs, Task GUIDs, tasklist GUIDs, and tenant keys;
- internal profile names and absolute personal paths;
- private business terms in fixtures and examples.

Fixtures use clearly synthetic identifiers. The public repository contains a provenance note explaining clean-room reconstruction without mentioning private values.

## 12. Testing strategy

Development follows test-driven development. Tests are grouped as:

- domain unit tests for canonical serialization, hashing, expiry, policies, and reconciliation;
- CLI contract tests for stdin/stdout, schemas, exit codes, and stderr separation;
- HTTP adapter tests using mocked Feishu responses;
- failure tests for token expiry, ambiguous mutation transport failures, API rejection, partial readback, and redaction;
- property-style cases for artifact tampering and secret-shaped strings;
- replay, process-crash, request-delivered/response-lost, and journal recovery tests;
- an active-executor concurrency test proving a second process returns `execution_in_progress`, submits no mutation, preserves the first process state, and allows the first process to write its terminal state;
- AuthContext mismatch and precondition-change rejection tests;
- self-review, different declared identities, intended-executor mismatch, and missing-executor tests;
- build/install smoke tests for the `feishu-task` entry point;
- renderer golden tests for concise, non-misleading Markdown, including prompt-like and malicious-link fixtures.

No live token or tenant is used in public CI. A documented, opt-in local live smoke procedure may be run by maintainers before releases and must not save credentials or tenant data as artifacts.

## 13. Continuous integration and security

Every pushed branch and pull request runs GitHub Actions jobs for:

- Ruff format and lint;
- mypy strict-enough type checking for package code;
- pytest with coverage threshold;
- package build, metadata validation, and clean-environment install smoke;
- JSON Schema validation and CLI contract tests;
- gitleaks full-history scan;
- dependency review on pull requests;
- `pip-audit` for published dependency vulnerabilities;
- CodeQL for Python;
- provenance/privacy pattern scan over tracked files and fixtures.

The gitleaks job checks out full history with `fetch-depth: 0`. Workflow permissions default to read-only and are elevated only per job when required. Actions are pinned to immutable commit SHAs and updated through Dependabot, whose pull requests target `develop`. Release publishing uses GitHub trusted publishing or an environment-gated workflow; no long-lived PyPI token is stored.

## 14. GitHub development workflow

The public repository owner is `Alex-ghost599`.

The empty repository requires one documented bootstrap exception: a direct initial commit on `main` containing the approved design, MIT license, governance files, and a minimal pinned GitHub Actions workflow that runs formatting/lint, tests if present, build validation, and full-history gitleaks. No product implementation enters through this exception. This local root commit may be amended before its first remote push so the first public push already contains and triggers that workflow; after the first push it is immutable.

After bootstrap:

- `main` contains released states only;
- `develop` is the long-lived integration branch;
- work starts from an Issue and a short branch from `develop`;
- branches use `<kind>--<slug>`, for example `feat--agent-plan-protocol`;
- every product or workflow change enters `develop` through a pull request;
- merges use squash merge;
- remote branches are retained unless the user explicitly requests deletion;
- bugs start with an Issue, then `fix--<slug>`, tests reproducing the defect, and a PR to `develop`;
- a coherent release uses a PR from `develop` to `main`;
- an annotated semantic version tag is created from the merged `main` commit only after required checks pass, and automation verifies the tag commit equals the release PR merge commit at `main` HEAD;
- release notes link the included Issues and PRs.

Branch protections or rulesets on both `main` and `develop` require pull requests, required CI checks, resolved conversations, and no force pushes or deletions. `main` additionally restricts direct pushes after bootstrap. Self-authored PRs cannot satisfy an approval requirement, so required approvals are not configured unless an eligible GitHub reviewer exists; validation-only agent review remains documented evidence rather than a fake GitHub approval.

## 15. Initial delivery slices

The first release is `v0.1.0` and is implemented through issue-sized PRs:

1. repository governance, packaging, baseline CI, security scans, and schemas;
2. canonical Plan/Review/Policy domain models and policy engine;
3. OAuth/keyring and redacted Feishu client;
4. Task get/create/update/assign/complete planning and execution;
5. readback reconciliation and Receipt protocol;
6. Markdown renderer, agent integration examples, documentation, and release checks.

Each slice has behavior tests before implementation and must merge into `develop`. `v0.1.0` is released only after the complete suite, privacy scan, independent validation review, and `develop` to `main` release PR pass.

## 16. Repository documentation

The repository ships with:

- README with agent-first examples and accurate maturity labels;
- LICENSE (MIT);
- CONTRIBUTING with Issue/branch/PR/release rules;
- SECURITY with private vulnerability reporting instructions;
- CODE_OF_CONDUCT;
- CODEOWNERS;
- architecture and artifact protocol documentation;
- JSON Schemas and synthetic examples;
- changelog and release process;
- provenance/privacy checklist;
- a behavior inventory that maps public API documentation and abstract test intent without private-source code, fixtures, comments, naming, or error text;
- issue and pull-request templates.

Every initial implementation PR includes a clean-room declaration referencing the behavior inventory. README examples must never imply that a Plan is an executed Task or that a declared agent identity relationship is cryptographically verified.

## 17. Acceptance criteria

- A fresh installation exposes `feishu-task` and validates all committed schemas.
- An agent can generate, review, execute, reconcile, and render a task mutation without interactive prompts.
- Tampered, expired, rejected, ambiguous, or policy-incompatible artifacts fail closed with stable JSON errors.
- Replayed or concurrently executed Plans, changed Task preconditions, and mismatched AuthContext fingerprints fail closed before a second mutation.
- Verified, partial, unknown, failed, and rejected outcomes are distinguishable in both JSON and Markdown.
- No real profile, credential, account, member, tenant, task, tasklist, or personal path exists in tracked content or Git history.
- CI and branch rules are active and verified on both long-lived branches.
- All implementation changes after bootstrap are traceable to Issues and PRs into `develop`.
- `v0.1.0` is merged from `develop` to `main`, tagged from the merged main commit, and accompanied by release notes.
