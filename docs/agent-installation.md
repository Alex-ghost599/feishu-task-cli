# Agent installation and usage

This page contains two prompts with different authority. The first may only install and inspect
the isolated CLI tool. The second may perform an authorized Task workflow after the user supplies
the required target and identity context. See the [Agent protocol](agent-protocol.md) for the
authoritative artifact, outcome, and recovery rules.

The pinned installation becomes a usable stable path only after the annotated `v0.1.2` tag is on
`main` and the corresponding GitHub Release has succeeded. There is no branch or unpinned fallback.

## Copy to Agent: install and verify

```text
Install and verify feishu-task-cli within these exact boundaries:

1. Check for an existing Python interpreter at version 3.11 or newer and for uv. If either is
   unavailable, do not install a system prerequisite. Stop with status blocked in the final JSON.
   Do not reveal environment variable values or unrelated environment and machine details while
   checking. Record the absolute eligible Python path internally as $PYTHON_311, but do not return
   it.
2. Before changing the isolated tool, inspect `uv tool list --show-paths
   --show-version-specifiers`. If it already shows package version 0.1.2 from the exact v0.1.2 Git
   ref, leave it unchanged and record status already_installed. Otherwise install or replace only
   this uv-managed tool, using the verified interpreter and preventing another Python download:
   uv tool install --force --python "$PYTHON_311" --no-python-downloads "feishu-task-cli @ git+https://github.com/Alex-ghost599/feishu-task-cli@v0.1.2"
3. Run `uv tool list --show-paths --show-version-specifiers` again. Resolve the feishu-task
   executable to an absolute path, verify that it belongs to the uv tool installation, and verify
   that the installed feishu-task-cli package version is exactly 0.1.2. If any check fails, report
   failed and stop.
4. Using that absolute executable, run these read-only interface checks:
   feishu-task --help
   feishu-task schema show --artifact plan
   feishu-task schema show --artifact review
   feishu-task schema show --artifact policy
   feishu-task schema show --artifact receipt
   If the help or any schema check fails, report failed and stop.
5. This prompt grants installation and local inspection authority only. Do not authenticate, open
   a browser, call a Feishu API, perform a Task write, alter a Task, request credentials, or print
   secrets, tenant data, environment variable values, unrelated environment and machine details,
   or business content. The executable is the only permitted machine-local path in the fixed
   report, and it must be verified and absolute.
6. Return the exact JSON object below, with no prose or Markdown and no additional fields. Allowed
   status values: installed, already_installed, blocked, failed. Allowed check values: passed,
   failed. Use already_installed only when the exact pinned tool was present before installation;
   use installed only after a successful new or replacement installation; use blocked when Python
   3.11+ or uv is unavailable; and use failed when installation, post-installation, or any interface
   check fails.
   Keep all mutation booleans false. Use null for unavailable version or executable values, and
   place only safe diagnostics in warnings and errors. The executable is the only permitted
   machine-local path in this report, and it must be verified and absolute.

{
  "status": "installed",
  "package": "feishu-task-cli",
  "requested_ref": "v0.1.2",
  "installed_version": "0.1.2",
  "executable": "/absolute/path/to/feishu-task",
  "checks": {
    "python": "passed",
    "uv": "passed",
    "version": "passed",
    "help": "passed",
    "schemas": "passed"
  },
  "auth_attempted": false,
  "browser_opened": false,
  "task_write_attempted": false,
  "warnings": [],
  "errors": []
}
```

## Copy to Agent: authorized Task workflow

```text
Use feishu-task only for the single write I explicitly authorize. Before creating a Plan, require
me to provide all of the following: the exact action; the explicit account and AuthContext; the
Task GUID or Tasklist GUID required by that action; the typed assignee identifier
(open_id:<value>, user_id:<value>, or union_id:<value>), or an explicit not-applicable value; the
requested fields; and unambiguous authorization for this exact write. Do not infer IDs, select an
implicit profile, reuse remembered targets, request secrets in chat, or proceed with missing data.

Run the bounded workflow Plan -> Review -> Execute -> API readback -> Receipt -> Render. Inspect
the relevant command form with `feishu-task plan create --help`, `feishu-task plan update --help`,
`feishu-task plan assign --help`, or `feishu-task plan complete --help`, then create one immutable
Plan for the authorized action. Treat the Plan as intent only. Check the action, target, assignees,
requested fields, AuthContext fingerprints, warnings, and expiry.

Prefer a separate reviewing Agent. Record distinct reviewer and intended executor IDs with
`feishu-task review` when independent review is available. If it is genuinely unavailable and
policy permits continuation, keep the same declared identity visible so the result remains
`declared_self_reviewed`; never present self-review as independent review.

Run `feishu-task execute` once with the approved Plan, Review, explicit executor ID, and explicit
configuration. Inspect the authoritative Receipt and its API readback. Never infer success from a
Plan, review verdict, Task GUID, process output, or a non-execution exit code.

Run `feishu-task render --artifact receipt.json --format markdown --output result.md`, then show or
faithfully summarize the rendered handoff to the user while preserving warnings, mismatches,
omitted fields, review state, outcome, and next action. Keep the JSON Receipt authoritative.

Only a `verified` Receipt supports a complete-success claim. On `partial` or `unknown`, stop,
report that exact outcome, preserve the artifacts, investigate remotely as appropriate, and never
replay the same Plan automatically.
```

Repository contributors should also follow the [repository Agent router](../AGENTS.md), the
[README](../README.md), the public [architecture and trust boundaries](architecture.md), and
[CONTRIBUTING.md](../CONTRIBUTING.md).
