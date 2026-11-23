# Voice profile — starter

**Version:** 0.0.0 · **Status:** starter (unpersonalized) · **Built:** initialized by `cowriter.py init`
Register covered: journal and conference papers in astrophysics, physics, ML
and their intersections, written in LaTeX.

Every rule carries a grade and a tag. **Grades:** `HARD` (never violate),
`STRONG` (roughly four times in five; breaking it occasionally is fine),
`LIGHT` (nice when it fits; context decides — also the default when
unlabelled). **Tags:** `measured` (from the author's papers, with a code into
`extraction-report.md`), `attested` (from the author's interview or explicit
notes, with the date), `starter` (universal baseline until overridden by the
author).
**Authority:** verbatim specimens in §11 outrank the rules; the rules outrank
everything else. Where a rule and a specimen disagree, imitate the specimen.
Size cap on this file: 400 lines. When it grows past that, compress — do
not append.

---

## Core identity

*(Starter profile — no author-specific voice captured yet. Write clear, direct,
restrained scientific prose without generic LLM flourish, and let the author's
edits build this profile over time via `"co-writer update"` and
`"co-writer review"`, or bootstrap it from existing papers with
`scripts/extract_prose.py`, `references/extraction.md`, and
`references/interview.md`.)*

---

## Quick reference card

### Always
- Preserve every number, unit, sign, uncertainty, citation, reference, and math expression verbatim. `HARD · starter`
- State claims directly with concrete referents instead of empty flourish. `HARD · starter`

### Never
- Sentence-initial empty emphasis or boilerplate ("It is worth noting", "It should be noted", "In summary,"). `HARD · starter`
- Generic hype or field-impact claims ("revolutionize", "change how science is done", "paradigm shift", "game-changing"). `HARD · starter`
- Rhetorical reveal constructions ("It is not X, it is Y"). `HARD · starter`

### Words that stay (do not scrub in a de-AI pass)
*(empty — populated from the author's papers and accepted edits)*

---

## 1. Claim ladder

Weakest to strongest (`starter` default; customize via interview or review):

`suggests < is consistent with < indicates < shows < demonstrates < proves`

- *find / observe / see* are reporting verbs, not claims.
- Negations and "we cannot rule out" sit below everything.
- A rewrite may hold a claim at its input level or weaken it only if requested; never strengthen it.

---

## 2. Spelling, mechanics, and punctuation

- Follow the spelling convention of the surrounding document (defaulting to American English if unspecified). `LIGHT · starter`
- Avoid stacking em-dashes, rhetorical questions, or stock AI transitions. `STRONG · starter`

---

## 3. Section moves & paragraph architecture

*(empty — grows from `extraction.md` or `"co-writer update"` digests)*

---

## 4. Sentence rhythm, vocabulary, and math/figure integration

*(empty — grows from `extraction.md` or `"co-writer update"` digests)*

---

## 5. Content quarantine

*(List topic-specific nouns and framings from specimens here once specimens are added, so specimen subject matter never leaks into unrelated papers.)*

---

## 6. Rejected candidates

*(Candidates the author declined in `"co-writer review"`, with the reason, so future digests do not re-propose them.)*

---

## 11. Verbatim specimens

*(empty — populated from the author's accepted paragraphs or paper extraction, indexed by slot: abstract, intro-opener, gap, methods, definition, equation, results, interpretation, limitation, close, caption. Sentences the author rejected go in [counterexamples.md](counterexamples.md).)*

---

## Changelog

- **0.0.0** — starter profile created from `co-writer` templates.
