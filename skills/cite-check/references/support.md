# Claim-support protocol — does the cited paper say what the sentence says?

An existing paper cited for something it does not say is as much a
fabrication as a paper that does not exist. This protocol produces one
**verdict per atomic assertion and attached citation occurrence** (or per
undecomposed simple sentence occurrence) — bound to key, sentence and context —
recorded in `<manuscript dir>/.cite-check/ledger.json` through
`record_support`, which refuses any verdict that is not backed by evidence
the tool can check.

## Units

- **Claim** = the sentence in which the citation sits, exactly as
  `extract_cites` returns it (`⟨cite:key⟩` marks the citation's position;
  inline and display mathematics are preserved). Pass it verbatim.
- **Context** = the extracted surrounding sentences and mathematics. Give it
  to the judge and pass it verbatim as `context` to `record_support`; it is
  part of verdict identity, not reading-only material.
- A sentence citing several papers (`⟨cite:a,b⟩`) yields one instance per key;
  each paper is judged for the part of the claim it is attached to. "A and B
  showed X" cited to both means each must show X (or its share of X).
- `\nocite` instances are recorded as such and need no verdict.

## Atomic claims and citation scope

Use `extract_cites`'s `sentences`, `sentence_id`, and each citation's
`occurrence_id`. Repeated identical sentences or repeated uses of the same
key are distinct source occurrences. Includes are followed once per physical
file, as before; this is source-location extraction, not a TeX compiler's
expanded execution trace. Main manuscript identity is included, so two main
files sharing an included file do not share occurrence judgments.

For a sentence containing multiple assertions, the agent proposes a complete
ordered partition through `register_claims(tex_path, sentence_id, atoms)`.
An atom has `start`, `end`, and `citation_ids` (the supporting occurrence IDs).
Offsets are zero-based **Unicode codepoints in the exact extracted `claim`**,
with an exclusive end; they are not UTF-8 byte offsets or positions in raw
LaTeX. The tool derives exact `text`, `byte_start`, `byte_end` into the UTF-8
encoding of that same claim, and stable `atom_id` values. Each citation also
reports its original source command, character offsets, and UTF-8 byte
offsets from the same strict UTF-8 source snapshot (CRLF is preserved).

The spans must cover every character exactly once, with no gaps or overlaps.
Keep conjunctions and punctuation in a neighboring assertion span. Do not
split a citation marker or a mathematical expression. Every actual citation
occurrence must be attached, and an atom containing its marker must retain
that attachment. A citation at the end of a sentence can attach to several
atoms explicitly. For `A ⟨cite:a⟩, and B ⟨cite:b⟩`, attach A to a and B to b;
neither paper must prove the other paper's assertion.

If part of a sentence is the authors' own work or uncited context, retain it
as `kind: "uncited"`, `citation_ids: []`, with a meaningful `reason` (at least
15 characters). The default kind is `"cited"`; it needs attached citations.
Uncited spans cannot contain citation markers. They appear separately in the
audit as **unverified**, including their exact text and scope reason. They
are not citation-support successes. The independent judge must review this
scope declaration so a supported or unsupported assertion is not disguised
as author-only context.

For example, given the exact extracted sentence and occurrence IDs:

```python
sentence = "We measure X, and Smith measured Y ⟨cite:Smith⟩."
split = sentence.index(" and ")
atoms = [
    {"start": 0, "end": split, "citation_ids": [], "kind": "uncited",
     "reason": "This clause reports the authors' own measurement."},
    {"start": split, "end": len(sentence), "citation_ids": [smith_occurrence_id]},
]
registration = register_claims(tex_path, sentence_id, atoms)
```

Offsets mechanically certify coverage and preserve symbols; they do **not**
certify that a split is scientifically atomic or that a scope assignment is
correct. The independent judge sees every atom, including declared uncited
scope, plus the unchanged original sentence/context. Preserve shared subjects,
negation, qualifications, causal relations and conditional scope when judging
fragments. If a logical assertion cannot be safely separated, retain the
coupled assertion as one span and explain the limitation to the caller.

Call `record_support` separately for every registered cited atom and attached
occurrence, passing `tex_path`, `occurrence_id`, and `atom_id`, and the full
original `claim` and `context`. `claim` is never replaced by a paraphrase or
by the fragment. The ledger retains the exact atom separately. Missing atoms
remain missing even if another atom or an old whole-sentence judgment passes.
Changed decompositions, sentence/context, source bytes or source versions
require new judgments. Registration is idempotent when unchanged; replacing
and then restoring a split does not resurrect old atom judgments. Stale
registrations fail closed, including after citations move in the source.

The first registration enables **atomic mode for the main manuscript**.
Every current citation sentence then needs an exact registration; use one
span for a simple assertion. This conservative rule prevents an assertion
that moves and changes text, including a move into another included file,
from silently returning to whole-sentence checking. Re-extract and register
all missing/stale sentences. Removed sentences have no current obligation;
history remains to prevent accidental fallback. Registering an observed
revision invalidates judgments for historical sentence identities absent from
the current document, so restoring old text cannot resurrect those judgments.

Legacy sentence-level calls still work for unambiguous undecomposed
occurrences in manuscripts that have not entered atomic mode. Repeated identical key/sentence pairs require explicit occurrence
IDs. Once decomposition is registered, a legacy sentence judgment cannot
satisfy it. An audit detects manuscript/ledger changes during its run and
returns `audit-stale`; rerun it before relying on the result.

## Verdicts

