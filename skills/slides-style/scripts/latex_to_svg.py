#!/usr/bin/env python3
r"""Render display math to an SVG of outlines, for Claude Slides decks.

    python latex_to_svg.py '\frac{a}{b}' eq.svg [--size 28]

Claude Slides has no math markup, and fonts never load inside an SVG, so
fractions, limits and matrices go on a slide as an image whose glyphs are
paths. Prints the width and height, in canvas pixels, at which the image
sets the math at --size points (1 pt = 2 px on the 1920 x 1080 canvas).
Standard library only; needs `latex` and `dvisvgm` (TeX Live) on PATH.
"""

import argparse
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

PX_PER_PT = 2.0  # 1920 px across 13.333 in = 144 px/in = 2 px/pt.
BASE_SIZE_PT = 10.0


def render(
    latex: str, output: pathlib.Path, size: float
) -> tuple[float, float]:
    """Writes the SVG and returns its on-canvas size.

    Args:
        latex: The math, without $ delimiters.
        output: Path of the .svg to write.
        size: Font size the math should appear at, in points.

    Returns:
        A tuple (width, height) in canvas pixels.

    Raises:
        FileNotFoundError: latex or dvisvgm is not installed.
        subprocess.CalledProcessError: The LaTeX did not compile.
        ValueError: dvisvgm produced an SVG without a viewBox.
    """
    for tool in ("latex", "dvisvgm"):
        if shutil.which(tool) is None:
            raise FileNotFoundError(f"latex_to_svg needs {tool} on PATH")
    document = (
        "\\documentclass[10pt,border=1pt]{standalone}\n"
        "\\usepackage{amsmath,amssymb,bm}\n"
        "\\begin{document}\n"
        f"$\\displaystyle {latex}$\n"
        "\\end{document}\n"
    )
    with tempfile.TemporaryDirectory() as workdir:
        root = pathlib.Path(workdir)
        (root / "eq.tex").write_text(document, encoding="utf-8")
        subprocess.run(
            ["latex", "-interaction=nonstopmode", "-halt-on-error", "eq.tex"],
            cwd=root,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["dvisvgm", "--no-fonts", "--exact-bbox", "-o", "eq.svg", "eq.dvi"],
            cwd=root,
            check=True,
            capture_output=True,
        )
        svg = (root / "eq.svg").read_text(encoding="utf-8")
    svg = re.sub(r"<\?xml[^>]*\?>\s*", "", svg)
    svg = re.sub(r"<!--.*?-->\s*", "", svg, flags=re.S)
    output.write_text(svg, encoding="utf-8")
    match = re.search(
        r"viewBox=[\"']([-\d.]+) ([-\d.]+) ([\d.]+) ([\d.]+)[\"']", svg
    )
    if match is None:
        raise ValueError(f"dvisvgm wrote no viewBox to {output}")
    scale = size / BASE_SIZE_PT * PX_PER_PT
    return float(match.group(3)) * scale, float(match.group(4)) * scale


def main() -> None:
    """Parses arguments, renders, and prints the canvas size."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("latex")
    parser.add_argument("output", type=pathlib.Path)
    parser.add_argument("--size", type=float, default=28.0)
    args = parser.parse_args()
    try:
        width, height = render(args.latex, args.output, args.size)
    except (
        FileNotFoundError,
        ValueError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"latex_to_svg failed: {error}", file=sys.stderr)
        sys.exit(1)
    kilobytes = args.output.stat().st_size / 1024
    print(
        f"{args.output}: width {width:.0f}px height {height:.0f}px,"
        f" {kilobytes:.1f} KB"
    )


if __name__ == "__main__":
    main()
