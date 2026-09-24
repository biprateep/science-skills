# Figure Recipes

Copy-paste templates for the recurring figure types, in house style. Every
snippet assumes the preamble:

```python
import matplotlib.pyplot as plt
import numpy as np

import plotstyle

plotstyle.use_style()  # AASTeX; use_style(journal="...") for another class
plotstyle.verify_style()  # raises if the serif face did not resolve
```

The helper is imported as a module and every name is reached through it
(`plotstyle.figsize`, `plotstyle.TEXT_WIDTH`), as the code-style skill
requires. Every recipe saves with `plotstyle.save(fig, "./figs/<name>")`,
which writes a tight 300 dpi PNG — written out, that is
`fig.savefig("./figs/<name>.png", bbox_inches="tight", dpi=300)` — and then
closes the figure with `plt.close(fig)`.

---

## 0. Choosing the height

Width is fixed by the journal; only the aspect (height / width) is a choice.
These are the ratios the source manuscripts actually used, by figure type:

| Figure | `figsize` | Aspect | Seen |
|---|---|---|---|
| Single column, one panel | `figsize("column")` | golden, 0.618 | 0.56–0.75, most often 0.7 |
| Single column, short (histogram, flat trend) | `figsize("column", "wide")` | 0.5625 | 5 figures |
| Single column, room for a band or inside legend | `figsize("column", "tall")` | 0.75 | 3 figures |
| Single column, square (1:1, sky map, `aspect="equal"`) | `figsize("column", "square")` | 1.0 | 5 figures |
| Full width, one panel | `figsize("text", 0.6)` | 0.5–0.65 | 12 figures |
| Full width, two panels | `grid_figsize(1, 2, "text", panel_aspect=0.7)` → `0.35 * TEXT_WIDTH` | 0.35–0.4 | 4 figures |
| Full width, two histograms | `(TEXT_WIDTH, 0.35 * TEXT_WIDTH)` | 0.35 | 2 figures |
| Full width, square grid | `(TEXT_WIDTH, TEXT_WIDTH)` | 1.0 | 1 figure |

`grid_figsize(nrows, ncols, width, panel_aspect)` turns a *per-panel* aspect
into the figure height: `nrows * panel_aspect * width / ncols`.

---

## 0b. Palette

Unless the user names one, colour is whatever matplotlib ships by default:
the `tab10` property cycle for series (`C0`, `C1`, …) and `viridis` for
continuous data. `use_style()` pins both, overriding any personal
`matplotlibrc`. Nothing else needs writing.

When the user *has* stated a palette, it goes in the preamble, once:

```python
plotstyle.use_style(palette="Dark2")  # qualitative colormap -> property cycle
plotstyle.use_style(palette="tab20", cmap="cividis")  # both at once
# An explicit list:
plotstyle.use_style(palette=["#0072B2", "#E69F00", "#009E73", "#CC79A7"])
plotstyle.set_palette(cmap="magma")  # change one after the fact
plotstyle.set_palette()  # back to matplotlib defaults
```

Series code does not change — it still says `color="C1"` — and a
continuous map passed by name is sampled at 10 evenly spaced points
(`n=` to choose). A diverging quantity takes a matplotlib built-in with
limits symmetric about zero, `cmap="RdBu_r", vmin=-a, vmax=a`; that is a
property of the data, not a palette choice.

---

## 1. Panel grid with one shared colorbar

Full text width, two panels, one slim colorbar to the right of the *figure*
(not of a panel), so both panels read off the same scale.

```python
fig, ax = plt.subplots(
    1, 2, figsize=(plotstyle.TEXT_WIDTH, 0.4 * plotstyle.TEXT_WIDTH)
)

for i, field in enumerate(field_names):
    in_field = catalogue[catalogue["FIELD_NAME"] == field]
    points = ax[i].scatter(
        in_field["TARGET_RA"],
        in_field["TARGET_DEC"],
        marker=".",
        s=4,
        c=in_field["EXPTIME"] / 60,
        vmin=15,
        vmax=500,
        cmap="viridis",
        rasterized=True,
    )
    ax[i].set_title(f"DESI-{field}", fontsize=plotstyle.BIG_SIZE)
    ax[i].set_xlabel("R.A. [deg]")
    ax[i].set_ylabel("DEC. [deg]")

plotstyle.side_colorbar(fig, points, "Exposure Time [min]")
plotstyle.save(fig, "./figs/points_on_sky")
plt.close(fig)
```

