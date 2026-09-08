---
name: plot-style
description: >-
  Enforce the publication matplotlib aesthetic on every figure: journal
  column/text-width sizing (AASTeX by default, per-journal registry), Nimbus
  Roman serif with Computer Modern math at 9/10/12 pt on every piece of text,
  inward ticks on all four sides, frameless legends, matplotlib's own
  default palettes (the tab10 cycle as C0/C1/C2, viridis) unless the user
  names one, and tight 300 dpi PNG output. This is the DEFAULT for all
  matplotlib figures — apply it unless the user explicitly asks for something
  else. Use whenever creating, editing, restyling, or reviewing a plot, and
  when the user mentions: plot, figure, chart, histogram, scatter, contour,
  colorbar, subplot, matplotlib, rcParams, plot style, figure size, paper
  figure, publication quality, or journal column width.
license: MIT
metadata:
  version: "1.2.0"
---

# Publication Plot Style

## Overview

Every figure is built to drop into the manuscript **at its natural size, with
no scaling**. That single constraint drives the whole style: fix the figure
width to the journal's column or text width, express the height as a
fraction of that width, set the type to the manuscript's own face and sizes,
and the printed figure then carries the same 9/10/12 pt type as the
surrounding paragraph, in the same proportions matplotlib drew. A figure that
gets scaled in LaTeX arrives with the wrong type size no matter how carefully
it was made.

This skill is **harness-agnostic**: it constrains matplotlib code you write.
It needs nothing beyond file-writing and, optionally, a shell to run the
result and the checker.

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
from plotstyle import use_style, verify_style, figsize, COLUMN_WIDTH, TEXT_WIDTH, BIG_SIZE

use_style()      # rcParams + AASTeX geometry; use_style(journal="...") for another class
verify_style()   # raises if the serif face did not resolve or an rcParam was overridden
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

The inline block does **not** set `legend.frameon`, `savefig.bbox`,
`savefig.dpi` or `savefig.format`, so with it every legend call carries
`frameon=False` and every save carries `bbox_inches="tight", dpi=300` and a
`.png` name. Nor does it touch colour, so it inherits whatever the local
`matplotlibrc` says. The style sheet sets all of these, pins matplotlib's
default palettes, and adds `legend.title_fontsize` (10 pt) and
`figure.titlesize` (12 pt) so legend titles and suptitles also land on the
type scale.

> **Font availability.** `Nimbus Roman No9 L` is the URW Times clone
> matching the manuscript body text; newer `urw-base35` packages ship the
> same face as plain `Nimbus Roman`. On such a machine (this one included)
> asking for the exact classic name makes matplotlib fall back to **DejaVu
> Sans**, and it says so only in a debug-level log line — the figure comes
> out in the wrong face with no warning. The style sheet therefore requests
> the generic `serif` family with the chain `Nimbus Roman No9 L` →
> `Nimbus Roman` → `Times New Roman` → `Liberation Serif` → `DejaVu Serif`,
> and `verify_style()` raises if the chain fell through to DejaVu. Use the
> inline form only where the exact face is known to exist, and still call
> `verify_style()` (or check `matplotlib.font_manager.findfont`) once.

---

## Figure Geometry

<HARD-RULE>
Figure width is ALWAYS the journal's column width or text width (or a
deliberate multiple). Never `figsize=(8, 6)` or any other invented number.
Height is a fraction of the width, never an absolute.
</HARD-RULE>

### Widths come from a journal registry

Widths are measured from the manuscript itself with `\showthe\columnwidth` /
`\showthe\textwidth`; the divisor is **72.27**, the LaTeX point, not 72.

| Journal | `\columnwidth` | `\textwidth` | Status |
|---|---|---|---|
| `aastex` (AJ / ApJ) — **default** | 242.26653 pt = 3.352 in | 513.11743 pt = 7.100 in | measured |

`COLUMN_WIDTH` and `TEXT_WIDTH` are the default journal's widths in inches,
for the inline `figsize=(COLUMN_WIDTH, 0.62 * COLUMN_WIDTH)` form. For
another class, measure it and register it — never guess a width, a wrong
one silently rescales every figure in the paper:

```python
from plotstyle import register_journal, use_style, figsize

register_journal("mnras", column_pt=<measured>, text_pt=<measured>)
use_style(journal="mnras")
fig, ax = plt.subplots(figsize=figsize("column"))   # now MNRAS widths
```

`figsize()` and `grid_figsize()` follow the journal passed to `use_style()`;
the module constants do not, so a non-default journal uses the helpers.

### Heights are a named aspect of the width

These are the ratios the source manuscripts actually used, by figure type:

| Figure | `figsize` | Aspect |
|---|---|---|
| Single column, one panel (default) | `figsize("column")` | golden, 0.618 |
| Single column, short — histogram, flat trend | `figsize("column", "wide")` | 16:9, 0.5625 |
| Single column, room for a band or an inside legend | `figsize("column", "tall")` | 4:3, 0.75 |
| Single column, square — 1:1 plots, sky maps, `aspect="equal"` | `figsize("column", "square")` | 1.0 |
| Full width, one panel | `figsize("text", 0.6)` | 0.5–0.65 |
| Full width, two panels side by side | `grid_figsize(1, 2, "text", panel_aspect=0.7)` | 0.35 of the width |
| Full width, two histograms | `(TEXT_WIDTH, 0.35 * TEXT_WIDTH)` | 0.35 |

