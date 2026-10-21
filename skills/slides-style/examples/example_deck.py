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
# # House Slide Style — A Worked Deck
#
# A twelve-slide talk on synthetic data that uses every slide type the
# author's decks use: title, acknowledgements, statement, figure with
# annotations and an Appear build, an annotated equation, a two-panel
# comparison, a progressive build as duplicated slides, summary, divider
# and a hidden backup slide. Run it from this folder:
#
#     uv run --with python-pptx --with lxml --with pillow --with numpy \
#         --with matplotlib --with pypandoc_binary example_deck.py
#
# It writes `example_deck.pptx` and the figures it places into `out/`.

# %% Imports
import importlib.util
import pathlib
import sys

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np

_SKILL = pathlib.Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "slidestyle", _SKILL / "assets" / "slidestyle.py"
)
slidestyle = importlib.util.module_from_spec(_SPEC)
sys.modules["slidestyle"] = slidestyle
_SPEC.loader.exec_module(slidestyle)

mpl.use("Agg")

# %% Configuration
OUT = pathlib.Path(__file__).resolve().parent / "out"
SEED = 42
# A figure made only for a slide is drawn at half its on-slide size, so
# plot-style's 9-12 pt type lands at 18-24 pt on the slide.
HALF_SCALE = 0.5

# %% [markdown]
# ## Figures
#
# Synthetic photometric redshifts: a one-to-one comparison for two methods
# and a predicted distribution. Computer Modern, inward ticks, frameless
# legend, as plot-style draws them.

# %% Figures
rng = np.random.default_rng(SEED)
OUT.mkdir(parents=True, exist_ok=True)
plt.rcParams.update(
    {
        "font.family": "serif",
        "font.serif": ["CMU Serif", "Latin Modern Roman", "cmr10"],
        "mathtext.fontset": "cm",
        "axes.formatter.use_mathtext": True,
        "font.size": 10,
        "xtick.direction": "in",
        "ytick.direction": "in",
        "xtick.top": True,
        "ytick.right": True,
        "legend.frameon": False,
    }
)
z_true = rng.uniform(0.05, 1.0, 3000)
z_knn = z_true + rng.normal(0, 0.05 * (1 + z_true))
z_cnn = z_true + rng.normal(0, 0.02 * (1 + z_true))

for name, z_pred in (("knn", z_knn), ("cnn", z_cnn)):
    fig, ax = plt.subplots(figsize=(6.0 * HALF_SCALE, 5.2 * HALF_SCALE))
    ax.scatter(z_true, z_pred, s=0.5, c="C0", marker=".", rasterized=True)
    ax.plot([0, 1.1], [0, 1.1], "k--", lw=1)
    ax.set(xlim=(0, 1.1), ylim=(0, 1.1), aspect="equal")
    ax.set_xlabel(r"$z_{\rm spec}$")
    ax.set_ylabel(r"$z_{\rm phot}$")
    fig.savefig(OUT / f"one_to_one_{name}.png", dpi=300, bbox_inches="tight")
    plt.close(fig)

grid = np.linspace(0, 1.5, 400)
pdf = 0.7 * np.exp(-0.5 * ((grid - 0.45) / 0.05) ** 2) + 0.3 * np.exp(
    -0.5 * ((grid - 0.9) / 0.08) ** 2
)
fig, ax = plt.subplots(figsize=(11.0 * HALF_SCALE, 5.0 * HALF_SCALE))
ax.plot(grid, pdf / np.trapezoid(pdf, grid), c="C0", label="Predicted")
ax.axvline(0.47, c="k", ls="--", lw=1, label="True redshift")
ax.set_xlabel("Redshift")
ax.set_ylabel(r"$p(z\,|\,\mathbf{x})$")
ax.legend(loc="upper right")
fig.savefig(OUT / "pdf.png", dpi=300, bbox_inches="tight")
plt.close(fig)

# %% [markdown]
# ## The Deck

# %% Opening
deck = slidestyle.new_deck()
slidestyle.title_slide(
    deck,
    "**Cosmic Cartography:** Photometric Redshifts for "
    "==Next-Generation== Sky Surveys",
    subtitle="with collaborators at the University of Toronto",
    hero=slidestyle.asset("hero/desi-3d-map"),
    hero_alt="DESI 3D map of galaxies, coloured by redshift",
    hero_credit="Image courtesy: DESI Collaboration",
)
slidestyle.acknowledgements_slide(
    deck,
    ["person/alexandros-pratsos", "person/josh-speagle", "person/ting-li"],
)
slidestyle.statement_slide(deck, "Why do we need to know galaxy distances?")

