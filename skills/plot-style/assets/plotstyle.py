"""Publication plot style: journal geometry, rcParams and figure helpers.

The module sets the house matplotlib style (use_style, verify_style,
set_palette), sizes figures to a journal's column or text width (figsize,
grid_figsize, register_journal), and draws the recurring figure idioms
(better_step, stacked_hist, running_median, one_to_one, side_colorbar). save
writes the house output, a tight 300 dpi PNG. It depends only on numpy and
matplotlib.

Copy it, with paper.mplstyle, next to the analysis script, or into the
project's own package and import it from there. Typical usage example:

  import plotstyle

  plotstyle.use_style()  # AASTeX geometry, house rcParams.
  plotstyle.verify_style()  # Optional: fails loudly if the serif is missing.
  fig, ax = plt.subplots(figsize=plotstyle.figsize("column"))
  ...
  plotstyle.save(fig, "./figs/name")
  plt.close(fig)
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
import dataclasses
import os
import pathlib
from typing import Any

import cycler
import matplotlib as mpl
from matplotlib import axes
from matplotlib import cm
from matplotlib import colorbar
from matplotlib import figure
from matplotlib import font_manager
import matplotlib.pyplot as plt
import numpy as np
import numpy.typing as npt

__all__ = [
    "PT_PER_INCH",
    "Journal",
    "JOURNALS",
    "DEFAULT_JOURNAL",
    "register_journal",
    "journal",
    "COLUMN_WIDTH",
    "TEXT_WIDTH",
    "SMALL_SIZE",
    "NORMAL_SIZE",
    "BIG_SIZE",
    "FONT_FAMILY",
    "SERIF_FALLBACKS",
    "RC_PARAMS",
    "DEFAULT_PALETTE",
    "set_palette",
    "GOLDEN",
    "ASPECTS",
    "use_style",
    "verify_style",
    "figsize",
    "grid_figsize",
    "better_step",
    "stacked_hist",
    "binned_quantiles",
    "running_median",
    "one_to_one",
    "side_colorbar",
    "save",
]

# A float array. Assigned plainly, since typing.TypeAlias needs Python 3.10
# and this module still runs on 3.9.
_FloatArray = npt.NDArray[np.float64]

# --------------------------------------------------------------------------
# Journal geometry
# --------------------------------------------------------------------------
# LaTeX points are 72.27 to the inch (NOT 72 — that is the PostScript point).
PT_PER_INCH = 72.27


@dataclasses.dataclass(frozen=True)
class Journal:
    r"""Column and text width of one journal class, in LaTeX points.

    Measure them in the manuscript itself: put `\showthe\columnwidth` and
    `\showthe\textwidth` in the body, compile, and read the two numbers off
    the log. Register the result with register_journal().

    Attributes:
      name: The name the journal is registered under, e.g. "aastex".
      column_pt: The `\columnwidth`, in LaTeX points.
      text_pt: The `\textwidth`, in LaTeX points.
    """

    name: str
    column_pt: float
    text_pt: float

    @property
    def column_width(self) -> float:
        """One column, in inches."""
        return self.column_pt / PT_PER_INCH

    @property
    def text_width(self) -> float:
        """Full page width, in inches."""
        return self.text_pt / PT_PER_INCH

    def width(self, kind: str) -> float:
        """Return the column or the text width, in inches.

        Args:
          kind: "column" or "text".
        """
        try:
            return {"column": self.column_width, "text": self.text_width}[kind]
        except KeyError:
            raise ValueError(
                f"width must be 'column' or 'text', got {kind!r}"
            ) from None


# Only measured classes go in here. Add a journal with register_journal(),
# never by guessing — a wrong width silently rescales every figure in the
# paper.
JOURNALS: dict[str, Journal] = {
    # AJ and ApJ.
    "aastex": Journal("aastex", column_pt=242.26653, text_pt=513.11743),
}
DEFAULT_JOURNAL = "aastex"
# Module state by design: use_style() selects the journal once, in the
# preamble, and figsize() and grid_figsize() follow it through journal().
_active_journal: Journal = JOURNALS[DEFAULT_JOURNAL]


def register_journal(name: str, column_pt: float, text_pt: float) -> Journal:
    r"""Add (or replace) a journal's measured widths and return it.

    Args:
      name: The name to register the journal under.
      column_pt: Its `\columnwidth` in LaTeX points, as `\showthe` prints it.
      text_pt: Its `\textwidth` in LaTeX points, as `\showthe` prints it.

    Returns:
      The registered journal.
    """
    JOURNALS[name] = Journal(name, float(column_pt), float(text_pt))
    return JOURNALS[name]


def journal(name: str | Journal | None = None) -> Journal:
    """Return the named journal, or the one activated by use_style().

    Args:
      name: The name of a registered journal; a Journal, returned as it is;
        or None for the journal of the last use_style() call.

    Returns:
      The journal.

    Raises:
      KeyError: If no journal of that name is registered.
    """
    return _find_journal(name)


def _find_journal(name: str | Journal | None) -> Journal:
    """Implements journal(), which use_style()'s journal parameter hides."""
    if name is None:
        return _active_journal
    if isinstance(name, Journal):
        return name
    try:
        return JOURNALS[name]
    except KeyError:
        raise KeyError(
            f"unknown journal {name!r}; known: {sorted(JOURNALS)}. "
            "Measure \\columnwidth / \\textwidth and call register_journal()."
        ) from None