`grid_figsize(nrows, ncols, width, panel_aspect)` turns a *per-panel* aspect
into the figure height, `nrows * panel_aspect * width / ncols`, so a grid's
panels keep a pleasing shape regardless of how many there are. Anything
drawn with `aspect="equal"` gets a square figure, or matplotlib pads the
canvas with blank margins.

> **Tight cropping and the nominal width.** `bbox_inches="tight"` crops the
> saved image to its artists, so the file is not exactly the nominal width
> and LaTeX rescales it by that ratio at `width=\columnwidth`. Proportions
> survive; type size drifts by the same factor. Measured on the examples:
> with matplotlib's default layout the saved image is 5–16 % *narrower*
> than nominal (the unused subplot margins are cropped away, most for a
> two-panel row), so the type prints 5–16 % larger; with
> `plt.subplots(..., layout="constrained")` the axes fill the canvas and
> the drift falls to about 3 % the other way. Use `layout="constrained"`
> when a figure has no manually placed axes — it is not compatible with
> `side_colorbar`'s `fig.add_axes` — and accept the residual either way.
> `examples/example_figures.py` prints the ratio per figure. Do not "fix"
> the drift by dropping the tight bounding box, which clips labels instead.

---

## The Rules

**Type** —
<HARD-RULE>
Every piece of text in the figure — tick labels, axis labels, titles,
suptitles, legend entries and titles, colorbar labels, `ax.text` /
`annotate` — is in the serif face at one of the three sizes: `SMALL_SIZE`
(9) for ticks and crowded legends, `NORMAL_SIZE` (10) for everything else,
`BIG_SIZE` (12) for panel titles. Math is Computer Modern via mathtext.
</HARD-RULE>
The preamble sets all of this; the only per-call size ever written is
`fontsize=BIG_SIZE` on a panel title or `fontsize=SMALL_SIZE` on a legend
that would otherwise overflow. Never a numeric literal, never a `fontdict`,
never a `family=` override.

**Ticks** — inward, on all four sides. Set once in the preamble; never
overridden per-axis. No grid.

**Legends** — always `frameon=False`. Move with an explicit `loc` tuple when
the default collides with the data: `ax.legend(frameon=False, loc=(0.41, 0.78))`.

**Palette** —
<HARD-RULE>
Unless the user explicitly names a palette, use the palettes matplotlib
ships by default: the default property cycle (`tab10`, addressed as `C0`,
`C1`, …) for categorical series and the default colormap (`viridis`) for
continuous data. No seaborn, cmocean, colorcet, or hand-assembled colour
lists on your own initiative.
</HARD-RULE>
The style sheet pins both defaults so a personal `matplotlibrc` cannot
quietly change them. When the user *does* state a palette, install it once
in the preamble and nowhere else:

```python
use_style(palette="Dark2")                  # property cycle from a qualitative map
use_style(cmap="cividis")                   # default colormap for c=, imshow, pcolormesh
set_palette(["#0072B2", "#E69F00", "#009E73"])   # or an explicit list, after use_style()
```

Series keep addressing the cycle by `C`-index either way, so changing the
palette later is one line. A signed quantity that genuinely needs a
diverging map takes a matplotlib built-in (`RdBu_r`, `coolwarm`) with
limits symmetric about zero — that is a judgment about the data, not a
palette preference, and a user-stated palette still wins.

**Color** — data series by index into the palette in effect: `"C0"`,
`"C1"`, `"C2"`.
<HARD-RULE>
Never hand-pick hex colors or named colors for data series at the call
site. `C`-indices keep every figure in a paper mutually consistent and
re-orderable, and keep the palette a single preamble decision.
</HARD-RULE>
Black (`"k"`) is reserved for reference lines and annotation, never for a
data series. Continuous quantities take the default colormap (leave `cmap`
unset, or `cmap="viridis"` explicitly) with **explicit** `vmin`/`vmax` so
panels sharing a colorbar share a scale.

**Markers** — `marker="."` with a small `s`: `s=0.5` for dense clouds
(thousands of points), `s=4`–`5` for sparse ones. Background scatter under
contours drops to `alpha=0.2`.

**Reference lines** — dashed black, thin: `ax.axhline(1, c="k", ls="--")`,
`ax.plot(x, x, "k--")`. A fitted or median level uses the same dashes in the
series color at `lw=1`.

**Labels** — units in **square** brackets (`"Exposure Time [min]"`), Title
Case for worded labels, raw strings for math (`r"$i$-magnitude"`). Panel
titles at `fontsize=BIG_SIZE`; everything else inherits from the preamble.

**Output** —
<HARD-RULE>
Save as a **PNG** with `bbox_inches="tight"` and `dpi=300`, into a `figs/`
directory beside the script. Every figure, every time.
</HARD-RULE>

