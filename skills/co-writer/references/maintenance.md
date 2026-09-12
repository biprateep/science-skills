# Maintenance — the improvement loop

Not read at write time. How the profile improves from use: capture, collect, digest, eval, new paper.

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
