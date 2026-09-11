---
name: co-writer
description: >-
  Write or rewrite paper prose in the author's own voice, from any input —
  rough notes, an agent's draft, a collaborator's section, a paragraph that
  reads like a language model wrote it — preserving every number, claim,
  hedge and citation exactly and changing only how it is said. Covers journal
  and conference papers in astrophysics, physics, ML and their intersections,
  in LaTeX. Use when the user says "in my style", "in my voice", "sound like
  me", "as I would write it", "restyle", "de-AI this", "co-writer", or asks
  for a section, paragraph, abstract or caption to be drafted or rewritten
  the way they write. NOT for producing the science, the analysis, or the
  report structure (co-scientist), for figures (plot-style), for
  copy-editing that does not involve voice, or — yet — for emails, letters,
  proposals or referee reports.
license: MIT
metadata:
  version: "0.1.0"
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
verbatim exemplars indexed by section function. Read all of it, every time.
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

1. **Read the input for information.** Before writing anything, list what
   must survive: every number with its precision, every claim with its hedge
   level, every citation and where it attaches, every defined symbol, every
   figure and table reference. For a paragraph this is a glance; for a
   section, write the list down.
2. **Identify the slot and the register.** Slot: abstract, introduction
   opener, gap-and-contribution, methods, definition, equation, results,
   interpretation, limitation, close, caption. Register: journal (AAS, MNRAS)
   or workshop (four-page NeurIPS-style). Infer from the input and the
   surrounding document; if the user has said, that wins.
3. **Load the profile** and read the exemplar for that slot. Note the venue's
   spelling.
4. **Write.** Apply every `HARD` rule, most `STRONG` rules, `LIGHT` rules
   where they fit. Carry the exemplar's construction, never its nouns.
5. **Check** — the self-check below, in order.
6. **Return the text only.** No preamble, no "Here is the rewritten version",
   no summary of changes, no closing offer. If the user asked for a diff or a
   rationale, give the text first and the rationale after a rule.

## Session Log

Every rewrite is logged, whichever agent performs it. The log is what the
improvement loop runs on; a rewrite that is not logged teaches nothing.

After delivering the text, append a file to `.co-writer/log/` **in the
repository that holds the paper** (create the directory if it is missing),
named `YYYY-MM-DD-NN.md` with `NN` the next free number that day:

```
---
id: 2026-09-12-03
date: 2026-09-12T14:05
agent: claude-code | antigravity | <other>
profile_version: <the Version line at the top of voice-profile.md>
slot: abstract | intro-opener | gap | methods | definition | equation | results | interpretation | limitation | close | caption
register: journal | workshop
file: <path of the .tex the output went into, relative to the repo root; omit if returned inline only>
---
## Input
<the input exactly as received>
## Output
<the output exactly as delivered>
## Note
<what the user said about the output in the same session, verbatim; omit the section if nothing>
```

At the end of any session in which co-writer was used, append one more file,
`YYYY-MM-DD-session.md`, same frontmatter with `slot: session`, and three
lines under `## Note`: what was asked, what was produced, what the user said
was wrong. This makes the record independent of where each agent keeps its
chat.

The log is gitignored where the paper lives. Never write it into the skill's
own directory.

## Hard Rules — Preservation

These are correctness rules and outrank every voice rule. A rewrite that
reads exactly like the author and breaks one of these is a failure.

- **Numbers survive exactly.** Value, precision, unit, sign, uncertainty.
  `0.00898` does not become "about 0.009". A number the input lacks is not
  invented; write `[NEEDS: value]` and say so after the text.
- **Modality is never strengthened.** Order: *negated < speculative < hedged
  < suggested < asserted*. "We cannot rule out X" may not become "we show X";
  "suggests" may not become "demonstrates". Weakening is allowed only if the
  user asked.
- **Flourish is not information.** An evaluation with no checkable content —
  "a substantial leap forward", "proved pivotal", "remarkable" — is style and
  may be dropped. A comparison with a referent — "outperforms the CNN
  baseline", "important for this performance" — is a claim and survives.
- **No reference is invented.** The profile's results pattern opens with
  "Figure N shows"; if the input has no figure, do not add one. Never
  introduce a `\ref`, `\cite`, equation number or table to satisfy a slot.
- **The citation set never grows, shrinks or moves.** Every `\cite` key in
  the output was in the input, attached to the same claim. No new
  references, however obvious.
- **Markup passes through untouched.** `\cite`, `\ref`, `\label`, `\eqref`,
  math (inline and display), `\begin{figure}` … `\end{figure}` bodies,
  macros. Rewrite the prose around them. If the input is LaTeX, the output
  is LaTeX.
- **Exemplar content does not leak.** The profile's quarantine list names
  the nouns; if any phrase of eight or more words from an exemplar appears
  in the output and was not in the input, remove it.
- **Hard limits cut content only visibly.** If a page or word limit forces
  dropping information, return the list of what was dropped after the text.
  Never silently compress a claim away.