# Module constants for the DEFAULT journal (AASTeX), for the inline
# `figsize=(COLUMN_WIDTH, 0.62 * COLUMN_WIDTH)` form. For any other journal
# use figsize() / grid_figsize(), which follow the journal passed to
# use_style().
COLUMN_WIDTH = JOURNALS[DEFAULT_JOURNAL].column_width  # 3.352 in
TEXT_WIDTH = JOURNALS[DEFAULT_JOURNAL].text_width  # 7.100 in

# --------------------------------------------------------------------------
# Type: sizes in points, matched to the 10 pt manuscript body
# --------------------------------------------------------------------------
SMALL_SIZE = 9  # tick labels; crowded legends
NORMAL_SIZE = 10  # body: axis labels, legends, axes titles, free text
BIG_SIZE = 12  # panel titles, suptitles

# The URW Times clone that matches the manuscript body text. "Nimbus Roman
# No9 L" is its classic name; newer urw-base35 packages ship the same face as
# plain "Nimbus Roman". Asking matplotlib for the exact classic name on such a
# machine silently falls back to DejaVu Sans, so the rcParams request the
# generic "serif" family and let this chain resolve it. Tail entries are
# Times-metric stand-ins for machines without any Nimbus at all.
FONT_FAMILY = "Nimbus Roman No9 L"
SERIF_FALLBACKS = [
    "Nimbus Roman No9 L",
    "Nimbus Roman",
    "Times New Roman",
    "Liberation Serif",
    "DejaVu Serif",
]

STYLE_FILE = pathlib.Path(__file__).with_name("paper.mplstyle")

# Every piece of text in a figure — ticks, labels, titles, legends, colorbar
# labels, annotations — takes its face and size from these. (Keys are typed
# Any: matplotlib 3.11 types rcParams keys as a Literal older versions lack.)
RC_PARAMS: dict[Any, Any] = {
    "font.family": "serif",
    "font.serif": SERIF_FALLBACKS,
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
    "legend.title_fontsize": NORMAL_SIZE,
    "legend.frameon": False,
    "figure.titlesize": BIG_SIZE,
    "figure.facecolor": "w",
    "figure.dpi": 300,
    "mathtext.fontset": "cm",
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "savefig.format": "png",
}

