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
  version: "0.3.0"
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
6. **The cold read** (section below): always for a section or a draft; for a
   single paragraph, whenever an agent is available.
7. **Citations, when the text is file-backed and a citing sentence changed**
   — hand the changed instances to cite-check (see "Citations" below). A
   section or draft is not done until cite-check's `audit` is `ok`.
8. **Return the text only.** No preamble, no "Here is the rewritten version",
   no summary of changes, no closing offer. If the user asked for a diff or a
   rationale, give the text first and the rationale after a rule. Never
   certify the voice; the passages you are least sure of go into the session
   log, not into the reply.

## The Cold Read

The session that has just written a passage is the worst-placed reader it will
ever have: it knows what every sentence was meant to do. So the litmus question
— would he have written this? — is never answered by the writer. It goes to a
reader that never saw the composition.

**Who.** A separate agent: Claude Code `Agent` (general-purpose); Antigravity, a
spawned agent; a harness with neither, a later pass in a fresh context with the
text in front of you and nothing else, recorded in the session log as
`cold_read: no`. Section and draft mode: always. A single paragraph: when an
agent is available.

**What it gets.** The output, the profile, the slot and the register. Never the
input, never the content list, never the writer's reasoning — a reader told
what a passage was meant to do reads what it was meant to do.

**The brief.** Hand it over with the slots filled.

> Read the passage at `<path>` as its author would, and report what he would
> not have written. You rewrite nothing and propose no sentences. His voice
> profile is `<profile path>`; read it whole, specimens first. The passage is
> a `<slot>` from a `<journal | workshop>` paper.
>
> Answer three questions, each item with the sentence quoted.
> 1. Which sentences read as a model imitating him rather than as him? Name
>    the construction that gives each away.
> 2. Where is a signature stacked — a construction from the profile used more
>    than twice in one paragraph, or a "(also called …)", a "Therefore," or a
>    "To …, we …" that carries nothing?
> 3. Which claims read stronger than a careful referee would accept as
>    written — a hedge missing, a result verb above what the sentence's
>    evidence supports, a flourish standing where a fact should be?
>
> Nothing else is a finding: not length, not what the passage says twice, not
> whether you would have said it differently. If you find nothing under a
> question, say so; a clean answer is information. Order each list by how
> much it matters. Say what you mean — no metaphor where a literal phrase
> exists. Do not certify the voice, and do not stop to ask.

**What the writer does with it.** Check each item against the profile and the
specimen; a construction the corpus attests is not a finding. For each that
survives, re-read the specimen for the slot and write that stretch again. Do
not patch the sentence against the Never list — a passage revised against a
list gets worse. One round; then the passage moves on. The cold read
describes; only the author certifies.

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
cold_read: yes | no | n/a
file: <path of the .tex the output went into, relative to the repo root; omit if returned inline only>
---
## Input
<the input exactly as received>
## Output
<the output exactly as delivered>
## Note
<what the user said about the output in the same session, verbatim; omit the section if nothing>
## Unsure
<the passages the writer is least sure of, quoted; omit if none>
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
- **Specimen content does not leak.** The profile's quarantine list names
  the nouns; if any phrase of eight or more words from an specimen appears
  in the output and was not in the input, remove it.
- **Hard limits are met by the trim** (section below), never by writing
  shorter or by compressing a claim away. What leaves under a ruled cut is
  listed after the text.

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

## Hard Limits — The Trim

A page or word limit is met by a trim: measure, propose, the author rules,
cut, measure again. Nothing is written shorter to begin with.

1. **Measure the gap first.** `python <skill>/scripts/extract_prose.py
   --counts main.tex` gives words per section; pages come from the compile.
   Write the excess per section against the target before any candidate is
   looked at, because the gap decides how deep the cuts go and which kind
   they are. A gap that removing a whole section would not close is a fault
   in the paper's design, not a cutting problem: say so and stop.
2. **Never cut scaffolding**, whatever else is over: the plain-language
   explanation of a technique at first use, the sentence after an equation
   saying what it means, the mechanism offered for a result, the concessive
   sentence binding a caveat to its claim. These are the author's voice
   (profile A.5, I.1, D.2, A.7); a trim that removes them has cut him, not
   the excess. The test for a cut is what the reader loses, never whether
   words recur.
3. **The proposer** — a cold agent that did not write the text, given the
   file, the counts and the gap — proposes and cuts nothing. Two classes,
   every candidate with the passage quoted, its class, the words it recovers
   and what the reader loses in one sentence:
   - *Mechanical, repeats:* a result stated a second time; a hand-off
     restated at the next section's opening; a value printed in the prose and
     again in its caption; a sentence recapping what an earlier section
     established; a caption narrating what the paragraph beside it narrates.
   - *Judgment, content:* an explanation that continues after the reader has
     it; a second example where the first taught the point; a derivation whose
     steps could move to an appendix, the text keeping the statement; a
     paragraph answering an objection the referee would not raise; a figure
     making a comparison another figure already makes.
   The proposer lists separately every passage it left because it could not
   tell a repeat from scaffolding.
