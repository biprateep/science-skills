#!/usr/bin/env python3
"""Static compliance check for the publication plot style.

    python check_plot_style.py script.py [more.py ...] [--strict]

Parses each script's AST and reports, per line:

  ERROR  no-style        no use_style() / plt.style.use() / rcParams.update()
  ERROR  figsize         figsize not derived from COLUMN_WIDTH / TEXT_WIDTH /
                         figsize()
  ERROR  savefig-format  saves a .pdf / .svg / .eps (house output is PNG)
  ERROR  savefig-args    savefig without bbox_inches="tight" and dpi=300, and
                         no rc coverage (savefig.bbox / savefig.dpi) from the
                         style sheet
  ERROR  legend-frame    legend(frameon=True), or legend() without
                         frameon=False when only the inline rcParams block
                         (which lacks legend.frameon) is used
  WARN   color           hand-picked hex / named colour on a data series (use
                         C0, C1, ...)
  WARN   palette         third-party palette (seaborn, cmocean, colorcet,
                         palettable, cmasher) — only when the user explicitly
                         asked for one
  WARN   fontsize        numeric fontsize literal (use SMALL_SIZE /
                         NORMAL_SIZE / BIG_SIZE)
  WARN   pyplot-state    plt.title() / plt.xlabel() / ... on the implicit
                         current axes
  WARN   tight-layout    plt.tight_layout() (breaks figure-level colorbars;
                         bbox is tight anyway)

Exit status is 1 if any ERROR was found (or any WARN with --strict), else 0.
Only the standard library is used, so it runs anywhere Python 3.9+ does.
"""

from __future__ import annotations

import ast
from collections.abc import Sequence
import pathlib
import re
import sys

WIDTH_TOKENS = (
    "COLUMN_WIDTH",
    "TEXT_WIDTH",
    ".column_width",
    ".text_width",
    ".width(",
)
FIGSIZE_FUNCS = {"figsize", "grid_figsize"}
VECTOR_EXT = re.compile(r"\.(pdf|svg|eps|ps)\b", re.IGNORECASE)
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{3,8}$")
ALLOWED_COLORS = {"k", "black", "w", "white", "none", "gray", "grey"}
CYCLE_COLOR = re.compile(r"^C\d+$")
COLOR_KWARGS = {"color", "c", "facecolor", "edgecolor", "colors", "fc", "ec"}
SERIES_FUNCS = {
    "plot",
    "scatter",
    "hist",
    "bar",
    "barh",
    "fill_between",
    "fill_betweenx",
    "step",
    "errorbar",
    "contour",
    "contourf",
    "hexbin",
    "stairs",
}
PYPLOT_STATE = {
    "title",
    "xlabel",
    "ylabel",
    "legend",
    "xlim",
    "ylim",
    "xticks",
    "yticks",
}
PALETTE_MODULES = {"seaborn", "cmocean", "colorcet", "palettable", "cmasher"}
PALETTE_CALLS = {
    "set_palette",
    "color_palette",
    "set_theme",
    "husl_palette",
    "cubehelix_palette",
    "light_palette",
    "dark_palette",
    "diverging_palette",
    "blend_palette",
}
_PALETTE_WARNING = "third-party palette, only when the user asked for one"

# One finding: (line, "ERROR" or "WARN", code, message).
_Finding = tuple[int, str, str, str]


def _name(node: ast.AST) -> str:
    """Dotted name of a call target, e.g. 'plt.savefig'.

    A subscripted base is dropped: 'ax[0].legend' gives 'legend'.
    """
    if isinstance(node, ast.Attribute):
        base = _name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _kw(call: ast.Call, key: str) -> ast.expr | None:
    """The value of a call's keyword argument, or None if it is not given."""
    for keyword in call.keywords:
        if keyword.arg == key:
            return keyword.value
    return None


def _const(node: ast.AST | None) -> object:
    """The value of a constant node, or None for anything else."""
    return node.value if isinstance(node, ast.Constant) else None


