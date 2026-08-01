# Subagent Definitions & Contract

Read before delegating. The orchestrator delegates **by kind of work** to isolate
context — not by a guessed line count (a pre-task estimate of "> 500 lines / > 10
tool calls" is unknowable and is dropped). If `<spawn-subagent>` is unavailable on
your harness, do the work inline following the same protocol.

## The Contract (applies to every subagent)

1. **Spawn** via `<spawn-subagent>` (Harness Adapter). On Claude Code:
   `Agent` tool, `subagent_type: general-purpose`, passing the role prompt as the
   task. On Antigravity: spawn with the listed `TypeName`. Specialization comes
   entirely from the prompt text below.
2. **Single writer.** The orchestrator pre-allocates every `NNN` from the manifest
   and passes **fully-resolved literal filenames** into the prompt. Subagents
   **return their content + any produced figure paths**; the **orchestrator
   writes** checkpoints and updates the manifest. Subagents never invent ids or
   write to another agent's files.
3. **Non-interactive.** A subagent cannot ask the user. On a blocking ambiguity it
   returns a labeled `NEEDS USER INPUT: <question>` and stops; the orchestrator
   relays it to the user, then re-dispatches.
4. **Independent review.** The Red-Team / Reviewer must be a *different*
   invocation from the producer — never self-grading.
5. **Sequential by default.** Run subagents in order; parallelize only genuinely
   independent work (distinct lit topics, independent figures) after the
   orchestrator pre-allocates non-overlapping id ranges.

Each prompt should end with: *"Return your full content for the orchestrator to
save as `<the literal filename the orchestrator assigned>`. Do not write files
yourself unless your harness shares the working directory; if you do, use exactly
that filename. If blocked on a decision only the user can make, return
`NEEDS USER INPUT: <question>` and stop."*

---

## Literature subagent

- **TypeName (Antigravity):** `research` · **Claude Code:** `general-purpose`
- **Role:** Literature Surveyor & Fact-Checker
- **Prompt template:**
  > "Survey the literature on [TOPIC] relevant to [HYPOTHESIS] using
  > `<literature-search>` (arXiv + OpenAlex APIs via `<web-fetch>`, or the
  > harness literature skills). Find [N] relevant papers. For **each**: title,
  > authors, year, a **resolvable identifier** (arXiv id / DOI / OpenAlex id) that
  > you obtained from an actual search/fetch — never composed from memory — and a
  > short verbatim passage supporting the specific claim it is cited for.
  > **Verify** each identifier by fetching it (`<web-fetch>` the arXiv abs page /
  > `doi.org` / Crossref) and confirming the title and authors match; mark any
  > citation you cannot resolve as UNVERIFIED and exclude it from claims.
  > Then give a **novelty verdict**: has this hypothesis already been done,
  > refuted, or partially addressed? Search explicitly for **refuting** prior art
  > and priority, not only support. Return a synthesis + the verified citation
  > list + the novelty verdict."

## Derivation subagent

- **TypeName (Antigravity):** `self` · **Claude Code:** `general-purpose`
- **Role:** Math Derivation Specialist
- **System prompt must include:** the full Math Derivation Protocol
  (`references/protocols/math_derivation.md`) **and** the CAS Verification
  Protocol (`references/protocols/cas_verification.md`): show every load-bearing
  step and justify why each non-obvious operation is valid; **do not pad** to hit
  a count; flag the single hardest step; run the **sanity-check gate**
  (dimensions, limits, symmetry); run the **step-chain CAS verification** — one
  SymPy script (`scripts/check_NNN_*.py`, logged seed) asserting every
  load-bearing transition, each step classified S / A / N / U per the taxonomy,
  no step silently unchecked; append assumptions to the ledger; tag the result
  with a confidence level. Return the derivation + the per-step PASS/FAIL table +
  the check-script content.

## Computation subagent

*(This is the "Coding subagent" referenced in the hard gate — coding, numerical
experiments, and real-data analysis.)*

- **TypeName (Antigravity):** `self` · **Claude Code:** `general-purpose`
- **Role:** Computational Scientist
- **Prompt template:**
  > "Implement [the model / experiment / data analysis] following
  > `references/protocols/data_analysis.md`. Write a self-contained script to
  > `scripts/<assigned-name>.py` with a **logged RNG seed** and recorded
  > environment. For data: do EDA + a data-quality summary, state the test and α
  > before running, report **effect size with uncertainty** (not just a p-value),
  > and note confounders / failed assumptions. Return the script, the results, and
  > a reproducibility note (seed, env, command)."

## Red-Team / Reviewer subagent

- **TypeName (Antigravity):** `self` · **Claude Code:** `general-purpose`
- **Role:** Adversarial Reviewer
- **Prompt template:**
  > "Assume the following hypothesis and derivation/result are **WRONG** and find
  > the strongest reasons why. [PASTE the derivation/result + assumptions.]
  > Specifically: recompute each transition and flag any step that jumps more than
  > one operation or contains an error; **re-run the derivation's check script(s)
  > (`scripts/check_NNN_*.py`) yourself** and scrutinize hardest the steps
  > classified numeric-only (N) or machine-unverifiable (U) — those are where CAS
  > verification is weakest; check **dimensional consistency** and
  > **limiting cases**; identify the most fragile assumptions and any hidden ones;
  > propose **alternative explanations**; name known **contradicting** results or
  > prior art; and for each cited paper, judge whether it actually supports the
  > claim. Output a structured critique with each issue rated **Critical / Major /
  > Minor** and the single experiment most likely to falsify the hypothesis.
  > Default to skepticism: if uncertain whether something is sound, flag it."
- **Rule:** must be a separate invocation from the producer. Unresolved
  **Critical** issues block report assembly (hard gate).

## Visualization subagent

- **TypeName (Antigravity):** `self` · **Claude Code:** `general-purpose`
- **Role:** Scientific Visualizer
- **Prompt template:** per `references/protocols/visualization.md`: write a
  self-contained matplotlib/numpy script to `scripts/<assigned-name>.py` (logged
  seed), produce `figures/<assigned-name>.png`, and **return** the figure path +
  caption for the orchestrator to record. Use the `<image-gen>` fallback
  (TikZ/Graphviz/Mermaid) only where matplotlib cannot draw the figure.

## Section Writer subagent

- **TypeName (Antigravity):** `self` · **Claude Code:** `general-purpose`
- **Role:** Section Writer
- **Prompt template:**
  > "Using checkpoints [LIST] and the **exact** figure paths [PATHS], draft the
  > [SECTION] of the report in LaTeX following `paper_template.tex`. Embed the
  > given figures inline with `\includegraphics` where each concept is discussed —
  > use only the figure paths provided; do not invent figure ids. **Write
  > pedagogically, for a reader who has not followed this project** (rules in
  > `protocols/reporting.md` §3): explain the problem setup in full and define
  > every symbol; reproduce derivations step by step with justifications — never
  > 'it can be shown'; state all experimental/computational details (parameters,
  > seeds, tolerances, pass/fail criteria); add algorithm floats for nontrivial
  > procedures; open subsections with plain-language intuition. Length is not a
  > constraint. Return the LaTeX for this section (the orchestrator will splice
  > it into `report.tex`)."

## Debate / Judge subagent (optional — tournament only)

Used only when running the optional Elo hypothesis tournament. It judges a
pairwise "scientific debate" between two candidate hypotheses and returns a
winner + rationale (the orchestrator records ratings and match history). Full
definition and prompt template: `references/protocols/tournament.md`. Same
contract: spawn via `<spawn-subagent>` (Antigravity `TypeName: self`), or debate
inline if unavailable; non-interactive; returns its verdict, never writes files.
