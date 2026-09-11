# Voice interview — the layer the text cannot supply

**Status:** Part 1 completed 2026-09-11 (all 27 ratified). Part 2 answered so
far: 4, 5, 6, 10, 11, 12, 15, 16, 21, 23, 31, 32, 33. Remaining Part 2 and
Part 3 in progress.

Extraction ([extraction-report.md](extraction-report.md)) reads what the
papers do. It cannot read *why*, whether a habit is a choice, which of two
registers is the target, or how the author positions a result. That is what
this interview supplies. Answers go into [voice-profile.md](voice-profile.md)
tagged `attested`, alongside the `measured` rules from extraction.

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
- **Reject the generic.** If an answer could describe any astronomer, flag it
  and ask what is specific to this author.
- **Demand sentences.** For every rule, ask for one sentence that follows it
  and one that breaks it.
- **Do not accept "I don't know."** Reframe: show two of the author's own
  sentences that differ on the point and ask which one they would keep.
- **Rejections are the richest data.** Spend more time on what the author
  refuses than on what they like.
- **Grade as you go.** Every answer gets a strength: HARD RULE (never
  violate), STRONG TENDENCY (roughly four times in five), or LIGHT PREFERENCE
  (context decides). Ask the author to grade it, then check the grade against
  the corpus count.

---

## Part 1 — Ratify the extraction (≈15 minutes)

Each item is a pattern the extraction found. The author answers **keep**,
**drop**, or **modify**, then grades it. Cross-references are to the report.

| # | Pattern | Report |
|---|---|---|
| 1.1 | Abstract runs two or three sentences of need before the first "We" | A.1 |
| 1.2 | Every named technique explained in plain language at first use, even standard ones | A.5 |
| 1.3 | Results narrated from the figure: "Figure N shows… We see that…" | A.6 |
| 1.4 | Concessive sentences "While / Though / Although X, Y" as the way to bind a caveat to a result | A.7 |
| 1.5 | "in a future work" — with the article | A.8 |
| 1.6 | Paragraphs close on "Therefore, …" / "Consequently, …" / "Thus, …" | B.1 |
| 1.7 | Sentence-initial bare "This" as the glue between sentences | B.2 |
| 1.8 | Long single-topic paragraphs; no one-sentence paragraphs | B.3 |
| 1.9 | "We first… We then… Next,… Finally," for procedures; never a numbered list | B.4 |
| 1.10 | Purpose-infinitive openers: "To [verb] …, we …" | C.1 |
| 1.11 | "(also called X)" and "(e.g., X, Y, etc.)" glosses | C.2 |
| 1.12 | Short sentences carry setup facts only, never emphasis | C.3 |
| 1.13 | Restrictive "which" without a comma | C.6 |
| 1.14 | Hedged mechanism: "This might be because", "We suspect", "can be attributed to" | D.2 |
| 1.15 | Negative result in the same paragraph as the positive, with "However," and a cause | D.3 |
| 1.16 | Surprise marked with "remarkably / unsurprisingly / as expected", never "interestingly" | D.4 |
| 1.17 | Credit a competing method before criticising it | E.2 |
| 1.18 | Paired numbers in parentheses with "vs." | E.3 |
| 1.19 | "gives us / provides us with / allows us to / tells us" | F.2 |
| 1.20 | "We note that" — never "Note that" or "It is worth noting" | F.4 |
| 1.21 | "leverage", "utilize", "robust", "crucial", "transformative", "powerful", "very", "significantly" are yours and stay | G.1 |
| 1.22 | Dashes almost never; semicolons in journal papers only | H.1, H.2 |
| 1.23 | Double quotes around a coined term at first use | H.4 |
| 1.24 | Plain-English restatement sentence after an equation's "where" clause | I.1 |
| 1.25 | Captions are full legends ending in the takeaway | I.3 |
| 1.26 | Exact counts, thousands separators from five digits, ranges in parentheses | J.1, J.2 |
| 1.27 | Explicit naming: "which we call", "hereafter", "(or simply …)" | G.2 |

---

## Part 2 — The seven categories

### 2.1 Stance and positioning (was "Beliefs & contrarian takes")

1. When you introduce a competing method, what are you trying to make the reader feel about it before you say what is wrong with it? The papers always credit first (E.2) — is that generosity, caution, or strategy?
2. What do you think is wrong with how papers in your subfield are usually written? Name a habit you see in referee reports or on arXiv that you refuse to do.
3. How much of a paper's introduction should teach? The extraction found you explain logistic regression and CNNs to readers who know them (A.5). Who is the reader you are writing for — the referee, a first-year student, your future self?
4. When your result contradicts a well-known paper, how do you say so? Give a sentence.
5. What do you never claim about your own method, even when it is true?
6. The 2026 conference papers reach for "novel", "uniquely", "for the first time", "Crucially,", "This proves that". The 2021–2024 papers never do. Which one is you, and what happened in between?