# Colour is deliberately NOT in RC_PARAMS. Unless the user names a palette,
# figures use exactly what matplotlib ships: the default property cycle
# (tab10, addressed as C0, C1, ...) for categorical series and the default
# colormap (viridis) for continuous data. These are taken from matplotlib's
# own defaults rather than retyped, so they track the installed version and
# override anything a personal matplotlibrc may have changed.
DEFAULT_PALETTE: dict[Any, Any] = {
    "axes.prop_cycle": mpl.rcParamsDefault["axes.prop_cycle"],
    "image.cmap": mpl.rcParamsDefault["image.cmap"],
}


def set_palette(
    colors: str | Iterable[str | Sequence[float]] | None = None,
    cmap: str | None = None,
    n: int | None = None,  # noqa: GS030 - a public keyword; a rename would break callers.
) -> tuple[list[Any], str]:
    """Install a user-stated palette once, in the preamble.

    Only call this when the user has explicitly asked for a palette. With
    neither colors nor cmap, it restores matplotlib's defaults.

    Args:
      colors: The property cycle, which series keep addressing as C0, C1,
        ...: a list of colours, or the name of a matplotlib colormap. A
        qualitative map ("Dark2", "Set2", "tab20") contributes its colours
        as they are; a continuous one is sampled at n evenly spaced points.
      cmap: The name of the default colormap for scatter(c=...), imshow,
        pcolormesh and friends.
      n: How many colours to take from the colormap named by colors: the
        first n of a qualitative map (all by default), or n samples of a
        continuous one (10 by default).

    Returns:
      A tuple (colors, cmap): the colours of the property cycle and the name
      of the default colormap now in effect.
    """
    if colors is None and cmap is None:
        mpl.rcParams.update(DEFAULT_PALETTE)
    if colors is not None:
        if isinstance(colors, str):
            colormap = mpl.colormaps[colors]  # KeyError for an unknown name.
            # Qualitative maps are ListedColormaps with a handful of entries
            # (tab20 is the largest at 20); viridis & co. are Listed too but
            # carry 256 samples, so they are sampled rather than copied.
            if hasattr(colormap, "colors") and len(colormap.colors) <= 20:
                colors = list(colormap.colors)[: n or len(colormap.colors)]
            else:
                colors = [
                    colormap(position)
                    for position in np.linspace(0, 1, n or 10)
                ]
        mpl.rcParams["axes.prop_cycle"] = cycler.cycler(color=list(colors))
    if cmap is not None:
        mpl.colormaps[cmap]  # Validate early.
        mpl.rcParams["image.cmap"] = cmap
    return (
        mpl.rcParams["axes.prop_cycle"].by_key()["color"],
        mpl.rcParams["image.cmap"],
    )


def use_style(
    style_file: str | os.PathLike[str] | None = None,
    journal: str | Journal = DEFAULT_JOURNAL,
    palette: str | Iterable[str | Sequence[float]] | None = None,
    cmap: str | None = None,
) -> Journal:
    """Apply the publication rcParams globally and select the journal geometry.

    Prefers the paper.mplstyle sheet shipped alongside this module and falls
    back to the equivalent RC_PARAMS dict if it is missing. Colour is reset
    to matplotlib's default palettes unless palette (property cycle) and/or
    cmap (default colormap) are given — pass them only when the user has
    explicitly stated a palette; see set_palette().

    Args:
      style_file: A style sheet to apply instead of paper.mplstyle.
      journal: The journal, or the name it is registered under, whose widths
        figsize() and grid_figsize() use from now on.
      palette: The property cycle, as set_palette() takes its colors.
      cmap: The name of the default colormap.

    Returns:
      The journal now in effect.
    """
    global _active_journal
    path = pathlib.Path(style_file) if style_file is not None else STYLE_FILE
    if path.exists():
        plt.style.use(str(path))
    else:
        mpl.rcParams.update(RC_PARAMS)
    set_palette(palette, cmap)
    _active_journal = _find_journal(journal)
    return _active_journal