def _literal_str(node: ast.AST) -> str | None:
    """String content of a str constant or an f-string (with holes blanked)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            value.value
            for value in node.values
            if isinstance(value, ast.Constant) and isinstance(value.value, str)
        )
    return None


class Checker(ast.NodeVisitor):
    """Collects the plot-style findings of one script as its AST is visited.

    Attributes:
      path: The script.
      src: Its source.
      findings: The findings so far, as (line, level, code, message).
      style_calls: Which ways of applying the style the script uses:
        "use_style", "style.use" or "rcParams.update".
    """

    def __init__(self, path: pathlib.Path, src: str) -> None:
        """Initializes the checker for one script.

        Args:
          path: The script.
          src: Its source.
        """
        self.path = path
        self.src = src
        self.findings: list[_Finding] = []
        self.style_calls: set[str] = set()

    # -- reporting -----------------------------------------------------------
    def err(self, node: ast.expr | ast.stmt, code: str, msg: str) -> None:
        """Records an ERROR at the line of node."""
        self.findings.append((node.lineno, "ERROR", code, msg))

    def warn(self, node: ast.expr | ast.stmt, code: str, msg: str) -> None:
        """Records a WARN at the line of node."""
        self.findings.append((node.lineno, "WARN", code, msg))

    # -- visitors ------------------------------------------------------------
    def visit_Import(self, node: ast.Import) -> None:
        """Warns on imports of third-party palette packages."""
        for alias in node.names:
            root = alias.name.split(".")[0]
            if root in PALETTE_MODULES:
                self.warn(
                    node, "palette", f"imports {alias.name}: {_PALETTE_WARNING}"
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Warns on imports from third-party palette packages."""
        root = (node.module or "").split(".")[0]
        if root in PALETTE_MODULES:
            self.warn(
                node,
                "palette",
                f"imports from {node.module}: {_PALETTE_WARNING}",
            )
        self.generic_visit(node)

    def visit_Call(self, call: ast.Call) -> None:
        """Runs the checks that look at one call."""
        name = _name(call.func)
        tail = name.rsplit(".", 1)[-1]
        self._check_palette_call(call, name, tail)
        self._note_style_call(name, tail)

        figsize_value = _kw(call, "figsize")
        if figsize_value is not None:
            self.check_figsize(figsize_value)

        if tail == "savefig":
            self.check_savefig(call)
        if tail == "legend":
            self.check_legend(call)
        if tail in SERIES_FUNCS:
            self.check_colors(call)
        self._check_layout_calls(call, name, tail)
        self._check_fontsize(call)
        self.generic_visit(call)

    def _check_palette_call(self, call: ast.Call, name: str, tail: str) -> None:
        """Warns on seaborn-style palette setters."""
        # plotstyle's own set_palette is the sanctioned route for a
        # user-stated palette and is not flagged.
        is_own_palette = tail == "set_palette" and name in (
            "set_palette",
            "plotstyle.set_palette",
            "ps.set_palette",
        )
        if tail in PALETTE_CALLS and not is_own_palette:
            self.warn(call, "palette", f"{name}(): {_PALETTE_WARNING}")

    def _note_style_call(self, name: str, tail: str) -> None:
        """Records a call that applies the style, for the later checks."""
        if tail == "use_style":
            self.style_calls.add("use_style")
        elif name.endswith("style.use"):
            self.style_calls.add("style.use")
        elif name.endswith("rcParams.update"):
            self.style_calls.add("rcParams.update")

    def _check_layout_calls(self, call: ast.Call, name: str, tail: str) -> None:
        """Warns on tight_layout() and on the pyplot state machine."""
        if tail == "tight_layout":
            self.warn(
                call,
                "tight-layout",
                "tight_layout() ignores fig.add_axes() colorbars;"
                " savefig(bbox_inches='tight') already crops",
            )
        if name.startswith("plt.") and tail in PYPLOT_STATE:
            fix = f"ax.{tail}()" if tail == "legend" else f"ax.set_{tail}()"
            self.warn(
                call,
                "pyplot-state",
                f"plt.{tail}() acts on the implicit current axes; use {fix}",
            )

    def _check_fontsize(self, call: ast.Call) -> None:
        """Warns on a numeric fontsize literal."""
        fontsize_value = _const(_kw(call, "fontsize"))
        if isinstance(fontsize_value, (int, float)):
            self.warn(
                call,
                "fontsize",
                f"fontsize={fontsize_value}: use SMALL_SIZE / NORMAL_SIZE /"
                " BIG_SIZE",
            )

    # -- individual checks ---------------------------------------------------
    def check_figsize(self, node: ast.expr) -> None:
        """Errors unless a figsize derives from the journal widths."""
        text = ast.unparse(node)
        if isinstance(node, ast.Call):
            if _name(node.func).rsplit(".", 1)[-1] in FIGSIZE_FUNCS:
                return
        if isinstance(node, (ast.Tuple, ast.List)) and node.elts:
            width = ast.unparse(node.elts[0])
            if any(token in width for token in WIDTH_TOKENS):
                return
            if isinstance(_const(node.elts[0]), (int, float)):
                self.err(
                    node,
                    "figsize",
                    f"figsize={text}: invented width; use COLUMN_WIDTH /"
                    " TEXT_WIDTH",
                )
                return
        if any(token in text for token in WIDTH_TOKENS):
            return
        self.err(
            node,
            "figsize",
            f"figsize={text}: width must derive from COLUMN_WIDTH / TEXT_WIDTH"
            " or figsize()",
        )

    def check_savefig(self, call: ast.Call) -> None:
        """Errors on vector output and on savefig without house arguments."""
        target = call.args[0] if call.args else _kw(call, "fname")
        literal = _literal_str(target) if target is not None else None
        if literal is not None and VECTOR_EXT.search(literal):
            self.err(
                call,
                "savefig-format",
                f"saves {literal!r}: house output is a 300 dpi PNG",
            )

        has_bbox = _const(_kw(call, "bbox_inches")) == "tight"
        has_dpi = _const(_kw(call, "dpi")) == 300
        # savefig.bbox and savefig.dpi come from the style sheet when it is in
        # effect.
        rc_covered = bool(self.style_calls & {"use_style", "style.use"})
        if not (has_bbox and has_dpi) and not rc_covered:
            missing = [
                argument
                for argument, present in (
                    ("bbox_inches='tight'", has_bbox),
                    ("dpi=300", has_dpi),
                )
                if not present
            ]
            self.err(
                call, "savefig-args", "savefig missing " + ", ".join(missing)
            )

    def check_legend(self, call: ast.Call) -> None:
        """Errors on boxed legends."""
        frameon = _kw(call, "frameon")
        if frameon is not None and _const(frameon) is True:
            self.err(
                call,
                "legend-frame",
                "legend(frameon=True): legends are always frameless",
            )
            return
        inline_only = self.style_calls and not (
            self.style_calls & {"use_style", "style.use"}
        )
        if frameon is None and inline_only:
            self.err(
                call,
                "legend-frame",
                "legend() without frameon=False: the inline rcParams block"
                " does not set legend.frameon",
            )

    def check_colors(self, call: ast.Call) -> None:
        """Warns on hand-picked colours given to a data series."""
        for keyword in call.keywords:
            if keyword.arg not in COLOR_KWARGS:
                continue
            if isinstance(keyword.value, (ast.Tuple, ast.List)):
                values = keyword.value.elts
            else:
                values = [keyword.value]
            for value in values:
                color = _const(value)
                if not isinstance(color, str):
                    continue
                if color in ALLOWED_COLORS or CYCLE_COLOR.match(color):
                    continue
                if (
                    HEX_COLOR.match(color)
                    or color.isalpha()
                    or color.startswith(("tab:", "xkcd:"))
                ):
                    self.warn(
                        call,
                        "color",
                        f"{keyword.arg}={color!r}: hand-picked colour; series"
                        " take C0, C1, ... from the palette in effect"
                        " (set_palette for a stated one)",
                    )

    # -- module-level ---------------------------------------------------------
    def finish(self) -> list[_Finding]:
        """Adds the whole-script checks and returns the sorted findings."""
        if not self.style_calls:
            self.findings.insert(
                0,
                (
                    1,
                    "ERROR",
                    "no-style",
                    "no use_style() / plt.style.use() / rcParams.update()"
                    " before plotting",
                ),
            )
        self.findings.sort()
        return self.findings


