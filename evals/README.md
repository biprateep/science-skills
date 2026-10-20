# Shared skill evaluation

Every directory matching `skills/*/SKILL.md` inherits the same discovery,
execution, measurement, and reporting contract. Each skill supplies its own
tasks and independent checks in `evals/manifest.json`. Adding a future skill
does not require a runner change; CI requires it to supply a manifest.

The framework uses the Python 3.10+ standard library. Run from the repository
root:

```sh
python -m evaluation list
python -m evaluation validate --require-coverage
python -m evaluation run --runner replay --repeats 3
python -m evaluation report .eval-runs/RUN/report.json
python -m evaluation compare .eval-runs/NEW/report.json .eval-runs/OLD/report.json
```

`replay` copies committed reference answers and artifacts into a fresh task
workspace and grades them. **This calibrates fixtures and graders; it measures
no agent performance.** Broken-answer regression tests complement reference
replay so an always-passing grader cannot be justified by positive fixtures
alone. Most skills currently have one starter case, not comprehensive coverage of
every instruction. Plot-style evaluates a style review, not rendered figure
quality. [Cite-check](../skills/cite-check/evals/README.md) adds three controlled
offline tasks and citation-specific metrics; these do not exercise live
registries or MCP integration.

Keep three kinds of evidence distinct:

1. Unit/regression tests verify implementation behavior.
2. CLI/MCP integration tests verify tool and transport behavior.
3. Live agent task evaluations measure actual skill use under a named harness.

This framework supplies the third layer and its offline calibration. Existing
unit and MCP tests remain separate. Results do not establish compatibility with
an agent until that agent has actually run the tasks successfully.

## Live runners

Copy `evals/runners.example.json` to the ignored `evals/runners.local.json` and
adapt the command, model selection, and declared capabilities to your installed
CLI. The three examples use flags checked against local CLI help; they are
templates, not claims of successful live evaluation.

```sh
cp evals/runners.example.json evals/runners.local.json
python -m evaluation run --runner codex --allow-live --skill cite-check --repeats 3
```

Live runs may consume paid tokens and invoke agent tools. They require
`--allow-live`; CI never runs them. The runner inherits the current environment,
authentication, native permissions, and configured MCP servers. Set model
selection in `argv` and its corresponding descriptive `model` field together.
`model: null` means the actual model is unknown; it is never guessed. Record
CLI/model versions in your local configuration's `description` when comparing
runs across upgrades. These declarations and capability labels are operator
assertions, not automatic capability or version detection.

Commands are argument arrays executed without a shell. Supported substitutions:
`{python}`, `{repo}`, `{workspace}`, `{prompt_file}`, `{response_file}`,
`{skill_dir}`, `{seed}`. Put command logic in script files; braces in argument
strings are reserved for these placeholders. `stdin` is `prompt` (default) or
`none`. `output` is `stdout`, `file` (write `{response_file}`), or `envelope`.
The seed is recorded and exposed to commands; the framework cannot force a
native model to use it or guarantee deterministic model output.

Envelope runners print one JSON object:

```json
{
  "response": "The final task response",
  "reported_success": true,
  "usage": {
    "input_tokens": 120,
    "output_tokens": 35,
    "tool_calls": 2,
    "cost_usd": null
  }
}
```

`reported_success` and each usage value may be absent or null. Plain output
does not imply an explicit success claim. Unknown telemetry stays null; the
report gives observation coverage and observed totals, never invented zeros or
estimated provider prices. A wrapper must translate native CLI telemetry into
this envelope if those measurements are needed.

## Adding a task

Use the existing skill manifests as examples. Manifest schema version 1 has:

```json
{
  "schema_version": 1,
  "skill": "example",
  "skill_dependencies": [],
  "cases": [{
    "id": "task-name",
    "description": "What behavior this task measures",
    "prompt": "task/prompt.md",
    "inputs": "task/input",
    "reference": "task/reference",
    "capabilities": ["filesystem"],
    "tags": ["offline"],
    "checks": [{
      "id": "correct-answer",
      "kind": "json_equals",
      "pointer": "/answer",
      "expected": 42,
      "dimension": "task_success",
      "critical": true
    }]
  }]
}
```

Paths are relative to the manifest directory. `inputs`, `reference`,
`skill_dependencies`, `tags`, and `capabilities` are optional. An optional
positive `timeout_s` overrides `evals/defaults.json`; the output limit always
comes from those shared defaults. Reference directories contain `response.txt`
and optionally `artifacts/`, whose files may replace input files during replay.
The agent gets the prompt, input files at workspace root, and copied skill
sources under `skills/`; it does not get the manifest, reference answers, or
grader code as task inputs. Dependencies must name other discovered skills.

