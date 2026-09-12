---
name: co-writer
description: >-
  Write or rewrite paper prose in the author's own voice, from any input —
  rough notes, an agent's draft, a collaborator's section, a paragraph that
  reads like a language model wrote it — preserving every number, claim,
  hedge and citation exactly and changing only how it is said. Covers journal
  and conference papers in astrophysics, physics, ML and their intersections,
  in LaTeX. Citations are never verified here: existence, official BibTeX
  and claim support are delegated to the cite-check skill. Use when the user
  says "in my style", "in my voice", "sound like me", "as I would write it",
  "restyle", "de-AI this", "co-writer", or asks for a section, paragraph,
  abstract or caption to be drafted or rewritten the way they write. NOT for
  producing the science, the analysis, or the report structure
  (co-scientist), for figures (plot-style), for citation work on its own
  (cite-check), for copy-editing that does not involve voice, or — yet — for
  emails, letters, proposals or referee reports.
license: MIT
metadata:
  version: "0.3.1"
---

# Co-Writer: Papers in the Author's Voice

## Overview

co-writer does two things and only two: **preserve the information** in
whatever it is given, and **write it the way the author writes**. The input's
own style is discarded, not modelled — an agent artefact, a collaborator's
draft and the author's own rough notes are all treated identically, as a bag
of facts to be re-expressed.

The voice lives in one file, [references/voice-profile.md](references/voice-profile.md):
graded rules, a Never list, the words a de-AI pass must leave alone, and
verbatim specimens indexed by section function. Read all of it, every time.
Its specimens outrank its rules: where a rule and a specimen disagree, imitate
the specimen and say what you departed from.
Its provenance — the extraction prompt, the evidence report and the interview
— is in `references/` for maintenance and is not needed at write time.

## When to Apply

Apply when the user asks for text in their voice, or to restyle, rewrite,
draft or de-AI a piece of paper prose. Apply to any length: a sentence, a
caption, a section, a whole draft.

Do not apply when the request is for the science itself, for structure or
argument, or for a register the profile does not cover. co-scientist writes
the report; co-writer restyles its prose afterwards. If a request mixes both
("write up these results"), do the writing here only after the results, the
claims and the citations already exist in the input.

## Process

1. **Read the input for information, and write the content list.** Before
   writing anything, list what must survive: every number with its precision,
   every claim with its hedge level, every citation and where it attaches,
   every defined symbol, every equation, every figure and table reference. For
   a paragraph this is a glance; for a section, and always for "de-AI this",
   write the list down — it is what step 4 composes from.
2. **Identify the slot and the register.** Slot: abstract, introduction
   opener, gap-and-contribution, methods, definition, equation, results,
   interpretation, limitation, close, caption. Register: journal (AAS, MNRAS)
   or workshop (four-page NeurIPS-style). Infer from the input and the
   surrounding document; if the user has said, that wins.
3. **Load the profile, then read the specimen for the slot immediately before
   writing.** The register is transferred from the specimen, not assembled
   from the rule list: read it at length and write while it is fresh.
   Spelling is American whatever the venue.
4. **Write, in one sitting, from the content list.** When the input reads as
   model prose — "de-AI this", or `check_mannered.py` lights up on it — close
   the input and compose from the list alone, because a writer with the old
   prose open keeps its sentences and its hooks. Otherwise the input may stay
   open, for information only. Apply every `HARD` rule, most `STRONG` rules,
   `LIGHT` rules where they fit. Carry the specimen's construction, never its
   nouns.
5. **Check what is fixed.** `python <skill>/scripts/check_fixed.py INPUT
   OUTPUT` (write both to the scratchpad in inline mode). It must print
   "fixed items identical", or only WARN lines after a ruled hard-limit cut.
   Then the self-check below.
6. **The cold read** ([references/cold-read.md](references/cold-read.md)):
   always for a section or a draft; for a single paragraph, whenever an agent
   is available.
7. **Citations, when the text is file-backed and a citing sentence changed**
   — hand the changed instances to cite-check (see "Citations" below). A
   section or draft is not done until cite-check's `audit` is `ok`.
8. **Return the text only.** No preamble, no "Here is the rewritten version",
   no summary of changes, no closing offer. If the user asked for a diff or a
   rationale, give the text first and the rationale after a rule. Never
   certify the voice; the passages you are least sure of go into the session
   log, not into the reply.
9. **Log it.** Append the entry on the form in
   [references/session-log.md](references/session-log.md), in the paper's
   repository. A rewrite that is not logged teaches nothing.

## Hard Rules — Preservation

These are correctness rules and outrank every voice rule. A rewrite that
reads exactly like the author and breaks one of these is a failure.

- **Numbers survive exactly.** Value, precision, unit, sign, uncertainty.
  `0.00898` does not become "about 0.009". A number the input lacks is not
  invented; write `[NEEDS: value]` and say so after the text.
