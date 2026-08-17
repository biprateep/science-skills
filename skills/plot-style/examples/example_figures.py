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
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "assets"))

from plotstyle import (  # noqa: E402
    BIG_SIZE,
    COLUMN_WIDTH,
    TEXT_WIDTH,
    figsize,
    one_to_one,
    running_median,
    save,
    side_colorbar,
    stacked_hist,
    use_style,
)

# %% [markdown]
# ## Apply the style
#
# One call, before any figure is created. Everything downstream — serif type,
# CM math, inward ticks on four sides, frameless legends, 300 dpi — follows
# from this.

# %% Set the style
use_style()

OUT = Path(__file__).resolve().parent / "figs"
rng = np.random.default_rng(42)

# %% [markdown]
# ## Synthetic catalogue
#
# Two "fields" with different depths, standing in for the real catalogue.

# %% Generate data
fields = ["XMMLSS", "COSMOS"]
labels = [f"DESI-{name}" for name in fields]

cat = {}
for name, (n, ra0, dec0, mag0) in zip(
    fields, [(4000, 35.0, -4.8, 22.9), (3000, 150.1, 2.2, 23.2)]
):
    mag = rng.normal(mag0, 0.45, n)
    cat[name] = {
        "ra": ra0 + rng.uniform(-1.6, 1.6, n),
        "dec": dec0 + rng.uniform(-1.6, 1.6, n),
        "mag_i": mag,
        # Seconds. Fainter targets are given exponentially longer exposures.
        "exptime": np.clip(
            10 ** (0.5 * (mag - 21)) * 400 * rng.lognormal(0, 0.3, n), 900, 31200
        ),
    }

# %% [markdown]
# ## 1. Two sky panels sharing one colorbar
#
# Full text width, panels a little under half as tall. The scatter is
# **rasterized** — thousands of markers stay a bitmap inside an otherwise
# vector PDF, which is the difference between a 200 kB figure and a 20 MB
# one. The colorbar gets its own axes to the right of the whole figure so
# both panels share it.

# %% Sky distribution
fig, ax = plt.subplots(1, 2, figsize=(TEXT_WIDTH, 0.4 * TEXT_WIDTH))

for i, name in enumerate(fields):
    d = cat[name]
    s = ax[i].scatter(
        d["ra"],
        d["dec"],
        marker=".",
        s=4,
        c=d["exptime"] / 60,
        vmin=15,
        vmax=350,
        cmap="viridis",
        rasterized=True,
    )
    ax[i].set_title(f"DESI-{name}", fontsize=BIG_SIZE)
    ax[i].set_xlabel("R.A. [deg]")
    ax[i].set_ylabel("DEC. [deg]")

side_colorbar(fig, s, "Exposure Time [min]")
save(fig, OUT / "points_on_sky.pdf")

# %% [markdown]
# ## 2. Stacked histograms
#
# The signature histogram: a white `histtype="step"` underlay tracing the
# full-width envelope, then semi-transparent bars narrowed to `rwidth=0.8`.
# Colours are the default cycle (`C0`, `C1`, ...) — never hand-picked hex.

# %% Magnitude distributions
fig, ax = plt.subplots(1, 2, figsize=(TEXT_WIDTH, 0.35 * TEXT_WIDTH))

stacked_hist(ax[0], [cat[f]["mag_i"] for f in fields], labels=labels, bins=30)
ax[0].set_xlabel(r"$i$-magnitude")
ax[0].set_ylabel("Counts")
ax[0].legend()

stacked_hist(ax[1], [cat[f]["exptime"] / 60 for f in fields], labels=labels, bins=20)
ax[1].set_xlabel("Exposure Time [min]")
ax[1].set_ylabel("Counts")
ax[1].legend()

save(fig, OUT / "distributions.pdf")

# %% [markdown]
# ## 3. One-to-one comparison
#
# Square, single-column, equal aspect, matched limits, dashed identity line.
# Anything that compares two measurements of the same quantity gets this
# shape — the eye reads departures from the diagonal directly.

# %% Measurement comparison
fig, ax = plt.subplots(1, 1, figsize=(COLUMN_WIDTH, COLUMN_WIDTH))

truth = np.concatenate([cat[f]["mag_i"] for f in fields])
measured = truth + rng.normal(0.02, 0.12, truth.size)

ax.scatter(truth, measured, marker=".", s=0.5, rasterized=True)
one_to_one(ax, 21.5, 25.0)
ax.set_xlabel("HSC $i$ fiber mag")
ax.set_ylabel("LS $i$ fiber mag")

save(fig, OUT / "one_to_one.pdf")

# %% [markdown]
# ## 4. Residuals with a running median
#
# The workhorse diagnostic: raw points as a faint dust of tiny markers, an
# equal-count binned median staircase with a shaded 25–75 band over the top,
# the global median as a dashed line, and `k--` at the null value.

# %% Residual trend
fig, ax = plt.subplots(1, 1, figsize=figsize("column", 1.0))

offset = measured - truth

ax.scatter(truth, offset, marker=".", s=0.5, rasterized=True)
running_median(ax, truth, offset, nbins=10)
ax.axhline(0, c="k", ls="--")
ax.set_xlim(21.5, 25.0)
ax.set_xlabel("HSC $i$ fiber mag")
ax.set_ylabel("LS $-$ HSC [mag]")

save(fig, OUT / "residual_trend.pdf")

# %% [markdown]
# ## Done
#
# Four PDFs in `figs/`, each sized to drop straight into the manuscript at
# `width=\columnwidth` or `width=\textwidth` with **no scaling** — which is
# the whole point of fixing the widths up front.

# %% Report
for path in sorted(OUT.glob("*.pdf")):
    print(f"{path.name:24s} {path.stat().st_size / 1024:7.1f} kB")
