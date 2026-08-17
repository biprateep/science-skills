---
name: plot-style
description: >-
  Enforce the publication matplotlib aesthetic on every figure: AASTeX
  column/text-width sizing, Nimbus Roman serif with Computer Modern math,
  inward ticks on all four sides, frameless legends, the default C0/C1/C2
  color cycle, rasterized scatter, and vector PDF output at 300 dpi. This is
  the DEFAULT for all matplotlib figures — apply it unless the user explicitly
  asks for something else. Use whenever creating, editing, restyling, or
  reviewing a plot, and when the user mentions: plot, figure, chart, histogram,
  scatter, contour, colorbar, subplot, matplotlib, rcParams, plot style, figure
  size, paper figure, publication quality, or journal column width.
license: MIT
metadata:
  version: "1.0.0"
---

# Publication Plot Style

## Overview

Every figure is built to drop into an AASTeX (AJ / ApJ) manuscript **at its
natural size, with no scaling**. That single constraint drives the whole
style: fix the figure width to the journal's column or text width, set the
type to the manuscript's own face and sizes, and the printed figure then
carries the same 9/10/12 pt type as the surrounding paragraph. A figure that
gets scaled in LaTeX arrives with the wrong type size no matter how carefully
it was made.

This skill is **harness-agnostic**: it constrains matplotlib code you write.
It needs nothing beyond file-writing and, optionally, a shell to run the
result.

---

## When to Apply

<HARD-RULE>
This style is the DEFAULT for every matplotlib figure. Apply it unless the
user explicitly asks for something else, or the figure is destined for a
slide deck / web page rather than a manuscript.
</HARD-RULE>

Applies to paper figures, exploratory plots, and quick diagnostics alike —
an exploratory plot made in house style costs nothing extra and is already
publishable when it turns out to matter.

**Not** for: interactive/web charts, non-matplotlib libraries (plotly, d3,
Recharts), or slide graphics — those want a larger, sans-serif, higher-
contrast treatment.

---

## The Preamble

<HARD-RULE>
Every plotting script begins by applying the style, before any figure is
created. Never write bare matplotlib defaults and never restyle a figure
axis-by-axis after the fact.
</HARD-RULE>

Preferred — copy `assets/plotstyle.py` and `assets/paper.mplstyle` next to
the analysis script (they are self-contained, numpy + matplotlib only):

```python
from plotstyle import use_style, figsize, COLUMN_WIDTH, TEXT_WIDTH, BIG_SIZE

use_style()
```

When a helper module is unwanted, inline the equivalent — this exact block:

```python
# figure defaults for AASTEX AJ
COLUMN_WIDTH = 242.26653 / 72.27  # in inches
TEXT_WIDTH = 513.11743 / 72.27
SMALL_SIZE = 9  # in pts
NORMAL_SIZE = 10
BIG_SIZE = 12
FONT_FAMILY = "Nimbus Roman No9 L"

params = {
    "font.family": FONT_FAMILY,
    "font.size": NORMAL_SIZE,
    "axes.titlesize": NORMAL_SIZE,
    "axes.labelsize": NORMAL_SIZE,
    "xtick.labelsize": SMALL_SIZE,
    "ytick.labelsize": SMALL_SIZE,
    "xtick.top": True,
    "ytick.right": True,
    "xtick.direction": "in",
    "ytick.direction": "in",
    "legend.fontsize": NORMAL_SIZE,
    "figure.facecolor": "w",
    "figure.dpi": 300,
    "mathtext.fontset": "cm",
}
plt.rcParams.update(params)
```

> **Font availability.** `Nimbus Roman No9 L` is the URW Times clone matching
> AASTeX body text; newer `urw-base35` packages renamed the same face to
> plain `Nimbus Roman`. `assets/paper.mplstyle` sets `font.family: serif`
> with a fallback chain (`Nimbus Roman No9 L` → `Nimbus Roman` →
> `Times New Roman` → `Liberation Serif` → `DejaVu Serif`) so it degrades
> quietly instead of emitting findfont warnings and silently rendering
> DejaVu. The inline form above pins the exact name — use it only where that
> font is known to exist.

