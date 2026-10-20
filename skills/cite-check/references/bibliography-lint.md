# Advisory bibliography lint

Use `lint_bib` to review bibliography metadata quality separately from
citation identity, official-export provenance and scientific support. The
tool does not change the bibliography, write a support judgment, or alter
the audit gate. Its default mode is offline.

```json
{
  "bib_path": "/project/refs.bib",
  "keys": ["example2020"],
  "verify": false
}
```

Omit `keys` to inspect all entries; `keys=[]` selects none. The input must
be a regular UTF-8 file of at most 4 MiB with at most 2000 entries. The
whole file is parsed even when a subset is selected. Native MCP and CLI use
the same API:

```sh
python <skills>/cite-check/mcp/server.py call lint_bib '<json>'
```

## Read the result by scope

| Field | Meaning |
|---|---|
| `ok`, `input_complete` | The requested input was processed successfully; metadata advice can still be present. |
| `advisory_only` | Always true: this tool does not issue citation-integrity verdicts. |
| `advisory_clean` | No advisory issues were found in the inspected scope; this is not proof of bibliographic or scientific correctness. |
| `comparison_complete` | Null in offline mode; when requested, whether applicable selected registry comparisons could be completed. Non-work helper entries are not applicable. |
| `submission_ready` | Always false; only the ordinary strict audit can establish readiness. |
| `issues` | Stable diagnostic codes, affected entry/field, explanations and next actions. |

Each issue identifies the inspected entry's file, one-based source lines,
and zero-based, end-exclusive character and UTF-8 byte offsets. The location
scope is the whole entry, not an invented precise field span. Locations and
the input digest come from the same strict UTF-8 snapshot, preserving CRLF
and Unicode offsets. Re-run after changing the file. A concurrent change
during inspection prevents a successful current result.

Malformed syntax, duplicate keys, invalid UTF-8, missing requested keys and
input-limit failures are processing failures, never an empty clean report.
The CLI follows processing success: advisory issues can accompany exit 0.
Inspect the result fields rather than treating the exit code as approval.

## Offline advice

Rules consider entry type and common alternative fields. An article's venue
may be `journal` or `journaltitle`; a date may use `year` or `date`. Books,
proceedings, software, datasets and online material have different metadata
needs. Non-work helper entries and custom styles cannot be judged by an
article-only checklist. Unknown types prompt a style review, not a claim
that the cited work is invalid.

Date and future-year advice is deliberately separate from identity. A
future publication date can be legitimate, and complex date expressions
may require the bibliography processor's own interpretation. Abbreviated
venues, eprints, article numbers and intentional preprint citations are not
automatically mistakes.

BibTeX macros and field inheritance are not fully expanded. Unresolved
values receive `field-macro-unexpanded` or `inheritance-not-expanded`
advice; the tool must not turn an unknown inherited value into a claim that
the field is absent. Review these with the project's bibliography processor
and style. The linter is a conservative metadata aid, not a replacement for
BibTeX/Biber validation. The maintainer's
[BibLaTeX examples](https://github.com/plk/biblatex/blob/dev/bibtex/bib/biblatex/biblatex-examples.bib)
illustrate supported alternative fields and macro usage; the
[package documentation](https://www.ctan.org/tex-archive/macros/latex/contrib/biblatex/)
describes the broader data model and inheritance behavior.

## Optional registry comparison

Set `verify=true` explicitly to compare metadata through each entry's own
identifiers. The tool does not search by title to find a substitute and does
not read an old `verify.json` as proof. It uses the existing resolver and
normal cache policy; a lookup is not necessarily a fresh network request.
Reported identifier lookup counts do not measure physical HTTP requests,
tokens or billed cost.

Publication, year and venue advice requires a confirmed identity and
applicable registry metadata. A mismatched, unresolved, misrouted or
insufficiently identified result cannot justify an update. Missing
identifiers, failed lookups and recognized but unchecked version pins remain
explicit and prevent complete optional comparison. A preprint/publication suggestion
requires an explicit registry cross-link; title resemblance alone is not
enough. The `identifiers_requested` list and `identifier_count` describe
the resolver's requested identifiers. Outcomes distinguish compared entries
from unavailable, unconfirmed, skipped and not-applicable work; helper
entries such as `@xdata` and `@set` do not require a work identity.
A published alternative does not establish support for the sentence
or automatically supersede the edition the author intentionally cited.

Review advice against the work and the target journal's requirements. If a
change is appropriate, fetch its official export with `bib_add` or
`fetch_bibtex`; do not compose missing fields or replace identifiers from
memory. Repeat source/version checks and independent judgments where the
cited edition changes, then run the normal submission-ready audit.

## Stable advisory codes

| Code | Review needed |
|---|---|
| `missing-field` | A type-specific field or accepted alternative is absent. |
| `unknown-entry-type` | The type has no local rule set; check the project's style. |
| `invalid-year` | A literal year/date is outside the supported syntax. |
| `future-year` | Confirm a future or forthcoming date in the official source. |
| `field-macro-unexpanded` | Resolve a macro/concatenation with the bibliography processor. |
| `inheritance-not-expanded` | Inspect fields inherited through `crossref` or `xdata`. |
| `registry-comparison-unavailable` | The requested comparison could not be completed. |
| `registry-identity-unconfirmed` | Metadata or identifier aliases do not establish the same work. |
| `registry-version-unchecked` | Latest metadata cannot stand in for the recognized version pin. |
| `registry-year-difference` | Confirm which same-work publication date is intended. |
| `preprint-publication-review` | Review a registry-linked published alternative while preserving intentional editions. |
