# Release process

Releases preserve the repository's Issue → branch → PR → `develop` workflow. Release preparation
has its own Issue and branch, passes independent validation, and is squash-merged into `develop`.
Remote task branches are retained.

## Prepare

1. Set one semantic version in `pyproject.toml`, `feishu_task_cli.__version__`, and the changelog.
2. Run the complete local gate:

   ```bash
   uv sync --extra test
   uv run ruff format --check .
   uv run ruff check .
   uv run mypy src scripts
   uv run pytest -v --cov=feishu_task_cli --cov-fail-under=90
   uv run pip-audit
   uv build --clear
   uv run twine check dist/*
   SMOKE_ROOT="$(mktemp -d)"
   uv venv "$SMOKE_ROOT/venv"
   uv pip install --python "$SMOKE_ROOT/venv/bin/python" dist/*.whl
   "$SMOKE_ROOT/venv/bin/feishu-task" --help
   test "$("$SMOKE_ROOT/venv/bin/python" -c \
     'import feishu_task_cli; print(feishu_task_cli.__version__)')" = "0.1.1"
   gitleaks git --redact --no-banner
   uv run python scripts/privacy_scan.py --history
   git diff --check
   ```

3. Obtain validation-only review covering Agent UX, artifact/replay/AuthContext/review policy,
   secret and privacy boundaries, workflow permissions, claims, and failure modes.
4. Merge the preparation PR to `develop` only after required checks pass.

Public CI uses synthetic fixtures and no credentials, so a passing release gate is no
live-tenant validation. An optional maintainer smoke may be run only against an authorized test
tenant and must not store tokens or tenant data as an artifact.

The privacy identity gate covers commits reachable from publishable `HEAD`. The already-public
bootstrap identity is recorded only by its legacy commit SHA. Retained remote task branches may
still expose older author metadata; that bounded residual risk is not a clean-all-refs claim.

## Promote and tag

Open a release PR from `develop` to `main` with included Issues/PRs, validation verdict, changelog,
and exact gates. Squash-merge after all checks pass, fetch the resulting `main`, then create an
annotated tag on that exact commit:

```bash
git fetch origin main develop --tags
git switch main
git pull --ff-only origin main
git tag -a v0.1.1 -m "feishu-task-cli v0.1.1"
test "$(git rev-list -n 1 v0.1.1)" = "$(git rev-parse origin/main)"
git push origin v0.1.1
```

The tag-only workflow independently rejects a lightweight tag, a tag not pointing at current
`origin/main`, an event SHA that is not the checked-out commit, or a tag/version mismatch. The
event SHA, checked-out `HEAD`, peeled annotated tag commit, and fetched `origin/main` commit must
all match exactly. It reruns the full gate, builds wheel and sdist, runs
`twine check`, smoke-tests the wheel, records `SHA256SUMS`, uploads one immutable workflow
artifact, creates build provenance attestations for those bytes, and creates a GitHub Release from
the same bytes.

Published tags are immutable, including tags whose workflow fails before a Release is created.
Never move, delete, or reuse a failed release tag; fix the release path and use the next patch
version.

PyPI publishing is skipped by default. It runs only when the repository variable
`PYPI_TRUSTED_PUBLISHING` is explicitly `true` and the protected `pypi` environment is configured
for trusted publishing. That job downloads the validated workflow artifact, verifies
`SHA256SUMS`, reruns `twine check`, and publishes without rebuilding. No long-lived package token
is stored.