The style sheet additionally sets `legend.frameon: False`,
`savefig.bbox: tight`, and `savefig.dpi: 300`, which the inline form leaves
to be repeated at each call site.

---

## Figure Geometry

<HARD-RULE>
Figure width is ALWAYS `COLUMN_WIDTH` or `TEXT_WIDTH` (or a deliberate
multiple). Never `figsize=(8, 6)` or any other invented number.
</HARD-RULE>

Height is expressed as a fraction of the width, so the aspect ratio is
explicit and the width stays exact:

| Figure | `figsize` | Use |
|---|---|---|
| Single column, 16:9 | `(COLUMN_WIDTH, 0.5625 * COLUMN_WIDTH)` | one-panel histogram, trend |
| Single column, square | `(COLUMN_WIDTH, COLUMN_WIDTH)` | 1:1 comparisons, sky maps, anything `aspect="equal"` |
| Full width, 2 panels | `(TEXT_WIDTH, 0.4 * TEXT_WIDTH)` | side-by-side maps / scatter |
| Full width, 2 histograms | `(TEXT_WIDTH, 0.35 * TEXT_WIDTH)` | shorter, since histograms need less height |

`figsize("column", 0.5625)` from `plotstyle` returns the tuple, if you prefer
it named. Widths are measured from the manuscript itself with
`\showthe\columnwidth` / `\showthe\textwidth`; the divisor is **72.27**, the
LaTeX point, not 72.

---

## The Rules

**Ticks** — inward, on all four sides. Set once in the preamble; never
overridden per-axis. No grid.

**Legends** — always `frameon=False`. Move with an explicit `loc` tuple when
the default collides with the data: `ax.legend(frameon=False, loc=(0.41, 0.78))`.

**Color** — the default matplotlib cycle, by index: `"C0"`, `"C1"`, `"C2"`.
<HARD-RULE>
Never hand-pick hex colors or named colors for data series. `C`-indices keep
every figure in a paper mutually consistent and re-orderable.
</HARD-RULE>
Black (`"k"`) is reserved for reference lines and annotation, never for a
data series. Continuous quantities use `cmap="viridis"` with **explicit**
`vmin`/`vmax` so panels sharing a colorbar share a scale.

**Markers** — `marker="."` with a small `s`: `s=0.5` for dense clouds
(thousands of points), `s=4`–`5` for sparse ones. Background scatter under
contours drops to `alpha=0.2`.

**Rasterization** —
<HARD-RULE>
Any scatter with more than ~1000 points gets `rasterized=True`. The axes,
text, and lines stay vector; only the point cloud becomes a bitmap. Without
it a PDF can reach tens of MB and will choke the journal's compiler.
</HARD-RULE>

**Reference lines** — dashed black, thin: `ax.axhline(1, c="k", ls="--")`,
`ax.plot(x, x, "k--")`. A fitted or median level uses the same dashes in the
series color at `lw=1`.

**Labels** — units in **square** brackets (`"Exposure Time [min]"`), Title
Case for worded labels, raw strings for math (`r"$i$-magnitude"`). Panel
titles at `fontsize=BIG_SIZE`; everything else inherits from the preamble.

**Output** —
<HARD-RULE>
Save as **PDF** (vector) with `bbox_inches="tight"` and `dpi=300`, into a
`figs/` directory beside the script.
</HARD-RULE>

```python
plt.savefig("./figs/points_on_sky.pdf", bbox_inches="tight", dpi=300)
```

PNG only when a raster is specifically requested. `dpi=300` still matters for
a PDF — it sets the resolution of the rasterized scatter inside it.

---

## Figure Idioms

Full templates live in `references/recipes.md`; read it when building any of
these. `assets/plotstyle.py` implements each as a helper.