def verify_style(strict: bool = True) -> dict[str, Any]:
    """Check that the house rcParams are active and the serif face resolved.

    The palette is reported, not enforced — a user-stated one is legitimate.

    Args:
      strict: Whether to raise when a problem is found.

    Returns:
      A dict with the keys "font" (the path of the font matplotlib will use),
      "palette" (the colours of the property cycle), "cmap" (the name of the
      default colormap), "default_palette" (whether both are matplotlib's
      defaults) and "problems" (what is wrong; empty when nothing is).

    Raises:
      RuntimeError: If strict and an rcParam differs from RC_PARAMS, or the
        font chain fell through to a DejaVu face — which is what happens on
        a machine without Nimbus Roman, and which matplotlib otherwise
        reports only as a debug-level log line.
    """
    expected = mpl.RcParams(RC_PARAMS)  # Runs values through the validators.
    problems = [
        f"{key} is {mpl.rcParams[key]!r}, expected {expected[key]!r}"
        for key in RC_PARAMS
        if mpl.rcParams[key] != expected[key]
    ]
    font_path = pathlib.Path(
        font_manager.findfont(
            font_manager.FontProperties(family=mpl.rcParams["font.serif"])
        )
    )
    if "dejavu" in font_path.name.lower():
        problems.append(
            f"serif font resolved to {font_path.name}; install Nimbus Roman "
            "(package urw-base35 / gsfonts / fonts-urw-base35) and clear "
            "~/.cache/matplotlib"
        )
    if strict and problems:
        raise RuntimeError(
            "plot style not in effect:\n  - " + "\n  - ".join(problems)
        )
    colors = mpl.rcParams["axes.prop_cycle"].by_key().get("color", [])
    default_colors = DEFAULT_PALETTE["axes.prop_cycle"].by_key()["color"]
    is_default = (
        colors == default_colors
        and mpl.rcParams["image.cmap"] == DEFAULT_PALETTE["image.cmap"]
    )
    return {
        "font": str(font_path),
        "palette": colors,
        "cmap": mpl.rcParams["image.cmap"],
        "default_palette": is_default,
        "problems": problems,
    }


# --------------------------------------------------------------------------
# Figure geometry helpers
# --------------------------------------------------------------------------
GOLDEN = 2 / (1 + 5**0.5)  # 0.618: height / width of a golden rectangle

# Named height:width ratios. The bracket is what the source manuscripts used:
# single-column panels 0.56–0.75 (0.7 most often), full-width two-panel rows
# 0.35–0.4, full-width single panels 0.5–0.65, comparisons square.
ASPECTS = {
    "golden": GOLDEN,  # default single panel
    "wide": 0.5625,  # 16:9 — histograms, trends with little vertical range
    "tall": 0.75,  # 4:3 — scatter with a running median or a legend inside
    "square": 1.0,  # one-to-one comparisons, sky maps, anything aspect="equal"
}


def _resolve_width(
    width: str | float, journal_: str | Journal | None = None
) -> float:
    """Return a width in inches: a journal's "column" or "text", or a number."""
    if isinstance(width, str):
        return journal(journal_).width(width)
    return float(width)


def _resolve_aspect(aspect: str | float) -> float:
    """Return a height:width ratio, looking a name up in ASPECTS."""
    if isinstance(aspect, str):
        try:
            return ASPECTS[aspect]
        except KeyError:
            raise ValueError(
                f"aspect must be a float or one of {sorted(ASPECTS)}"
            ) from None
    return float(aspect)


def figsize(
    width: str | float = "column",
    aspect: str | float = "golden",
    journal: str | Journal | None = None,
) -> tuple[float, float]:
    """Return (width, height) in inches for a journal-width figure.

    Args:
      width: "column" for a single column, "text" for the full page width
        (of the journal selected by use_style(), unless journal overrides
        it), or an explicit width in inches.
      aspect: Height as a fraction of the width, or a key of ASPECTS.
        Default is the golden ratio.
      journal: Take the widths from this journal instead of the active one.

    Returns:
      A tuple (width, height), in inches.
    """
    width_inches = _resolve_width(width, journal)
    return (width_inches, _resolve_aspect(aspect) * width_inches)


