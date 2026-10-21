# Calling cite-check from another skill (co-writer, co-scientist, …)

cite-check is the one citation engine in this repository. A writing or
research skill does not verify citations itself; it calls these tools and
treats their results as the verdict. The contract below is what a caller
must do, must not do, and may rely on.

## Tool access

1. If the harness lists the tools (Claude Code: `mcp__cite-check__*`; other
   harnesses: server `cite-check`), call them directly. Claude Code may list
   them by name only, as deferred tools; load them (`ToolSearch`,
   `select:mcp__cite-check__ping`) — that is not the same as absent.
2. Otherwise run `bash <skills>/cite-check/mcp/setup_mcp.sh` once (idempotent;
   registers the server for the next session) and for the current session use
   CLI mode, which is the same code:
   `<skills>/cite-check/mcp/.venv/bin/python <skills>/cite-check/mcp/server.py call <tool> '<json>'`
   (exit 0 = pass, 1 = fail/blocked; JSON on stdout).
3. `ping` tells you whether an ADS token is present. Astronomy manuscripts
   without one lose ADS search and export; say so to the user once.

## Manuscript formats and citation scope

The historical `tex_path` argument accepts the supported manuscript formats;
callers must inspect extraction diagnostics and citation-scope completeness
before claiming a complete inventory. Explicit Markdown/plain-text key
markers can feed the same atomic registration, independent judgment and
audit workflow. Pass the official bibliography explicitly where needed.

PDF page extraction and manually mapped numeric/author-year citations are
review inputs. `register_input` binds exact marker spans to keys, not to a
verified work identity; changing the source, extraction or mapping invalidates
the prior mapping/obligations. Inline bibliography entries remain original
printed-reference evidence. A same-key official sidecar cannot establish that
their displayed text is correct. These review limits prevent strict readiness
and cannot be overridden by successful lookups or support judgments.

Relate observed instances and remaining unknown scope separately. Missing or
unreadable PDF text is not a citation-free document. PDF locations are page
and extracted-text positions, never purported binary-PDF byte offsets. Use
[manuscript-inputs.md](manuscript-inputs.md) for supported syntax, mapping
arguments, uncertainty and migration guidance.

## When the caller adds a citation

For broader discovery, explicitly select `semanticscholar`, `pubmed` or
`dblp` in `search_citation.registries`. Their provider-qualified IDs are
discovery locators, not export identifiers. Review the candidate, resolve a
reported `suggested_ids` identifier through the ordinary registry workflow,
then obtain the official export and independent support judgment. A high
search score never changes `verification_status: "unverified"`. See
[literature-sources.md](literature-sources.md) for limits and provenance.

```
search_citation(title=…, author=…, year=…)      # or hint="Smith2019", context="<the sentence>"
   → pick a candidate (confidence high, or the user confirms a medium one)
bib_add(bib_path, items=[{"identifier": <candidate id>, "key": <cite key>}], tex_path=…)
   → status added | exists | duplicate (use existing_key) | no-official-bibtex (do not cite)
write the sentence with \cite{<key>}
support check for that instance (below) before the section is called done
```

Software follows the same chain: a GitHub URL (or
`search_citation(title=<package>, registries=["github"])`) →
`bib_add(items=[{"identifier": "github.com/owner/repo", "key": …, "version": <tag used>}])`.
When the result carries `preferred_citation`, add that paper too; the
repository's authors asked for it.

Never write a `.bib` entry by hand, never edit a fetched one beyond its key,
never cite an identifier that did not come from `search_citation` /
`resolve_citation` in this session. If `bib_add` reports
`no-official-bibtex`, the work cannot be cited from a registry export: tell
the user, cite a version that has a DOI or arXiv id, or leave the sentence
uncited.

## When the caller rewrites text that already carries citations

- **Citation-set preservation is the caller's job** and needs no lookup:
  `keys_out ⊆ keys_in`, and no citation moves to a claim it was not attached
  to. A key that appears in the output and not in the source is a fabrication
  whether or not it resolves.
- **Every instance whose claim changed must be re-judged.** Run
  `extract_cites` on the source and on the rewrite; instances whose
  exact claim or context changed need a fresh verdict; `audit` reports
  missing or stale support. Rewording that keeps the meaning still changes
  the hash — that is intended: the judge decides whether the paraphrase still
  matches the paper's strength.
