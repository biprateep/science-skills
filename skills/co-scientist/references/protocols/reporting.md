# Reporting Protocol — Assemble & Compile the LaTeX Report

Read this at Phase 10. Used in **Full Project** mode (and Derivation mode only if
the user asks for a written report).

## 1. Copy the template into the working directory (never edit it in place)

The bundled `resources/paper_template.tex` is a **read-only source**. Editing it
would corrupt it for the next run and may fail if the skill is installed
read-only. Copy it to the working directory as `report.tex` and edit **that**:

```
cp <skill-dir>/resources/paper_template.tex ./report.tex
cp <skill-dir>/resources/requirements.txt   ./requirements.txt   # if not present
```

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
`\includegraphics`, with a caption explaining what it shows and why it matters.

## 3. Writing style — pedagogy over compression

The report's reader is a scientifically literate person who has **not** followed
this project. Write to teach, not to summarize. Length is not a constraint: a
long, clear report beats a short, dense one. Every Section Writer must follow
these rules (the orchestrator includes them in each writer's prompt):

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

## 4. Validate figure references, then compile

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

## 5. Bibliography (optional)

The template ships with `\bibliography` commented out. If you have citations,
write them to `report.bib` and **uncomment** `\bibliography{report}` in
`report.tex`. The compile script runs `bibtex` only when both `report.bib` exists
**and** `report.tex` contains an active `\bibliography{...}` — so an orphan
`.bib` will not trigger spurious bibtex errors, and an active bibliography
without a `.bib` is reported clearly.

## 6. Negative-result reports

If Phase 8 concluded the hypothesis was not supported, frame the report honestly:
"Result: hypothesis not supported", state what was ruled out and the strength of
the evidence, and keep the Assumptions and Limitations section. A clear negative
result is a valid scientific output.