# %% Figure with annotations and an Appear build
slide = slidestyle.content_slide(deck, "Photo-z Prediction Performance")
slidestyle.figure(
    slide,
    OUT / "one_to_one_cnn.png",
    (0.6, 1.40, 6.6, 5.50),
    alt="Predicted against true redshift for a deep network; tight scatter",
    align="left",
)
label = slidestyle.text(
    slide,
    "Ideal photo-z’s follow\nthe identity line",
    7.4,
    2.0,
    4.6,
    size=slidestyle.LABEL_SIZE,
)
pointer = slidestyle.arrow(slide, (7.45, 2.45), (5.2, 3.2))
takeaway = slidestyle.text(
    slide,
    "Scatter is **3× smaller** than\nclassical k-NN",
    7.4,
    4.4,
    5.2,
)
slidestyle.credit(
    slide,
    "Dey et al. 2022, [arXiv:2112.03939](https://arxiv.org/abs/2112.03939)",
)
slidestyle.appear(slide, [[label, pointer], takeaway])

# %% Annotated equation
slide = slidestyle.content_slide(deck, "Calibration Using Local PIT (Cal-PIT)")
slidestyle.equation(
    slide,
    r"\widetilde{F}(z \mid \mathbf{x}) := \hat{r}^{\hat{f}}"
    r"\left(\hat{F}(z \mid \mathbf{x});\, \mathbf{x}\right)",
    3.2,
    2.3,
    size=40,
)
for left, words, tip in (
    (1.0, "New distribution\n(calibrated by construction)", (4.0, 3.45)),
    (5.0, "Learnt regression\nfunction", (6.5, 3.45)),
    (8.6, "Old distribution\n(uncalibrated)", (8.4, 3.45)),
):
    slidestyle.text(
        slide,
        words,
        left,
        4.3,
        3.4,
        size=slidestyle.LABEL_SIZE,
        align="center",
    )
    slidestyle.line(slide, (left + 1.7, 4.3), tip)
slidestyle.text(
    slide,
    "P.S. This is an **optimal transport** map between the two distributions.",
    1.0,
    5.9,
    11.0,
    size=slidestyle.LABEL_SIZE,
)

# %% Two-panel comparison
slide = slidestyle.content_slide(deck, "Classical ML vs Deep Networks")
for box, name, label_text in (
    (slidestyle.LEFT_HALF, "knn", "Classical ML (k-NN)"),
    (slidestyle.RIGHT_HALF, "cnn", "Deep Capsule Network"),
):
    left, top, width, height = box
    slidestyle.text(
        slide,
        label_text,
        left,
        top,
        width,
        size=slidestyle.LABEL_SIZE,
        align="center",
        bold=True,
    )
    slidestyle.figure(
        slide,
        OUT / f"one_to_one_{name}.png",
        (left, top + 0.5, width, height - 0.5),
        alt=f"Predicted against true redshift, {label_text}",
    )
slidestyle.credit(slide, "Beck et al. 2016; Dey et al. 2022")

# %% Progressive build as duplicated slides
steps = ["Low signal-to-noise", "+ Selection cuts", "+ Missing bands"]
for count in range(1, len(steps) + 1):
    slide = slidestyle.content_slide(deck, "The Boons and Banes of Survey Data")
    slidestyle.figure(
        slide,
        OUT / "pdf.png",
        (4.6, 1.5, 8.3, 5.3),
        alt="A bimodal predicted redshift distribution and the true value",
    )
    slidestyle.text(
        slide,
        "\n".join(steps[:count]),
        0.8,
        2.2,
        3.7,
        size=slidestyle.LABEL_SIZE,
    )

# %% Closing
slidestyle.summary_slide(
    deck,
    [
        "Photo-z’s derived from **resolved images** are more accurate.",
        "We can **test and produce** statistically meaningful photo-z "
        "distributions with Cal-PIT.",
        "Deep spectroscopy collects **complete training sets** in "
        "reasonable time.",
    ],
    references=[
        "Dey et al. 2022 ([arXiv:2112.03939](https://arxiv.org/abs/2112.03939))",
    ],
)
slidestyle.divider_slide(deck)
backup = slidestyle.content_slide(deck, "Predicted Redshift Distributions")
slidestyle.figure(backup, OUT / "pdf.png", alt="A predicted distribution")
slidestyle.hide(backup)
slidestyle.save(deck, OUT / "example_deck.pptx")
print(f"wrote {OUT / 'example_deck.pptx'}")
