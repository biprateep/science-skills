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
6. **Component skills by name, never by content.** When a subagent's work falls
   in a component skill's portion (SKILL.md → Component Skills), its prompt
   says *"Load the `<name>` skill with `<load-skill>` and follow it in full"*.
   Do not paste, summarize or paraphrase that skill's rules into the prompt:
   the subagent reads the current version itself.

Each prompt should end with: *"Return your full content for the orchestrator to
save as `<the literal filename the orchestrator assigned>`. Do not write files
yourself unless your harness shares the working directory; if you do, use exactly
that filename. If blocked on a decision only the user can make, return
`NEEDS USER INPUT: <question>` and stop."*

---

## Literature subagent

- **TypeName (Antigravity):** `research` · **Claude Code:** `general-purpose`
- **Role:** Literature Surveyor
- **Prompt template:**
  > "Survey the literature on [TOPIC] relevant to [HYPOTHESIS] using
  > `<literature-search>` (arXiv + OpenAlex APIs via `<web-fetch>`, or the
  > harness literature skills). Find [N] relevant papers. Load the
  > **cite-check** skill with `<load-skill>` and read its caller contract,
  > `<skills>/cite-check/references/integration.md`; identify every paper you
  > report through its tools exactly as that contract says — an identifier
  > from memory or from a page you read is a search query, not a result. For
  > each paper return: the identifier and candidate confidence cite-check gave,
  > title, year, and the specific claim you would cite it for. A paper
  > cite-check cannot identify is listed as UNVERIFIED and supports no claim.
  > Then give a **novelty verdict**: has this hypothesis already been done,
  > refuted, or partially addressed? Search explicitly for **refuting** prior art
  > and priority, not only support. Return a synthesis + the candidate list +
  > the novelty verdict. Do not write a `.bib`; the orchestrator does that
  > through cite-check."
