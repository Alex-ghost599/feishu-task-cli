# feishu-task-cli

Agent-native, review-gated Feishu Task writes with readback verification.

> **Status:** pre-alpha design and repository bootstrap. Task mutation commands are not yet
> implemented. Do not treat a generated Plan as an executed Feishu Task.

The v0.1 protocol is designed for agents:

```text
Plan → declared Agent review → guarded execution → API readback → Receipt → Markdown
```

The project intentionally has no built-in profile, tenant, member, Tasklist, or task defaults.
Declared Agent identities are audit metadata, not cryptographically verified identities.

See the [approved design](docs/superpowers/specs/2026-07-15-feishu-task-cli-design.md) and
[implementation plan](docs/superpowers/plans/2026-07-15-feishu-task-cli-implementation.md).

## Development

```bash
uv sync --extra test
uv run pytest
uv run ruff check .
uv run mypy src scripts
```

Contributions follow Issue → task branch → pull request → `develop`. Releases move from
`develop` to `main` through a release pull request.

## License

MIT
