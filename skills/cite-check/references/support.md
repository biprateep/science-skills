# Claim-support protocol — does the cited paper say what the sentence says?

An existing paper cited for something it does not say is as much a
fabrication as a paper that does not exist. This protocol produces one
**verdict per citation instance** — per (cite key, claim sentence) pair —
recorded in `<manuscript dir>/.cite-check/ledger.json` through
`record_support`, which refuses any verdict that is not backed by evidence
the tool can check.

## Units

- **Claim** = the sentence in which the citation sits, exactly as
  `extract_cites` returns it (`⟨cite:key⟩` marks the citation's position;
  `$…$` math is kept; display equations appear as `⟨display equation⟩`).
  The ledger keys on a hash of this sentence, so pass it verbatim.
- **Context** = one sentence either side, given to the judge for reading only.
- A sentence citing several papers (`⟨cite:a,b⟩`) yields one instance per key;
  each paper is judged for the part of the claim it is attached to. "A and B
  showed X" cited to both means each must show X (or its share of X).
- `\nocite` instances are recorded as such and need no verdict.

## Verdicts

| Verdict | Meaning | What `record_support` demands |
|---|---|---|
| **SUPPORTS** | the paper states or shows the claim as written, at the strength written | ≥ 1 quote found verbatim in the fetched text |
| **PARTIAL** | the paper supports part of the claim, or a weaker/narrower version (different sample, conditional result, "suggests" where the sentence says "shows") | ≥ 1 verbatim quote **and** a note saying which part is not covered |
| **UNSUPPORTED** | the paper is real but does not say this (wrong paper for the claim, claim over-reaches, the number is not in it) | a note saying what was searched and what the paper does say |
| **CONTRADICTS** | the paper says the opposite | ≥ 1 verbatim quote **and** a note |
| **UNVERIFIABLE** | no text could be obtained (paywalled, no open-access copy, no PDF supplied) — **refused when full text is available** | a note |

The **basis** (`fulltext` / `abstract` / `none`) is recorded from the text
cache, not from the caller. A SUPPORTS judged from an abstract alone is a
warning in the audit, not a pass with full marks: fetch the PDF (`fetch_text`
with `pdf_path=`) when the claim is specific (a number, a method detail, a
sample size).

Modality matters. "X **may** contribute to Y" cited to a paper that says "we
cannot rule out X" is SUPPORTS; "X **causes** Y" cited to the same paper is
PARTIAL at best. This is the silent-damage mode of LLM drafting: the citation
is real, the strength is not.

## Quotes

- Quotes are checked by normalised substring match, or ≥ 0.85 sequence
  similarity to absorb PDF-extraction damage (ligatures, broken hyphens,
  superscripts). Paraphrases fail. Quotes under 15 characters are rejected.
- Quote the sentence(s) that carry the claim — a result sentence, a stated
  number, a method description — not a related keyword.
- `find_passages(identifier, [claim, …])` returns the abstract and the top
  passages of the paper ranked by overlap with each claim. The judge reads
  those (and more of the text if needed) and quotes from them.

## Who judges

The judge must be **independent of the writer**: an agent (or a fresh pass)
that sees only the claim, its context, the paper's title and abstract, and
the retrieved passages — not the manuscript's argument or what the writer
hoped the paper says. On harnesses with `<spawn-subagent>`, spawn one judge
**per cited paper** and hand it every claim instance for that paper in one
prompt (one text fetch, N claims). Without subagents, do the judging as a
separate step after all writing is done, with the passages in front of you,
and record `judge: "inline"`.

Judge prompt template (fill the brackets; return JSON only):

> You are checking whether a cited paper supports the sentences that cite it.
> Paper: [title] ([id]). Abstract: [abstract]. Retrieved passages, one block
> per claim: [find_passages output]. For each claim, decide SUPPORTS /
> PARTIAL / UNSUPPORTED / CONTRADICTS, quote the passage(s) that decide it
> **verbatim** (copy exact text; do not paraphrase), and for anything but
> SUPPORTS say in one sentence what the paper does and does not say. Judge
> the claim as written, including its strength ("shows" vs "suggests"), and
> only the part the citation is attached to. If the passages do not settle it,
> say what to search for in the full text. Return:
> `[{"claim": "...", "verdict": "...", "quotes": ["..."], "note": "..."}]`

The orchestrator then calls `record_support` for each item; a refused record
(quote not found, note missing) goes back to the judge with the tool's reason.

## Efficiency

1. `extract_cites` once; group instances `by_key`.
2. `verify_bib` once (batched registry calls); only VERIFIED/FOUND keys go on
   to support checking — a MISMATCH entry gets fixed first.
3. `fetch_text` per paper (cached globally, reused across manuscripts and
   sessions); `find_passages` with **all** claims for that paper in one call.
4. One judge per paper; one `record_support` per instance.
5. On revision, only instances whose claim hash changed need re-judging: the
   ledger keeps the rest. `audit` reports exactly which instances are missing.

## Common cases

- **Software / data citations** ("we used `numpy` ⟨cite:harris2020⟩"): the
  claim is that the cited work is that software; the abstract settles it.
- **"We follow the method of ⟨cite:x⟩"**: SUPPORTS if the paper presents that
  method; quote its description.
- **Review or textbook cited for a general fact**: SUPPORTS if the fact is
  stated there; if only a specific chapter says it and no text is available,
  UNVERIFIABLE with a note — do not assume.
- **Numbers**: the exact value (within rounding) must appear; a different
  value with the same meaning is PARTIAL with the paper's value in the note.
- **Preprint vs published**: the text fetched is the arXiv version when that
  is what is available; if the claim depends on something changed in the
  journal version, say so in the note.
