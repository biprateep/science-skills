# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.16.0
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %% [markdown]
# # Publication Plot Style — Worked Examples
#
# Four canonical figures in the house style, on synthetic data so the file
# runs anywhere. Each one is a template: swap in real columns and keep the
# structure. Run it as `python example_figures.py`, or open it cell-by-cell.

# %% Imports
import pathlib
import sys

import matplotlib.pyplot as plt
import numpy as np
from PIL import Image  # ships with matplotlib; used only to measure the output

# This example takes the helper from the skill's assets/ directory. A real
# script has plotstyle.py beside it, so the import needs no path change.
sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parent.parent / "assets")
)

import plotstyle

# %% [markdown]
# ## Configuration
#
# Where the figures go, and the seed that makes the synthetic data
# reproducible.

# %% Configuration
OUT = pathlib.Path(__file__).resolve().parent / "figs"
SEED = 42

# %% [markdown]
# ## Apply the style
#
# One call, before any figure is created. Everything downstream — serif type
# at 9/10/12 pt on every piece of text, CM math, inward ticks on four sides,
# frameless legends, matplotlib's default palettes, tight 300 dpi PNG output
# — follows from this. Nobody asked for a palette here, so none is set; a
# stated one would go in this same call as `use_style(palette=..., cmap=...)`.
# The verify call fails loudly if the serif face is missing, instead of
# letting matplotlib substitute DejaVu Sans in silence.

# %% Set and verify the style
plotstyle.use_style()
style = plotstyle.verify_style()
print("serif font in use:", style["font"])
print(
    "palette:",
    "matplotlib default" if style["default_palette"] else style["palette"],
    "/",
    style["cmap"],
)

# %% [markdown]
# ## Synthetic catalogue
#
# Two "fields" with different depths, standing in for the real catalogue.

# %% Generate data
rng = np.random.default_rng(SEED)
fields = ["XMMLSS", "COSMOS"]
labels = [f"DESI-{name}" for name in fields]

catalogue = {}
for name, (n_targets, ra_center, dec_center, mag_mean) in zip(
    fields, [(4000, 35.0, -4.8, 22.9), (3000, 150.1, 2.2, 23.2)]
):
    mag = rng.normal(mag_mean, 0.45, n_targets)
    catalogue[name] = {
        "ra": ra_center + rng.uniform(-1.6, 1.6, n_targets),
        "dec": dec_center + rng.uniform(-1.6, 1.6, n_targets),
        "mag_i": mag,
        # Seconds. Fainter targets are given exponentially longer exposures.
        "exptime": np.clip(
            10 ** (0.5 * (mag - 21)) * 400 * rng.lognormal(0, 0.3, n_targets),
            900,
            31200,
        ),
    }

# %% [markdown]
# ## 1. Two sky panels sharing one colorbar
#
# Full text width, panels a little under half as tall (`0.4 * TEXT_WIDTH`,
# the manuscripts' usual two-panel height). The colorbar gets its own axes to
# the right of the whole figure so both panels share it, and both panels are
# given the same explicit `vmin`/`vmax` so that shared scale is honest.

# %% Sky distribution
fig, ax = plt.subplots(
    1, 2, figsize=(plotstyle.TEXT_WIDTH, 0.4 * plotstyle.TEXT_WIDTH)
)

for i, name in enumerate(fields):
    field = catalogue[name]
    points = ax[i].scatter(
        field["ra"],
        field["dec"],
        marker=".",
        s=4,
        c=field["exptime"] / 60,
        vmin=15,
        vmax=350,
        cmap="viridis",
        rasterized=True,
    )
    ax[i].set_title(f"DESI-{name}", fontsize=plotstyle.BIG_SIZE)
    ax[i].set_xlabel("R.A. [deg]")
    ax[i].set_ylabel("DEC. [deg]")

plotstyle.side_colorbar(fig, points, "Exposure Time [min]")
plotstyle.save(fig, OUT / "points_on_sky")
plt.close(fig)

# %% [markdown]
# ## 2. Stacked histograms
#
# The signature histogram: a white `histtype="step"` underlay tracing the
# full-width envelope, then semi-transparent bars narrowed to `rwidth=0.8`.
# Colours are the default cycle (`C0`, `C1`, ...) — never hand-picked hex.
# `grid_figsize` derives the height from a per-panel aspect: two panels of
# aspect 0.7 across the text width come to `0.35 * TEXT_WIDTH`.