- **Orchestrator, after it returns:** add the papers the report will cite to
  `report.bib` with cite-check (its contract, "When the caller adds a
  citation"), and record each in the manifest's `citations` section. Whether a
  paper supports its sentence is judged later, on the report's final prose
  (`protocols/reporting.md` §5), because rewording a sentence invalidates a
  verdict on the old one.

## Derivation subagent

- **TypeName (Antigravity):** `self` · **Claude Code:** `general-purpose`
- **Role:** Math Derivation Specialist
- **System prompt must include:** the full Math Derivation Protocol
  (`references/protocols/math_derivation.md`) **and** the CAS Verification
  Protocol (`references/protocols/cas_verification.md`): show every load-bearing
  step and justify why each non-obvious operation is valid; **do not pad** to hit
  a count; flag the single hardest step; run the **sanity-check gate**
  (dimensions, limits, symmetry); run the **step-chain CAS verification** — via
  the `verify_derivation` tool for expression-chain steps (each classified
  S / A / N / U per the taxonomy, no step silently unchecked), plus a custom
  SymPy script (`scripts/check_NNN_*.py`, logged seed) for structures the tool
  cannot express (`cas_verification.md` §0), written under the **code-style**
  skill (load it); append assumptions to the ledger; tag the result with a
  confidence level. Return the derivation + the per-step
  PASS/FAIL table (the tool's output, not a hand-written table) + any
  check-script content.

## Computation subagent

*(This is the "Coding subagent" referenced in the hard gate — coding, numerical
experiments, and real-data analysis.)*

- **TypeName (Antigravity):** `self` · **Claude Code:** `general-purpose`
- **Role:** Computational Scientist
- **Prompt template:**
  > "Implement [the model / experiment / data analysis] following
  > `references/protocols/data_analysis.md`. Load the **code-style** skill
  > with `<load-skill>` and write the script under it, to
  > `scripts/<assigned-name>.py`, with a **logged RNG seed** and recorded
  > environment; any figure it draws is made under the **plot-style** skill
  > (load it too). For data: do EDA + a data-quality summary, state the test and α
  > before running, report **effect size with uncertainty** (not just a p-value),
  > and note confounders / failed assumptions. Return the script, the results,
  > a reproducibility note (seed, env, command), and the result of every check
  > those skills require."

## Red-Team / Reviewer subagent

- **TypeName (Antigravity):** `self` · **Claude Code:** `general-purpose`
- **Role:** Adversarial Reviewer
- **Prompt template:**
  > "Assume the following hypothesis and derivation/result are **WRONG** and find
  > the strongest reasons why. [PASTE the derivation/result + assumptions.]
  > Specifically: recompute each transition and flag any step that jumps more than
  > one operation or contains an error; **re-run the verification yourself** —
  > the `verify_derivation` call with the recorded step JSON and any check
  > scripts (`scripts/check_NNN_*.py`) — and scrutinize hardest the steps
  > classified numeric-only (N) or machine-unverifiable (U) — those are where CAS
  > verification is weakest; check **dimensional consistency** and
  > **limiting cases**; identify the most fragile assumptions and any hidden ones;
  > propose **alternative explanations**; name known **contradicting** results or
  > prior art. (Whether a cited paper supports the sentence that cites it is
  > not yours to judge: cite-check's independent judge does that on the final
  > report prose.) Output a structured critique with each issue rated **Critical / Major /
  > Minor** and the single experiment most likely to falsify the hypothesis.
  > Default to skepticism: if uncertain whether something is sound, flag it."
- **Rule:** must be a separate invocation from the producer. Unresolved
  **Critical** issues block report assembly (hard gate).

## Visualization subagent

- **TypeName (Antigravity):** `self` · **Claude Code:** `general-purpose`
- **Role:** Scientific Visualizer
- **Prompt template:**
  > "Make [FIGURE: what it shows and why] per
  > `references/protocols/visualization.md`. Load the **plot-style** and
  > **code-style** skills with `<load-skill>` and follow both in full: the
  > figure's look, size and output are plot-style's, the script's code is
  > code-style's. co-scientist fixes only the paths: script
  > `scripts/<assigned-name>.py` (logged seed), figure
  > `figures/<assigned-name>.png`, width from the report geometry in
  > `visualization.md`. Return the figure path, a caption stating what the
  > reader should conclude, and the result of every check those skills
  > require." Use the `<image-gen>` fallback (TikZ/Graphviz/Mermaid) only where
  > matplotlib cannot draw the figure.

## Section Writer subagent

- **TypeName (Antigravity):** `self` · **Claude Code:** `general-purpose`
- **Role:** Section Writer
- **Prompt template:**
  > "Using checkpoints [LIST], the **exact** figure paths [PATHS] and the cite
  > keys already in `report.bib` [KEYS, each with the claim it supports],
  > draft the [SECTION] of the report in LaTeX following `paper_template.tex`.
  > Embed the given figures inline with `\includegraphics` where each concept
  > is discussed — use only the figure paths provided; do not invent figure
  > ids. Cite only the keys given, each for the claim it was given for; where
  > a sentence needs a citation you were not given, write `[cite]` and say so.
  > **Write pedagogically, for a reader who has not followed this project**,
  > following the content rules of `protocols/reporting.md` §3 (pasted below).
  > Length is not a constraint. Write for content and completeness; the
  > sentences will be rewritten in the author's voice afterwards by
  > co-writer, so do not spend effort on style. Return the LaTeX for this
  > section (the orchestrator will splice it into `report.tex`)."
  >
  > [PASTE `protocols/reporting.md` §3.]

## Debate / Judge subagent (optional — tournament only)

Used only when running the optional Elo hypothesis tournament. It judges a
pairwise "scientific debate" between two candidate hypotheses and returns a
winner + rationale (the orchestrator records ratings and match history). Full
definition and prompt template: `references/protocols/tournament.md`. Same
contract: spawn via `<spawn-subagent>` (Antigravity `TypeName: self`), or debate
inline if unavailable; non-interactive; returns its verdict, never writes files.
