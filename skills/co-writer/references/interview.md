# Voice interview — the layer the text cannot supply

Extraction (`extraction-report.md` in the active profile directory) reads what
the author's papers do. It cannot read *why*, whether a habit is a choice,
which of two registers is the target, or how the author positions a result.
That is what this interview supplies. Answers go into `voice-profile.md` in the
active profile directory (`~/.co-writer/profile/`, or `$CO_WRITER_PROFILE_DIR`)
tagged `attested`, alongside the `measured` rules from extraction.

Keep the author's completed interview status and Part 1 ratification table in
the active profile directory (`<profile>/interview.md`), not in the public
skill repository.

## How to run it

An agent runs this conversationally with the author, in batches of five to
eight questions, over one or two sessions. Part 1 first — it is fast, and its
answers make Part 2 specific. Record answers verbatim where the author gives a
sentence; a real sentence is worth more than any paraphrase.

## The interviewer's contract

Adapted from the two published voice-profile methods this skill drew on.

- **Push back on vague answers.** "I like directness" is not an answer. Ask
  what it looks like in a real sentence from one of the papers.
- **Reject the aspirational.** If an answer describes the writer the author
  wishes they were rather than the one on the page, say so — and cite the
  page. The extraction report exists for exactly this.
- **Reject the generic.** If an answer could describe any researcher in the
  field, flag it and ask what is specific to this author.
- **Demand sentences.** For every rule, ask for one sentence that follows it
  and one that breaks it.
- **Do not accept "I don't know."** Reframe: show two of the author's own
  sentences that differ on the point and ask which one they would keep.
- **Rejections are the richest data.** Spend more time on what the author
  refuses than on what they like.
- **Grade as you go.** Every answer gets a strength: `HARD` (never violate),
  `STRONG` (roughly four times in five), or `LIGHT` (context decides). Ask the
  author to grade it, then check the grade against the corpus count.

---

## Part 1 — Ratify the extraction (≈15 minutes)

Populate this table from the `DISTINCTIVE` and `UNSURE` findings in
`<profile>/extraction-report.md` (if paper extraction has been run; otherwise
skip straight to Part 2 or build rules incrementally from edits). For each
item, the author answers **keep**, **drop**, or **modify**, then grades it.

| # | Pattern | Report code | Ruling & grade |
|---|---|---|---|
| 1.1 | *(from extraction-report.md)* | A.1 | |

---

## Part 2 — The seven categories

### 2.1 Stance and positioning

1. When you introduce a competing method, what are you trying to make the reader feel about it before you say what is wrong with it?
2. What do you think is wrong with how papers in your subfield are usually written? Name a habit you see in referee reports or preprints that you refuse to do.
3. How much of a paper's introduction should teach? Who is the reader you are writing for — the referee, a first-year student, or your future self?
4. When your result contradicts a well-known paper, how do you say so? Give a sentence.
5. What do you never claim about your own method, even when it is true?
6. If your papers span multiple venues (journal vs. workshop/conference) or years, where do they differ in register, and which one is your target voice?

### 2.2 Writing mechanics

7. Do you draft in LaTeX from the first sentence, or in prose first? How do you use dashes, semicolons, and colons?
8. How long is a paragraph allowed to be? Do you prefer long, even single-topic paragraphs or shorter ones?
9. Do you care about restrictive "which" versus "that", or other copy-editing distinctions?
10. Are there word pairs you have strong preferences on (e.g., "use" vs. "utilize", "data set" vs. "dataset")?
11. American or British spelling — is it purely venue-dependent, or do you have a default?
12. How do you connect consecutive sentences (e.g., bare "This ...", explicit connectives, or repeating the noun)?
13. How do you decide between *we find*, *we observe*, *we see*, *we show*, and *we demonstrate*? Are they interchangeable, or is there a ladder?

### 2.3 What makes you wince

14. Name three phrases in other people's papers that you would cut on sight.
15. What does an AI-written paragraph look like to you? Be specific — which construction gives it away first?
16. Which of your own writing habits would you want toned down?
17. Rhetorical questions in a paper: never, or sometimes?
18. One-sentence paragraphs for emphasis: never, or sometimes?
19. Sentence-initial evaluative adverbs (*Interestingly,*, *Notably,*, *Importantly,*, *Crucially,*): allow, restrict, or ban?

### 2.4 Claim strength and hedging

20. When a result is good, how strongly do you say so in the abstract versus in the results section? Are they allowed to differ?
21. When a result is weak or null, where does it go — inline beside the main result, in a separate limitations section, or in a footnote?
22. What is your hedge ladder? Order these as you would use them: *suggests*, *indicates*, *shows*, *demonstrates*, *is consistent with*, *we find*, *proves*.
23. Are there intensifiers or loaded words (*significantly*, *very*, *robust*, *crucial*, *leverage*) that are naturally yours and should stay, or ones that should be cut?
24. When you do not know why something happened, what do you write? Give a sentence for a result you cannot explain.

### 2.5 Structure

25. Does every journal paper get a roadmap paragraph at the end of the introduction? What about short letters or workshop papers?
26. In a results section, do you open from the figure ("Figure N shows ...") or state the finding first and point to the figure parenthetically?
27. Where do derivations and pedagogical explanations belong — introduction, methods, or appendix?
28. How do you decide what goes in a caption versus the body text? Should a caption stand alone with a takeaway sentence?
29. Do you write the abstract first or last?
30. Summary versus Discussion versus Conclusions — which structure do you prefer, and do you include back-pointers to figures/sections?

### 2.6 Hard nos

31. Claims you will not make about your own work, regardless of what a co-author wants.
32. Words or constructions you will not use (beyond generic AI clichés).
33. Things you will not do to a co-author's or student's prose when you edit it.
34. Is there any construction you would want the skill to refuse to produce even if asked?

### 2.7 Red flags

35. What tells you within one paragraph that a paper was written by someone who does not understand their own method?
36. What tells you a limitation is being hidden?
37. What is the first thing you check in a results section as a referee?
38. What does over-polished prose look like in a technical paper, and what does it cost the reader?

---

## Part 3 — Calibration sentences (≈10 minutes)

Ask for these verbatim; they go straight into the profile's specimens or calibration block.

39. One sentence from your own papers you are proudest of, and why.
40. One sentence from your own papers you would rewrite today, and the rewrite.
41. The sentence you would write to open a results paragraph when the result is exactly what you expected.
42. The sentence you would write when the result is not what you expected.
43. The last sentence of a paper, when the future work is concrete.
44. The last sentence of a paper, when it is not.

## Output

Every answer becomes either a rule in `<profile>/voice-profile.md` (with its
grade and `attested` tag), an entry in the Never or keep list, a specimen, or a
note in the profile's Rejected section recording that the author saw the
pattern and declined it. Nothing from the interview is discarded silently.
