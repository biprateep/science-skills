# Calling cite-check from another skill (co-writer, co-scientist, …)

cite-check is the one citation engine in this repository. A writing or
research skill does not verify citations itself; it calls these tools and
treats their results as the verdict. The contract below is what a caller
must do, must not do, and may rely on.

## Tool access

1. If the harness lists the tools (Claude Code: `mcp__cite-check__*`; other
   harnesses: server `cite-check`), call them directly.
2. Otherwise run `bash <skills>/cite-check/mcp/setup_mcp.sh` once (idempotent;
   registers the server for the next session) and for the current session use
   CLI mode, which is the same code:
   `<skills>/cite-check/mcp/.venv/bin/python <skills>/cite-check/mcp/server.py call <tool> '<json>'`
   (exit 0 = pass, 1 = fail/blocked; JSON on stdout).
3. `ping` tells you whether an ADS token is present. Astronomy manuscripts
   without one lose ADS search and export; say so to the user once.

## When the caller adds a citation

```
search_citation(title=…, author=…, year=…)      # or hint="Smith2019", context="<the sentence>"
   → pick a candidate (confidence high, or the user confirms a medium one)
bib_add(bib_path, items=[{"identifier": <candidate id>, "key": <cite key>}], tex_path=…)
   → status added | exists | duplicate (use existing_key) | no-official-bibtex (do not cite)
write the sentence with \cite{<key>}
support check for that instance (below) before the section is called done
```

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
  `(key, claim-hash)` pair is new have no ledger entry and show up in `audit`
  as `support-missing`. Rewording that keeps the meaning still changes the
  hash — that is intended: the judge decides whether the paraphrase still
  matches the paper's strength.
- `audit(tex_path, require_support=true)` must return `ok: true` before the
  caller reports the manuscript as finished. The caller relays
  `failures` / `warnings` to the user; it does not lower the bar.

## The support check, from the caller's side

```
ex = extract_cites(tex_path)                     # instances + claims, grouped by_key
verify_bib(bib_path, keys=ex.keys, tex_path)     # fix MISMATCH / NOT_FOUND / UNRESOLVED first
for each key with status VERIFIED or FOUND:
    fetch_text(id)                               # cached globally; pdf_path= for paywalled papers
    find_passages(id, [claim for every instance of key])
    judge  ← independent subagent, prompt in references/support.md
    record_support(workdir, key, claim, verdict, id, quotes, note, judge=…)   # per instance
audit(tex_path)
```

The caller never records a verdict it decided itself while writing; the
judge is a separate invocation (or a separate, later pass with the passages
in front of it). `record_support` enforces the evidence rules mechanically —
a SUPPORTS without a verbatim quote is rejected — so the ledger cannot be
narrated into a pass.

## co-scientist specifically

- The Literature subagent's `resolve_citation` in co-scientist's own toolbox
  is a subset of this one. Prefer `cite-check`'s `search_citation` (multiple
  registries, local ranking) and `resolve_citation` (cross-linked ids, ADS
  bibcodes) when the tools are available.
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

- `audit.ok == true` means: every cite key exists in the `.bib`; every cited
  entry's identifier resolves to a record whose title, first author and year
  match; every citation instance has a support verdict that is not
  UNSUPPORTED / CONTRADICTS / missing / judged against a different paper.
- Warnings are not failures but are the user's to see: PROBABLE and FOUND
  entries, PARTIAL and UNVERIFIABLE verdicts, SUPPORTS judged from an
  abstract only, uncited entries, entries not written by cite-check.
- Everything is re-runnable and cached; a second `audit` on an unchanged
  manuscript costs no network calls.
