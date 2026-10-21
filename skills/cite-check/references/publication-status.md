# Retractions, corrections and publication status

Cite-check retains post-publication update metadata supplied by Crossref.
Publication status is separate from identity, official export integrity and
claim support: a retracted paper can still be a real, correctly identified work.

## Direction and source

Crossref's `updated-by` relations describe updates affecting the current work.
Its `update-to` relations describe works updated by the current item, which may
be a correction or retraction notice. A notice is not itself retracted merely
because it reports another paper's retraction. Both directions are retained,
including an item that is itself updated or an in-situ update with the same DOI.

Relations retain the affected work, notice identifier, update type/date and
provider attribution. Crossref distinguishes publisher deposits from its
Retraction Watch enrichment; cite-check preserves that distinction. It does
not infer retraction from a title, search ranking or an unverified comment.

The implementation uses the existing bounded Crossref metadata request and
cache. It does not launch an unbounded search for related notices. Other
registries' identity records do not silently become Crossref status evidence.

## Meaning and policy

A reported retraction prevents strict submission readiness. Corrections and
expressions of concern prompt explicit review of the notice and the affected
claim; they do not by themselves prove every claim in the paper false. The
ordinary independent support judgment remains required. No bibliography or
manuscript text is rewritten automatically.

A successful Crossref record without update relations means only that no
updates were reported in that record. It is not a certificate that the work
has never been corrected or retracted. Unsupported registries, unavailable or
malformed metadata and incomplete relation processing remain explicit. An
unknown status does not turn an identity result into a fabrication finding.

Status information appears with resolved/verified records and in audit/report
findings. Coverage remains three separate axes: existence, export provenance
and support. Status warnings do not claim comprehensive retraction coverage.

The structured states are `RETRACTED`, `CORRECTED`,
`EXPRESSION_OF_CONCERN`, other `UPDATED`, outgoing `NOTICE`,
`NO_UPDATES_REPORTED` and `UNKNOWN`. `complete` describes processing of the
supplied metadata, not exhaustive knowledge of the work's history. An incomplete
record can still contain a valid retraction that blocks strict readiness.

## Freshness and bounds

The observation time is when cite-check inspected the metadata, which may have
come from cache; it is not a claim that a network fetch occurred at that instant.
The response describes the configured cache policy. HTTP and normalized-record
cache reuse can compound; the default metadata TTL is 14 days per layer. It is
not an overall source-age guarantee. Registry deposits themselves can lag a
publisher's update, and the data can change after an audit.

Each direction processes at most 100 relations. Truncation or malformed siblings do not erase
an already observed retraction or make incomplete metadata appear clear.
For consequential decisions, read the linked notice and confirm the current
publisher record. A retraction/reinstatement sequence is not resolved by
silently discarding adverse history.

## Upstream contract

- [Crossref: registering updates](https://www.crossref.org/documentation/register-maintain-records/maintaining-your-metadata/registering-updates/)
  explains notice-to-work direction and in-situ updates.
- [Crossref: Retraction Watch data](https://www.crossref.org/documentation/retrieve-metadata/retraction-watch/)
  explains publisher and Retraction Watch attribution and coverage limits.
- [Crossref: production replacement for its Labs data](https://www.crossref.org/labs/retraction-watch/)
  points to `updated-by` in the current production API. The obsolete Labs
  annotations are not used.

Tests use deterministic local fixtures shaped like these documented records;
passing them does not establish live provider availability or exhaustive
retraction coverage.
