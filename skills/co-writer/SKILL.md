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
  version: "0.2.0"
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
6. **Citations, when the text is file-backed and a citing sentence changed**
   — hand the changed instances to cite-check (see "Citations" below). A
   section or draft is not done until cite-check's `audit` is `ok`.
7. **Return the text only.** No preamble, no "Here is the rewritten version",
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
- **Exemplar content does not leak.** The profile's quarantine list names
  the nouns; if any phrase of eight or more words from an exemplar appears
  in the output and was not in the input, remove it.
- **Hard limits cut content only visibly.** If a page or word limit forces
  dropping information, return the list of what was dropped after the text.
  Never silently compress a claim away.

## Citations — cite-check does the verifying

co-writer has no citation logic of its own beyond the set comparison above.
Existence, provenance and support are computed by the **cite-check** skill
(`skills/cite-check/`), the repository's one citation engine, and every
improvement made there applies here with no change to this file. Before the
first citation action in a session, read its contract —
`<skills>/cite-check/references/integration.md` — and follow it; where this
section and that file differ, that file wins.

**Finding the tools.** cite-check is a sibling of this skill: the same
`skills/` directory in the repository, or the same directory of symlinks the
installer wrote (`~/.claude/skills/`). In order: (1) the harness lists the
tools (`mcp__cite-check__*` in Claude Code; server `cite-check` elsewhere) →
call them; (2) it does not → run `bash <skills>/cite-check/mcp/setup_mcp.sh`
once, and for the rest of this session use the identical CLI:
`<skills>/cite-check/mcp/.venv/bin/python <skills>/cite-check/mcp/server.py call <tool> '<json>'`
(exit 0 pass, 1 fail, JSON on stdout); (3) `ping` once — no ADS token → say
so to the user once, then proceed with the other registries.

**When co-writer calls it — three triggers.**

1. **A rewrite changed a sentence that carries a citation.** Restyling a
   citing sentence changes its claim, and the cited paper may no longer
   support the claim as now written. After a section rewrite: `extract_cites`
   on the rewritten file; cite-check's support check (its Workflow C —
   `fetch_text`, `find_passages`, an **independent** judge, `record_support`)
   on every instance whose claim changed; then
   `audit(tex_path, require_support=true)`. Two rules must both hold:
   co-writer's, that the sentence is no stronger than the input's; and
   cite-check's, that the paper supports the sentence as written.
2. **The user asks for a citation, or the input carries a gap** — `[cite]`,
   `\cite{?}`, "(REF)", "citation needed". cite-check's Workflow A:
   `search_citation` → take a `high` candidate, ask the user about a `medium`,
   never a `low` → `bib_add` → write `\cite{<key>}` → support check for that
   instance. `no-official-bibtex` → leave the sentence uncited and say so.
   This is the only way a key enters the output that was not in the input.
3. **A whole draft, or anything the user calls finished.** `audit` must
   return `ok: true`. Relay its `failures` and `warnings` to the user
   verbatim; do not soften them and do not lower `require_support`.

**Inline mode.** A paragraph pasted into the chat has no `.bib` and no file.
There co-writer applies the set comparison only, and says once that the
support check runs when the paragraph is in its file.

**Never**, however the request is phrased: write or complete a `.bib` entry;
cite a key, DOI, arXiv id or bibcode from memory; record a support verdict
co-writer decided itself while writing; re-implement any cite-check check
with its own reasoning; edit anything under `cite-check/mcp/`.

## Modes by Input

| Input | What changes |
|---|---|
| A sentence or paragraph pasted inline | Rewrite in place; return the paragraph. |
| A section (`\section` to `\section`) | Keep the paragraph count and order unless a `HARD` rule forbids it (no one-sentence paragraphs). Keep every heading. |
| A whole draft | Section by section, re-reading the profile's register table between sections. Keep the document's structure; do not add or remove sections. |
| A word or page limit | Preserve first, then cut; report every cut. |
| "de-AI this" | Same process; the Never list and the "words that are his" list carry the weight. Do not scrub *leverage*, *utilize*, *robust*, *crucial*, *very*, *significantly* — they are the author's. |
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
- **Import a framing from the exemplars.** The DESI/photo-*z* nouns are
  content.
- **Conjure a figure.** "Figure N shows …" is how *he* opens a results
  paragraph when there is a figure; it is not a licence to reference one the
  input does not have.
- **Add a summary sentence** at the end of a section that the input did not
  have.
- **Verify a citation by reasoning.** "This DOI looks right", "I recall that
  paper shows this" — not a check. cite-check's tools are the check.
- **Write a preamble or postamble.** Text only.

## Self-Check Before Finishing

1. Every number in the input is in the output, at the same precision. ☐
2. No claim is stronger than it was. ☐
3. `keys_out ⊆ keys_in`, each key attached to the claim it was attached to. ☐
4. File-backed and a citing sentence changed → cite-check's support pass run;
   a section or draft is called done only with `audit` ok. ☐
5. All `\ref` / `\label` / math / floats untouched. ☐
6. No phrase of eight-plus words from an exemplar that was not in the input. ☐
7. Nothing from the Never list. ☐
8. Dashes ≤ 1 per page. ☐
9. No signature stacked more than twice in a paragraph. ☐
10. American spelling throughout. ☐
11. Litmus: read it once as the author. Would he have written it, or does it
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

skills/cite-check/references/integration.md   # read before any citation action — the contract this skill follows
```
