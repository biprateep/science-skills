# Cite-check controlled evaluation

This suite uses the repository's [shared evaluator](../../../evals/README.md).
It adds citation-specific observations, not a replacement runner or composite
quality score. All source packets are original synthetic test data. They must
never be represented as real papers or registry exports.

There are 20 claims across three tasks:

| Task | Coverage | Claims |
| --- | --- | --- |
| `evidence-boundaries` | Supported result, unsupported generalization, direct contradiction, inaccessible text | 4 |
| `quantitative-controls` | Numbers, signs, negation, and causal overstatement, each paired with a supported control | 8 |
| `identity-version-access` | Matching and conflicting titles/versions, stale result, unavailable text, unresolved record | 8 |

The private rubric contains 9 planted errors, 8 true controls, and 3 inaccessible
claims. New task claim IDs are opaque and ordered without alternating positive
and negative cases. The live workspace receives source packets and prompts;
`gold.json`, manifests, reference responses, graders, and scorer tests stay in
the evaluator's checkout. These are controlled instruction-following tasks,
not a blind held-out benchmark or a security-isolated evaluation.

## Calibration and optional live runs

Run these commands from the repository root:

```sh
python -m evaluation validate --require-coverage
python -m pytest --import-mode=importlib skills/cite-check/evals/tests -q
python -m evaluation run --runner replay --skill cite-check --repeats 3
python skills/cite-check/evals/score.py .eval-runs/RUN/report.json --repeats 3
python skills/cite-check/evals/score.py .eval-runs/RUN/report.json --repeats 3 --format markdown
```

Replace `RUN` with the directory printed by the shared runner. Replay copies
reference answers and verifies the fixture/grader plumbing. A perfect replay
score establishes **no agent performance**. Negative-output tests check that the
graders and report reject known mistakes, missing responses, and stale results.

To evaluate an installed agent, first copy `evals/runners.example.json` to the
ignored `evals/runners.local.json`. Inspect and adapt the selected command,
model, native permissions, and capability declarations for your installation.
These commands use the shared adapters; no model run happens merely by scoring
an existing report:

```sh
python -m evaluation run --runner claude --allow-live --skill cite-check --repeats 3
python -m evaluation run --runner codex --allow-live --skill cite-check --repeats 3
python -m evaluation run --runner antigravity --allow-live --skill cite-check --repeats 3
```

Each command is a separate optional live run and may consume paid tokens.
Record CLI/model versions in the local runner description. Score each returned
run directory separately with the same `--repeats` value used when running it.
The output labels replay and live observations separately. Even a successful
live run establishes performance only on this finite synthetic suite. Shared
reports remain the source for latency, resource usage, and repeated-trial
consistency; unavailable telemetry stays unknown.

## Metrics and denominators

The scorer reports a record for every expected `(case, repeat, claim)` slot,
per-case summaries, and pooled counts. It does not drop an observation because
the runner was blocked, failed, timed out, or produced invalid output.

| Metric | Numerator | Denominator |
| --- | --- | --- |
| `exact_verdict_accuracy` | Exact four-way verdict matches | All expected claims |
| `planted_errors_detected` | Planted errors flagged as contradicted or unsupported | All planted errors |
| `planted_errors_missed` | Planted errors not flagged, including missing or invalid verdicts | All planted errors |
| `false_accusations_on_controls` | Supported controls flagged as contradicted or unsupported | All true controls |
| `controls_unassessed` | Controls omitted, invalid, or marked unverifiable | All true controls |
| `omitted_claims` | Claim IDs absent from usable output | All expected claims |
| `invalid_claim_outputs` | Present claim entries with an invalid or missing verdict | All expected claims |
| `verbatim_evidence_spans` | Nonblank quotations found exactly in the cited source | All readable claims |
| `evidence_anchor_matches` | Verbatim quotations containing the private fixture's relevant literal phrases | All readable claims |
| `inaccessible_triage` | Inaccessible claims correctly marked unverifiable | All inaccessible claims |
| `inaccessible_evidence_restraint` | Inaccessible claims explicitly returning an empty evidence string | All inaccessible claims |
| `false_accusations_on_inaccessible` | Inaccessible claims asserted to be contradicted or unsupported | All inaccessible claims |

Detection and exact classification are different: flagging a contradiction as
unsupported detects an error but does not earn an exact-verdict match. A quote
can be verbatim yet irrelevant; the two evidence metrics expose that difference.
Anchor matching is a narrow lexical oracle, **not general semantic entailment**.
Read exact verdict and evidence results together. Empty or whitespace-only
quotations do not count as valid spans. No evidence is required where text is
unavailable; invented quotations reduce the separate restraint metric.

A low false-accusation rate is insufficient by itself: an agent that produces
nothing has zero false accusations and every control unassessed. Missing and
invalid output instead reduce accuracy, detection, and evidence coverage.
Unexpected claim IDs are listed in each trial; they do not expand the gold
claim denominator or replace omitted claims.

The explicit `--repeats N` defines the expected full cite-check suite schedule,
including missing whole cases and repeats. It is required because shared report
schema v1 does not store the requested repeat count. The scorer cannot infer the
operator's intended schedule; pass the same count used for the run. Observed
repeats outside `1..N`, duplicate or unknown citation trial IDs, and runs with no
citation trial establishing fixture compatibility are rejected.

Only completed shared trials (`pass` or `fail`) have their outputs scored.
Outputs left behind by `blocked`, `error`, or `timeout` trials are ignored;
all their claims remain unobserved in the denominators. Missing, malformed,
duplicate-key, or oversized response JSON likewise leaves the trial's claims
omitted. A valid `claims` object with an invalid individual entry instead counts
that entry as an invalid claim output. JSON report fields preserve both trial
and response statuses so these causes remain distinguishable.

## Compatibility and storage

Every supplied citation trial must match the current combined fixture/grader
and shared-framework fingerprint. Runner configuration fingerprint and seed
must be present. Any change to the cite-check `evals/` tree, including gold,
grader, scorer, tests, or this documentation, invalidates earlier results
conservatively. Score old runs with the matching checkout; never silently apply
new gold to old results. Fingerprints are provenance metadata, not tamper-proof
attestation. Changing the skill source itself is permitted by the shared
comparison contract because measuring skill changes is its purpose.

Response paths are derived from validated manifest IDs and explicit repeat
indices under the supplied report's directory. Reads reject symlinks, special
files, and outputs larger than the shared configured bound. Report input is
limited to 16 MiB. The scorer does not follow arbitrary paths supplied in report
records. Its JSON output contains observations, not raw response/source text.

The scoring CLI prints JSON or Markdown to stdout and returns 0 when scoring
succeeds, even if the measured results are poor; exit 2 means incompatible or
invalid input. Inspect the separate metric counts when applying a quality gate.
Use shared `evaluation compare` for compatible baseline regression checks.
Keep generated reports under ignored `.eval-runs/` or another untracked output
location. Do not commit run logs, live responses, or local credentials.

This upgrade does not exercise live registry lookup, PDF/full-text retrieval,
BibTeX export, MCP transport, or general claim entailment. Those require separate
integration tests and additional evidence-grounded tasks.