- **Modality is never strengthened.** The profile's claim ladder, weakest to
  strongest: *suggests < is consistent with < indicates < shows <
  demonstrates < proves*; *find / observe / see* are reporting, not claims;
  negations and "we cannot rule out" sit below everything. A claim may stay
  where it is or move down; "suggests" may not become "demonstrates", "we
  cannot rule out X" may not become "we show X". One exception, from the
  author: the **abstract may sit one rung above the results section** for
  the same claim — one rung, never two. Weakening elsewhere is allowed only
  if the user asked.
- **Flourish is not information.** An evaluation with no checkable content —
  "a substantial leap forward", "proved pivotal", "remarkable" — is style and
  may be dropped. A comparison with a referent — "outperforms the CNN
  baseline", "important for this performance" — is a claim and survives.
- **No reference is invented.** The profile's results pattern opens with
  "Figure N shows"; if the input has no figure, do not add one. Never
  introduce a `\ref`, `\cite`, equation number or table to satisfy a slot.
- **The citation set never grows or moves.** `keys_out ⊆ keys_in`, and
  every `\cite` key in the output is attached to the claim it was attached
  to in the input; a key drops out only under a reported hard-limit cut.
  This is a set comparison, needs no lookup, and is the only citation check
  co-writer performs itself. Whether the paper exists, whether the `.bib`
  entry is genuine, whether the paper supports the sentence — that is
  cite-check's, below.
- **Markup passes through untouched.** `\cite`, `\ref`, `\label`, `\eqref`,
  math (inline and display), `\begin{figure}` … `\end{figure}` bodies,
  macros. Rewrite the prose around them. If the input is LaTeX, the output
  is LaTeX.
- **Specimen content does not leak.** The profile's quarantine list names
  the nouns; if any phrase of eight or more words from an specimen appears
  in the output and was not in the input, remove it.
- **Hard limits are met by the trim** ([references/trim.md](references/trim.md)),
  never by writing shorter or by compressing a claim away. What leaves under a
  ruled cut is listed after the text.

## Citations — cite-check does the verifying

co-writer has no citation logic beyond the set comparison above. Existence,
provenance and claim support are computed by the **cite-check** skill
(`skills/cite-check/`, a sibling of this one), and every improvement made
there applies here with no change to this file. Before the first citation
action in a session read its contract,
`<skills>/cite-check/references/integration.md`: it says how to reach the
tools (listed by the harness as `mcp__cite-check__*`, or run its
`mcp/setup_mcp.sh` once and use the identical CLI for the session, `ping`
once for the ADS token) and it wins wherever this section differs.

Three triggers:

1. **A rewrite changed a sentence carrying a citation.** `extract_cites` on
   the rewritten file, cite-check's support check on every instance whose
   claim changed, then `audit(tex_path, require_support=true)`. Two rules
   must both hold: co-writer's, that the sentence is no stronger than the
   input's; cite-check's, that the paper supports the sentence as written.
2. **The user asks for a citation, or the input carries a gap** — `[cite]`,
   `\cite{?}`, "(REF)". cite-check's Workflow A: `search_citation` → a `high`
   candidate, ask about a `medium`, never a `low` → `bib_add` → write
   `\cite{<key>}` → support check. `no-official-bibtex` → leave it uncited and
   say so. This is the only way a key enters the output that was not in the
   input.
3. **A draft the user calls finished.** `audit` returns `ok: true`; relay its
   failures and warnings verbatim and do not lower `require_support`.

Inline mode — no file, no `.bib` — gets the set comparison only, and one
sentence saying the support check runs when the paragraph is in its file.
Never: write or complete a `.bib` entry; cite a key, DOI, arXiv id or
bibcode from memory; record a support verdict yourself; re-implement a
cite-check check with your own reasoning; edit anything under
`cite-check/mcp/`.

## Modes by Input

| Input | What changes |
|---|---|
| A sentence or paragraph pasted inline | Rewrite in place; return the paragraph. |
| A section (`\section` to `\section`) | Keep the paragraph count and order unless a `HARD` rule forbids it (no one-sentence paragraphs). Keep every heading. |
| A whole draft | Section by section, re-reading the profile's register table between sections. Keep the document's structure; do not add or remove sections. |
| A word or page limit | The trim (`references/trim.md`): measure, propose in two classes, the author rules, cut, measure again. |
| "de-AI this" | Compose from the content list with the input closed. The Never list and the "words that are his" list carry the weight: do not scrub *leverage*, *utilize*, *robust*, *crucial*, *very*, *significantly* — they are the author's. |
| Any file-backed input with citations | After the rewrite, the cite-check pass in "Citations"; a section or draft is not done until `audit` is `ok`. |

## Anti-Patterns

What a model reaching for "good academic prose" will do, and must not:

- **Stack signatures.** Every paragraph ending "Therefore,", every methods
  sentence opening "To …", "(also called …)" three times on a page. One or two
  per paragraph is the author; five is a parody.
- **Scrub the author's words as AI-isms.** The profile's "words that are his
  and stay" list exists because a generic de-AI pass removes them.
- **Add dashes.** The corpus has at most one per page. A rewrite with an em-dash
  aside in every paragraph is the single loudest tell.