| Idiom | Helper | What it is |
|---|---|---|
| Panels sharing a colorbar | `side_colorbar` | slim colorbar on its own figure-level axes, label rotated `-90` |
| Stacked histogram | `stacked_hist` | white `histtype="step"` underlay, then `alpha=0.5, rwidth=0.8` fills |
| One-to-one comparison | `one_to_one` | square, `aspect="equal"`, matched limits, `k--` diagonal |
| Trend / residual band | `running_median` | equal-count bins, median staircase + 25–75 shaded band |
| Staircase with band | `better_step` | the step plot matplotlib's `step` should have been |
| Density over scatter | — | KDE `contour` in `C`-color over the same-color scatter at `alpha=0.2` |

`examples/example_figures.py` builds four of these end-to-end on synthetic
data and runs standalone.

---

## Anti-Patterns

Stop and fix if you catch any of these:

- **Invented figure size** — `figsize=(10, 6)`, `figsize=(8, 8)`. Use the
  journal widths.
- **Bare matplotlib defaults** — DejaVu Sans, outward ticks on two sides, a
  boxed legend. The preamble is not optional.
- **Hand-picked colors** — `color="#1f77b4"`, `color="steelblue"`. Use `C0`.
- **Un-rasterized dense scatter** — a 50 MB PDF that the journal rejects.
- **Saving PNG for a paper figure** — vector PDF, unless asked otherwise.
- **`plt.tight_layout()` as a substitute for `bbox_inches="tight"`** — a
  figure-level colorbar added with `fig.add_axes` is not a layout-managed
  axes, so matplotlib warns (*"includes Axes that are not compatible with
  tight_layout"*) and reflows the panels without accounting for it, letting
  them expand into the colorbar. Save with `bbox_inches="tight"` instead,
  which grows the saved bounding box around everything.
- **`plt.title()` / `plt.xlabel()` on the pyplot state machine** — address
  axes explicitly: `ax.set_xlabel(...)`, `ax[i].set_title(...)`.
- **Units in parentheses** — `"Exposure Time (min)"`. Square brackets.
- **Autoscaled color limits across shared-colorbar panels** — set `vmin` and
  `vmax` explicitly or the panels lie.

---

## Self-Check Before Finishing

- [ ] Style applied via `use_style()` or the inline `params` block, before any figure.
- [ ] Every `figsize` derives from `COLUMN_WIDTH` or `TEXT_WIDTH`.
- [ ] Data series colored by `C`-index; `k` only for reference lines.
- [ ] Dense scatters carry `rasterized=True`.
- [ ] Legends are `frameon=False`.
- [ ] Axis labels carry units in square brackets; math in raw strings.
- [ ] Saved as PDF into `figs/` with `bbox_inches="tight", dpi=300`.
- [ ] Script actually ran and produced the file — no findfont warnings.

---

## Interaction With Other Skills

- **jupytext** — plotting scripts are `.py` files, so they get the percent
  format by default: one figure per `# %%` cell, with a markdown cell above
  saying what it shows.
- **co-scientist** — its visualization protocol decides *whether and what* to
  plot; this skill decides *how it looks*. Figures produced under that
  protocol still follow these rules.
- **dataviz** — that skill governs web/interactive charts with their own
  palette system. For matplotlib manuscript figures, this skill wins.

---

## Files

| Path | Contents |
|---|---|
| `assets/paper.mplstyle` | the rcParams as a matplotlib style sheet |
| `assets/plotstyle.py` | widths, sizes, `use_style`, and every idiom as a helper |
| `references/recipes.md` | copy-paste template per figure type, long and short form |
| `examples/example_figures.py` | four runnable figures on synthetic data |

Derived from the figure code in `biprateep/desi-deep-pilot`, notebook
`notebooks/paper_general_stat.ipynb` (the `better_step` helper comes from that
repo's `notebooks/utils.py`). The sibling `paper_*.ipynb` notebooks there hold
further idioms not yet folded in.
