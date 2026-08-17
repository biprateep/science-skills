"""Publication plot style: journal geometry, rcParams, and figure helpers.

Drop this file next to your analysis script (or add its directory to
``sys.path``) and start every plotting script with::

    from plotstyle import use_style, figsize, COLUMN_WIDTH, TEXT_WIDTH
    use_style()

Depends only on numpy + matplotlib.
"""

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np

__all__ = [
    "PT_PER_INCH",
    "COLUMN_WIDTH",
    "TEXT_WIDTH",
    "SMALL_SIZE",
    "NORMAL_SIZE",
    "BIG_SIZE",
    "FONT_FAMILY",
    "RC_PARAMS",
    "use_style",
    "figsize",
    "better_step",
    "stacked_hist",
    "binned_quantiles",
    "running_median",
    "one_to_one",
    "side_colorbar",
    "save",
]

# --------------------------------------------------------------------------
# Journal geometry — AASTeX (AJ / ApJ)
# --------------------------------------------------------------------------
# Measured in the manuscript with \showthe\columnwidth / \showthe\textwidth.
# LaTeX points are 72.27 to the inch (NOT 72 — that is the PostScript point).
PT_PER_INCH = 72.27
COLUMN_WIDTH = 242.26653 / PT_PER_INCH  # 3.352 in — one column
TEXT_WIDTH = 513.11743 / PT_PER_INCH  # 7.100 in — full page width

# --------------------------------------------------------------------------
# Type sizes, in points, matched to the 10 pt manuscript body
# --------------------------------------------------------------------------
SMALL_SIZE = 9  # tick labels
NORMAL_SIZE = 10  # body: axis labels, legends, axes titles
BIG_SIZE = 12  # panel titles

# The URW Times clone that matches AASTeX body text. The first name is the
# classic URW name; "Nimbus Roman" is the same face under the newer
# urw-base35 naming. The tail entries are Times-metric fallbacks.
FONT_FAMILY = [
    "Nimbus Roman No9 L",
    "Nimbus Roman",
    "Times New Roman",
    "Liberation Serif",
    "DejaVu Serif",
]

STYLE_FILE = Path(__file__).with_name("paper.mplstyle")

RC_PARAMS = {
    "font.family": "serif",
    "font.serif": FONT_FAMILY,
    "font.size": NORMAL_SIZE,
    "axes.titlesize": NORMAL_SIZE,
    "axes.labelsize": NORMAL_SIZE,
    "legend.fontsize": NORMAL_SIZE,
    "legend.frameon": False,
    "xtick.labelsize": SMALL_SIZE,
    "ytick.labelsize": SMALL_SIZE,
    "xtick.top": True,
    "ytick.right": True,
    "xtick.direction": "in",
    "ytick.direction": "in",
    "mathtext.fontset": "cm",
    "figure.facecolor": "w",
    "figure.dpi": 300,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
}


def use_style(style_file=None):
    """Apply the publication rcParams globally.

    Prefers the ``paper.mplstyle`` sheet shipped alongside this module and
    falls back to the equivalent ``RC_PARAMS`` dict if it is missing.
    """
    path = Path(style_file) if style_file is not None else STYLE_FILE
    if path.exists():
        plt.style.use(str(path))
    else:
        mpl.rcParams.update(RC_PARAMS)
    return mpl.rcParams


def figsize(width="column", aspect=0.5625):
    """Return ``(w, h)`` in inches for a journal-width figure.

    Parameters
    ----------
    width : {"column", "text"} or float
        ``"column"`` for a single column, ``"text"`` for the full page
        width, or an explicit width in inches.
    aspect : float
        Height as a fraction of the width. ``0.5625`` is 16:9; ``1.0`` is
        square (use it with :func:`one_to_one`).
    """
    widths = {"column": COLUMN_WIDTH, "text": TEXT_WIDTH}
    if isinstance(width, str):
        if width not in widths:
            raise ValueError(f"width must be one of {sorted(widths)} or a float")
        w = widths[width]
    else:
        w = float(width)
    return (w, aspect * w)