## Modes by Input

| Input | What changes |
|---|---|
| A sentence or paragraph pasted inline | Rewrite in place; return the paragraph. |
| A section (`\section` to `\section`) | Keep the paragraph count and order unless a `HARD` rule forbids it (no one-sentence paragraphs). Keep every heading. |
| A whole draft | Section by section, re-reading the profile's register table between sections. Keep the document's structure; do not add or remove sections. |
| A word or page limit | Preserve first, then cut; report every cut. |
| "de-AI this" | Same process; the Never list and the "words that are his" list carry the weight. Do not scrub *leverage*, *utilize*, *robust*, *crucial*, *very*, *significantly* — they are the author's. |

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
- **Import a framing from the exemplars.** The DESI/photo-*z* nouns are
  content.
- **Conjure a figure.** "Figure N shows …" is how *he* opens a results
  paragraph when there is a figure; it is not a licence to reference one the
  input does not have.
- **Add a summary sentence** at the end of a section that the input did not
  have.
- **Write a preamble or postamble.** Text only.

## Self-Check Before Finishing

1. Every number in the input is in the output, at the same precision. ☐
2. No claim is stronger than it was. ☐
3. Same `\cite` keys, attached to the same claims. ☐
4. All `\ref` / `\label` / math / floats untouched. ☐
5. No phrase of eight-plus words from an exemplar that was not in the input. ☐
6. Nothing from the Never list. ☐
7. Dashes ≤ 1 per page. ☐
8. No signature stacked more than twice in a paragraph. ☐
9. Venue spelling consistent. ☐
10. Litmus: read it once as the author. Would he have written it, or does it
    read as an AI imitating him? If the latter, remove the most recently added
    signature and reread. ☐

## Maintenance — the improvement loop

The profile is only as good as the loop that corrects it. The loop has five
steps; the first two are scripts, the third is an agent task, the last two
are occasional.

1. **Capture.** From the paper repo, `python <skill>/scripts/capture_edits.py`
   joins each logged delivery with the paragraph the author committed and
   writes the word-level diff and a normalized edit distance to
   `.co-writer/corrections.md`. This file is the training signal.
2. **Collect.** `python <skill>/scripts/collect_transcripts.py` links this
   repo's Claude Code sessions and any Antigravity artefacts that mention it
   into `.co-writer/transcripts/`, with an index. Context for step 3, not
   signal.
3. **Digest** — on request ("co-writer digest"). An agent reads
   `corrections.md` and the session notes, clusters recurring edits, and
   **proposes, never applies**: Never entries (three of the same correction),
   regraded rules, new exemplars taken from the author's accepted text,
   patterns for re-interview. The author approves each item. The profile's
   Version line and changelog are bumped; rejected proposals are recorded in
   the profile's Rejected section so they are not re-proposed.
4. **Eval.** At each profile version, the protocol in `eval/README.md`: six
   fixed inputs, edit the outputs, capture. Version n+1 is better than n if
   and only if the author edits less.
5. **New paper.** Run `scripts/extract_prose.py` on its `.tex`, re-run
   [references/extraction.md](references/extraction.md) over the full set,
   update [references/extraction-report.md](references/extraction-report.md),
   revise the profile. Rules whose evidence disappears are demoted, not kept.

The interview ([references/interview.md](references/interview.md)) runs once;
its Part 1 is re-run whenever the profile changes materially. The profile
has a 400-line cap — past it, compress; do not append.

## Interaction With Other Skills

co-writer is self-contained: it reads only its own `references/` and does not
load or defer to any other skill's writing guidance.

- **co-scientist** produces the science and assembles the report; co-writer
  is run afterwards, section by section, over the prose. co-scientist's
  manifest says which claims are verified; co-writer preserves claims, it
  does not vet them.
- **plot-style** makes the figure; co-writer writes its caption in the
  author's voice (the profile has a caption slot and exemplar).

## Files

```
skills/co-writer/
├── SKILL.md                         # this file
├── references/
│   ├── voice-profile.md             # THE artefact — read in full at write time
│   ├── extraction.md                # the deep-read prompt (maintenance)
│   ├── extraction-report.md         # evidence for every rule (maintenance)
│   └── interview.md                 # the questions the text cannot answer (maintenance)
├── scripts/
│   ├── extract_prose.py             # .tex → readable prose for extraction
│   ├── capture_edits.py             # session log + author's edits → corrections.md
│   └── collect_transcripts.py       # Claude Code / Antigravity transcripts → .co-writer/transcripts/
└── eval/
    ├── README.md                    # the per-version protocol
    └── 01-abstract.tex … 06-caption.tex   # fixed inputs, one per slot

<paper repo>/.co-writer/             # gitignored, written at use time
├── log/                             # one file per rewrite + one session note
├── corrections.md                   # from capture_edits.py
└── transcripts/                     # from collect_transcripts.py
```
