# Agent onboarding and repository discovery design

**Status:** Approved for implementation by an independent validation-only reviewer

**Issues:** #54 and #55

**Target version:** v0.1.2

## Problem

The CLI is designed for Agents, but its public entry point still assumes a human will translate
installation and protocol documentation into Agent instructions. The repository also has no
Homepage or Topics and only a short About description. A visitor cannot copy one bounded prompt
to install the tool, and GitHub has little structured metadata with which to classify the project.

GitHub documents Topics as a repository discovery mechanism and permits at most 20 normalized
topics. Comparable Feishu/Lark Agent repositories consistently use precise product and audience
terms such as `feishu`, `lark`, `ai-agent`, and `cli`. Metadata helps classification; it does not
guarantee Stars.

## Chosen approach

Ship one coherent Agent onboarding and discovery package in a docs-only task branch after the
checksum fix reaches `develop`:

1. Put a short, prominent copy-to-Agent installer prompt near the top of README.
2. Put the complete installer and a separate write workflow prompt in
   `docs/agent-installation.md`.
3. Add a concise root `AGENTS.md` that routes a cloned-repository Agent to the installation guide,
   Agent protocol, contribution rules, and security boundaries.
4. Expand README with factual badges, purpose, use cases, Agent contract, rendered result example,
   troubleshooting, and a documentation map.
5. Commit the exact GitHub About, Homepage, and Topics values in `docs/repository-metadata.md`, then
   apply and read back that external state only after v0.1.2 reaches `main` and its Release succeeds.

A README-only patch was rejected because it leaves the install contract and GitHub metadata
unreviewable. A Pages site, GIF, and social preview are deferred until real usage evidence exists.

## Installer contract

The copied installer prompt pins the annotated `v0.1.2` tag. It may read the GitHub tag, download
Python dependencies, and create or update the caller's isolated `uv tool` environment. It must not:

- use `sudo` or modify the system Python installation;
- install missing system-level prerequisites on its own;
- open a browser, run OAuth, or call a Feishu Task API;
- create, update, assign, complete, or otherwise mutate a Task;
- ask the user to paste a token or secret into chat or a CLI argument;
- print environment variable values, credentials, tenant data, or business content.

If Python 3.11+ or `uv` is absent, the Agent stops and reports `blocked`. Otherwise it verifies the
absolute executable path, package version, `--help`, and the Plan, Review, Policy, and Receipt
schemas. Its only final response is JSON with this stable shape:

```json
{
  "status": "installed|already_installed|blocked|failed",
  "package": "feishu-task-cli",
  "requested_ref": "v0.1.2",
  "installed_version": "0.1.2|null",
  "executable": "/absolute/path|null",
  "checks": {
    "python": "passed|failed",
    "uv": "passed|failed",
    "version": "passed|failed",
    "help": "passed|failed",
    "schemas": "passed|failed"
  },
  "auth_attempted": false,
  "browser_opened": false,
  "task_write_attempted": false,
  "warnings": [],
  "errors": []
}
```

The documentation may enter `develop` before the tag exists, but the prompt is not described as a
usable stable install path until `v0.1.2` is an annotated tag on `main` and the Release succeeds.
No fallback to `@main`, `@develop`, or an unpinned Git URL is allowed.

## Task execution prompt

The separate usage prompt requires an explicit action, account/AuthContext, Task or Tasklist ID,
assignee identifier, and user authorization for the intended write. It follows:

`Plan -> Review -> Execute -> API readback -> Receipt -> Render`

Plan is intent, not proof of execution. Independent review is preferred when available; self-review
must remain declared. An `unknown` or `partial` outcome is never replayed automatically and is never
reported as success. Only a `verified` Receipt supports a complete-success claim. JSON Receipt
remains authoritative; rendered Markdown is the bounded user-facing handoff.

## README and metadata

README badges are limited to CI, CodeQL, latest Release, Python, and MIT facts. It must not claim
download volume, production readiness, broad Agent compatibility, or live-tenant validation.

The tracked metadata is:

- **Description:** `Agent-first CLI for safe Feishu/Lark Task writes: review artifacts, dry-run plans, API readback, execution journals, and machine-readable receipts.`
- **Homepage:** `https://github.com/Alex-ghost599/feishu-task-cli/blob/main/docs/agent-installation.md`
- **Topics:** `feishu`, `lark`, `larksuite`, `cli`, `python`, `ai-agent`, `agent-tools`,
  `agentic-ai`, `task-management`, `workflow-automation`, `oauth2`, `api-client`, `dry-run`,
  `developer-tools`, `automation`.

Homepage is applied only after the file exists on `main`, so the public URL cannot lead to a 404.

## Testing and release

Contract tests must fail before implementation and then enforce:

- README installation ref equals the package version and is never a branch or unpinned ref;
- prompts contain no `sudo`, pipe-to-shell installer, secret CLI flag, `auth login`, or `execute`
  command in the install phase;
- all JSON report fields and value sets are present;
- README, `AGENTS.md`, installation guide, Agent protocol, and metadata links resolve;
- description is at most 160 characters; Topics are unique normalized names and at most 20;
- public capability statements stay within existing implementation and test evidence.

The branch goes through Issue -> RED/GREEN -> PR -> required checks -> independent review -> squash
to `develop`. v0.1.2 then follows the existing `develop` to `main` promotion, annotated tag, Release,
public flat-download checksum, attestation, and mandatory post-release ancestry sync. Issues #54 and
#55 remain open until `main`, Release, and GitHub metadata readback all agree.
