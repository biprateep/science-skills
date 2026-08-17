# Figure Recipes

Copy-paste templates for the recurring figure types, in house style. Every
snippet assumes the preamble:

```python
import matplotlib.pyplot as plt
import numpy as np
from plotstyle import *   # or: from plotstyle import use_style, figsize, ...

use_style()
```

---

## 1. Panel grid with one shared colorbar

Full text width, two panels, one slim colorbar to the right of the *figure*
(not of a panel), so both panels read off the same scale.

```python
fig, ax = plt.subplots(1, 2, figsize=(TEXT_WIDTH, 0.4 * TEXT_WIDTH))

for i, field in enumerate(field_names):
    sel = cat[cat["FIELD_NAME"] == field]
    s = ax[i].scatter(
        sel["TARGET_RA"], sel["TARGET_DEC"],
        marker=".", s=4, c=sel["EXPTIME"] / 60,
        vmin=15, vmax=500, cmap="viridis", rasterized=True,
    )
    ax[i].set_title(f"DESI-{field}", fontsize=BIG_SIZE)
    ax[i].set_xlabel("R.A. [deg]")
    ax[i].set_ylabel("DEC. [deg]")

side_colorbar(fig, s, "Exposure Time [min]")
save(fig, "./figs/points_on_sky.pdf")
```

`side_colorbar` is the long form written out:

```python
cbar_ax = fig.add_axes([0.95, 0.15, 0.02, 0.7])   # [left, bottom, w, h], figure coords
cbar = fig.colorbar(s, cax=cbar_ax)
cbar.set_label("Exposure Time [min]", rotation=-90, labelpad=15)
```

`s` is the mappable from the **last** scatter drawn — fine when every panel
shares `vmin`/`vmax`, which is exactly why they are set explicitly rather
than left to autoscale. Never pass `fraction=` alongside `cax=`; it is
silently ignored.

---

## 2. Stacked histogram

The signature two-pass idiom. Pass one is a white `histtype="step"` outline
over the full-width stacked envelope; pass two lays the semi-transparent bars
on top, narrowed by `rwidth=0.8` so neighbouring bins stay separable.

```python
fig, ax = plt.subplots(1, 2, figsize=(TEXT_WIDTH, 0.35 * TEXT_WIDTH))

i_mag = [cat[cat["FIELD_NAME"] == f]["mag_i"] for f in field_names]
labels = [f"DESI-{f}" for f in field_names]

ax[0].hist(i_mag, bins=30, stacked=True, histtype="step", color=("white",) * len(i_mag))
ax[0].hist(i_mag, bins=30, stacked=True, color=["C0", "C1"],
           alpha=0.5, rwidth=0.8, label=labels)

ax[0].set_xlabel(r"$i$-magnitude")
ax[0].set_ylabel("Counts")
ax[0].legend(frameon=False)
```

Or, with identical bin edges guaranteed across both passes:

```python
stacked_hist(ax[0], i_mag, labels=labels, bins=30)
ax[0].legend()
```

Variants seen in practice:
- **Explicit edges** for a controlled range: `bins = np.linspace(22, 24.5, 10)`.
- **Nudged legend** when the default placement collides with the tallest bar:
  `ax.legend(frameon=False, loc=(0.41, 0.78))`.
- **Manual ticks** after a hard `set_xlim`: `ax.set_xticks(np.linspace(0, 3, 7))`.

---

## 3. One-to-one comparison

Two measurements of the same quantity. Square, single column, equal aspect,
matched limits, dashed identity line — departures from the diagonal are then
read directly off the page.

```python
fig, ax = plt.subplots(1, 1, figsize=(COLUMN_WIDTH, COLUMN_WIDTH))
ax.scatter(cat["mag_r_fiber"], cat["rfibermag"], marker=".", s=0.5, rasterized=True)
one_to_one(ax, 22, 26)
ax.set_xlabel("HSC r fiber mag")
ax.set_ylabel("LS r fiber mag")
```

Long form:

```python
x = np.linspace(22, 26)
ax.plot(x, x, "k--")
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
fig, ax = plt.subplots(1, 1, figsize=(COLUMN_WIDTH, COLUMN_WIDTH))

offset = cat["mag_r_fiber"] - cat["rfibermag"]

ax.scatter(cat["mag_r_fiber"], offset, marker=".", s=0.5, rasterized=True)
running_median(ax, cat["mag_r_fiber"], offset, nbins=10, color="C1")
ax.axhline(0, c="k", ls="--")
ax.set_xlim(22, 26)
```

Long form, with pandas + scipy as written in the notebooks:

```python
from scipy.stats import binned_statistic

_, bins = pd.qcut(cat["mag_r_fiber"], 10, retbins=True)
med, _, _ = binned_statistic(cat["mag_r_fiber"], offset, bins=bins, statistic="median")
p25, _, _ = binned_statistic(cat["mag_r_fiber"], offset, bins=bins,
                             statistic=lambda v: np.percentile(v, 25))
p75, _, _ = binned_statistic(cat["mag_r_fiber"], offset, bins=bins,
                             statistic=lambda v: np.percentile(v, 75))

better_step(bins, med, (p25, p75), ax=ax, c="C1")
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
from scipy.stats import gaussian_kde

xi = np.linspace(x_all.min(), x_all.max(), 100)
yi = np.linspace(y_all.min(), y_all.max(), 100)
X, Y = np.meshgrid(xi, yi)

for (x, y), c, label in [(cosmos, "C1", "DESI-COSMOS"), (xmm, "C0", "DESI-XMM")]:
    kde = gaussian_kde(np.vstack([x, y]))
    Z = kde(np.vstack([X.ravel(), Y.ravel()])).reshape(X.shape)
    ax.contour(X, Y, Z, colors=c, linewidths=1.5)
    ax.scatter(x, y, color=c, s=5, alpha=0.2, label=label)
```

`ax.contour` ignores `label=`; put the legend entry on the scatter pass, or
build proxy handles.

---

## 6. Shaded region + annotated thresholds

For marking selection cuts or regimes on a distribution:

```python
ax.axvline(bound[0], c="k", ls="--", lw=0.8, zorder=5, alpha=0.8)
ax.fill_betweenx(np.linspace(0, ymax), bound[0], bound[1],
                 facecolor="k", linewidth=0, zorder=5, alpha=0.05)
ax.text(0.15, 1.03, "82", transform=ax.transAxes)   # above the axes
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
