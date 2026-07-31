#!/usr/bin/env bash
# Cut a release: validate the version, tag master, push the tag.
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
if [[ "$branch" != "master" ]]; then
  echo "error: releases are cut from master (currently on $branch)" >&2
  exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "error: working tree is not clean" >&2
  exit 1
fi

git fetch origin master
if [[ "$(git rev-parse HEAD)" != "$(git rev-parse origin/master)" ]]; then
  echo "error: local master is not in sync with origin/master" >&2
  exit 1
fi

git tag -a "$version" -m "$version"
git push origin "$version"
echo "Pushed tag $version — the Release workflow will publish the GitHub release."
