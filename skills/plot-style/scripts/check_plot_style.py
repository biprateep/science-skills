#!/usr/bin/env python3
"""Static compliance check for the publication plot style.

    python check_plot_style.py script.py [more.py ...] [--strict]
        [--allow-vector] [--allow-palette]

Parses each script's AST and reports, per line:

  ERROR  no-style        no recognized house style before figure creation
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
The allow flags record explicit user requests; they do not waive other rules.
This is a static heuristic, not a runtime certificate: use verify_style() too.
"""

from __future__ import annotations

import argparse
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
ALLOWED_COLORS = {"none"}
CYCLE_COLOR = re.compile(r"^C\d+$")
PLOT_FORMAT_COLOR = re.compile(
    r"^[-:.ox+*<>^vpsDhH1234|_]*(C\d|[bgrcmykw])[-:.ox+*<>^vpsDhH1234|_]*$"
)
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
_INLINE_RC = {
    "font.family": "serif",
    "font.serif": ["CMU Serif", "Latin Modern Roman", "cmr10"],
    "font.size": 10,
    "axes.titlesize": 10,
    "axes.labelsize": 10,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "xtick.top": True,
    "ytick.right": True,
    "xtick.direction": "in",
    "ytick.direction": "in",
    "legend.fontsize": 10,
    "figure.facecolor": "w",
    "figure.dpi": 300,
    "mathtext.fontset": "cm",
    "axes.formatter.use_mathtext": True,
}
_OUTPUT_RC = {
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "savefig.format": "png",
    "legend.frameon": False,
}
_FIGURE_CALLS = {
    "matplotlib.pyplot.figure",
    "matplotlib.pyplot.subplots",
    "matplotlib.pyplot.subplot_mosaic",
}

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

    def __init__(
        self,
        path: pathlib.Path,
        src: str,
        *,
        allow_vector: bool = False,
        allow_palette: bool = False,
    ) -> None:
        """Initializes the checker for one script.

        Args:
          path: The script.
          src: Its source.
          allow_vector: Whether the user explicitly requested vector output.
          allow_palette: Whether the user explicitly requested custom colors.
        """
        self.path = path
        self.src = src
        self.findings: list[_Finding] = []
        self.style_calls: set[str] = set()
        self.aliases: dict[str, str] = {}
        self.constants: dict[str, object] = {}
        self.allow_vector = allow_vector
        self.allow_palette = allow_palette

    def _resolved_name(self, node: ast.AST) -> str:
        """Resolve imported module and function aliases."""
        name = _name(node)
        root, separator, rest = name.partition(".")
        return self.aliases.get(root, root) + separator + rest

    def _value(self, node: ast.AST | None) -> object:
        """Read literal settings and previously assigned literal constants."""
        if isinstance(node, ast.Name):
            return self.constants.get(node.id)
        if isinstance(node, (ast.Tuple, ast.List)):
            return [self._value(value) for value in node.elts]
        if isinstance(node, ast.Dict):
            return {
                self._value(key): self._value(value)
                for key, value in zip(node.keys, node.values)
                if isinstance(key, (ast.Constant, ast.Name))
            }
        return _const(node)

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
            self.aliases[alias.asname or alias.name.split(".")[0]] = (
                alias.name if alias.asname else alias.name.split(".")[0]
            )
            root = alias.name.split(".")[0]
            if root in PALETTE_MODULES and not self.allow_palette:
                self.warn(
                    node, "palette", f"imports {alias.name}: {_PALETTE_WARNING}"
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Warns on imports from third-party palette packages."""
        root = (node.module or "").split(".")[0]
        for alias in node.names:
            self.aliases[alias.asname or alias.name] = (
                f"{node.module}.{alias.name}"
            )
        if root in PALETTE_MODULES and not self.allow_palette:
            self.warn(
                node,
                "palette",
                f"imports from {node.module}: {_PALETTE_WARNING}",
            )
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        """Track literal constants and reject explicit rcParam overrides."""
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.constants[target.id] = self._value(node.value)
            elif isinstance(target, ast.Subscript) and self._resolved_name(
                target.value
            ).endswith(".rcParams"):
                key = self._value(target.slice)
                self._check_rc_values(node, {key: self._value(node.value)})
        self.generic_visit(node)

    def visit_Call(self, call: ast.Call) -> None:
        """Runs the checks that look at one call."""
        name = self._resolved_name(call.func)
        tail = name.rsplit(".", 1)[-1]
        self._check_palette_call(call, name, tail)
        self._note_style_call(call, name)

        figsize_value = _kw(call, "figsize")
        if figsize_value is not None:
            self.check_figsize(figsize_value)
        if name in _FIGURE_CALLS:
            if not self.style_calls:
                self.err(
                    call, "no-style", "apply the house style before figures"
                )
            if figsize_value is None:
                # figure(num, figsize, ...) also accepts a positional size.
                if name.endswith(".figure") and len(call.args) > 1:
                    self.check_figsize(call.args[1])
                else:
                    self.err(
                        call,
                        "figsize",
                        "figure requires journal-derived figsize",
                    )

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
        if (
            tail in PALETTE_CALLS
            and not is_own_palette
            and not self.allow_palette
        ):
            self.warn(call, "palette", f"{name}(): {_PALETTE_WARNING}")

    def _note_style_call(self, call: ast.Call, name: str) -> None:
        """Records a call that applies the style, for the later checks."""
        if name == "plotstyle.use_style":
            self.style_calls.add("use_style")
        elif name.endswith("style.use"):
            value = self._value(call.args[0]) if call.args else None
            if (
                isinstance(value, str)
                and pathlib.PurePath(value).name == "paper.mplstyle"
            ):
                self.style_calls.add("style.use")
            else:
                self.style_calls.clear()
                self.err(
                    call,
                    "style",
                    "unrecognized style: use plotstyle.use_style() or"
                    " the supplied paper.mplstyle",
                )
        elif name.endswith("rcParams.update"):
            argument = call.args[0] if call.args else None
            values = self._value(argument)
            if argument is not None and self._resolved_name(argument) == (
                "plotstyle.RC_PARAMS"
            ):
                values = _INLINE_RC
            if isinstance(values, dict):
                self._check_rc_values(call, values)
                if all(
                    values.get(key) == value
                    for key, value in _INLINE_RC.items()
                ):
                    self.style_calls.add("rcParams.update")
            else:
                self.style_calls.clear()
                self.err(
                    call, "style", "cannot verify dynamic rcParams settings"
                )

    def _check_rc_values(
        self, node: ast.expr | ast.stmt, values: dict[object, object]
    ) -> None:
        """Reject explicit contradictions even after a recognized preamble."""
        for key, expected in {**_INLINE_RC, **_OUTPUT_RC}.items():
            if key in values and values[key] != expected:
                if (
                    key == "savefig.format"
                    and self.allow_vector
                    and values[key] in ("pdf", "svg", "eps", "ps")
                ):
                    continue
                self.err(node, "style-override", f"{key} must be {expected!r}")
                self.style_calls.clear()

    def _check_layout_calls(self, call: ast.Call, name: str, tail: str) -> None:
        """Warns on tight_layout() and on the pyplot state machine."""
        if tail == "tight_layout":
            self.warn(
                call,
                "tight-layout",
                "tight_layout() ignores fig.add_axes() colorbars;"
                " savefig(bbox_inches='tight') already crops",
            )
        if name.startswith("matplotlib.pyplot.") and tail in PYPLOT_STATE:
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
            if self._resolved_name(node.func) in {
                f"plotstyle.{function}" for function in FIGSIZE_FUNCS
            }:
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
        output_format = self._value(_kw(call, "format"))
        if not self.allow_vector and (
            (literal is not None and VECTOR_EXT.search(literal))
            or output_format in ("pdf", "svg", "eps", "ps")
        ):
            self.err(
                call,
                "savefig-format",
                f"saves {literal!r}: house output is a 300 dpi PNG",
            )

        # savefig.bbox and savefig.dpi come from the style sheet when it is in
        # effect.
        rc_covered = bool(self.style_calls & {"use_style", "style.use"})
        missing = []
        for key, expected in (("bbox_inches", "tight"), ("dpi", 300)):
            value = _kw(call, key)
            if value is None and rc_covered:
                continue
            if self._value(value) != expected:
                missing.append(f"{key}={expected!r}")
        if missing:
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
        inline_only = not (self.style_calls & {"use_style", "style.use"})
        if frameon is None and inline_only:
            self.err(
                call,
                "legend-frame",
                "legend() without frameon=False or a recognized style sheet",
            )

    def check_colors(self, call: ast.Call) -> None:
        """Warns on hand-picked colours given to a data series."""
        if self.allow_palette:
            return
        identity_line = len(call.args) >= 2 and ast.dump(
            call.args[0]
        ) == ast.dump(call.args[1])
        if _name(call.func).rsplit(".", 1)[-1] == "plot":
            for argument in call.args:
                value = _const(argument)
                match = (
                    PLOT_FORMAT_COLOR.fullmatch(value)
                    if isinstance(value, str)
                    else None
                )
                if match and not CYCLE_COLOR.fullmatch(match[1]):
                    if not (identity_line and match[1] == "k"):
                        self.warn(
                            call, "color", f"format {value!r}: use cycle colors"
                        )
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
                if (
                    color in ALLOWED_COLORS
                    or CYCLE_COLOR.fullmatch(color)
                    or (identity_line and color in ("k", "black"))
                    or (
                        color in ("w", "white")
                        and _const(_kw(call, "histtype")) == "step"
                    )
                ):
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
                    "no recognized plotstyle helper, paper.mplstyle, or"
                    " complete inline rcParams preamble",
                ),
            )
        self.findings.sort()
        return self.findings


def check_file(
    path: pathlib.Path,
    *,
    allow_vector: bool = False,
    allow_palette: bool = False,
) -> list[_Finding]:
    """Checks one script.

    Args:
      path: The script.
      allow_vector: Whether the user explicitly requested vector output.
      allow_palette: Whether the user explicitly requested custom colors.

    Returns:
      Its findings, sorted, as (line, level, code, message).

    Raises:
      OSError: If the file cannot be read.
      SyntaxError: If it does not parse.
    """
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(path))
    checker = Checker(
        path, src, allow_vector=allow_vector, allow_palette=allow_palette
    )
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=pathlib.Path)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--allow-vector", action="store_true")
    parser.add_argument("--allow-palette", action="store_true")
    options = parser.parse_args(argv)
    n_err = n_warn = 0
    for path in options.files:
        try:
            findings = check_file(
                path,
                allow_vector=options.allow_vector,
                allow_palette=options.allow_palette,
            )
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
    return 1 if n_err or (options.strict and n_warn) else 0


if __name__ == "__main__":
    sys.exit(main())
