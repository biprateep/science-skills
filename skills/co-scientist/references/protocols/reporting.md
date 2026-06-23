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

## 3. Validate figure references, then compile

Before compiling, confirm every `\includegraphics{...}` target exists in
`figures/`; fail fast (and fix) if not. Then:

```
bash <skill-dir>/scripts/compile_report.sh report     # note: name WITHOUT .tex extension
```

The script removes any stale PDF, runs `pdflatex` in nonstop mode, surfaces real
LaTeX errors from the `.log`, and runs `bibtex` **only** when a bibliography is
actually present (see below).

## 4. Bibliography (optional)

The template ships with `\bibliography` commented out. If you have citations,
write them to `report.bib` and **uncomment** `\bibliography{report}` in
`report.tex`. The compile script runs `bibtex` only when both `report.bib` exists
**and** `report.tex` contains an active `\bibliography{...}` — so an orphan
`.bib` will not trigger spurious bibtex errors, and an active bibliography
without a `.bib` is reported clearly.

## 5. Negative-result reports

If Phase 8 concluded the hypothesis was not supported, frame the report honestly:
"Result: hypothesis not supported", state what was ruled out and the strength of
the evidence, and keep the Assumptions and Limitations section. A clear negative
result is a valid scientific output.