### 2.2 Writing mechanics

7. Do you draft in LaTeX from the first sentence, or in prose first? Does that explain the near-absence of dashes (H.1)?
8. How long is a paragraph allowed to be? ENC has a 330-word paragraph. Would you split it today?
9. "which" without a comma before a restrictive clause (C.6). Keep, or would you accept a copy-editor changing it to "that"?
10. "utilize" vs "use" — DESI has both. Which is yours?
11. "data set" or "dataset"?
12. British or American — you have written both. Is it purely venue, or do you have a default when the venue does not care?
13. Sentence-initial "This" with no noun (B.2) — do you know you do it? Keep?
14. How do you decide between "We find", "We observe", "We see", "We show", "We demonstrate"? Are they interchangeable to you, or is there a ladder?

### 2.3 What makes you wince (was "Aesthetic crimes")

15. Name three phrases in other people's astronomy papers that you would cut on sight.
16. What does an AI-written paragraph look like to you? Be specific — which construction gives it away first?
17. Which of your own habits would you be embarrassed to see a referee point out?
18. Rhetorical questions in a paper: never, or sometimes?
19. One-sentence paragraphs for emphasis: never, or sometimes?
20. Sentence-initial "Interestingly," / "Notably," / "Importantly,": you used "Importantly" once in 33,000 words. Rule or accident?

### 2.4 Claim strength and hedging (was "Voice & personality")

21. When a result is good, how strongly do you say so in the abstract versus in the results section? Are they allowed to differ?
22. When a result is weak or null, where does it go — abstract, results, discussion, or a footnote? The papers integrate it inline with "However," (D.3). Deliberate?
23. What is your hedge ladder? Order these as you would use them: *suggests*, *indicates*, *shows*, *demonstrates*, *is consistent with*, *we find*, *proves*.
24. "significantly" — you use it about once per 700 words, never with a p-value. Do you mean it statistically, or as "a lot"? Would you accept a reader taking it statistically?
25. "very" — you use it. Most style guides say cut it. Keep?
26. When you do not know why something happened, what do you write? The corpus says "This might be because" / "We suspect" (D.2). Confirm, and give the sentence you would write for a result you cannot explain at all.

### 2.5 Structure

27. Does every journal paper get a roadmap paragraph (A.4)? Would you write one for a letter-length paper?
28. Results section: figure first, then narration (A.6) — or would you sometimes state the number and then point at the figure?
29. Where does the method's pedagogical explanation belong — introduction, methods, or appendix? ENC puts the capsule maths in an appendix and the intuition in the body.
30. How do you decide what goes in a caption versus the text? Your captions are full legends with a takeaway (I.3) — is the caption supposed to stand alone?
31. Do you write the abstract first or last?
32. Summary versus Discussion versus Conclusions — which do you want, and do you want the "(see Fig. N)" pointers in the summary (A.9)?

### 2.6 Hard nos

33. Claims you will not make about your own work, regardless of what a co-author wants.
34. Words you will not use. (The extraction found none of the usual AI-isms; is there a list of your own?)
35. Things you will not do to a co-author's or student's prose when you edit it.
36. Is there any construction you would want the skill to refuse to produce even if asked?

### 2.7 Red flags

37. What tells you within one paragraph that a paper was written by someone who does not understand their own method?
38. What tells you a limitation is being hidden?
39. What is the first thing you check in a results section as a referee?
40. What does over-polished prose look like in a physics paper, and what does it cost the reader?

---

## Part 3 — Calibration sentences (≈10 minutes)

Ask for these verbatim; they go straight into the profile's Voice Calibration
block.

41. One sentence from your own papers you are proudest of, and why.
42. One sentence from your own papers you would rewrite today, and the rewrite.
43. The sentence you would write to open a results paragraph when the result is exactly what you expected.
44. The sentence you would write when the result is not what you expected.
45. The last sentence of a paper, when the future work is concrete.
46. The last sentence of a paper, when it is not.

## Output

Every answer becomes either a rule in the profile (with its grade and
`attested` tag), an entry in the Never list, a Voice Calibration line, or a
note in the profile's "rejected" section recording that the author saw the
pattern and declined it. Nothing from the interview is discarded silently.
