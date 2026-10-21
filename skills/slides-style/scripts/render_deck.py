#!/usr/bin/env python3
"""Render a .pptx to one PNG per slide for visual QA, with LibreOffice.

    python render_deck.py talk.pptx [--outdir renders] [--dpi 110]

Writes <outdir>/<stem>.pdf and <outdir>/<stem>-NN.png and prints the PNG
paths. Standard library only; needs `soffice` (LibreOffice) and `pdftoppm`
(Poppler) on PATH.

LibreOffice is not PowerPoint, and the preview differs in two known ways:
Aptos is substituted (the preview's text runs wider or narrower than the
real deck, so leave slack rather than trusting a tight fit), and native
equations show their fallback picture, not the editable OMML.
"""

import argparse
import pathlib
import shutil
import subprocess
import sys
import tempfile


def render(
    deck: pathlib.Path, outdir: pathlib.Path, dpi: int
) -> list[pathlib.Path]:
    """Converts a deck to PDF, then to one PNG per slide.

    Args:
        deck: The .pptx file.
        outdir: Directory for the PDF and PNGs; created if missing.
        dpi: PNG resolution.

    Returns:
        The PNG paths, in slide order.

    Raises:
        FileNotFoundError: soffice or pdftoppm is not installed.
        subprocess.CalledProcessError: A conversion failed.
    """
    for tool in ("soffice", "pdftoppm"):
        if shutil.which(tool) is None:
            raise FileNotFoundError(f"render_deck needs {tool} on PATH")
    outdir.mkdir(parents=True, exist_ok=True)
    for old in outdir.glob(f"{deck.stem}-*.png"):
        old.unlink()
    with tempfile.TemporaryDirectory(prefix="lo_profile_") as profile:
        subprocess.run(
            [
                "soffice",
                f"-env:UserInstallation={pathlib.Path(profile).as_uri()}",
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(outdir),
                str(deck),
            ],
            check=True,
            capture_output=True,
            timeout=600,
        )
    pdf = outdir / f"{deck.stem}.pdf"
    subprocess.run(
        ["pdftoppm", "-png", "-r", str(dpi), str(pdf), str(outdir / deck.stem)],
        check=True,
        capture_output=True,
    )
    return sorted(outdir.glob(f"{deck.stem}-*.png"))


def main() -> None:
    """Parses arguments, renders, and prints the image paths."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("deck", type=pathlib.Path)
    parser.add_argument("--outdir", type=pathlib.Path, default=None)
    parser.add_argument("--dpi", type=int, default=110)
    args = parser.parse_args()
    outdir = args.outdir or args.deck.parent / "renders"
    try:
        images = render(args.deck.resolve(), outdir.resolve(), args.dpi)
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        print(f"render failed: {error}", file=sys.stderr)
        sys.exit(1)
    for image in images:
        print(image)


if __name__ == "__main__":
    main()
