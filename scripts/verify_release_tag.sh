#!/usr/bin/env bash
set -euo pipefail

tag_name="${GITHUB_REF_NAME:-}"
if [[ ! "$tag_name" =~ ^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]]; then
  echo "error: invalid release tag name" >&2
  exit 1
fi

event_sha="${GITHUB_SHA:-}"
if [[ ! "$event_sha" =~ ^[0-9a-fA-F]{40}$ ]] ||
  [[ "$(git cat-file -t "$event_sha" 2>/dev/null || true)" != "commit" ]]; then
  echo "error: invalid GITHUB_SHA commit" >&2
  exit 1
fi

tag_ref="refs/tags/${tag_name}"
main_ref="refs/remotes/origin/main"

# A tag-triggered checkout can contain only the peeled commit. Fetch the exact
# remote tag ref so annotated-tag validation never depends on local tag state.
git fetch --force --no-tags origin "${tag_ref}:${tag_ref}"

if [[ "$(git cat-file -t "$tag_ref")" != "tag" ]]; then
  echo "error: release tag must be annotated" >&2
  exit 1
fi

git fetch --force --no-tags origin "refs/heads/main:${main_ref}"

head_commit="$(git rev-parse 'HEAD^{commit}')"
event_commit="$(git rev-parse "${event_sha}^{commit}")"
tag_commit="$(git rev-parse "${tag_ref}^{commit}")"
main_commit="$(git rev-parse "${main_ref}^{commit}")"

if [[ "$head_commit" != "$event_commit" ]] ||
  [[ "$head_commit" != "$tag_commit" ]] ||
  [[ "$head_commit" != "$main_commit" ]]; then
  echo "error: release commits must match checkout, event, annotated tag, and origin/main" >&2
  exit 1
fi
