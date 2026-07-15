# feishu-task-cli

An Agent-native CLI for review-gated Feishu Task writes, API readback, and safe user-facing
results. JSON artifacts are the stable Agent contract; the Markdown renderer turns a Receipt
into a concise handoff for a user.

> **Safety boundary:** A Plan is not an executed Task. Only a Receipt records an execution
> outcome, and only `verified` means required fields matched API readback. This v0.1.2 release
> candidate was validated with synthetic mocked responses and has **no live-tenant validation**
> claim.

## Agent workflow

Install the tagged source with Python 3.11+ (PyPI publishing is optional and disabled by default),
then configure one explicit Feishu app/account context:

```bash
uv tool install \
  "feishu-task-cli @ git+https://github.com/Alex-ghost599/feishu-task-cli@v0.1.2"
```

Before login, configure the Feishu application in the developer console:

1. Add the exact redirect URI `http://127.0.0.1:8765/callback` to the application's redirect URL
   allowlist. This stable default is what the local listener, authorization request, and token
   exchange all use.
2. Enable the user permissions `task:task:read` and `task:task:write` (plus the OAuth-provided
   offline access scope).
3. Publish the Feishu application/version and make it available to the intended test users.

If that port is unavailable, set `FEISHU_OAUTH_REDIRECT_URI` (or `oauth_redirect_uri` in the
explicit private config) to another exact `http://127.0.0.1:PORT/callback` or
`http://[::1]:PORT/callback`, then register that exact URI in Feishu before login. The CLI rejects
other schemes, hosts, missing/zero ports, paths, user info, queries, and fragments before browser
or network activity.

The CLI has no default profiles, tenant, account, member, Tasklist, assignee, or Task target.

```bash
# One-time, explicitly invoked OAuth setup; this is the only flow that may open a browser.
export FEISHU_APP_ID="$APP_ID"
export FEISHU_APP_SECRET="$APP_SECRET"
export FEISHU_ACCOUNT_ID="$ACCOUNT_ID"
feishu-task auth login

# Agent A creates an immutable intent artifact. This does not write a Task.
feishu-task plan create \
  --tasklist-guid "$TASKLIST_GUID" \
  --summary "Prepare synthetic release notes" \
  --assignee "open_id:$ASSIGNEE_OPEN_ID" \
  --output plan.json

# A reviewing Agent records its declared checks and intended executor.
feishu-task review \
  --plan plan.json \
  --reviewer-id reviewer-agent \
  --intended-executor-id executor-agent \
  --verdict approved \
  --checked-fact action_checked \
  --checked-fact target_identity_checked \
  --checked-fact assignees_checked \
  --checked-fact auth_context_checked \
  --output review.json

# The executor consumes the Plan once, writes once, reads back, and emits a Receipt.
feishu-task execute \
  --plan plan.json \
  --review review.json \
  --executor-id executor-agent \
  --output receipt.json

# Render safe Markdown for the Agent to show or summarize to the user.
feishu-task render --artifact receipt.json --format markdown --output result.md
```

Use `feishu-task auth login --no-browser` when an Agent must not open a browser itself. The CLI
prints the exact authorization URL to stderr for an authorized user to open, while the same
registered loopback callback listener waits with its normal state and timeout checks.

Plan, Review, Policy, and Receipt artifacts are versioned and hash-bound. A reviewer/executor
relationship is a **declared identity** relationship, not a cryptographically authenticated
Agent identity. When reviewer and executor IDs match, the Receipt says `declared_self_reviewed`;
production policy can require different declared IDs.

Typed assignee values use `open_id:`, `user_id:`, or `union_id:`. A Plan cannot mix identifier
types. Use `feishu-task schema show --artifact plan` (or `review`, `policy`, `receipt`) when an
Agent needs the current JSON Schema.

## Outcomes and recovery

- `verified`: the mutation response was followed by readback and required fields matched.
- `partial`: readback succeeded but fields were missing or different; do not report success.
- `unknown`: transport failed after submission may have occurred; investigate, never replay the
  same Plan.
- `failed` / `rejected`: no successful mutation is known, or policy stopped execution.

The execution journal is a single host safety mechanism. It blocks duplicate or concurrent
consumption on that host; it is not distributed exactly-once delivery. See the
[Agent protocol](docs/agent-protocol.md) for exit codes and handoff rules.

## Authentication and privacy

OAuth tokens are kept in the operating-system keyring. A process may explicitly inject a user
access token through the environment. Secrets are never CLI flags. An explicit config containing
an app secret must be a current-user regular file with mode `0600`; configuration is never chosen
implicitly. The API origin is restricted to the official Feishu origin.

Public CI uses no live credentials or tenant data. Fixtures and examples are synthetic. Content
scans cover tracked files and Git content across all refs; identity policy covers publishable
`HEAD` history. The project is a clean-room reconstruction from abstract behavior requirements.
Retained remote task branches may preserve already-public legacy metadata; this is not a
clean-all-refs claim. See [architecture](docs/architecture.md), the public-source-only
[behavior inventory](docs/behavior-inventory.md), and the [release process](docs/release-process.md).

## Development

```bash
uv sync --extra test
uv run ruff format --check .
uv run ruff check .
uv run mypy src scripts
uv run pytest -v --cov=feishu_task_cli --cov-fail-under=90
```

Contributions use Issue → branch → PR → `develop` with squash merge. A coherent version uses a
`develop` → `main` PR and an annotated tag on the merged `main` commit. See
[CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT
