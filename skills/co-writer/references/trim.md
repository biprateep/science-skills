# Hard limits — the trim

Read only when a page or word limit is in play. The protocol and the proposer's brief.

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
   `python <skill>/scripts/check_fixed.py --allow-drop PRE-TRIM POST-TRIM`: every WARN is a number,
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
