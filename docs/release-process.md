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
     'import feishu_task_cli; print(feishu_task_cli.__version__)')" = "0.1.2"
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
git tag -a v0.1.2 -m "feishu-task-cli v0.1.2"
test "$(git rev-list -n 1 v0.1.2)" = "$(git rev-parse origin/main)"
git push origin v0.1.2
```

The tag-only workflow independently rejects a lightweight tag, a tag not pointing at current
`origin/main`, an event SHA that is not the checked-out commit, or a tag/version mismatch. The
event SHA, checked-out `HEAD`, peeled annotated tag commit, and fetched `origin/main` commit must
all match exactly. It reruns the full gate, builds wheel and sdist, runs
`twine check`, smoke-tests the wheel, records `SHA256SUMS` using distribution basenames, uploads
one immutable workflow artifact, creates build provenance attestations for those bytes, and
creates a GitHub Release from the same bytes.

The nested workflow artifact is verified from `release/packages` against `../SHA256SUMS`. A user
can download the wheel, sdist, and `SHA256SUMS` as three sibling GitHub Release assets and run
`sha256sum -c SHA256SUMS` directly in that flat directory.

Published tags are immutable, including tags whose workflow fails before a Release is created.
Never move, delete, or reuse a failed release tag; fix the release path and use the next patch
version.

## Restore release ancestry

After every successful `develop` → `main` squash release and release verification, create a
zero-file ancestry-only `main` → `develop` PR. Merge it with a validation-approved normal merge
only when it is a validation-approved, zero-file ancestry PR.
Product, documentation, and bug-fix PRs remain squash-merged; a normal merge is not available to
them.

Use this restore-first checklist for the controlled window:

1. Before changing settings, save a machine-readable repository settings snapshot and
   machine-readable branch-protection snapshots for both `main` and `develop`. The snapshots must
   include merge methods; required checks and strictness; PR review requirements; administrator
   enforcement; conversation resolution; force-push and deletion protection; linear-history
   requirements; and all `main` protection. Also record the exact `main`, `develop`, and PR head
   commit IDs and their exact tree IDs. Abort if the PR is not approved, has changed files, or any
   recorded commit or tree no longer matches the remote readback.
2. Install a `trap/finally` restore handler *before* opening the window. It must attempt restoration
   on success, failure, or timeout, before reporting the merge outcome. The restore target is the
   complete saved policy with `allow_merge_commit=false` and
   `develop.required_linear_history=true`.
3. Open only these two temporary switches: set `allow_merge_commit=true` and
   `develop.required_linear_history=false`. Required checks and strictness, PR review requirements,
   administrator enforcement, conversation resolution, force-push and deletion protection, all
   `main` protection, and every other repository or branch setting must remain byte-for-byte
   equivalent to the pre-window snapshots.
4. Recheck the exact commit and tree guards, then normal-merge only the approved ancestry PR. Do
   not use the window for any other PR. Whether the merge command succeeds, fails, or times out,
   run the restore handler first; only then interpret or retry the operation.
5. After restoration, read back the complete repository and branch-protection snapshots and compare
   every field listed above with the saved values. Then verify the merged PR has zero changed files,
   the resulting `develop` has an unchanged tree ID, both pre-window commits are ancestors of
   `develop`, and the remote task branch remains present.
6. Close the window only when policy readback and graph/tree checks all pass.
   No later release or bug-fix work may begin until this ancestry-sync loop is closed or explicitly
   reported blocked.

Never substitute marker commits, force-pushes, moved tags, or attempts to delete branches for this
ancestry restoration. Remote task branches remain retained.

PyPI publishing is skipped by default. It runs only when the repository variable
`PYPI_TRUSTED_PUBLISHING` is explicitly `true` and the protected `pypi` environment is configured
for trusted publishing. That job downloads the validated workflow artifact, verifies
`SHA256SUMS`, reruns `twine check`, and publishes without rebuilding. No long-lived package token
is stored.