def check_file(path: pathlib.Path) -> list[_Finding]:
    """Checks one script.

    Args:
      path: The script.

    Returns:
      Its findings, sorted, as (line, level, code, message).

    Raises:
      OSError: If the file cannot be read.
      SyntaxError: If it does not parse.
    """
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(path))
    checker = Checker(path, src)
    checker.visit(tree)
    return checker.finish()


def main(argv: Sequence[str] | None = None) -> int:
    """Checks the scripts named on the command line and prints the findings.

    Args:
      argv: The arguments after the program name; None reads sys.argv.

    Returns:
      The exit status: 1 for errors (or warnings under --strict), 2 when no
      file is given, 0 otherwise.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    strict = "--strict" in argv
    files = [pathlib.Path(a) for a in argv if not a.startswith("--")]
    if not files:
        print(__doc__)
        return 2
    n_err = n_warn = 0
    for path in files:
        try:
            findings = check_file(path)
        except SyntaxError as error:
            print(f"{path}:{error.lineno}: ERROR syntax {error.msg}")
            n_err += 1
            continue
        for line, level, code, msg in findings:
            print(f"{path}:{line}: {level} {code:<14} {msg}")
            if level == "ERROR":
                n_err += 1
            else:
                n_warn += 1
        if not findings:
            print(f"{path}: OK")
    print(f"\n{n_err} error(s), {n_warn} warning(s)")
    return 1 if n_err or (strict and n_warn) else 0


if __name__ == "__main__":
    sys.exit(main())
