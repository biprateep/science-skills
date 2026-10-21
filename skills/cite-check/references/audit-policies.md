# Audit policies and coverage

`audit(..., policy="submission-ready")` is the default completion gate.
`policy="exploratory"` reports partial progress. Both produce the same
coverage structure and preserve missing, failed, stale, and inaccessible
work in the denominator. Neither rewrites the manuscript or bibliography.

| Field | Meaning |
|---|---|
| `input_complete` | All required manuscript/bibliography inputs were parsed without missing files, undefined keys, or ambiguous duplicate entries. |
| `complete` | Every current requirement has an assessed outcome and the input snapshot remains current. Negative verdicts and inaccessible-source triage are assessed outcomes; this does not mean verified. |
| `ok` | No blocking findings under the selected policy. Exploratory `ok` is progress, not completion approval. |
| `submission_ready` | Literal `true` only under the submission-ready policy with all strict requirements satisfied. |
| `coverage` | Separate existence, provenance, and support axes; no composite score. |

A caller reporting finished work must require the exact policy
`"submission-ready"` and literal `true` for `ok`, `input_complete`,
`complete`, and `submission_ready`. Missing fields and older reports do not
establish readiness. Re-run the audit on the final manuscript.

## Submission-ready

Every cited bibliography entry must be `VERIFIED`, with a well-formed
provenance declaration naming a known export source, identifier, and fetch
date, plus a valid digest-bound export receipt. Its identifier must match the
verified work or one of its resolved aliases. The receipt checks the original
export, permitted tool transformations and exact current entry. Legacy
comments alone, missing/corrupt receipts, edited entries, `FOUND`/`PROBABLE`,
and identifier disagreements require resolution before submission. See
`export-provenance.md` for storage, migration and the local-integrity limits.

Every current atom/occurrence must have a fresh `SUPPORTS` judgment from
full text with usable extraction quality. A verified canonical GitHub repository may instead use its
primary README/CITATION.cff record (`basis="readme"`); the judge still must
check the exact cited property and version. A README cannot certify a paper.
Abstract-only `SUPPORTS` remains limited evidence and does not establish
submission readiness, even when sufficient for exploratory assessment.

`PARTIAL`, `UNVERIFIABLE`, `UNSUPPORTED`, `CONTRADICTS`, missing judgments,
stale source/context, and missing atomic registrations prevent readiness.
`verify=false` or `require_support=false` cannot weaken this policy: the
report contains a configuration failure. Explicitly uncited author/context
atoms remain visible and unverified; they are not citation-support successes
and do not falsely require a paper to support the authors' own results.

## Exploratory

Unverified existence, undeclared provenance, partial support, inaccessible
sources, and limited evidence remain visible. Known contradictions,
unsupported claims, identity failures, malformed inputs, and stale judgments
remain failures. Missing judgments also fail when `require_support=true`
(the default); pass `false` explicitly for a partial progress report.
Exploratory reports always set `submission_ready=false`, even if their
assessments happen to meet all evidence criteria.

## Coverage units

- **Existence:** every cited key, including undefined keys and absent registry
  result rows. Counts distinguish `VERIFIED`, `FOUND`, `PROBABLE`,
  `MISMATCH`, `NOT_FOUND`, `UNRESOLVED`, `UNCHECKED`, and `UNDEFINED`.
- **Provenance:** every cited key, checked directly from parsed entries even
  with `verify=false`. Counts distinguish digest-verified entries, legacy
  declarations, missing or corrupt receipts, edited entries and identity
  disagreements. `declared` and `declaration_rate` remain separate from
  verified counts; `assurance` describes local export-integrity checking,
  not a registry's digital signature.
- **Support:** every current atom/citation attachment, or a whole-sentence
  occurrence outside atomic mode. Missing and stale work stays expected;
  inaccessible triage is `INACCESSIBLE`. `basis_counts` distinguishes the
  evidence read. `verified` counts adequate current `SUPPORTS` only.

An unresolved atomic registration contributes an unresolved citation
placeholder. The number of future semantic atoms is unknown:
`unresolved_decompositions` remains visible and `atomic_total_known=false`.
A rate over these placeholders is not a claim of complete atomic coverage.
All rates use explicit expected denominators; zero obligations use `null`
rates. Extraction failure reports unknown expected totals as `null`, not
zero or a vacuous success. A citation-free document with no declared
bibliography has zero citation obligations; missing declared bibliographies
still fail. `\nocite{*}` checks every bibliography entry's existence and
provenance but introduces no claim-support obligations.

Before publishing a report, the audit rechecks manuscript, bibliography,
ledger, and assessed source snapshots. Concurrent changes yield
`audit-stale`, `complete=false`, and `submission_ready=false`; retry against
the current files. Generated reports stay under `.cite-check/`.

## Actionable findings

Audit JSON includes full `corrections` alongside the compact failure list.
Use [correction_report](correction-reports.md) for JSON, Markdown and optional
annotated HTML artifacts from a fresh audit. `report_written` is independent
of `ok` and readiness. Missing or stale evidence receives next actions, never
fabricated replacement text; a stale publication suppresses quotes and drafts.
