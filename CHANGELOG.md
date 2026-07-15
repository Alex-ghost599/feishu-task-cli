# Changelog

All notable changes to this project are documented here.

## [0.1.2] - 2026-07-15

### Added

- A copyable install-only Agent prompt pinned to `v0.1.2`, with an isolated `uv tool` path,
  explicit no-auth/no-write boundaries, and a self-contained machine-readable installation report.
- A separate authorized Task workflow prompt, repository `AGENTS.md` routing, expanded README
  guidance, factual badges, and a bounded user-handoff example.
- A reviewed source of truth for GitHub About metadata and 15 relevant repository topics; public
  metadata deployment remains gated until the annotated `v0.1.2` GitHub Release succeeds.

### Validation

- Agent onboarding and Task workflow behavior were validated with synthetic mocked responses;
  this release makes no live-tenant validation claim.

### Fixed

- Generate `SHA256SUMS` with distribution basenames so the same manifest verifies both the
  nested workflow artifact and flat GitHub Release downloads.

### Release note

- The `v0.1.1` automated release and attestations succeeded, but its public `SHA256SUMS` paths
  could not be verified directly after downloading the three GitHub Release assets into one
  directory. The immutable `v0.1.1` tag and assets are not modified.

## [0.1.1] - 2026-07-15

### Fixed

- Fetch the exact remote tag object, then require the checked-out `HEAD`, event `GITHUB_SHA`,
  peeled annotated tag commit, and current `origin/main` to match exactly.

### Release note

- The immutable `v0.1.0` tag workflow failed before the build step because the runner did not
  have the annotated tag ref; it created no GitHub Release or release assets. Failed release
  tags are never moved, deleted, or reused.
- `v0.1.1` is the first complete release candidate.

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

[0.1.2]: https://github.com/Alex-ghost599/feishu-task-cli/releases/tag/v0.1.2
[0.1.1]: https://github.com/Alex-ghost599/feishu-task-cli/releases/tag/v0.1.1
[0.1.0]: https://github.com/Alex-ghost599/feishu-task-cli/releases/tag/v0.1.0
