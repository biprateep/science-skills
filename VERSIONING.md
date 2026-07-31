# Versioning

This repo uses a single repo-level version with tags of the form
**`vMAJOR.MINOR.PATCH`** (e.g. `v0.4.0`).

## When to bump what

- **MAJOR** — breaking changes: a skill is removed or renamed, or its
  invocation/interface changes in a way that breaks existing users.
- **MINOR** — a new skill is added, or an existing skill gets a substantive
  revision (new capabilities, rewritten workflow).
- **PATCH** — fixes, typos, docs, and other changes that don't alter what a
  skill can do.

Individual skill iterations mentioned in commit messages (e.g. "co-scientist
v0.4") are informal working labels; the repo tag is the version of record.

## How to cut a release

From an up-to-date `master` with a clean tree:

```sh
scripts/release.sh v0.5.0
```

The script validates the version format, creates an annotated tag, and pushes
it. Pushing the tag triggers `.github/workflows/release.yml`, which creates the
GitHub release with auto-generated notes. No other steps are needed.

## History note

Tags `0.1` and `v0.2` predate this convention and are kept as-is. The
convention applies from `v0.4.0` onward.
