# Export digests and bibliography integrity

A provenance comment identifies a claimed source. It does not establish that an
entry still matches what that source exported. Cite-check now records a local
receipt when it fetches an official export and checks that receipt during audit.

## What the receipt records

A versioned receipt binds:

- The original registry export text before cite-check sanitization, and its
  SHA-256 digest. This is decoded export text, not a capture of TLS wire bytes.
- The exact emitted BibTeX entry, its key and digest after the tool's permitted
  encoding repairs, layout and key replacement.
- The source, canonical identifier and aliases, request/version information,
  export options, and the record snapshot used by the transformation.
- The transformation policy and acquisition date.

The receipt is stored under the SHA-256 digest of its canonical JSON content.
The entry's adjacent provenance comment contains the receipt and export/entry
hashes. Validation checks the receipt content, identifier/version bindings,
entry bytes, and the derivation from the stored export using the recorded
transformation inputs. A checksum written into a comment alone is insufficient.

GitHub and CITATION.cff retain the existing software-export exception: the tool
lays out the authors' public metadata as BibTeX. These receipts explicitly label
the input as a tool-generated software entry and retain the underlying record
snapshot. They do not pretend GitHub supplied a registry BibTeX response.

## Edits and migration

The emitted entry is exact. Changing a title, identifier, year, citation key,
field order, spacing or line endings changes its digest. Request the desired key
and supported export options through `fetch_bibtex` or `bib_add`; re-export an
entry rather than editing the checksum to make a changed entry pass.

Legacy source/date comments remain declarations. They can be displayed in an
exploratory audit, but they no longer meet strict export-integrity requirements.
Use an official re-export under the same key to create a receipt. Identity
verification and claim support remain separate requirements: a valid receipt
does not prove that the cited work supports the sentence.

Missing, corrupt, mismatched or altered receipts and edited entries are reported
explicitly. Exploratory mode does not turn a mismatch into verified provenance.
Audit coverage distinguishes declarations from digest-verified entries. States
include `VERIFIED`, legacy `DECLARED`, missing receipt `MISSING`, corrupt receipt
`CORRUPT`, changed entry `EDITED`, identity/binding `MISMATCH`, and malformed
provenance `MALFORMED`, alongside `UNOFFICIAL` and `UNDEFINED`.
`verified`/`verification_rate` count validated receipts;
`declared`/`declaration_rate` describe declarations separately.

## Storage and freshness

`fetch_bibtex` stores receipts in the citation cache's `exports` directory.
`bib_add` also copies the receipt into `.cite-check/exports` beside the
bibliography before committing the entry. A failed transaction can leave an
unused receipt; it must not leave an accepted entry without its proof.

An adjacent project receipt takes precedence over the global cache. A corrupt
project receipt is not silently replaced by a valid global copy. Audits snapshot
receipt state and check it again before publishing their result, so a concurrent
proof change cannot leave an apparently current success.

Receipts are runtime artifacts and remain ignored by repository source control.
When moving a bibliography to another machine, retain its adjacent receipts or
re-export there. A comment by itself is not portable proof.

Receipt reads are bounded to 4 MiB; individual export and entry text to 1 MiB.
Missing or malformed proof fails closed. The hashes provide local integrity and
provenance traceability, not a registry's digital signature or protection against
someone deliberately rewriting all trusted local artifacts.