- `audit(tex_path, require_support=true, verify=true,
  policy="submission-ready")` must return the exact strict policy and literal
  true for `ok`, `input_complete`, `complete`, and `submission_ready` before
  the caller reports the manuscript as finished. The caller relays
  `failures` / `warnings` to the user; it does not lower the bar.

## Publication-status findings

Relay publication-status findings separately from identity verification. A known
retraction blocks strict readiness; corrections and expressions of concern
require review of the linked notice and the affected claim. Unknown status or
no reported update is not a guarantee that the work is unaffected. An item
that is a retraction notice is not itself retracted merely because it links to
an affected paper. See [publication-status.md](publication-status.md).

## The support check, from the caller's side

```
ex = extract_cites(tex_path)                     # instances + claims, grouped by_key
verify_bib(bib_path, keys=ex.keys, tex_path)     # resolve failures before proceeding
for each sentence in ex.sentences with a non-nocite occurrence:
    register_claims(tex_path, sentence.sentence_id, complete_atomic_spans)
    # One span for simple assertions; split compound assertions.
    # Explicit citation IDs; preserve any uncited scope with kind + reason.
for each key with status VERIFIED or FOUND:
    fetch_text(id, version=version)             # same pin as the bibliography; pdf_path= if supplied
    find_passages(id, [claim for every instance of key], version=version)
    judge  ← independent subagent, prompt in references/support.md
    record_support(workdir, key, claim=instance.claim, context=instance.context,
                   verdict=verdict, identifier=id, quotes=quotes, note=note,
                   judge=…, version=version, tex_path=tex_path,
                   occurrence_id=instance.occurrence_id, atom_id=atom.atom_id)
    # Repeat for each attached atom, including registered single-span sentences.
audit(tex_path, policy="submission-ready")  # require explicit readiness
```

The judge receives the exact atom, full extracted sentence/context, all
citation attachments, and any declared uncited scope. `claim` always remains
the full original extracted sentence. Atomic spans form a complete partition
in Unicode character offsets, including conjunctions, punctuation and math;
see `references/support.md` for the schema and validation rules. The caller
must not apply one atom's verdict to another or attach an unrelated source
to author-only results. Uncited spans remain explicitly unverified in audit.
Re-extract and register again after changing the sentence, context or split;
missing/stale atoms remain visible failures. Once any sentence is registered,
atomic mode requires exact registration for every current citation sentence
in that main manuscript. Legacy
sentence-only calls apply only to unambiguous undecomposed occurrences in
manuscripts without atomic-registration history. Retry `audit-stale` after a
concurrent manuscript or ledger update before treating any report as current.

UNRESOLVED is a lookup failure, not proof of fabrication or absence. Report
its reason and retry after the transient failure; do not remove a citation
solely because a registry was unavailable. MISMATCH / NOT_FOUND require
checking the intended identity before replacement or removal.

Use the bibliography's same pin for retrieval and recording: pass `version`
or keep the versioned identifier throughout (for example, an arXiv `v1` id
or a GitHub commit URL). Do not drop the pin after `resolve_citation` returns
work-level identifiers. If an official arXiv export omits the requested pin,
`fetch_bibtex` refuses it; do not hand-edit the export or substitute a newer
version. Source snapshot changes and legacy unbound ledger records require
fresh judgments, even when the prose did not change.

The caller never records a verdict it decided itself while writing; the
judge is a separate invocation (or a separate, later pass with the passages
in front of it). `record_support` enforces the evidence rules mechanically —
a SUPPORTS without a verbatim quote is rejected — so the ledger cannot be
narrated into a pass.

## Bounded verification progress

When the caller needs limited or resumable registry work, use
`verification_job` with a per-run budget and optional priorities tied to
current occurrence/atom IDs. Resume with the returned `job_id`; omitted
priorities and search configuration retain the stored settings. The next
budget is a fresh grant, and cumulative usage remains visible. Status reads
perform no network work. See [verification-jobs.md](verification-jobs.md).

The caller must relay every UNCHECKED identity and the ordered support-work
queue. `identity_complete` does not mean the scientific claims were checked;
`identity_verified` does not replace export provenance or support evidence.
Source reading and independent judgments remain outside this job's automated
work, with no model-call or token-cost accounting invented. Even a finished
identity queue has `submission_ready=false`. Complete the normal support
workflow and obtain the existing strict audit before reporting readiness.
Changed input, ledger or source snapshots require a fresh job; a stored job
is never an authorization to reuse stale evidence.