def grid_figsize(
    nrows: int = 1,
    ncols: int = 1,
    width: str | float = "text",
    panel_aspect: str | float = "golden",
    journal: str | Journal | None = None,
) -> tuple[float, float]:
    """Return (width, height) for an nrows x ncols grid of panel_aspect panels.

    The figure spans width; each panel is nominally width / ncols wide and
    panel_aspect times that tall, so the figure is
    nrows * panel_aspect * width / ncols tall. Two golden panels across the
    text width give 0.31 * TEXT_WIDTH; the manuscripts used 0.35–0.4 for
    two-panel rows, i.e. a panel_aspect of roughly 0.7–0.8.

    Args:
      nrows: The number of rows of panels.
      ncols: The number of columns of panels.
      width: The figure width, as figsize() takes it.
      panel_aspect: The height of one panel as a fraction of its width, or a
        key of ASPECTS.
      journal: Take the widths from this journal instead of the active one.

    Returns:
      A tuple (width, height), in inches.
    """
    width_inches = _resolve_width(width, journal)
    return (
        width_inches,
        nrows * _resolve_aspect(panel_aspect) * width_inches / ncols,
    )


# --------------------------------------------------------------------------
# Figure idioms
# --------------------------------------------------------------------------
def _interleave(first: Iterable[Any], second: Iterable[Any]) -> list[Any]:
    """Return [first[0], second[0], first[1], second[1], ...]."""
    values: list[Any] = []
    for pair in zip(first, second):
        values.extend(pair)
    return values


def better_step(
    bin_edges: Sequence[float] | _FloatArray,
    y: Iterable[float],  # noqa: GS030 - matplotlib's step() names it y; a rename would break callers.
    yerr: tuple[Iterable[float], Iterable[float]] | None = None,
    ax: axes.Axes | None = None,
    **kwargs: Any,
) -> axes.Axes:
    """A 'better' version of matplotlib's step function.

    Given a set of bin edges and bin heights, this plots the thing that I
    wish matplotlib's `step` command plotted.

    Args:
      bin_edges: The bin edges. This should be one element longer than the
        bin heights y.
      y: The bin heights.
      yerr: Asymmetric error on y, as a (lower, upper) pair of bin values,
        drawn as a shaded band.
      ax: The axes where this should be plotted; the current axes if None.
      **kwargs: Passed directly to matplotlib's `plot` command.

    Returns:
      The axes plotted on.
    """
    new_x = _interleave(bin_edges[:-1], bin_edges[1:])
    new_y = _interleave(y, y)
    if ax is None:
        ax = plt.gca()
    lines = ax.plot(new_x, new_y, **kwargs)
    if yerr is not None:
        lower = np.array(_interleave(yerr[0], yerr[0]))
        upper = np.array(_interleave(yerr[1], yerr[1]))
        ax.fill_between(
            new_x, upper, lower, alpha=0.1, color=lines[0].get_color()
        )
    return ax


