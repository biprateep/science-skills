#!/usr/bin/env python3
"""Static compliance check for the publication plot style.

    python check_plot_style.py script.py [more.py ...] [--strict]

Parses each script's AST and reports, per line:

  ERROR  no-style        no use_style() / plt.style.use() / rcParams.update()
  ERROR  figsize         figsize not derived from COLUMN_WIDTH / TEXT_WIDTH / figsize()
  ERROR  savefig-format  saves a .pdf / .svg / .eps (house output is PNG)
  ERROR  savefig-args    savefig without bbox_inches="tight" and dpi=300, and no
                         rc coverage (savefig.bbox / savefig.dpi) from the style sheet
  ERROR  legend-frame    legend(frameon=True), or legend() without frameon=False when
                         only the inline rcParams block (which lacks legend.frameon) is used
  WARN   color           hand-picked hex / named colour on a data series (use C0, C1, ...)
  WARN   fontsize        numeric fontsize literal (use SMALL_SIZE / NORMAL_SIZE / BIG_SIZE)
  WARN   pyplot-state    plt.title() / plt.xlabel() / ... on the implicit current axes
  WARN   tight-layout    plt.tight_layout() (breaks figure-level colorbars; bbox is tight anyway)

Exit status is 1 if any ERROR was found (or any WARN with --strict), else 0.
Only the standard library is used, so it runs anywhere Python 3.9+ does.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

WIDTH_TOKENS = ("COLUMN_WIDTH", "TEXT_WIDTH", ".column_width", ".text_width", ".width(")
FIGSIZE_FUNCS = {"figsize", "grid_figsize"}
VECTOR_EXT = re.compile(r"\.(pdf|svg|eps|ps)\b", re.IGNORECASE)
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{3,8}$")
ALLOWED_COLORS = {"k", "black", "w", "white", "none", "gray", "grey"}
CYCLE_COLOR = re.compile(r"^C\d+$")
COLOR_KWARGS = {"color", "c", "facecolor", "edgecolor", "colors", "fc", "ec"}
SERIES_FUNCS = {"plot", "scatter", "hist", "bar", "barh", "fill_between", "fill_betweenx",
                "step", "errorbar", "contour", "contourf", "hexbin", "stairs"}
PYPLOT_STATE = {"title", "xlabel", "ylabel", "legend", "xlim", "ylim", "xticks", "yticks"}


def _name(node: ast.AST) -> str:
    """Dotted name of a call target, e.g. 'plt.savefig', 'ax[0].legend' -> 'legend'."""
    if isinstance(node, ast.Attribute):
        base = _name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _kw(call: ast.Call, key: str):
    for kw in call.keywords:
        if kw.arg == key:
            return kw.value
    return None


def _const(node) -> object:
    return node.value if isinstance(node, ast.Constant) else None


def _literal_str(node) -> str | None:
    """String content of a str constant or an f-string (with holes blanked)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value for v in node.values if isinstance(v, ast.Constant))
    return None