## Reviewing bibliography metadata

Call `lint_bib(bib_path, keys=..., verify=false)` for an offline metadata
review; omit `keys` to inspect all entries. `verify=true` optionally compares
entries through their own identifiers, using the ordinary registry cache.
The tool returns advice without editing the bibliography or changing audit
outcomes. Its `ok` and `input_complete` describe processing; `advisory_clean`
does not certify identity, export provenance or claim support, and
`submission_ready` is always false.

Relay deferred macros/inheritance and incomplete registry comparisons along
with actionable issues. A published record can be relevant without replacing
an intentionally cited preprint version. If a metadata change is chosen,
obtain its official export through `bib_add`/`fetch_bibtex` and rerun the
ordinary checks; do not fill fields from model memory or lint suggestions.
See [bibliography-lint.md](bibliography-lint.md) for scope and result fields.

## Reviewing actionable corrections

Call `correction_report(tex_path, bib_path, annotated=true)` when a user
needs actionable findings or an annotated source copy. It performs one fresh
audit, preserves its readiness flags, and returns `report_written` separately.
CLI exit status follows `ok`, so a failing audit can still produce useful
reports. Do not interpret artifact generation as a citation pass.

The independent judge may pass `proposed_correction` to `record_support`
for a non-support outcome bound to an explicit occurrence and registered
atom. The caller relays it as unapproved wording; it never silently applies
it or generates a new citation identifier. After the user chooses a change,
re-extract, register affected atoms, obtain fresh independent judgments and
rerun the strict gate. Use the same workflow in Codex, Claude Code and Gemini;
native MCP and CLI expose identical parameters. See
[correction-reports.md](correction-reports.md) for fields and examples.

## co-scientist specifically

- co-scientist has no citation tool of its own (its `resolve_citation` was
  removed in co-scientist 0.7.0). Its Literature subagent finds papers with
  its own search, then identifies each through `search_citation` /
  `resolve_citation` here; its orchestrator writes `report.bib` with
  `bib_add`.
- co-scientist runs the support check once, on the report's final prose
  (after its co-writer pass), and requires a current submission-ready audit before
  `compile_report`.
- The run manifest's `citations` section (`{"key", "id", "resolved",
  "supports"}`) maps onto the ledger: `id` is cite-check's canonical id,
  `resolved` is `verify_bib` status ∈ {VERIFIED, FOUND}, and `supports` is the
  claim whose `record_support` verdict is SUPPORTS. Write `report.bib` with
  `bib_add`, not by hand, and run `audit` before `compile_report`.

## co-writer specifically

- co-writer's preservation contract (its `SKILL.md`, "Hard Rules —
  Preservation": `keys_out ⊆ keys_in`, each key on its original claim) stays
  in co-writer; the resolution chain and the support check live here, and
  co-writer's "Citations" section says when it calls them.
- Modality: co-writer's modality ledger says a rewrite may not strengthen a
  claim; the judge here checks the *paper* against the sentence's strength.
  Both must hold. A rewrite that turns "suggests" into "shows" fails the
  first; a source sentence that already over-claims fails the second.

## What a caller may rely on

- `submission_ready == true` under `policy="submission-ready"`, with `ok`,
  `input_complete`, and `complete` also literal true, means every current
  cited entry is VERIFIED with a valid digest-bound official export receipt
  and every support requirement has fresh adequate SUPPORTS evidence from a
  usable source. Receipts establish local export integrity, not a registry's
  digital signature; see `export-provenance.md`.
- `complete` means every requirement has an assessed outcome; negative
  verdicts and inaccessible-source triage count as assessed. Exploratory
  `ok` can report usable progress and always has `submission_ready=false`.
- Full text is adequate; the primary README/CFF record of a verified GitHub
  repository is also eligible. Abstract-only support, PARTIAL, UNVERIFIABLE,
  missing/stale support, and unchecked existence cannot establish readiness.
- Explicit uncited atoms remain visibly unverified. The caller relays all
  failures/warnings, including scope declarations, and never labels them
  supported merely because the citation gate passed.
- The audit checks current manuscript, bibliography, ledger, and source
  snapshots before publishing. Retry an `audit-stale` result. Consult
  `audit-policies.md` for precise coverage units and unknown denominators.
