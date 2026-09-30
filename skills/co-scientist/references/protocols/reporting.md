# Reporting Protocol — Assemble & Compile the LaTeX Report

Read this at Phase 10. Used in **Full Project** mode (and Derivation mode only if
the user asks for a written report).

## 1. Copy the template into the working directory (never edit it in place)

The bundled `resources/paper_template.tex` is a **read-only source**. Editing it
would corrupt it for the next run and may fail if the skill is installed
read-only. Copy it to the working directory as `report.tex` and edit **that**:

```
cp <skill-dir>/resources/paper_template.tex ./report.tex
```

The run's environment record ships with the report, as it was set up before
the first script ran (`checkpointing.md` → Reproducibility). If no script has
run yet, set it up now the same way.

Because the template sets `\graphicspath{{figures/}}` (relative), compilation
**must** happen in the working directory, where `figures/` lives — which is
exactly where `report.tex` now is. Do not compile from `resources/`.

## 2. Aggregate checkpoints into sections

Delegate each section to a **Section Writer** subagent (single-writer rule still
applies: writers return draft text; the orchestrator splices it into
`report.tex`). The orchestrator passes each writer the **exact figure paths from
the manifest** — writers never guess `fig_NNN` ids. Map checkpoints → sections:

- Introduction ← project init + design
- Literature Review ← literature checkpoint (with verified citations)
- Methods & Brainstorming ← hypothesis ranking + chosen design
- Mathematical Derivations / Data Analysis ← derivation + computation checkpoints
- Results & Future Directions ← outcome decision + meta-review + best next experiment
- **Assumptions and Limitations** ← the assumptions ledger (do not omit, even —
  especially — for negative results)

Figures go **inline** in the section that discusses them, via
`\includegraphics` at the width they were drawn for (`visualization.md` →
Report geometry), with a caption explaining what it shows and why it matters.

Each writer gets the cite keys already in `report.bib`, each with the claim it
was added for, and cites nothing else; a sentence that needs a new citation
comes back marked `[cite]`, and the orchestrator adds the paper through
cite-check (§5) before the prose pass.

## 3. Content — pedagogy over compression

The report's reader is a scientifically literate person who has **not** followed
this project. Write to teach, not to summarize. Length is not a constraint: a
long, clear report beats a short, dense one. Every Section Writer must follow
these rules (the orchestrator includes them in each writer's prompt). They fix
**what** the report contains; how its sentences read is co-writer's (§3a).

- **Problem setup, always, in full.** Before any result: what question is being
  asked and why it matters, what the physical/mathematical objects are, every
  symbol defined at first use, the assumptions, and the regime of validity.
  Never open a section at the equations.
- **Derivations: every step on paper.** Reproduce the full step chain from the
  derivation checkpoint — one manipulation per step, each with a short
  justification ("integrate by parts; the boundary term vanishes because …").
  Never compress to "it can be shown that". If the derivation was verified in
  N steps, the report shows N steps. A very long chain may move to an appendix,
  but it must appear somewhere in full.
- **Experimental / computational detail.** For every numerical result: what was
  run, parameter values and ranges, seeds, sample sizes / resolution /
  tolerances, the environment, and the quantitative pass/fail criterion —
  enough that the reader could re-run it without opening the code.
- **Algorithm tables.** Any nontrivial procedure (simulation loop, fitting
  pipeline, sampling scheme, verification harness) gets a numbered algorithm
  float stating inputs, outputs, and steps. Check availability first
  (`kpsewhich algpseudocode.sty`); if present, enable the commented
  `algorithm`/`algpseudocode` lines in the template. If absent, fall back to a
  numbered-step list inside a `table` float — never skip the algorithm box
  because a package is missing.
- **Conceptual figures, not only result plots.** Alongside quantitative plots,
  add figures that build intuition: a schematic of the setup, a flow diagram of
  the method, an annotated sketch of the mechanism (see `visualization.md`,
  "Pedagogical figures"). Every caption must be self-contained: what the figure
  shows *and* what the reader should conclude from it.
- **Intuition before formalism.** Open each Methods / Derivation subsection with
  one or two plain-language sentences saying what the upcoming math will
  accomplish and why.

## 3a. Prose — co-writer

Once every section is spliced into `report.tex`, the prose goes through the
**co-writer** skill, section by section: `<load-skill>` it and follow its
process in full, including its own checks, cold read and log. Tell it the
register is *journal*; everything else about how it works is its own. co-writer
preserves every number, claim, hedge, equation, figure and citation, so the
verified content of §3 survives; if it reports a `[NEEDS: …]` or a cut, resolve
that with the user, not by editing around it. Do not add style rules of your
own to its brief. If co-writer is not installed, say so once and keep the
drafted prose.
## 4. Validate figure references, then compile

If the report cites anything, cite-check's `audit` (§5) must already have
returned `ok: true` on the final `report.tex`. Then:

**Preferred:** call the `compile_report` MCP tool (CLI fallback:
`mcp/.venv/bin/python mcp/server.py call compile_report '{"workdir": "..."}'`).
It runs the whole sequence with the hard gates built in:

1. **Verification gate** — refuses while the manifest contains
   derivation/data/computation checkpoints with `verified: false`. For an
   explicit negative-result report pass `allow_unverified: true`; the bypass is
   recorded in the result, never silent.
2. **Figure gate** — runs `validate_figures` and refuses on any missing
   `\includegraphics` target (you can also call `validate_figures` directly
   while drafting).
3. Compiles: stale-PDF removal, `pdflatex` nonstop mode, conditional `bibtex`
   (below), real errors surfaced from the `.log`.

**Fallback** (no toolbox): check figure targets by hand, then
`bash <skill-dir>/scripts/compile_report.sh report` (name WITHOUT the `.tex`
extension) — same compile behavior, but the verification gate is then on your
honor: re-read the manifest and confirm every derivation checkpoint is verified
before compiling.

## 5. Bibliography — cite-check

Every citation in the report is **cite-check**'s work. `<load-skill>` it and
follow its caller contract, `<skills>/cite-check/references/integration.md`,
which wins wherever this section seems to differ:

- `report.bib` is written only by cite-check (from the Literature phase and
  any `[cite]` gaps); nothing is typed into it.
- The support check runs **once, on the final prose** — after co-writer
  (§3a), since a reworded sentence needs a fresh verdict — and then cite-check's
  `audit` on `report.tex` with `require_support: true` must return `ok: true`.
  Relay its failures and warnings to the user as it reports them; fix a
  failure the way cite-check says, never by lowering the bar.
- Copy each cited paper's outcome into the manifest's `citations` section
  (the field mapping is in the contract).

The template ships with `\bibliography` commented out; with citations,
**uncomment** `\bibliography{report}` in `report.tex`. The compile step runs
`bibtex` only when both `report.bib` exists **and** `report.tex` contains an
active `\bibliography{...}` — so an orphan `.bib` will not trigger spurious
bibtex errors, and an active bibliography without a `.bib` is reported
clearly.

## 6. Negative-result reports

If Phase 8 concluded the hypothesis was not supported, frame the report honestly:
"Result: hypothesis not supported", state what was ruled out and the strength of
the evidence, and keep the Assumptions and Limitations section. A clear negative
result is a valid scientific output.