4. **Check and rank.** Strike any candidate that removes scaffolding, a value
   or label the paper depends on elsewhere, or a claim the argument later
   leans on; say what was struck. Rank the rest by words recovered against
   what the reader loses, mechanical first, and sum the list against the gap
   so the author can see how far down it the target sits.
5. **Take the author through them.** Mechanical cuts as one question with the
   list in front of him. Judgment cuts one at a time, each with its case in
   prose before the question: the passage, what it teaches, what the paper
   loses without it, what it recovers, your lean. Stop when the gap is closed
   or when he says the paper stays where it is. Nothing is cut before he has
   ruled.
6. **Make the ruled cuts**, with at most the words that join two standing
   sentences. A cut that needs prose — a condensed passage, a derivation moved
   to an appendix — is written from the specimen like any other unit. Then
   `check_fixed.py --allow-drop PRE-TRIM POST-TRIM`: every WARN is a number,
   citation or reference that left with a ruled cut and goes in the list after
   the text; a FAIL is something added, and is a bug.
7. **Measure again** and read the whole once, because a dozen small cuts read
   differently together. Report what came out, what he kept, and what remains
   over the target.

The proposer's brief:

> Propose the cuts that would bring `<file>` to `<target>`, and cut nothing.
> The words per section and the gap per section are at `<path>`; propose
> against those gaps and not elsewhere. Never propose: the explanation of a
> technique at its first use, the sentence after an equation that says what
> it means, the mechanism offered for a result, or a concessive sentence
> binding a caveat to its claim; where you cannot tell one of those from a
> repeat, leave it and list it under "left". Two classes, mechanical (repeats)
> and judgment (content), and every candidate names its class. For each: the
> passage quoted exactly, the class, the words it recovers, what the reader
> loses in one sentence, and, where the cut is not a pure removal, what the
> replacement would have to say. Hand back the candidates ordered by words
> recovered, mechanical first, then the passages you left, then the sections
> whose gap the candidates do not close. Say what you mean. Do not stop to ask.

## Modes by Input

| Input | What changes |
|---|---|
| A sentence or paragraph pasted inline | Rewrite in place; return the paragraph. |
| A section (`\section` to `\section`) | Keep the paragraph count and order unless a `HARD` rule forbids it (no one-sentence paragraphs). Keep every heading. |
| A whole draft | Section by section, re-reading the profile's register table between sections. Keep the document's structure; do not add or remove sections. |
| A word or page limit | The trim, above: measure, propose in two classes, the author rules, cut, measure again. |
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
   `corrections.md`, the session notes and the `Unsure` lines, clusters the
   recurring edits, and turns each cluster into a **candidate**: the smallest
   change to the profile that would have produced what the author accepted —
   a Never entry, a regraded rule, a new specimen taken from his accepted
   text, a counterexample from a rejected sentence with his objection
   verbatim. Every candidate takes one of three routes, his choice, one
   question each with your lean.
   - **Adopted.** He stated it as a rule, in a Note or in the interview. It
     goes in.
   - **Tested.** The candidate is your reading of his edits rather than his
     words, and an experiment decides: run co-writer in a fresh context on
     the logged input with the amended profile and nothing he said, and ask
     whether it now makes the change unprompted — `capture_edits.py`
     distance against his accepted text drops, or the cold read no longer
     flags what he fixed. Passing adopts. Failing rejects, and the profile's
     Rejected section records the candidate with what the experiment showed,
     so it is not re-proposed.
   - **Held.** It waits for the next digest, where recurrence is evidence.
   The profile's Version line and changelog are bumped once per digest.
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
  author's voice (the profile has a caption slot and specimen).

## Files

```
skills/co-writer/
├── SKILL.md                         # this file
├── references/
│   ├── voice-profile.md             # THE artefact — read in full at write time; specimens outrank rules
│   ├── counterexamples.md           # sentences the author rejected, objection verbatim — read once after drafting
│   ├── extraction.md                # the deep-read prompt (maintenance)
│   ├── extraction-report.md         # evidence for every rule (maintenance)
│   └── interview.md                 # the questions the text cannot answer (maintenance)
├── scripts/
│   ├── check_fixed.py               # INPUT vs OUTPUT: cites, refs, labels, math, numbers — the preservation gate
│   ├── check_mannered.py            # stock phrases and Never-list hits, with lines — calibration, not a verdict
│   ├── extract_prose.py             # .tex → readable prose; --counts gives words per section for the trim
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
