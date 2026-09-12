# Voice extraction — the deep read

A prompt for an agent that reads the author's finished papers and reports what
it observes. The output feeds [voice-profile.md](voice-profile.md); it is not
the profile. The extractor **describes**; the profile **decides**.

## Inputs

Prose files produced by `scripts/extract_prose.py` — one per paper, with
section headings kept, inline math kept, citations rendered as `[cite]` /
`[Author et al.]`, display equations as `⟨display equation⟩`. Read every file
end to end before writing anything. Skimming produces adjectives; reading
produces mechanisms.

## Rules for the reader

1. **Evidence or nothing.** A pattern is reported only with at least two
   verbatim excerpts, each tagged with document and section. One occurrence is
   an observation and goes in a separate "observed once" list, never in a rule.
2. **Adjudicate genre before recording anything.** For every candidate pattern
   ask: *would this be true of any competent paper in this venue?* Passive
   voice in a methods section, a roadmap paragraph closing the introduction,
   hedged conclusions — that is astronomy, not the author. Tag each finding
   `DISTINCTIVE`, `GENRE`, or `UNSURE`. `GENRE` findings are still listed, in
   their own section, because the profile must not fight the register — but
   they never become voice rules.
3. **Tier by how widely it holds.** `ALL` = every paper; `JOURNAL` = only the
   long journal papers; `CONFERENCE` = only the short workshop/conference
   papers; `SINGLE` = one paper. Short and long papers have different length
   budgets, so a pattern that only holds on one kind is a format rule, not a
   voice rule.
4. **Mechanism, not adjective.** "Direct" and "clear" are not findings. "Four
   of five abstracts open with the scientific need, and the method appears
   only in the third sentence" is a finding.
5. **Absences count.** List constructions the author does not use — especially
   ones a language model would reach for by default (sentence-initial
   *Notably*, rule-of-three lists, em-dash asides, "delve", "crucial role",
   rhetorical questions, one-sentence paragraphs for emphasis). A voice is
   defined as much by what it refuses.
6. **Quarantine content.** Topic-specific framings — photo-*z* calibration,
   DESI, LSST — are subject matter, not voice. Flag any phrase whose reuse in
   an unrelated paper would import content rather than style.
7. **Do not prescribe.** No "should", no "always", no "never" in the report.
   Frequency labels are assigned later, in the profile, with the author.

## Dimensions to read for

| | Dimension | What to look at |
|---|---|---|
| A | Section moves | What each section does and in what order: abstract, introduction, data/methods, results, discussion, conclusion. Where the contribution is first stated. What the last paragraph of each section does. |
| B | Paragraph architecture | How paragraphs open (claim first? context first?), how they close, typical length, whether each carries one idea. |
| C | Sentence rhythm | Length variation within a paragraph; where the short sentences land; sentence openers (subject-first vs subordinate-clause-first vs connective-first); how long a sentence is allowed to run and what holds it together. |
| D | Claim strength and hedging | Verbs used to state a result (*show*, *find*, *demonstrate*, *suggest*); hedge vocabulary; how a limitation or negative result is phrased; superlatives and intensifiers, present or absent. |
| E | Positioning against prior work | How cited work is introduced (as agent, in parentheses, in lists); contrast constructions; how the gap this paper fills is framed; tone toward competing methods. |
| F | Agency and pronouns | *we* / *this work* / *the model* / passive — who performs the verbs, and whether that changes by section. |
| G | Vocabulary | Recurring verbs, nouns, connectives, and turns of phrase; words the author reaches for repeatedly; words conspicuously absent. |
| H | Punctuation and typography | Commas, semicolons, colons, parentheticals, dashes, quotation marks, italics for terms; how lists are punctuated. |
| I | Math and figure integration | How an equation is introduced and what follows it; how figures and tables are referenced in prose (subject of the sentence? parenthetical?); whether results are narrated from the figure or stated then pointed to. |
| J | Numbers in prose | Precision, units, how comparisons are made (ratios, percentages, absolute), whether numbers lead or follow the claim. |
| K | Definitions and acronyms | How a term is introduced; whether acronyms are defined in prose or parenthetically; whether the author restates definitions. |
| L | Absences and refusals | Everything the author does not do. |

## Output format

Write `extraction-report.md` with one entry per finding:

```
### <dimension letter>.<n> <short name>
Tier: ALL | JOURNAL | CONFERENCE | SINGLE
Genre: DISTINCTIVE | GENRE | UNSURE
Pattern: one or two sentences — mechanism, not adjective.
Evidence:
- [<doc>, <section>] "verbatim excerpt"
- [<doc>, <section>] "verbatim excerpt"
Counter-evidence: where the pattern breaks, if it does.
```

Then four closing sections:

- **Genre baseline** — the `GENRE` findings, so the profile knows what the
  register demands and does not fight it.
- **Content to quarantine** — phrases and framings that are subject matter.
- **Candidate specimens by section function** — two or three verbatim
  paragraphs each for: abstract, introduction opener, gap-and-contribution
  statement, methods paragraph, results paragraph, limitation/hedge,
  discussion or conclusion close, figure caption. Tag each with document and
  section. These are chosen for being *typical*, not for being the best prose.
- **Questions for the interview** — everything the text cannot settle: whether
  a pattern is the author's or a co-author's, whether a construction is a
  choice or a habit, what the author would change on reread.

## Corpus notes for this run

Five papers, all first-author or corresponding-author with the prose written
by the author:

| doc id | venue | length | notes |
|---|---|---|---|
| DESI | journal (AAS) | ~11.5k words | 2024, large collaboration author list |
| encapzulate | journal | ~11k words | 2021, capsule networks for photo-*z* |
| recalibrate | NeurIPS workshop | ~1.8k words | 2021, PDF re-calibration |
| Peng | NeurIPS workshop | ~1.7k words | 2026, student first author; prose by the author |
| Pratsos | NeurIPS workshop | ~1.5k words | 2026, student first author; prose by the author |

Two long journal papers carry 82% of the words. A pattern that holds on the
long two and not the short three is `JOURNAL`, not `ALL`.