`side_colorbar` is the long form written out:

```python
# [left, bottom, width, height] in figure coordinates:
cbar_ax = fig.add_axes([0.95, 0.15, 0.02, 0.7])
cbar = fig.colorbar(points, cax=cbar_ax)
cbar.set_label("Exposure Time [min]", rotation=-90, labelpad=15)
```

`points` is the mappable from the **last** scatter drawn — fine when every panel
shares `vmin`/`vmax`, which is exactly why they are set explicitly rather
than left to autoscale. Never pass `fraction=` alongside `cax=`; it is
silently ignored.

---

## 2. Stacked histogram

The signature two-pass idiom. Pass one is a white `histtype="step"` outline
over the full-width stacked envelope; pass two lays the semi-transparent bars
on top, narrowed by `rwidth=0.8` so neighbouring bins stay separable.

```python
fig, ax = plt.subplots(
    1, 2, figsize=plotstyle.grid_figsize(1, 2, "text", panel_aspect=0.7)
)

i_mag = [
    catalogue[catalogue["FIELD_NAME"] == field]["mag_i"]
    for field in field_names
]
labels = [f"DESI-{field}" for field in field_names]

ax[0].hist(
    i_mag,
    bins=30,
    stacked=True,
    histtype="step",
    color=("white",) * len(i_mag),
)
ax[0].hist(
    i_mag,
    bins=30,
    stacked=True,
    color=["C0", "C1"],
    alpha=0.5,
    rwidth=0.8,
    label=labels,
)

ax[0].set_xlabel(r"$i$-magnitude")
ax[0].set_ylabel("Counts")
ax[0].legend(frameon=False)
```

Or, with identical bin edges guaranteed across both passes:

```python
plotstyle.stacked_hist(ax[0], i_mag, labels=labels, bins=30)
ax[0].legend()
```

Variants seen in practice:
- **Explicit edges** for a controlled range: `bins = np.linspace(22, 24.5, 10)`.
- **Nudged legend** when the default placement collides with the tallest bar:
  `ax.legend(frameon=False, loc=(0.41, 0.78))`.
- **Crowded legend** drops one step to the tick size, never lower:
  `ax.legend(frameon=False, fontsize=plotstyle.SMALL_SIZE, handlelength=1.5)`.
- **Titled legend** for a family of curves: `ax.legend(frameon=False,
  title=r"$i$-mag limit", loc="lower right")` — the title inherits
  `legend.title_fontsize` (10 pt); never pass a numeric `title_fontsize`.
- **Manual ticks** after a hard `set_xlim`: `ax.set_xticks(np.linspace(0, 3, 7))`.

---

## 3. One-to-one comparison

Two measurements of the same quantity. Square, single column, equal aspect,
matched limits, dashed identity line — departures from the diagonal are then
read directly off the page.

```python
fig, ax = plt.subplots(
    1, 1, figsize=(plotstyle.COLUMN_WIDTH, plotstyle.COLUMN_WIDTH)
)
ax.scatter(
    catalogue["mag_r_fiber"],
    catalogue["rfibermag"],
    marker=".",
    s=0.5,
    rasterized=True,
)
plotstyle.one_to_one(ax, 22, 26)
ax.set_xlabel("HSC r fiber mag")
ax.set_ylabel("LS r fiber mag")
```

Long form:

```python
diagonal = np.linspace(22, 26)
ax.plot(diagonal, diagonal, "k--")
ax.set_xlim(22, 26)
ax.set_ylim(22, 26)
ax.set_aspect("equal")
```

---

## 4. Residual / ratio trend with a running median

The workhorse diagnostic. Raw points as a faint dust of tiny markers; an
**equal-count** binned median as a staircase with a shaded 25–75 percentile
band; the global median dashed in the same colour; `k--` at the null value
(0 for a difference, 1 for a ratio).

