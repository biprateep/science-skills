# Fixed evaluation set

Six inputs, one per major slot, written deliberately in the register a
language model defaults to: sentence-initial "Notably," and "Crucially,",
em-dash asides, rule-of-three lists, "delve", "underscore", "paradigm
shift", "pave the way", a one-sentence punch, "In summary". Topics are
unrelated to the author's papers so that exemplar content leaking into the
output is detectable.

| file | slot | register |
|---|---|---|
| 01-abstract.tex | abstract | journal |
| 02-gap.tex | gap-and-contribution | journal |
| 03-methods.tex | methods, with an equation | journal |
| 04-results.tex | results | journal |
| 05-limitation.tex | limitation and close | journal |
| 06-caption.tex | caption | journal |

## Protocol, once per profile version

1. In a fresh session with no prior context, run co-writer over each input
   and save each output to `eval/runs/<profile-version>/NN.tex`. The skill's
   session-log convention records the delivery in `.co-writer/log/` with
   `file: skills/co-writer/eval/runs/<version>/NN.tex`.
2. Edit each output in place until it reads as yours. Do not retype it;
   edit the delivered text so the diff is the correction.
3. Run `python skills/co-writer/scripts/capture_edits.py` from the repo root.
   The summary prints mean edit distance per profile version.

Version n+1 is better than version n if and only if the mean distance is
lower on this set. `eval/runs/` is gitignored; the inputs are not.

The inputs cite keys that exist in no `.bib`, so for citations an eval run
is inline mode: the set comparison applies, the cite-check pass does not.