# %% Magnitude distributions
fig, ax = plt.subplots(
    1, 2, figsize=plotstyle.grid_figsize(1, 2, "text", panel_aspect=0.7)
)

plotstyle.stacked_hist(
    ax[0], [catalogue[name]["mag_i"] for name in fields], labels=labels, bins=30
)
ax[0].set_xlabel(r"$i$-magnitude")
ax[0].set_ylabel("Counts")
ax[0].legend()

plotstyle.stacked_hist(
    ax[1],
    [catalogue[name]["exptime"] / 60 for name in fields],
    labels=labels,
    bins=20,
)
ax[1].set_xlabel("Exposure Time [min]")
ax[1].set_ylabel("Counts")
ax[1].legend()

plotstyle.save(fig, OUT / "distributions")
plt.close(fig)

# %% [markdown]
# ## 3. One-to-one comparison
#
# Square, single-column, equal aspect, matched limits, dashed identity line.
# Anything that compares two measurements of the same quantity gets this
# shape — the eye reads departures from the diagonal directly.

# %% Measurement comparison
fig, ax = plt.subplots(
    1, 1, figsize=(plotstyle.COLUMN_WIDTH, plotstyle.COLUMN_WIDTH)
)

truth = np.concatenate([catalogue[name]["mag_i"] for name in fields])
measured = truth + rng.normal(0.02, 0.12, truth.size)

ax.scatter(truth, measured, marker=".", s=0.5, rasterized=True)
plotstyle.one_to_one(ax, 21.5, 25.0)
ax.set_xlabel("HSC $i$ fiber mag")
ax.set_ylabel("LS $i$ fiber mag")

plotstyle.save(fig, OUT / "one_to_one")
plt.close(fig)

# %% [markdown]
# ## 4. Residuals with a running median
#
# The workhorse diagnostic: raw points as a faint dust of tiny markers, an
# equal-count binned median staircase with a shaded 25–75 band over the top,
# the global median as a dashed line, and `k--` at the null value. A
# single-column "tall" (4:3) panel leaves room for the band.

# %% Residual trend
fig, ax = plt.subplots(1, 1, figsize=plotstyle.figsize("column", "tall"))

offset = measured - truth

ax.scatter(truth, offset, marker=".", s=0.5, rasterized=True)
plotstyle.running_median(ax, truth, offset, nbins=10)
ax.axhline(0, c="k", ls="--")
ax.set_xlim(21.5, 25.0)
ax.set_xlabel("HSC $i$ fiber mag")
ax.set_ylabel("LS $-$ HSC [mag]")

plotstyle.save(fig, OUT / "residual_trend")
plt.close(fig)

# %% [markdown]
# ## Done
#
# Four PNGs in `figs/`, each sized to drop into the manuscript at
# `width=\columnwidth` or `width=\textwidth`. The report below measures each
# file: `bbox_inches="tight"` crops the canvas to its artists, so the saved
# image is narrower than the nominal width by whatever subplot margin went
# unused (up to ~15 % for a two-panel row with the default layout, ~3 % with
# `layout="constrained"`), and LaTeX rescales it by the ratio shown. The
# proportions survive that scaling; the type size drifts by the same factor.

# %% Report
nominal = {
    "points_on_sky": plotstyle.TEXT_WIDTH,
    "distributions": plotstyle.TEXT_WIDTH,
    "one_to_one": plotstyle.COLUMN_WIDTH,
    "residual_trend": plotstyle.COLUMN_WIDTH,
}
print(
    f"\n{'figure':18s} {'kB':>7s} {'px':>11s} {'saved in':>9s}"
    f" {'nominal':>8s} {'scale':>6s}"
)
for path in sorted(OUT.glob("*.png")):
    with Image.open(path) as image:
        width_px, height_px = image.size
        dpi = image.info.get("dpi", (300, 300))[0]
    saved_in = width_px / dpi
    nominal_in = nominal.get(path.stem, float("nan"))
    print(
        f"{path.stem:18s} {path.stat().st_size / 1024:7.1f}"
        f" {width_px:5d}x{height_px:<5d} "
        f'{saved_in:8.2f}" {nominal_in:7.2f}" {nominal_in / saved_in:6.3f}'
    )