```python
fig, ax = plt.subplots(1, 1, figsize=plotstyle.figsize("column", "tall"))

offset = catalogue["mag_r_fiber"] - catalogue["rfibermag"]

ax.scatter(catalogue["mag_r_fiber"], offset, marker=".", s=0.5, rasterized=True)
plotstyle.running_median(
    ax, catalogue["mag_r_fiber"], offset, nbins=10, color="C1"
)
ax.axhline(0, c="k", ls="--")
ax.set_xlim(22, 26)
```

Long form, with pandas + scipy as written in the notebooks:

```python
from scipy import stats

_, bins = pd.qcut(catalogue["mag_r_fiber"], 10, retbins=True)
median, _, _ = stats.binned_statistic(
    catalogue["mag_r_fiber"], offset, bins=bins, statistic="median"
)
p25, _, _ = stats.binned_statistic(
    catalogue["mag_r_fiber"],
    offset,
    bins=bins,
    statistic=lambda v: np.percentile(v, 25),
)
p75, _, _ = stats.binned_statistic(
    catalogue["mag_r_fiber"],
    offset,
    bins=bins,
    statistic=lambda v: np.percentile(v, 75),
)

plotstyle.better_step(bins, median, (p25, p75), ax=ax, c="C1")
ax.axhline(np.median(offset), color="C1", ls="--", lw=1)
```

`pd.qcut(..., retbins=True)` gives **equal-count** bins, so the band is
equally well determined at every x — unlike equal-width bins, whose end bins
are noisy. `better_step` draws the median as a true staircase across each
bin's full width rather than as a polyline through bin centres.

---

## 5. Density contours over a scatter

When the point cloud is dense enough that the scatter alone saturates: KDE
contours carry the shape, the scatter underneath at `alpha=0.2` carries the
outliers. Contour colour matches the scatter colour, one `C`-index per class.

```python
from scipy import stats

# x, y, X, Y and Z follow matplotlib's contour(X, Y, Z) notation.
x_grid = np.linspace(x_all.min(), x_all.max(), 100)
y_grid = np.linspace(y_all.min(), y_all.max(), 100)
X, Y = np.meshgrid(x_grid, y_grid)

for (x, y), color, label in [
    (cosmos, "C1", "DESI-COSMOS"),
    (xmm, "C0", "DESI-XMM"),
]:
    kde = stats.gaussian_kde(np.vstack([x, y]))
    Z = kde(np.vstack([X.ravel(), Y.ravel()])).reshape(X.shape)
    ax.contour(X, Y, Z, colors=color, linewidths=1.5)
    ax.scatter(x, y, color=color, s=5, alpha=0.2, label=label)
```

`ax.contour` ignores `label=`; put the legend entry on the scatter pass, or
build proxy handles.

---

## 6. Shaded region + annotated thresholds

For marking selection cuts or regimes on a distribution:

```python
ax.axvline(bound[0], c="k", ls="--", lw=0.8, zorder=5, alpha=0.8)
ax.fill_betweenx(
    np.linspace(0, ymax),
    bound[0],
    bound[1],
    facecolor="k",
    linewidth=0,
    zorder=5,
    alpha=0.05,
)
ax.text(0.15, 1.03, "82", transform=ax.transAxes)  # above the axes
```

Thin dashed black rules; the band is nearly transparent black rather than a
colour, so it reads as annotation and not as data. `transform=ax.transAxes`
places text in axes fractions, immune to data rescaling.

---

## Axis-label conventions

| Quantity | Label |
|---|---|
| Coordinate | `"R.A. [deg]"`, `"DEC. [deg]"` |
| Time | `"Exposure Time [min]"` (convert from seconds at the call site: `EXPTIME / 60`) |
| Magnitude, symbolic | `r"$i$-magnitude"`, `r"$i$-fiber-magnitude"` |
| Magnitude, plain | `"HSC r fiber mag"` |
| Counts | `"Counts"`, or what is counted: `"Number of redshift failures"` |
| Derived | `"Spectroscopic Redshift"` |

Units go in **square** brackets, never parentheses. Title Case for worded
labels. Raw strings for anything with `$math$` or a backslash.