def better_step(bin_edges, y, yerr=None, ax=None, **kwargs):
    """A 'better' version of matplotlib's step function.

    Given a set of bin edges and bin heights, this plots the thing that I
    wish matplotlib's ``step`` command plotted. All extra arguments are
    passed directly to matplotlib's ``plot`` command.

    Args:
        bin_edges: The bin edges. This should be one element longer than
            the bin heights array ``y``.
        y: The bin heights.
        yerr: asymmetric error on y, as a ``(lower, upper)`` pair.
        ax (Optional): The axis where this should be plotted.
    """
    new_x = [a for row in zip(bin_edges[:-1], bin_edges[1:]) for a in row]
    new_y = [a for row in zip(y, y) for a in row]
    if ax is None:
        ax = plt.gca()
    p = ax.plot(new_x, new_y, **kwargs)
    if yerr is not None:
        new_yerr_lo = np.array([a for row in zip(yerr[0], yerr[0]) for a in row])
        new_yerr_up = np.array([a for row in zip(yerr[1], yerr[1]) for a in row])
        ax.fill_between(
            new_x, new_yerr_up, new_yerr_lo, alpha=0.1, color=p[0].get_color()
        )
    return ax


def stacked_hist(
    ax, datasets, labels=None, bins=20, colors=None, alpha=0.5, rwidth=0.8, **kwargs
):
    """Stacked histogram in house style: white step underlay + gapped fills.

    Two passes over the same bin edges — a ``histtype="step"`` pass in white
    that traces the full-width stacked envelope, then the semi-transparent
    ``rwidth``-narrowed bars on top. The gap plus the underlay keeps the
    individual bars legible where translucent stacks would otherwise merge.

    Returns the ``(counts, edges, patches)`` tuple of the filled pass.
    """
    datasets = list(datasets)
    n = len(datasets)
    if colors is None:
        colors = [f"C{i}" for i in range(n)]
    if np.isscalar(bins):
        pooled = np.concatenate([np.asarray(d).ravel() for d in datasets])
        bins = np.histogram_bin_edges(pooled, bins=bins)

    ax.hist(
        datasets,
        bins=bins,
        stacked=True,
        histtype="step",
        color=["white"] * n,
        **kwargs,
    )
    return ax.hist(
        datasets,
        bins=bins,
        stacked=True,
        color=colors,
        alpha=alpha,
        rwidth=rwidth,
        label=labels,
        **kwargs,
    )


def binned_quantiles(x, y, nbins=10, equal_count=True, bins=None, q=(25, 50, 75)):
    """Quantiles of ``y`` in bins of ``x``.

    ``equal_count=True`` puts an equal number of points in each bin (the
    ``pd.qcut`` behaviour) so the scatter band is equally well determined
    everywhere; set it False for equal-width bins.

    Returns ``(edges, values)`` where ``values`` has shape
    ``(len(q), len(edges) - 1)``. Empty bins come back as NaN.
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

    idx = np.clip(np.digitize(x, edges) - 1, 0, len(edges) - 2)
    values = np.full((len(q), len(edges) - 1), np.nan)
    for b in range(len(edges) - 1):
        sel = idx == b
        if sel.any():
            values[:, b] = np.percentile(y[sel], q)
    return edges, values


def running_median(
    ax, x, y, nbins=10, equal_count=True, bins=None, color="C1", global_median=True, **kwargs
):
    """Overlay a binned median with a 25–75 percentile band.

    Draws the median as a :func:`better_step` staircase with a shaded IQR,
    and (by default) the global median as a dashed line in the same colour.
    Returns ``(edges, p25, median, p75)``.
    """
    edges, (p25, med, p75) = binned_quantiles(
        x, y, nbins=nbins, equal_count=equal_count, bins=bins, q=(25, 50, 75)
    )
    better_step(edges, med, (p25, p75), ax=ax, c=color, **kwargs)
    if global_median:
        ax.axhline(np.nanmedian(y), color=color, ls="--", lw=1)
    return edges, p25, med, p75


def one_to_one(ax, lo, hi, color="k", ls="--", equal=True, **kwargs):
    """Dashed identity line on matched, optionally equal-aspect, axes."""
    x = np.linspace(lo, hi, 100)
    ax.plot(x, x, color=color, ls=ls, **kwargs)
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    if equal:
        ax.set_aspect("equal")
    return ax


def side_colorbar(fig, mappable, label=None, rect=(0.95, 0.15, 0.02, 0.7), labelpad=15):
    """Slim colorbar on its own axes to the right of the whole figure.

    ``rect`` is ``[left, bottom, width, height]`` in figure coordinates; the
    default sits just outside a standard axes and is shared by every panel.
    The label is rotated -90 deg so it reads top-to-bottom.
    """
    cax = fig.add_axes(rect)
    cbar = fig.colorbar(mappable, cax=cax)
    if label is not None:
        cbar.set_label(label, rotation=-90, labelpad=labelpad)
    return cbar


def save(fig, path, dpi=300, **kwargs):
    """Save to a vector PDF with a tight bounding box, creating parent dirs."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight", dpi=dpi, **kwargs)
    return path
