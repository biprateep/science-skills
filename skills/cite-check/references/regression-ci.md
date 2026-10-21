# Citation regression and compatibility checks

The citation engine has a dedicated GitHub Actions regression workflow in
addition to the repository's shared behavioral-evaluation workflow. The shared
replay cases calibrate grading; they are not a replacement for engine tests or
an agent-performance benchmark.

## Deterministic matrix

The citation workflow runs on pull requests and pushes to `master`:

| Python | MCP SDK generation |
|---|---|
| 3.10 | 1 |
| 3.13 | 1 |
| 3.12 | 2 |
| 3.13 | 2 |

Each cell installs the declared dependencies with an explicit MCP major-version
constraint, then runs the full citation unittest suite and offline CLI smoke
checks. Native stdio initialization, schema validation, PDF handling, pooled HTTP
behavior, provenance and publication-status regressions are included. HTTP
transport tests use local loopback servers or fixtures, not public registries.

The runner checks dependency availability and the selected SDK generation,
rejects empty discovery and fails on skipped citation tests. A green matrix
therefore cannot hide the native protocol, PDF or connection-pool tests behind
missing optional dependencies. Whole-command and job time limits also cover
native subprocess startup/shutdown failures.

CLI smoke tests accept an explicit Python interpreter so a checkout's existing
`mcp/.venv` cannot silently replace the selected matrix environment. Without an
override, their existing local interpreter selection is preserved. Set
`CITE_CHECK_TEST_PYTHON` to the absolute executable path for either skill's smoke
script.

To reproduce a citation matrix cell on Linux with its dependencies installed:

```sh
timeout --signal=TERM --kill-after=10s 300s python skills/cite-check/tests/run_regression.py --sdk-major 1
CITE_CHECK_TEST_PYTHON="$(command -v python)" timeout --signal=TERM --kill-after=10s 300s bash skills/cite-check/tests/verify_mcp.sh
```

Use `--sdk-major 2` in an MCP 2 environment. The runner exits 2 for an invalid
or incomplete environment, 1 for a failing/skipped/empty suite, and 0 for a
successful nonempty suite with no skips.

Installer and co-scientist integration checks run in one matrix cell. Any
optional TeX compilation coverage is reported separately from citation checks;
this workflow does not certify a complete TeX distribution or paper build.

## Live provider checks

A separate manually dispatched workflow checks a small set of fixed public
provider endpoints. It uses no model calls and requires no account credentials.
It is not triggered by a pull request and is not part of the deterministic merge
gate. Provider outages and throttling are distinguished from response-contract
failures in its results, rather than being reported as citation accuracy errors.

The fixed probes cover Crossref, DataCite and arXiv. Each response is bounded
to 1 MiB, each socket timeout to 15 seconds, and redirects are refused. The
workflow also imposes a whole-command timeout. Run explicitly with:

```sh
timeout --signal=TERM --kill-after=10s 90s python skills/cite-check/tests/public_live_probes.py --live
```

Without `--live`, the command exits 2 without requests. Any availability or
contract issue exits 1; all probes passing exits 0. Requests and response sizes
are bounded. These probes are service-contract
smoke checks, not exhaustive provider coverage or an evaluation of an agent's
citation judgments. The ordinary offline tests remain the reproducible
regression evidence.

Workflow logs and summaries are GitHub Actions run artifacts; they are not
committed source files. Runtime caches, `.cite-check`, `.eval-runs` and local
reviews remain ignored.

The trigger and timeout behavior follow
[GitHub's workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax).