def stacked_hist(
    ax: axes.Axes,
    datasets: Iterable[npt.ArrayLike],
    labels: Sequence[str] | None = None,
    bins: int | str | Sequence[float] | _FloatArray = 20,
    colors: Sequence[str] | None = None,
    alpha: float = 0.5,
    rwidth: float = 0.8,
    **kwargs: Any,
) -> tuple[Any, _FloatArray, Any]:
    """Stacked histogram in house style: white step underlay + gapped fills.

    Two passes over the same bin edges — a histtype="step" pass in white that
    traces the full-width stacked envelope, then the semi-transparent
    rwidth-narrowed bars on top. The gap plus the underlay keeps the
    individual bars legible where translucent stacks would otherwise merge.

    Args:
      ax: The axes to draw on.
      datasets: The values of each stacked class.
      labels: One legend label per dataset.
      bins: The number of bins (or a NumPy binning rule such as "auto"),
        spread over all datasets together, or the bin edges.
      colors: One colour per dataset; C0, C1, ... by default.
      alpha: The opacity of the filled bars.
      rwidth: The width of each filled bar, as a fraction of its bin.
      **kwargs: Passed to both ax.hist() calls.

    Returns:
      The tuple (counts, edges, patches) that ax.hist() returns for the
      filled pass.
    """
    datasets = list(datasets)
    n_datasets = len(datasets)
    if colors is None:
        colors = [f"C{i}" for i in range(n_datasets)]
    if np.isscalar(bins):
        pooled = np.concatenate(
            [np.asarray(dataset).ravel() for dataset in datasets]
        )
        bins = np.histogram_bin_edges(pooled, bins=bins)

    # matplotlib's stub types bins as a Sequence, which an ndarray of edges is
    # not, though hist() accepts one.
    ax.hist(
        datasets,
        bins=bins,  # type: ignore[arg-type]
        stacked=True,
        histtype="step",
        color=["white"] * n_datasets,
        **kwargs,
    )
    return ax.hist(
        datasets,
        bins=bins,  # type: ignore[arg-type]
        stacked=True,
        color=colors,
        alpha=alpha,
        rwidth=rwidth,
        label=labels,
        **kwargs,
    )