| Verdict | Meaning | What `record_support` demands |
|---|---|---|
| **SUPPORTS** | the paper states or shows the claim as written, at the strength written | ≥ 1 quote found verbatim in the fetched text |
| **PARTIAL** | the paper supports part of the claim, or a weaker/narrower version (different sample, conditional result, "suggests" where the sentence says "shows") | ≥ 1 verbatim quote **and** a note saying which part is not covered |
| **UNSUPPORTED** | the paper is real but does not say this (wrong paper for the claim, claim over-reaches, the number is not in it) | a note saying what was searched and what the paper does say |
| **CONTRADICTS** | the paper says the opposite | ≥ 1 verbatim quote **and** a note |
| **UNVERIFIABLE** | no text could be obtained (paywalled, no open-access copy, no PDF supplied) — **refused when full text is available** | a note |

The **basis** (`fulltext` / `readme` / `abstract` / `none`) is recorded
from the text cache, not from the caller. `readme` is a GitHub repository's
README, description and `CITATION.cff` abstract: UNVERIFIABLE is allowed on
it, because the code the README describes was not read. A SUPPORTS judged from an abstract alone is a
warning under exploratory policy and a submission-readiness failure: fetch the PDF (`fetch_text`
with `pdf_path=`) when the claim is specific (a number, a method detail, a
sample size).

Modality matters. "X **may** contribute to Y" cited to a paper that says "we
cannot rule out X" is SUPPORTS; "X **causes** Y" cited to the same paper is
PARTIAL at best. This is the silent-damage mode of LLM drafting: the citation
is real, the strength is not.

## Quotes

- Quotes must match a source span exactly after whitespace and typographic
  ligature normalization. Case, punctuation, signs, numbers, mathematical
  symbols and superscripts are preserved. Fuzzy similarity never certifies
  evidence. The result includes the original source span and character
  offsets. Quotes under 15 normalized characters are rejected.
- Quote the sentence(s) that carry the claim — a result sentence, a stated
  number, a method description — not a related keyword.
- `find_passages(identifier, [claim, …], version=…)` returns the abstract
  and top passages ranked by overlap with each claim. The judge reads
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
> For decomposed sentences, first check the proposed scope and any uncited
> spans. Judge each attached atom against its source in the full original
> sentence and context; preserve shared conditions, negation and strength.
> Return `[{"occurrence_id": "...", "atom_id": "...", "verdict": "...",
> "quotes": ["..."], "note": "..."}]` (omit atom_id only for undecomposed sentences outside atomic mode).

The orchestrator then calls `record_support` for each item with the original
extracted `claim` and `context`, plus the same source version used to retrieve
the passages. A refused record (quote not found, note missing) goes back to
the judge with the tool's reason.

## Efficiency

1. `extract_cites` once; group instances `by_key`.
2. `verify_bib` once (batched registry calls); only VERIFIED/FOUND keys go on
   to support checking — a MISMATCH entry gets fixed first.
3. `fetch_text` per paper and cited version (cached globally, reused across
   manuscripts and sessions); `find_passages` with **all** claims for that
   version in one call. Use the same `version` or versioned identifier for
   both calls and `record_support`; latest-version text is not a substitute
   for a pinned citation.
4. One judge per paper; one `record_support` per attached atom/occurrence.
5. On revision, re-judge instances whose claim, surrounding context, source
   snapshot, or evidence policy changed. `audit` reports missing and stale
   verdicts; unchanged instances retain their judgments.

## Common cases

- **Software / data citations** ("we used `numpy` ⟨cite:harris2020⟩"): the
  claim is that the cited work is that software; the abstract settles it.
- **A repository cited directly** ("sampled with `emcee` ⟨cite:emcee⟩",
  key resolving to `github:dfm/emcee`): the judge reads the README. A
  sentence that only names the tool and what it is for is SUPPORTS on a
  README quote saying so. A sentence attributing a property to the code
  ("GPU-accelerated", "uses a KD-tree", "implements method X") needs the
  README or `CITATION.cff` abstract to say it; if they do not, it is
  UNVERIFIABLE with a note, and the fix is a citation to the paper or
  documentation that does. A sentence about a specific version is judged
  only if the entry pins that version.
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

## Evidence freshness

Pass both `claim` and `context` from `extract_cites` to `record_support`.
Extraction preserves inline and display mathematics, including LaTeX symbol
names and citations inside equations. Context includes the neighboring sentence
on either side across paragraph boundaries, so changing an adjacent displayed
result also invalidates its old judgment.
Omitting context means the claim is the entire context, suitable only for an
isolated sentence. Claim identity preserves mathematical case and Unicode.
Verdicts bind to the source content digest, source version, extraction version
and quote policy. The audit rejects changed context, replaced source text and
legacy verdicts without this binding; obtain a fresh judgment.

## Versioned sources

For a software version, pass the same `version` or GitHub tree URL to
`fetch_text`, `find_passages` and `record_support`. GitHub CFF and README
content is fetched at the resolved full commit hash; source snapshots and
exported URLs keep that pin. arXiv version suffixes select separate source
caches, and unavailable versioned text never falls back to a newer version.
The work identifier remains stable while its evidence version is separate.
Legacy cache filenames are deliberately ignored because their lossy keys
cannot prove which identifier created them; they can be removed locally.

## Audit completion

Use `policy="submission-ready"` for a final gate and require `ok`,
`input_complete`, `complete`, and `submission_ready` all true. Exploratory
`ok` means progress only. Assessment completeness includes negative verdicts
and inaccessible-source triage; it never substitutes for readiness.
See `audit-policies.md` for coverage units, limited evidence, provenance
assurance, and the verified-repository README exception.
