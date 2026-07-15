# Changelog

All notable changes to this project are documented here.

## [0.1.0] - 2026-07-15

### Added

- Versioned, canonical Plan, Review, Policy, and Receipt JSON artifacts with committed schemas.
- Agent review policy with explicit self-review and declared independent-review states.
- Feishu user OAuth, keyring-backed token storage, redacted errors, and AuthContext binding.
- Task get, create, update, assign, and complete flows with typed assignee identifiers.
- Single-consumption local journal, mutation no-retry boundary, API readback, and reconciliation.
- Stable JSON errors and safe Markdown rendering for user-facing Agent handoff.
- Pinned CI, dependency, CodeQL, secret, privacy, package, and release gates.

### Security

- No implicit profiles or targets, no secret command flags, and strict private-config checks.
- Mutations fail closed on stale state, AuthContext mismatch, replay, concurrent execution, and
  invalid or expired review artifacts.

[0.1.0]: https://github.com/Alex-ghost599/feishu-task-cli/releases/tag/v0.1.0