class Checker(ast.NodeVisitor):
    def __init__(self, path: Path, src: str):
        self.path = path
        self.src = src
        self.findings: list[tuple[int, str, str, str]] = []
        self.style_calls: set[str] = set()  # "use_style" | "style.use" | "rcParams.update"

    # -- reporting -----------------------------------------------------------
    def err(self, node, code, msg):
        self.findings.append((node.lineno, "ERROR", code, msg))

    def warn(self, node, code, msg):
        self.findings.append((node.lineno, "WARN", code, msg))

    # -- visitors ------------------------------------------------------------
    def visit_Call(self, call: ast.Call):
        name = _name(call.func)
        tail = name.rsplit(".", 1)[-1]

        if tail == "use_style" or name.endswith("style.use") or name.endswith("rcParams.update"):
            self.style_calls.add("use_style" if tail == "use_style"
                                 else "style.use" if name.endswith("style.use")
                                 else "rcParams.update")

        fs = _kw(call, "figsize")
        if fs is not None:
            self.check_figsize(fs)

        if tail == "savefig":
            self.check_savefig(call)
        if tail == "legend":
            self.check_legend(call)
        if tail in SERIES_FUNCS:
            self.check_colors(call)
        if tail == "tight_layout":
            self.warn(call, "tight-layout",
                      "tight_layout() ignores fig.add_axes() colorbars; savefig(bbox_inches='tight') already crops")
        if name.startswith("plt.") and tail in PYPLOT_STATE:
            fix = f"ax.{tail}()" if tail == "legend" else f"ax.set_{tail}()"
            self.warn(call, "pyplot-state", f"plt.{tail}() acts on the implicit current axes; use {fix}")

        fsz = _kw(call, "fontsize")
        if fsz is not None and isinstance(_const(fsz), (int, float)):
            self.warn(call, "fontsize", f"fontsize={_const(fsz)}: use SMALL_SIZE / NORMAL_SIZE / BIG_SIZE")

        self.generic_visit(call)

    # -- individual checks ---------------------------------------------------
    def check_figsize(self, node):
        text = ast.unparse(node)
        if isinstance(node, ast.Call) and _name(node.func).rsplit(".", 1)[-1] in FIGSIZE_FUNCS:
            return
        if isinstance(node, (ast.Tuple, ast.List)) and node.elts:
            width = ast.unparse(node.elts[0])
            if any(tok in width for tok in WIDTH_TOKENS):
                return
            if isinstance(_const(node.elts[0]), (int, float)):
                self.err(node, "figsize", f"figsize={text}: invented width; use COLUMN_WIDTH / TEXT_WIDTH")
                return
        if any(tok in text for tok in WIDTH_TOKENS):
            return
        self.err(node, "figsize", f"figsize={text}: width must derive from COLUMN_WIDTH / TEXT_WIDTH or figsize()")

    def check_savefig(self, call: ast.Call):
        target = call.args[0] if call.args else _kw(call, "fname")
        lit = _literal_str(target) if target is not None else None
        if lit is not None and VECTOR_EXT.search(lit):
            self.err(call, "savefig-format", f"saves {lit!r}: house output is a 300 dpi PNG")

        has_bbox = _const(_kw(call, "bbox_inches")) == "tight"
        has_dpi = _const(_kw(call, "dpi")) == 300
        rc_covered = bool(self.style_calls & {"use_style", "style.use"})
        if not (has_bbox and has_dpi):
            missing = [k for k, ok in (("bbox_inches='tight'", has_bbox), ("dpi=300", has_dpi)) if not ok]
            if rc_covered:
                pass  # savefig.bbox / savefig.dpi come from the style sheet
            else:
                self.err(call, "savefig-args", "savefig missing " + ", ".join(missing))

    def check_legend(self, call: ast.Call):
        fr = _kw(call, "frameon")
        if fr is not None and _const(fr) is True:
            self.err(call, "legend-frame", "legend(frameon=True): legends are always frameless")
            return
        if fr is None and self.style_calls and not (self.style_calls & {"use_style", "style.use"}):
            self.err(call, "legend-frame",
                     "legend() without frameon=False: the inline rcParams block does not set legend.frameon")

    def check_colors(self, call: ast.Call):
        for kw in call.keywords:
            if kw.arg not in COLOR_KWARGS:
                continue
            values = kw.value.elts if isinstance(kw.value, (ast.Tuple, ast.List)) else [kw.value]
            for v in values:
                s = _const(v)
                if not isinstance(s, str):
                    continue
                if s in ALLOWED_COLORS or CYCLE_COLOR.match(s):
                    continue
                if HEX_COLOR.match(s) or s.isalpha() or s.startswith(("tab:", "xkcd:")):
                    self.warn(call, "color", f"{kw.arg}={s!r}: hand-picked colour; data series use C0, C1, ...")

    # -- module-level ---------------------------------------------------------
    def finish(self):
        if not self.style_calls:
            self.findings.insert(0, (1, "ERROR", "no-style",
                                     "no use_style() / plt.style.use() / rcParams.update() before plotting"))
        self.findings.sort()
        return self.findings


def check_file(path: Path):
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(path))
    c = Checker(path, src)
    c.visit(tree)
    return c.finish()


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    strict = "--strict" in argv
    files = [Path(a) for a in argv if not a.startswith("--")]
    if not files:
        print(__doc__)
        return 2
    n_err = n_warn = 0
    for path in files:
        try:
            findings = check_file(path)
        except SyntaxError as exc:
            print(f"{path}:{exc.lineno}: ERROR syntax {exc.msg}")
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
