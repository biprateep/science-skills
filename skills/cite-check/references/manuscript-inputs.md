# Manuscript inputs and explicit citation mappings

The existing `tex_path` parameter now means the main manuscript path. Format
selection follows the file extension: `.tex`, `.md`, `.markdown`, `.txt`, or
`.pdf`. Existing TeX calls keep their interface. Extraction reports the
observed occurrences, original assertion/context, source locations and
format-specific diagnostics. Repeated citations remain separate instances.

Input recognition is not a claim that every citation has been found. Inspect
`scope_complete`, `review_only` and `diagnostics` from extraction, then the
audit's explicit readiness fields. An uncertain inventory keeps
observed obligations visible while leaving the total unknown; it cannot
become a clean zero-citation audit. Input processing, scientific support and
submission readiness remain separate.

## TeX and inline bibliographies

Ordinary TeX citation commands and included files retain the existing
workflow. The tool also extracts `thebibliography` / `bibitem` reference
records with their original text and locations. Bibliography text is excluded
from claim prose, so a reference list is not mistaken for manuscript claims.

Inline reference text is not an official BibTeX export. It remains available
for review, but strict readiness is blocked even when an external official
`.bib` contains the same keys. For example, a printed `bibitem{a}` naming
one paper cannot be certified by a sidecar entry `a` naming another paper.
The original record must not disappear behind a key match.

Review each printed reference's intended identity, obtain the official
exports through the ordinary tools, and migrate the manuscript to use those
entries if submission-ready checking is required. Re-extract the changed
manuscript and repeat affected atomic judgments. Merely passing a sidecar
path does not perform that migration or validate printed metadata.

## Markdown and plain text

Use explicit bibliography-key markers such as `[@example2020]`,
`[@first2020; @second2021]`, and narrative `@example2020`. These keys identify
entries in the supplied
official bibliography; they are not guessed DOI or author-year identities.
Occurrences in code or comments are excluded, and extraction preserves
offsets in the original file. Unsupported or malformed citation syntax and
unmapped candidate markers remain diagnostics instead of being silently
dropped.

For supported explicit-key input with known citation scope, use the normal
`extract_cites` → `register_claims` → independent judgment → `record_support`
workflow, then `audit(tex_path=..., bib_path=..., policy="submission-ready")`.
All existing evidence and official-export requirements still apply. Readiness
depends on the returned strict flags, not simply the file extension or the
presence of one recognized citation.

Printed reference definitions, embedded front-matter `references` records,
and a `References` or `Bibliography` heading are retained as unverified
reference text. A heading conservatively marks
the rest of that text view as a reference block. These inputs remain
review-only even if an official sidecar uses matching keys; migrate the
printed references before seeking strict readiness. Ordinary Markdown URL
link definitions are not bibliography entries.

## Numeric and author-year mappings

`register_input` records explicit interpretations of citation markers whose
bibliography keys cannot be derived safely. The caller supplies exact source
spans and a substantive reason; the tool does not infer a work from a name,
year or reference number.

```json
{
  "tex_path": "/project/manuscript.pdf",
  "citations": [
    {"page": 2, "start": 143, "end": 146, "marker": "[1]", "key": "example2020"}
  ],
  "reason": "The displayed reference numbered 1 is the entry being reviewed as example2020."
}
```

The offsets in this example are illustrative; obtain the actual current
text and positions first. Spans use zero-based, end-exclusive Unicode
character offsets; PDF pages are one-based. Non-PDF text uses source-text
positions. Every marker must exactly match its span. Distinct keys attached
to the same complete marker must be explicit; overlapping interpretations
and duplicate attachments are refused.

A registration accepts at most 2,000 mappings and its serialized manifest
must fit within 1 MiB. Invalid or oversized registrations leave an existing
manifest unchanged. Repeating identical registration data preserves its
content digest.

Mappings are saved under ignored `.cite-check` state and bound to the input
snapshot and extraction policy. PDF mappings also bind the extracted page
text and extractor fingerprint. Changed inputs, mappings or extraction
require re-registration and fresh affected judgments. An empty mapping
does not certify citation completeness.

Mapped numeric/author-year input remains review-only. A mapping identifies
the caller's intended key, not the reference's verified identity or a complete
inventory. Use the existing registry and evidence tools to review known
instances. For strict checking, normalize the manuscript to the supported
explicit-key format and its official bibliography, then re-extract and audit.

## PDF page extraction

PDFs are read page by page with the installed PDF extractor in an isolated
process. Limits are 20 MiB of input, 500 pages, 2 MiB of extracted text and
a 30-second worker timeout. Encrypted, unreadable, empty, scanned or
over-limit inputs receive explicit diagnostics. OCR and layout interpretation
are not silently invented. No extracted text does not mean no citations.

The PDF binary digest is separate from the extracted page-text digest and
extractor/version/options fingerprint. Locations identify the page and
extracted-text span; binary-PDF byte offsets are null. Extraction can reorder
columns, lose glyphs or merge text. All PDF inputs therefore remain review-only
and cannot produce strict submission readiness, even after known markers
are mapped and their claims are independently assessed.

Correction reports can present observed assertions and evidence without
promoting unknown scope to complete. An annotated copy uses escaped extracted
page text and page locations; it is not a rewritten PDF or a guarantee of
visual-layout fidelity. Original manuscript and bibliography files remain
unchanged. Audit, report and job snapshots include the input and mapping
state so later edits cannot silently reuse old completion.

Native MCP and CLI expose the same tools and arguments. To call through CLI:

```sh
python <skills>/cite-check/mcp/server.py call extract_cites '{"tex_path":"/project/manuscript.md"}'
python <skills>/cite-check/mcp/server.py call register_input '<mapping JSON>'
```