Every case needs at least one `task_success` check. Check IDs are unique per
case; case IDs are unique per skill. Every check explicitly declares
`critical: true|false` and one dimension:

| Dimension | Measures |
| --- | --- |
| `task_success` | Whether the requested task was solved correctly |
| `constraint_adherence` | Whether required instructions were followed |
| `coverage` | Whether required task content was addressed |

Supported checks:

| Kind | Fields | Interpretation |
| --- | --- | --- |
| `json_equals` | `pointer`, `expected` | Strict JSON response, RFC 6901 pointer; empty pointer selects the entire value. No code-fence stripping or duplicate keys. Values compare by canonical JSON representation. |
| `file_exists` | `path` | A regular workspace file exists; no symlink traversal. |
| `file_contains` | `path`, `text` | A bounded UTF-8 workspace file contains the literal text. |
| `command` | `argv`, optional `timeout_s` | Trusted grader: exit 0 passes, 1 fails the task, other exits/timeouts are evaluator errors. Default grader budget: 10 seconds. |

All checks are required. A case passes only if all checks pass; errors take
precedence over failures. Critical failures are additionally listed, so average
success cannot hide them. Avoid brittle prose matching where an executable or
structured oracle is possible. Include deliberately incorrect outputs in
grader tests. Keep generated run data out of fixture directories.

## Metrics and comparisons

Reports retain every scheduled trial, including blocked runners and timeouts.
Success uses all scheduled trials as its denominator; completion counts graded
pass/fail outcomes. Per-dimension rates include missing check observations in
the denominator. Critical unsuccessful checks, explicit unsupported success
claims, and telemetry coverage are reported separately. Repeated-trial
consistency is descriptive; repeated fixtures are not independent samples of
all possible tasks. There is no single composite quality score.

Repository manifest coverage, exercised skills, and unexecuted skills are
separate from task-content coverage. A manifest is a starting point, not proof
of a comprehensive test suite. Reports provide per-skill results and pooled
counts; pooled counts weight skills with more cases more heavily.

Comparisons pair `(skill, case_id, repeat)` only when mode, runner configuration,
seed, fixture/grader contract, effective budgets, and framework fingerprints
match. Changing the skill source is allowed: measuring that change is the
purpose. Changing any file in a skill's `evals/` tree invalidates its case
comparisons conservatively. Command graders should live in that tree; external
grader dependencies, installed tools, model/provider changes, and environment
changes are not automatically fingerprinted. Hold these fixed and record their
versions in the runner configuration. Timing includes workspace preparation,
agent execution, and grading; it is end-to-end trial latency.

Exit statuses: `run` returns 0 for all passes, 1 for any unsuccessful trial,
and 2 for invalid configuration. `compare` returns 1 for measured regressions,
2 for incomplete/incomparable comparisons (including no matched trials), and
0 otherwise. New cases are listed separately. Missing baseline cases never
silently pass the comparison gate.

## Isolation, provenance, and storage

Each trial gets a fresh workspace. Git checkouts copy tracked and unignored
skill source files, excluding evals, tests, private scratch, dot-directories,
logs, bytecode, and virtual environments. Clean exported trees use the same
explicit exclusions but cannot recover Git ignore rules. Use clean exports.
Input symlinks and path traversal are rejected. Runtime and captured output
are bounded; output limits are polled, so temporary disk usage can briefly
exceed the limit. Generated artifact disk usage is not globally quota-limited.

**A workspace is not a security sandbox.** Agents may retain access through
native/global settings, installed skills, or MCP servers. The prompt prohibits
reading outside the workspace for answers, but this is not an OS boundary.
Trusted graders can execute generated code. For untrusted workloads, run the
entire evaluator in an externally restricted container or VM. POSIX process
groups are terminated after subprocess execution; on Windows only the direct
child is terminated. Descendants that deliberately escape a process group are
outside this mechanism.

JSON reports record Git commit/dirty status/diff hash, immutable pre-execution
skill input hashes, task/framework fingerprints, runner fingerprint, and seeds.
Fingerprints provide reproducibility metadata, not attestation against an agent
that can access the host. No raw Git diff is stored. Run directories contain
prompts, responses, runner output, and generated workspaces; treat them as
potentially private. `.eval-runs/`, local runner configuration, and
`evals/baselines.local/` are ignored. Custom `--output` paths must be kept out of
version control by their owner. PR descriptions document changes and test
results; run logs and review directories are not committed.

## Development checks

```sh
python -m pytest --import-mode=importlib evaluation/tests skills/*/evals/tests -q
python -m evaluation validate --require-coverage
python -m evaluation run --runner replay --repeats 2
```

The CI workflow runs these offline on Python 3.10 and 3.13. Formatter/linter and
type checks use the repository's code-style configuration. The existing
`skills/co-writer/eval/` protocol remains separate from these `evals/` fixtures.
