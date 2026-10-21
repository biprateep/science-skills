# Source extraction quality

`fetch_text` and `find_passages` report extraction quality alongside the evidence
basis. A source being labeled `fulltext` describes where it came from; it does
not establish that its extracted text is readable or complete.

## Read the quality result before judging

The versioned `quality` assessment distinguishes `no-known-defect`, `poor`,
`unreadable`, `truncated`, and `unknown`. It includes diagnostics, measured
properties, and `usable_for_judgment`. A result without a known extraction defect
still needs an independent scientific judgment and exact evidence quotes.
`document_completeness` remains `unknown`: these checks cannot prove that a
publisher supplied every section, figure, equation, or page of the work.

`input_complete` concerns the bounded acquisition/extraction operation. It is
not a statement that the scientific document is complete. Deliberately removing
a trailing reference list during normalization is recorded separately from an
unexpectedly interrupted or truncated source.

`preview_truncated` concerns only the inline preview requested with `max_chars`.
A shorter preview does not damage the cached source and does not imply that
source acquisition stopped early. Read additional passages or the cached text
when the preview is insufficient. `find_passages` marks retrieval as partial:
its ranked windows are selected excerpts, not a full reading of the paper.

## Evidence and audit behavior

Unusable or unknown-quality source text cannot establish a support judgment.
Use `UNVERIFIABLE` with a specific explanation, obtain a readable copy, and
refresh the source before judging again. An unreadable paper is not evidence
that a claim is false or absent from the paper.

Quality policy and assessment are bound into source identity. A changed source
or quality assessment invalidates old judgments. Strict audits require usable
source quality as well as the existing identity, official bibliography, evidence
basis and quote checks. Producing a correction report does not relax this gate.

Older cache artifacts without acquisition-quality metadata remain unknown;
refresh them rather than treating their existence as a successful extraction.
Current cache reads are bounded and their text is inspected under the current
quality policy.

## Bounded acquisition

Network response bodies are read in bounded chunks. Both declared response
sizes and actual bytes are checked, including responses without a reliable
`Content-Length` and HTTP error bodies. A failed or oversized download is not
published as a complete cached response or PDF.

Local source files are bounded before extraction. PDF extraction runs in an
isolated subprocess with file, page, text-output and time limits. These limits
bound accepted inputs and execution time; they are not a hard process-memory
sandbox or a guarantee that every scientific symbol survives PDF extraction.
A scanned or otherwise unreadable PDF needs a better text source or a separate,
reviewed OCR workflow.

Acquisition failures can lead to an abstract-only fallback. Read its diagnostics
and `basis`; an abstract does not become full-text evidence because a PDF request
was attempted first. Existing request/deadline budgets continue to apply.

## Current limits and diagnostics

| Operation | Limit |
|---|---|
| Default HTTP response | 8 MiB |
| PDF input/download | 20 MiB |
| Local or extracted source text | 2 MiB |
| PDF pages | 500 |
| PDF worker time | 30 seconds, or the remaining active deadline |

The readability check is deliberately language-independent: no alphanumeric
characters means unreadable; fewer than 20 means poor. A Unicode replacement
character or a non-whitespace control character is a corruption warning that
blocks evidence use. These checks do not measure scientific relevance or
correctness.

An empty extracted PDF page is a conservative quality failure. It may be an
intentional blank page, a scanned page needing OCR, or a failed extraction.
Inspect the source and supply a reviewed readable text copy rather than assuming
that the missing page is irrelevant. The tool does not infer which explanation
is correct.
