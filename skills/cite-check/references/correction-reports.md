# Actionable correction reports

Use `correction_report` when the user wants to review citation problems,
choose a correction, or inspect an annotated copy. It runs one fresh audit
with the usual strict default; it never reads an old `audit.json` as current.

```json
{
  "tex_path": "/project/main.tex",
  "bib_path": "/project/refs.bib",
  "policy": "submission-ready",
  "annotated": true
}
```

Call it through native MCP or CLI:

```sh
python <skills>/cite-check/mcp/server.py call correction_report '<json>'
```

The fixed outputs under the main manuscript's `.cite-check` directory are
`corrections.json`, `corrections.md`, and (with `annotated=true`)
`corrections.html`. The ordinary audit artifacts are also refreshed. The
original manuscript, included files, bibliography and fetched source text
are never rewritten. Output aliases, hard links to inputs and symlinked
report directories are refused before the audit can write artifacts.

`report_written=true` means the report artifacts were generated. `ok`,
`policy`, `input_complete`, `complete`, `submission_ready` and coverage retain
the audit's meaning. A negative verdict can therefore produce useful reports
with `report_written=true`, `ok=false`. CLI exits 1 for that result; parse its
JSON instead of discarding it. An exploratory report never establishes
submission readiness. Missing/unreadable inputs produce diagnostic JSON and
Markdown with unknown locations; an incomplete snapshot has no HTML copy.

## Finding fields

Each correction contains a stable `finding_id`, severity/type, citation key,
`occurrence_id`, `sentence_id`, optional `atom_id`, full extracted `claim`,
full surrounding `context`, and the exact disputed `assertion`. Repeated
citations with the same words and key remain separate occurrences. Missing
judgments and unsupported claims do not get invented quotations.

`location` identifies the current manuscript citation command where known,
with one-based line and zero-based, end-exclusive source byte offsets. An
uncited atomic span can have a reported sentence location without an invented
citation occurrence. `bibliography_locations` contains every matching parsed
entry, including duplicates and uncited entries: file, one-based line,
Unicode-codepoint span, and UTF-8 byte span from the same audit snapshot.
Unknown locations are null or an empty list; no path or line is guessed.

`source_evidence` contains the bound source identity/version/basis and exact
source spans, locally rechecked against the same cached text. Its separate
`attribution` is `verified` only when the current bibliography verification
is VERIFIED; an exact quote alone does not establish attribution. Stale or
unbound evidence and proposals are omitted. Invalid stored quote/proposal
structures fail closed as input diagnostics. `next_action` is deterministic
advice, such as obtaining full text, resolving bibliography identity or
supplying a missing judgment. It is separate from scientific replacement
wording. Declared uncited scope remains visibly unverified.

HTML contains escaped source text with line anchors, highlighted findings
and links in both directions. It includes bibliography sources where read
successfully. It is a static copy, with no scripts or remote assets; embedded
HTML/TeX is inert text. Markdown puts untrusted fields in JSON code fences.
Snapshot checks bind rendering to the audited manuscript, bibliography,
ledger and source evidence. If any changes before publication, generation
fails with `report_written=false`; evidence/drafts are suppressed and the
caller must rerun. Existing artifacts remain historical snapshots and must
not be reused as a fresh report merely because a new attempt failed.

## Optional judge-authored proposals

The independent judge can add `proposed_correction` to an otherwise valid
`record_support` call for PARTIAL, UNSUPPORTED, CONTRADICTS or UNVERIFIABLE:

```json
{
  "action": "revise-claim",
  "rationale": "The source reports the result only for the tested sample.",
  "replacement_text": "<judge-authored wording justified by the evidence>"
}
```

This is a nested optional object; all prior calls remain valid. Allowed actions
are `revise-claim`, `replace-citation`, `remove-claim`, `obtain-text`.
`rationale` must be a substantive string. Only `revise-claim` permits a
nonempty `replacement_text`, and only with a found source quote. Citation
commands/markers are refused in that wording. Other actions describe an
intended next step without supplying replacement scientific text or invented
citation identifiers. A real but inadequate source cannot generate a new
bibliography entry: identify an alternative with the normal registry tools
and obtain its official export separately.

An explicit current `tex_path`/`occurrence_id`, a nonempty `judge` label and,
in atomic mode, the registered `atom_id` are required. The proposal shares
the judgment's sentence/context, atom/decomposition and source/version
bindings. It is never inherited through legacy occurrence matching. The
runtime cannot certify judge independence; the skill's separate-invocation
or later independent-pass requirement still applies.

The stored proposal includes its author and fixed `approval="unapproved"`,
`replacement_verified=false`; every finding has `applied=false`. These are
not client-settable approval switches. A verified original quote does not
verify the proposed wording. The report only presents the draft for human
review. Applying a chosen correction requires the ordinary extraction,
registration, independent judgment and strict audit again; no auto-pass or
automatic rewrite is provided.