```python
save(fig, "./figs/points_on_sky")                                      # helper: adds .png
plt.savefig("./figs/points_on_sky.png", bbox_inches="tight", dpi=300)  # written out
```

300 dpi at column width is roughly 1000 px across, at text width roughly
2100 px — print resolution, and small enough that a paper's worth of
figures stays well under a journal's upload cap. Vector PDF/SVG only when
the user specifically asks for a vector figure. Keep `rasterized=True` on
dense scatters anyway: it costs nothing in a PNG and keeps the script sane
if someone later asks for the PDF.

---

## Verification

Two checks, both cheap, both enforced by code rather than by re-reading:

1. **At run time** — `verify_style()` right after `use_style()`. It compares
   every rcParam against the house values and resolves the serif font,
   raising if any param was overridden or the font fell through to DejaVu.
2. **On the script** — `python scripts/check_plot_style.py <script.py>`
   parses the file and reports invented figure sizes, vector output,
   `savefig` without the tight-bbox/dpi arguments, boxed legends,
   hand-picked colours, third-party palettes, numeric font sizes,
   pyplot-state calls and `tight_layout`. Nonzero exit means a rule was broken; `--strict` also
   fails on warnings. Run it on every plotting script before presenting it.

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
data, runs standalone, and prints the resolved font and the saved size of
each figure.

---

## Anti-Patterns

Stop and fix if you catch any of these:

- **Invented figure size** — `figsize=(10, 6)`, `figsize=(8, 8)`. Use the
  journal widths and a named aspect.
- **Bare matplotlib defaults** — DejaVu Sans, outward ticks on two sides, a
  boxed legend. The preamble is not optional.
- **The right font name, the wrong font** — `font.family = "Nimbus Roman
  No9 L"` on a machine that calls it `Nimbus Roman`, rendering DejaVu Sans
  in silence. Use the fallback chain and `verify_style()`.
- **Numeric font sizes** — `fontsize=14`, `title_fontsize=20`. Only
  `SMALL_SIZE` / `NORMAL_SIZE` / `BIG_SIZE`, and only where the rules allow.
- **Hand-picked colors** — `color="#1f77b4"`, `color="steelblue"`. Use `C0`.
- **An unrequested palette** — `import seaborn as sns; sns.set_palette(...)`,
  `cmap=cmocean.cm.thermal`, a "nicer" custom list. Matplotlib's defaults
  unless the user named a palette; then `use_style(palette=..., cmap=...)`.
- **Saving PDF/SVG by default** — the house output is a tight 300 dpi PNG;
  vector only on request.
- **`savefig` without `bbox_inches="tight", dpi=300`** when the inline
  params block is in use — the block sets neither.
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
- **Guessed journal widths** — a registry entry that was not measured with
  `\showthe`.

---

## Self-Check Before Finishing

- [ ] Style applied via `use_style()` or the inline `params` block, before any figure.
- [ ] `verify_style()` passed (or `findfont` confirmed a Nimbus / Times face).
- [ ] Every `figsize` derives from `COLUMN_WIDTH` / `TEXT_WIDTH` or `figsize()` / `grid_figsize()`; height is a fraction of width.
- [ ] No numeric `fontsize`; only `SMALL_SIZE` / `NORMAL_SIZE` / `BIG_SIZE` where allowed.
- [ ] Palette is matplotlib's default unless the user named one, and a named one is set once via `use_style(palette=…)` / `set_palette`.
- [ ] Data series colored by `C`-index; `k` only for reference lines.
- [ ] Legends are `frameon=False`.
- [ ] Axis labels carry units in square brackets; math in raw strings.
- [ ] Saved as PNG into `figs/` with `bbox_inches="tight", dpi=300`.
- [ ] `scripts/check_plot_style.py` exits 0 on the script.
- [ ] Script actually ran and produced the file.

---

## Interaction With Other Skills

- **jupytext** — plotting scripts are `.py` files, so they get the percent
  format by default: one figure per `# %%` cell, with a markdown cell above
  saying what it shows.
- **co-scientist** — its visualization protocol decides *whether and what*
  to plot and already saves to `figures/*.png`; this skill decides *how it
  looks*. Figures produced under that protocol follow these rules.
- **dataviz** — that skill governs web/interactive charts with their own
  palette system. For matplotlib manuscript figures, this skill wins.

---

## Files

| Path | Contents |
|---|---|
| `assets/paper.mplstyle` | the rcParams as a matplotlib style sheet |
| `assets/plotstyle.py` | journal registry, widths, sizes, `use_style` / `verify_style` / `set_palette`, `figsize` / `grid_figsize`, and every idiom as a helper |
| `scripts/check_plot_style.py` | static checker for plotting scripts (stdlib only) |
| `references/recipes.md` | aspect guide and a copy-paste template per figure type, long and short form |
| `examples/example_figures.py` | four runnable figures on synthetic data, with a size report |

Derived from the figure code in `biprateep/desi-deep-pilot`, notebooks
`notebooks/paper_*.ipynb` (the `better_step` helper comes from that repo's
`notebooks/utils.py`); the aspect table tallies every `figsize` in them.
