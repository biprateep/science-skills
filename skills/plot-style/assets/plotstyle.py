"""Publication plot style: journal geometry, rcParams, and figure helpers.

Drop this file (with ``paper.mplstyle``) next to your analysis script, or add
its directory to ``sys.path``, and start every plotting script with::

    from plotstyle import use_style, figsize, COLUMN_WIDTH, TEXT_WIDTH
    use_style()          # AASTeX geometry, house rcParams
    verify_style()       # optional: fail loudly if the serif font is missing

Depends only on numpy + matplotlib.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import matplotlib as mpl
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import numpy as np

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

# --------------------------------------------------------------------------
# Journal geometry
# --------------------------------------------------------------------------
# LaTeX points are 72.27 to the inch (NOT 72 — that is the PostScript point).
PT_PER_INCH = 72.27


@dataclass(frozen=True)
class Journal:
    """Column and text width of one journal class, in LaTeX points.

    Measure them in the manuscript itself: put ``\\showthe\\columnwidth`` and
    ``\\showthe\\textwidth`` in the body, compile, and read the two numbers
    off the log. Register the result with :func:`register_journal`.
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
        """``"column"`` or ``"text"`` width, in inches."""
        try:
            return {"column": self.column_width, "text": self.text_width}[kind]
        except KeyError:
            raise ValueError(f"width must be 'column' or 'text', got {kind!r}") from None


# Only measured classes go in here. Add a journal with register_journal(),
# never by guessing — a wrong width silently rescales every figure in the paper.
JOURNALS: dict[str, Journal] = {
    "aastex": Journal("aastex", column_pt=242.26653, text_pt=513.11743),  # AJ / ApJ
}
DEFAULT_JOURNAL = "aastex"
_active_journal: Journal = JOURNALS[DEFAULT_JOURNAL]


def register_journal(name: str, column_pt: float, text_pt: float) -> Journal:
    """Add (or replace) a journal's measured widths and return it."""
    JOURNALS[name] = Journal(name, float(column_pt), float(text_pt))
    return JOURNALS[name]


def journal(name: str | Journal | None = None) -> Journal:
    """The named journal, or the one activated by :func:`use_style`."""
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
# ``figsize=(COLUMN_WIDTH, 0.62 * COLUMN_WIDTH)`` form. For any other journal
# use figsize() / grid_figsize(), which follow the journal passed to use_style().
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

STYLE_FILE = Path(__file__).with_name("paper.mplstyle")

# Every piece of text in a figure — ticks, labels, titles, legends, colorbar
# labels, annotations — takes its face and size from these.
RC_PARAMS = {
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


def use_style(style_file=None, journal: str | Journal = DEFAULT_JOURNAL) -> Journal:
    """Apply the publication rcParams globally and select the journal geometry.

    Prefers the ``paper.mplstyle`` sheet shipped alongside this module and
    falls back to the equivalent ``RC_PARAMS`` dict if it is missing. The
    returned :class:`Journal` is what :func:`figsize` and
    :func:`grid_figsize` use from now on.
    """
    global _active_journal
    path = Path(style_file) if style_file is not None else STYLE_FILE
    if path.exists():
        plt.style.use(str(path))
    else:
        mpl.rcParams.update(RC_PARAMS)
    _active_journal = globals()["journal"](journal)
    return _active_journal


def verify_style(strict: bool = True) -> dict:
    """Check that the house rcParams are active and the serif face resolved.

    Returns ``{"font": <path matplotlib will use>, "problems": [...]}``.
    With ``strict=True`` (default) raises ``RuntimeError`` if any rcParam
    differs from :data:`RC_PARAMS` or if the font chain fell through to a
    DejaVu face — which is what happens on a machine without Nimbus Roman,
    and which matplotlib otherwise reports only as a debug-level log line.
    """
    expected = mpl.RcParams(RC_PARAMS)  # run values through the validators
    problems = [
        f"{key} is {mpl.rcParams[key]!r}, expected {expected[key]!r}"
        for key in RC_PARAMS
        if mpl.rcParams[key] != expected[key]
    ]
    font_path = Path(fm.findfont(fm.FontProperties(family=mpl.rcParams["font.serif"])))
    if "dejavu" in font_path.name.lower():
        problems.append(
            f"serif font resolved to {font_path.name}; install Nimbus Roman "
            "(package urw-base35 / gsfonts / fonts-urw-base35) and clear "
            "~/.cache/matplotlib"
        )
    if strict and problems:
        raise RuntimeError("plot style not in effect:\n  - " + "\n  - ".join(problems))
    return {"font": str(font_path), "problems": problems}


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


def _resolve_width(width, journal_=None) -> float:
    if isinstance(width, str):
        return journal(journal_).width(width)
    return float(width)


def _resolve_aspect(aspect) -> float:
    if isinstance(aspect, str):
        try:
            return ASPECTS[aspect]
        except KeyError:
            raise ValueError(f"aspect must be a float or one of {sorted(ASPECTS)}") from None
    return float(aspect)


def figsize(width="column", aspect="golden", journal=None):
    """``(w, h)`` in inches for a journal-width figure.

    Parameters
    ----------
    width : {"column", "text"} or float
        ``"column"`` for a single column, ``"text"`` for the full page
        width (of the journal selected by :func:`use_style`, unless
        ``journal`` overrides it), or an explicit width in inches.
    aspect : float or key of :data:`ASPECTS`
        Height as a fraction of the width. Default is the golden ratio.
    journal : str or Journal, optional
        Take the widths from this journal instead of the active one.
    """
    w = _resolve_width(width, journal)
    return (w, _resolve_aspect(aspect) * w)


def grid_figsize(nrows=1, ncols=1, width="text", panel_aspect="golden", journal=None):
    """``(w, h)`` for an ``nrows x ncols`` grid whose *panels* have ``panel_aspect``.

    The figure spans ``width``; each panel is nominally ``width / ncols``
    wide and ``panel_aspect`` times that tall, so the figure is
    ``nrows * panel_aspect * width / ncols`` tall. Two golden panels across
    the text width give ``0.31 * TEXT_WIDTH``; the manuscripts used 0.35–0.4
    for two-panel rows, i.e. ``panel_aspect`` of roughly 0.7–0.8.
    """
    w = _resolve_width(width, journal)
    return (w, nrows * _resolve_aspect(panel_aspect) * w / ncols)


# --------------------------------------------------------------------------
# Figure idioms
# --------------------------------------------------------------------------
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
    """Save as a tight 300 dpi PNG — the house output — creating parent dirs.

    A path with no suffix gets ``.png``. Pass an explicit ``.pdf`` only when
    a vector figure has been specifically requested. Returns the path.
    """
    path = Path(path)
    if not path.suffix:
        path = path.with_suffix(".png")
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight", dpi=dpi, **kwargs)
    return path