- **Add "Notably," / "Importantly," / "Interestingly,".** Surprise is marked
  with *remarkably* / *unsurprisingly* / *as expected*, once.
- **Shorten paragraphs into punchy ones**, or add a one-sentence paragraph
  for emphasis. His paragraphs are long and even.
- **Convert narrated procedure into a list.** "We first … We then …" stays
  prose.
- **Smooth away the concessive sentence.** "While X, Y" is how caveats are
  bound to claims; splitting it into two sentences loses the voice.
- **Strengthen a claim** to make the paragraph land. See Preservation.
- **Move a limitation** into its own section. It lives beside the result.
- **Import a framing from the specimens.** The DESI/photo-*z* nouns are
  content.
- **Conjure a figure.** "Figure N shows …" is how *he* opens a results
  paragraph when there is a figure; it is not a licence to reference one the
  input does not have.
- **Add a summary sentence** at the end of a section that the input did not
  have.
- **Verify a citation by reasoning.** "This DOI looks right", "I recall that
  paper shows this" — not a check. cite-check's tools are the check.
- **Revise against the list.** When a stretch misses, re-read the specimen
  and write it again. Patching sentence by sentence against the Never list
  yields prose that satisfies every rule and still reads as a model.
- **Certify the voice.** "This sounds like you" is not a finding. Only the
  author says that; the writer records what it is least sure of.
- **Write a preamble or postamble.** Text only.

## Self-Check Before Finishing

1. `check_fixed.py INPUT OUTPUT` prints "fixed items identical", or only WARN
   lines after a ruled cut. ☐
2. No claim is stronger than it was; the abstract at most one rung above the
   results. ☐
3. Each `\cite` key is attached to the claim it was attached to (the script
   checks the set; you check the attachment). ☐
4. File-backed and a citing sentence changed → cite-check's support pass run;
   a section or draft is called done only with `audit` ok. ☐
5. No phrase of eight-plus words from a specimen that was not in the input. ☐
6. `check_mannered.py OUTPUT` read: every hit looked at, the dash tally at or
   under one per page. A hit is a place to look, not a fault. ☐
7. Nothing from the Never list. ☐
8. No signature stacked more than twice in a paragraph. ☐
9. American spelling throughout. ☐
10. The cold read has run where the mode requires it, and each surviving item
    was answered by rewriting from the specimen. ☐

## Maintenance

The profile improves from use through the loop in
[references/maintenance.md](references/maintenance.md): capture the author's
edits, collect the transcripts, digest them into candidates he adopts, tests
or holds, score each version on the eval set, re-extract when a paper is
finished. Nothing there is read at write time.

## Interaction With Other Skills

co-writer reads its own `references/` and, for citation work, cite-check's
`references/integration.md`; it does not load or defer to any other skill's
writing guidance.

- **cite-check** is the citation engine. co-writer keeps only the set
  comparison; existence, BibTeX and claim support are cite-check's, called as
  in "Citations". Improvements to cite-check reach co-writer with no change
  here.
- **co-scientist** produces the science and assembles the report; co-writer
  is run afterwards, section by section, over the prose. co-scientist's
  manifest says which claims are verified; co-writer preserves claims, it
  does not vet them.
- **plot-style** makes the figure; co-writer writes its caption in the
  author's voice (the profile has a caption slot and specimen).

## Files — and when each is read

```
skills/co-writer/
├── SKILL.md                         # read whole when the skill is invoked
├── references/
│   ├── voice-profile.md             # every rewrite — THE artefact; specimens outrank rules
│   ├── session-log.md               # every rewrite, at the end — the form of the log entry
│   ├── cold-read.md                 # section and draft mode — who reads, what it gets, the brief
│   ├── counterexamples.md           # once after drafting — sentences the author rejected
│   ├── trim.md                      # only with a page or word limit — protocol and proposer's brief
│   ├── maintenance.md               # never at write time — capture, collect, digest, eval, new paper
│   ├── extraction.md                # never at write time — the deep-read prompt
│   ├── extraction-report.md         # never at write time — evidence for every rule
│   └── interview.md                 # never at write time — the questions the text cannot answer
├── scripts/
│   ├── check_fixed.py               # INPUT vs OUTPUT: cites, refs, labels, math, numbers — the preservation gate
│   ├── check_mannered.py            # stock phrases and Never-list hits, with lines — calibration, not a verdict
│   ├── extract_prose.py             # .tex → readable prose; --counts gives words per section for the trim
│   ├── capture_edits.py             # session log + author's edits → corrections.md
│   └── collect_transcripts.py       # Claude Code / Antigravity transcripts → .co-writer/transcripts/
└── eval/
    ├── README.md                    # the per-version protocol
    └── 01-abstract.tex … 06-caption.tex   # fixed inputs, one per slot

skills/cite-check/references/integration.md   # before any citation action — the contract this skill follows

<paper repo>/.co-writer/             # gitignored, written at use time
├── log/                             # one file per rewrite + one session note
├── corrections.md                   # from capture_edits.py
└── transcripts/                     # from collect_transcripts.py
```
