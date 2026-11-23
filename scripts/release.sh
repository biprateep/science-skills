#!/usr/bin/env bash
# Cut a release: validate the version, tag main, push the tag.
# The GitHub release itself is created by .github/workflows/release.yml.
#
# Usage: scripts/release.sh v0.5.0
set -euo pipefail

version="${1:-}"
if [[ ! "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "usage: scripts/release.sh vMAJOR.MINOR.PATCH (e.g. v0.5.0)" >&2
  exit 1
fi

if git rev-parse "$version" >/dev/null 2>&1; then
  echo "error: tag $version already exists" >&2
  exit 1
fi

branch="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$branch" != "main" ]]; then
  echo "error: releases are cut from main (currently on $branch)" >&2
  exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "error: working tree is not clean" >&2
  exit 1
fi

git fetch origin main
if [[ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ]]; then
  echo "error: local main is not in sync with origin/main" >&2
  exit 1
fi

git tag -a "$version" -m "$version"
git push origin "$version"
echo "Pushed tag $version — the Release workflow will publish the GitHub release."
