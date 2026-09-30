# Visualization Protocol

Read this at Phase 9 (or when a figure would clarify a result earlier).
Visualization is **encouraged where it genuinely aids understanding** — it is not
mandatory, and a gratuitous plot of a purely symbolic result adds nothing. Create
a figure when it makes a concept, comparison, or result easier to grasp.

This protocol decides **whether** to make a figure, **what** it shows and
**where** it goes. **How** a matplotlib figure looks, is sized and is saved
belongs to the **plot-style** skill, and how its script is written to
**code-style**: load both with `<load-skill>` before the first plotting script
of a run and follow them in full (SKILL.md → Component Skills). Nothing below
restates either.

## Interface points (the only co-scientist decisions plot-style follows)

- **Paths.** Script `scripts/viz_NNN_<descriptor>.py`, figure
  `figures/fig_NNN_<descriptor>.png`, with `NNN` from the manifest. The report
  template's `\graphicspath{{figures/}}` needs that directory; plot-style's own
  Interaction section defers the directory to co-scientist.
- **Report geometry.** `report.tex` is the bundled template (`article`, 11 pt,
  A4, 1 in margins), not a journal class. Its measured widths are
  `\textwidth` = `\columnwidth` = **452.9679 pt**. Register them as plot-style
  says for a class it does not know, under the name `co-scientist-report`, and
  size every report figure from them; include it at the matching width
  (`width=\textwidth`, or the deliberate fraction it was drawn at) so LaTeX
  never rescales it. If the template's class, font size, paper or margins
  change, measure again and change this number.

## Tooling (via the Harness Adapter)

- **matplotlib (default)** for all quantitative graphics: function plots, phase
  diagrams, histograms, scatter/contour, time series, model comparisons,
  distribution fits, made under plot-style.
- **`<image-gen>`** ONLY for genuine images that cannot be drawn quantitatively
  (an artistic schematic, a physical-apparatus illustration). On harnesses with
  no `<image-gen>` (e.g. Claude Code), use the **fallback**: **TikZ** (compiles in
  the LaTeX pipeline), **Graphviz**, or **Mermaid**. Never skip a needed figure
  just because `<image-gen>` is absent — fall back.

| Concept | Visualization |
|---------|---------------|
| Function / relationship | matplotlib plot |
| Phase / parameter space | 2D/3D scatter or contour |
| Process / evolution | time-series or animation |
| Model/theory comparison | overlay or side-by-side |
| Geometric / topological | matplotlib, else TikZ / `<image-gen>` |
| Distribution / fit | histogram + fitted curve |
| Algorithm / flow | Mermaid or Graphviz diagram |

## Pedagogical figures (for the report)

When assembling a report (Phase 10), result plots alone are not enough — the
reader also needs figures that build **conceptual** understanding, not just
evidence. For each major section ask: *could a schematic make this easier to
grasp than prose alone?* If yes, make one. Typical pedagogical figures:

- **Setup schematic** — the physical/mathematical objects, geometry, coordinate
  conventions, and where each key symbol lives (annotated matplotlib or TikZ).
- **Method flow diagram** — the pipeline from inputs to conclusion (TikZ,
  Graphviz, or Mermaid; it must render into the LaTeX report, so prefer TikZ).
- **Mechanism cartoon** — an annotated sketch of *why* the effect happens, e.g.
  regimes of a parameter space with each region labeled by its behavior.

These follow the same manifest/figure-path rules as any other figure. A caption
on a pedagogical figure states what the reader should take away, not just what
is drawn.

## Implementation Steps

1. Write a self-contained script under plot-style and code-style; **set and
   log an RNG seed** if anything is stochastic (see `checkpointing.md` →
   Reproducibility).
2. Save the script to `scripts/viz_NNN_<descriptor>.py` (id from the manifest).
3. Run it via `<run-shell>`; save output to `figures/fig_NNN_<descriptor>.png`.
   Run the checks plot-style and code-style require and keep their output.
4. **Return** the figure path, a caption, and those check results to the
   orchestrator (single-writer
   rule: the orchestrator records it in the manifest and places it in the
   checkpoint/report). Do not edit another agent's checkpoint.
5. Place the figure **inline** where the concept is discussed — never in a
   trailing "Figures" section.

## Mini-Experiments (numerical verification of theory)

When a theoretical result can be checked numerically, make a mini-experiment:

1. Generate synthetic data or numerical examples (logged seed).
2. Define a **quantitative pass/fail** up front — a metric and tolerance (e.g.
   max relative error `< tol`, or a KS/χ² test at a stated α). "Looks like it
   agrees" is not a result.
3. Plot theory vs. computation on the same axes with clear labels.
4. Record the metric value, pass/fail, seed, and environment in the checkpoint.

> **Example (CLT):** histograms of sample means for N = 1, 5, 30, 100 with the
> theoretical $\mathcal N(\mu, \sigma^2/n)$ overlaid; report the KS statistic vs.
> the normal at each N and whether it falls below the chosen threshold.