def binned_quantiles(
    x: npt.ArrayLike,  # noqa: GS030 - matplotlib's x, y and np.percentile's q; a rename would break callers.
    y: npt.ArrayLike,
    nbins: int = 10,
    equal_count: bool = True,
    bins: npt.ArrayLike | None = None,
    q: Sequence[float] = (25, 50, 75),
) -> tuple[_FloatArray, _FloatArray]:
    """Quantiles of y in bins of x.

    Points where x or y is not finite are left out.

    Args:
      x: The coordinate that is binned, shape (n,).
      y: The values whose quantiles are taken, shape (n,).
      nbins: The number of bins, unless bins gives the edges.
      equal_count: Whether to put an equal number of points in each bin (the
        pd.qcut behaviour), so the scatter band is equally well determined
        everywhere; False gives equal-width bins.
      bins: Explicit bin edges, overriding nbins and equal_count.
      q: The percentiles to compute, each between 0 and 100.

    Returns:
      A tuple (edges, values): the bin edges, and the percentiles of each
      bin with shape (len(q), len(edges) - 1). Empty bins come back as NaN.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    good = np.isfinite(x) & np.isfinite(y)
    x, y = x[good], y[good]

    if bins is not None:
        edges = np.asarray(bins, dtype=float)
    elif equal_count:
        edges = np.quantile(x, np.linspace(0.0, 1.0, nbins + 1))
    else:
        edges = np.linspace(x.min(), x.max(), nbins + 1)
    edges = np.unique(edges)

    bin_index = np.clip(np.digitize(x, edges) - 1, 0, len(edges) - 2)
    values = np.full((len(q), len(edges) - 1), np.nan)
    for i in range(len(edges) - 1):
        in_bin = bin_index == i
        if in_bin.any():
            values[:, i] = np.percentile(y[in_bin], q)
    return edges, values


def running_median(
    ax: axes.Axes,
    x: npt.ArrayLike,  # noqa: GS030 - matplotlib's x, y; a rename would break callers.
    y: npt.ArrayLike,
    nbins: int = 10,
    equal_count: bool = True,
    bins: npt.ArrayLike | None = None,
    color: str = "C1",
    global_median: bool = True,
    **kwargs: Any,
) -> tuple[_FloatArray, _FloatArray, _FloatArray, _FloatArray]:
    """Overlay a binned median with a 25–75 percentile band.

    Draws the median as a better_step() staircase with a shaded IQR, and (by
    default) the global median as a dashed line in the same colour.

    Args:
      ax: The axes to draw on.
      x: The coordinate that is binned, shape (n,).
      y: The values whose median is taken, shape (n,).
      nbins: The number of bins, unless bins gives the edges.
      equal_count: Whether each bin holds an equal number of points, as in
        binned_quantiles().
      bins: Explicit bin edges, overriding nbins and equal_count.
      color: The colour of the staircase, the band and the global median.
      global_median: Whether to draw the median of all of y as well.
      **kwargs: Passed to better_step().

    Returns:
      A tuple (edges, p25, median, p75): the bin edges and, per bin, the
      25th, 50th and 75th percentiles of y.
    """
    edges, (p25, median, p75) = binned_quantiles(
        x, y, nbins=nbins, equal_count=equal_count, bins=bins, q=(25, 50, 75)
    )
    better_step(edges, median, (p25, p75), ax=ax, c=color, **kwargs)
    if global_median:
        # y is numeric; its ArrayLike annotation also admits strings, which
        # np.nanmedian's stub rejects.
        ax.axhline(np.nanmedian(y), color=color, ls="--", lw=1)  # type: ignore[arg-type]
    return edges, p25, median, p75


def one_to_one(
    ax: axes.Axes,
    lo: float,
    hi: float,
    color: str = "k",
    ls: str = "--",
    equal: bool = True,
    **kwargs: Any,
) -> axes.Axes:
    """Dashed identity line on matched, optionally equal-aspect, axes.

    Args:
      ax: The axes to draw on.
      lo: The lower limit of both axes.
      hi: The upper limit of both axes.
      color: The colour of the line.
      ls: The line style.
      equal: Whether to give the axes an equal aspect ratio.
      **kwargs: Passed to ax.plot().

    Returns:
      The axes drawn on.
    """
    diagonal = np.linspace(lo, hi, 100)
    ax.plot(diagonal, diagonal, color=color, ls=ls, **kwargs)
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    if equal:
        ax.set_aspect("equal")
    return ax


def side_colorbar(
    fig: figure.Figure,
    mappable: cm.ScalarMappable,
    label: str | None = None,
    rect: tuple[float, float, float, float] = (0.95, 0.15, 0.02, 0.7),
    labelpad: float = 15,
) -> colorbar.Colorbar:
    """Slim colorbar on its own axes to the right of the whole figure.

    Args:
      fig: The figure.
      mappable: What the colorbar shows, e.g. the scatter of the last panel;
        panels that share it must share vmin and vmax.
      label: The colorbar's label, rotated -90 deg so it reads top to
        bottom.
      rect: The colorbar's axes as [left, bottom, width, height] in figure
        coordinates; the default sits just outside a standard axes and is
        shared by every panel.
      labelpad: The space between the colorbar and its label, in points.

    Returns:
      The colorbar.
    """
    cax = fig.add_axes(rect)
    cbar = fig.colorbar(mappable, cax=cax)
    if label is not None:
        cbar.set_label(label, rotation=-90, labelpad=labelpad)
    return cbar


def save(
    fig: figure.Figure,
    path: str | os.PathLike[str],
    dpi: float = 300,
    **kwargs: Any,
) -> pathlib.Path:
    """Save as a tight 300 dpi PNG — the house output — creating parent dirs.

    Args:
      fig: The figure to save.
      path: Where to save it. A path with no suffix gets .png; pass an
        explicit .pdf only when a vector figure has been specifically
        requested.
      dpi: The resolution, in dots per inch.
      **kwargs: Passed to fig.savefig().

    Returns:
      The path written.
    """
    path = pathlib.Path(path)
    if not path.suffix:
        path = path.with_suffix(".png")
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight", dpi=dpi, **kwargs)
    return path
