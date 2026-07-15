# Repository Agent guide

Keep changes small, evidence-backed, and within the authority granted by the user. This repository
defines a safety-sensitive CLI: a Plan is intent, and only a verified Receipt supports a
complete-success claim.

## Documentation routes

- Installation and copyable prompts: [docs/agent-installation.md](docs/agent-installation.md)
- Runtime artifact and outcome rules: [docs/agent-protocol.md](docs/agent-protocol.md)
- Public architecture and trust boundaries: [docs/architecture.md](docs/architecture.md)
- Contributions and Git workflow: [CONTRIBUTING.md](CONTRIBUTING.md)

The project overview and supported development checks are in [README.md](README.md).

## Safety boundaries

- Keep repository instructions generic. Do not add machine-local absolute paths or private
  environment assumptions.
- Never infer an account, tenant, profile, Task, Tasklist, member, assignee, reviewer, or executor.
  Require explicit context and typed identifiers for each workflow.
- Never place credentials, tokens, secrets, tenant data, or business content in source, examples,
  command arguments, logs, or Agent responses.
- Installation verification is install-and-inspect only. It must not authenticate, open a browser,
  call live Feishu APIs, or create, update, assign, complete, or otherwise write a Task.
- Do not install missing system prerequisites or modify the system Python. Use only the documented
  isolated, pinned `uv tool` installation path.
- Preserve the runtime protocol: Plan -> Review -> Execute -> API readback -> Receipt -> Render.
  Prefer declared independent review, preserve declared self-review when unavoidable, and never
  replay a Plan after an `unknown` or `partial` outcome.

## Change discipline

- Follow the existing architecture and public interfaces; avoid broad refactors and new
  dependencies unless the task requires them.
- Update tests when behavior or a public contract changes. Run the relevant focused tests, then the
  repository formatting, lint, typing, and test commands appropriate to the change.
- Do not claim live-tenant validation or production readiness without direct, reviewable evidence.
