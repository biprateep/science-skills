# Visualization Protocol

Read this at Phase 9 (or when a figure would clarify a result earlier).
Visualization is **encouraged where it genuinely aids understanding** — it is not
mandatory, and a gratuitous plot of a purely symbolic result adds nothing. Create
a figure when it makes a concept, comparison, or result easier to grasp.

## Tooling (via the Harness Adapter)

- **matplotlib (default)** for all quantitative graphics: function plots, phase
  diagrams, histograms, scatter/contour, time series, model comparisons,
  distribution fits. Write self-contained Python scripts (matplotlib + numpy).
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

## Implementation Steps

1. Write a self-contained script; **set and log an RNG seed** if anything is
   stochastic (see `checkpointing.md` → Reproducibility).
2. Save the script to `scripts/viz_NNN_<descriptor>.py` (id from the manifest).
3. Run it via `<run-shell>`; save output to `figures/fig_NNN_<descriptor>.png`.
4. **Return** the figure path + a caption to the orchestrator (single-writer
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
