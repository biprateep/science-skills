#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["python-pptx>=1.0", "lxml>=5"]
# ///
"""Check a .pptx against the house slide style.

    uv run check_slides.py talk.pptx [more.pptx ...] [--strict]
        [--allow-notes] [--json]

Reports, per slide:

  ERROR  aspect        canvas is not 13.333 x 7.5 in (16:9 widescreen)
  ERROR  font          a run names a typeface other than the theme's
                       (Aptos / Aptos Display), Cambria Math in equations,
                       or a Bengali face on Bengali text
  ERROR  text-size     text between 12 and 17 pt (credits are 8-11 pt, all
                       other text 18 pt or more; 14 pt captions are allowed
                       on the acknowledgements slide)
  ERROR  title-missing a content slide without a title
  ERROR  title-bold    a bold content-slide title
  ERROR  title-period  a title ending in a period
  WARN   title-case    a title not in Title Case
  WARN   title-length  a title over 12 words
  ERROR  title-drift   content-slide titles at different positions
  ERROR  bullets       a bulleted list outside a summary, agenda or
                       acknowledgements slide, or more than five items
  ERROR  sub-bullets   a second-level bullet
  ERROR  notes         speaker notes (unless --allow-notes)
  ERROR  chrome        a content slide without the accent dash or the
                       slide number
  ERROR  shrink        text set to shrink on overflow
  ERROR  chart         a native chart or SmartArt (figures are PNGs)
  WARN   words         more than 60 words on a slide
  WARN   figure        a content slide with text only

Exit status is 1 when any ERROR is reported (or any WARN with --strict).
Slide kinds come from the names slidestyle.py records; for other decks
they are inferred (a slide with a title placeholder is a content slide).
"""

import argparse
from collections.abc import Iterator
import dataclasses
import json
import pathlib
import re
import sys

from lxml import etree
import pptx
from pptx.oxml import ns

WIDESCREEN_EMU = (12192000, 6858000)
EMU_PER_INCH = 914400
CREDIT_MAX_PT = 11
BODY_MIN_PT = 18
CAPTION_MIN_PT = 14
MAX_BULLETS = 5
MAX_WORDS = 60
MAX_TITLE_WORDS = 12
LIST_KINDS = frozenset({"summary", "agenda", "acknowledgements"})
NO_CHROME_KINDS = frozenset({"title", "statement", "quote", "divider", "blank"})
ALLOWED_FONTS = frozenset(
    {
        "+mj-lt",
        "+mn-lt",
        "+mj-ea",
        "+mn-ea",
        "+mj-cs",
        "+mn-cs",
        "Aptos",
        "Aptos Display",
        "Cambria Math",
    }
)
BENGALI_FONTS = frozenset(
    {
        "Vrinda",
        "Nirmala UI",
        "Shonar Bangla",
        "Kohinoor Bangla",
        "Noto Sans Bengali",
        "Bangla MN",
        "Bangla Sangam MN",
    }
)
SMALL_WORDS = frozenset(
    "a an and as at but by for from in into of on or per the to via vs "
    "with".split()
)
_A14_M = "{http://schemas.microsoft.com/office/drawing/2010/main}m"
_BENGALI = re.compile("[ঀ-৿]")
_CHART_URIS = (
    "http://schemas.openxmlformats.org/drawingml/2006/chart",
    "http://schemas.openxmlformats.org/drawingml/2006/diagram",
)


@dataclasses.dataclass(frozen=True)
class Finding:
    """One rule violation.

    Attributes:
        deck: The file checked.
        slide: 1-based slide number, or 0 for the whole deck.
        severity: "ERROR" or "WARN".
        code: The rule's code, e.g. "text-size".
        message: What is wrong, specifically.
    """

    deck: str
    slide: int
    severity: str
    code: str
    message: str


def _kind(slide: pptx.slide.Slide) -> str:
    """Returns the slide kind recorded by slidestyle.py, or infers it."""
    name = slide._element.find(ns.qn("p:cSld")).get("name", "")  # noqa: SLF001 - no API.
    if name:
        return name
    title = _title_text(slide)
    if title is None:
        return "blank"
    if re.match(r"(summary|conclusions?|outline|agenda)\b", title, re.I):
        return "summary"
    if re.match(r"acknowledge?ments?\b", title, re.I):
        return "acknowledgements"
    return "content"


def _title_shape(slide: pptx.slide.Slide) -> etree._Element | None:
    """Returns the slide's title placeholder element, if any."""
    for shape in slide._element.iter(ns.qn("p:sp")):  # noqa: SLF001 - no API.
        ph = shape.find(f".//{ns.qn('p:ph')}")
        if ph is not None and ph.get("type") in {"title", "ctrTitle"}:
            return shape
    return None


def _title_text(slide: pptx.slide.Slide) -> str | None:
    """Returns the title's text, or None without a title placeholder."""
    shape = _title_shape(slide)
    if shape is None:
        return None
    return "".join(t.text or "" for t in shape.iter(ns.qn("a:t"))).strip()


def _effective_size(
    run: etree._Element, slide: pptx.slide.Slide
) -> float | None:
    """Returns a run's size in points from the run, its paragraph or box.

    Inherited sizes from placeholders resolve to the master defaults
    (titles 40, body 24), which pass, so None is safe to skip.
    """
    for element in (run.find(ns.qn("a:rPr")),):
        if element is not None and element.get("sz"):
            return int(element.get("sz")) / 100
    paragraph = run.getparent()
    while paragraph is not None and etree.QName(paragraph).localname != "p":
        paragraph = paragraph.getparent()
    if paragraph is not None:
        p_pr = paragraph.find(ns.qn("a:pPr"))
        def_rpr = p_pr.find(ns.qn("a:defRPr")) if p_pr is not None else None
        if def_rpr is not None and def_rpr.get("sz"):
            return int(def_rpr.get("sz")) / 100
    del slide  # Placeholder inheritance is not resolved here.
    return None


def _shapes_with_text(slide: pptx.slide.Slide) -> Iterator[etree._Element]:
    """Yields every p:sp with text, skipping equation fallbacks."""
    for shape in slide._element.iter(ns.qn("p:sp")):  # noqa: SLF001 - no API.
        if any(
            etree.QName(a).localname == "Fallback"
            for a in shape.iterancestors()
        ):
            continue
        if shape.find(ns.qn("p:txBody")) is not None:
            yield shape


def _placeholder(shape: etree._Element) -> str | None:
    """Returns the placeholder type of a shape, or None."""
    ph = shape.find(f".//{ns.qn('p:ph')}")
    return None if ph is None else ph.get("type", "body")


def _has_dash(slide: pptx.slide.Slide) -> bool:
    """Whether the slide or its layout carries the accent dash."""
    layout = slide.slide_layout
    trees = (slide._element, layout._element, layout.slide_master._element)  # noqa: SLF001 - no API.
    for tree in trees:
        for shape in tree.iter(ns.qn("p:cxnSp"), ns.qn("p:sp")):
            xfrm = shape.find(f".//{ns.qn('a:xfrm')}")
            geometry = shape.find(f".//{ns.qn('a:prstGeom')}")
            if xfrm is None or geometry is None:
                continue
            if geometry.get("prst") != "line":
                continue
            off, ext = xfrm.find(ns.qn("a:off")), xfrm.find(ns.qn("a:ext"))
            width = int(ext.get("cx")) / EMU_PER_INCH
            height = int(ext.get("cy")) / EMU_PER_INCH
            top = int(off.get("y")) / EMU_PER_INCH
            if 0.7 <= width <= 1.6 and height < 0.05 and 0.8 <= top <= 1.6:
                return True
    return False


def _is_title_case(title: str) -> bool:
    """Whether every word of four letters or more is capitalized."""
    for index, word in enumerate(title.split()):
        bare = word.strip("“”\"'(),:?!")
        if not bare or not bare[0].isalpha():
            continue
        if any(c.isdigit() or c in "._()" for c in bare):
            continue
        if bare.lower() in SMALL_WORDS and index > 0:
            continue
        if len(bare) >= 4 and bare[0].islower():
            return False
    return True


def _bullet_level(
    paragraph: etree._Element, placeholder: str | None
) -> int | None:
    """Returns a bulleted paragraph's level, or None if it has no bullet.

    Args:
        paragraph: An a:p element.
        placeholder: The placeholder type of its shape, or None.

    Returns:
        0 for a first-level bullet, 1+ for deeper ones, None for no bullet.
    """
    p_pr = paragraph.find(ns.qn("a:pPr"))
    level = int(p_pr.get("lvl", "0")) if p_pr is not None else 0
    explicit = p_pr is not None and (
        p_pr.find(ns.qn("a:buChar")) is not None
        or p_pr.find(ns.qn("a:buAutoNum")) is not None
    )
    inherited = placeholder in {"body", "obj"} and (
        p_pr is None or p_pr.find(ns.qn("a:buNone")) is None
    )
    return level if explicit or inherited else None


def _check_text(
    slide: pptx.slide.Slide, kind: str, report: list[tuple[str, str, str]]
) -> int:
    """Checks fonts, sizes, bullets and shrinking; returns the word count."""
    words = 0
    caption_min = CAPTION_MIN_PT if kind == "acknowledgements" else BODY_MIN_PT
    for shape in _shapes_with_text(slide):
        placeholder = _placeholder(shape)
        if placeholder == "sldNum":
            continue
        body_pr = shape.find(f".//{ns.qn('a:bodyPr')}")
        autofit = (
            body_pr.find(ns.qn("a:normAutofit"))
            if body_pr is not None
            else None
        )
        if autofit is not None and autofit.get("fontScale"):
            report.append(("ERROR", "shrink", "text is shrunk to fit its box"))
        bulleted = 0
        for paragraph in shape.iter(ns.qn("a:p")):
            text = "".join(t.text or "" for t in paragraph.iter(ns.qn("a:t")))
            if not text.strip():
                continue
            words += len(text.split())
            level = _bullet_level(paragraph, placeholder)
            if level is not None:
                bulleted += 1
                if level > 0:
                    report.append(
                        ("ERROR", "sub-bullets", f"sub-bullet: {text[:40]!r}")
                    )
            for run in paragraph.iter(ns.qn("a:r")):
                _check_run(run, slide, caption_min, report)
        if bulleted and kind not in LIST_KINDS:
            report.append(
                (
                    "ERROR",
                    "bullets",
                    f"{bulleted} bulleted items on a {kind} slide",
                )
            )
        elif bulleted > MAX_BULLETS:
            report.append(
                (
                    "ERROR",
                    "bullets",
                    f"{bulleted} bulleted items (at most {MAX_BULLETS})",
                )
            )
    return words


def _check_run(
    run: etree._Element,
    slide: pptx.slide.Slide,
    caption_min: int,
    report: list[tuple[str, str, str]],
) -> None:
    """Checks one run's typeface and size."""
    text = (run.findtext(ns.qn("a:t")) or "").strip()
    if not text:
        return
    r_pr = run.find(ns.qn("a:rPr"))
    if r_pr is not None:
        for tag in ("a:latin", "a:ea", "a:cs"):
            face = r_pr.find(ns.qn(tag))
            name = face.get("typeface") if face is not None else None
            if name is None or name in ALLOWED_FONTS:
                continue
            if _BENGALI.search(text) and name in BENGALI_FONTS:
                continue
            report.append(("ERROR", "font", f"typeface {name!r}"))
    size = _effective_size(run, slide)
    if size is None:
        return
    if CREDIT_MAX_PT < size < caption_min:
        report.append(
            (
                "ERROR",
                "text-size",
                f"{size:g} pt text {text[:30]!r}"
                f" (credits ≤ 11, else ≥ {caption_min})",
            )
        )


def _title_key(title: etree._Element) -> tuple[int, int]:
    """Returns a title box's position, rounded to 0.05 in, as a key."""
    xfrm = title.find(f".//{ns.qn('a:xfrm')}")
    if xfrm is None:
        return (-1, -1)
    off = xfrm.find(ns.qn("a:off"))
    return (round(int(off.get("x")) / 45720), round(int(off.get("y")) / 45720))


def _title_drift(
    path: pathlib.Path, positions: dict[tuple[int, int], list[int]]
) -> list[Finding]:
    """Flags content slides whose title is not where most titles are.

    Args:
        path: The deck, for the findings.
        positions: Title position key to the slide numbers using it.

    Returns:
        One title-drift finding per slide off the usual position.
    """
    if len(positions) < 2:
        return []
    usual = max(positions.values(), key=len)
    drifted: list[Finding] = []
    for slides in positions.values():
        if slides is usual:
            continue
        drifted.extend(
            Finding(
                str(path),
                number,
                "ERROR",
                "title-drift",
                "title box is not where the other titles are",
            )
            for number in slides
        )
    return drifted


def check_deck(
    path: pathlib.Path, *, allow_notes: bool = False
) -> list[Finding]:
    """Checks one deck against the house style.

    Args:
        path: The .pptx file.
        allow_notes: Accept speaker notes (only when the user asked).

    Returns:
        The findings, in slide order.
    """
    deck = pptx.Presentation(str(path))
    findings: list[Finding] = []
    width, height = deck.slide_width or 0, deck.slide_height or 0
    if (width, height) != WIDESCREEN_EMU:
        size = (width / EMU_PER_INCH, height / EMU_PER_INCH)
        findings.append(
            Finding(
                str(path),
                0,
                "ERROR",
                "aspect",
                f"canvas {size[0]:.2f} x {size[1]:.2f} in",
            )
        )
    title_positions: dict[tuple[int, int], list[int]] = {}
    for number, slide in enumerate(deck.slides, start=1):
        report: list[tuple[str, str, str]] = []
        kind = _kind(slide)
        _check_slide(slide, kind, report, allow_notes=allow_notes)
        title = _title_shape(slide)
        if title is not None and kind not in NO_CHROME_KINDS:
            key = _title_key(title)
            title_positions.setdefault(key, []).append(number)
        unique = dict.fromkeys(report)
        findings.extend(Finding(str(path), number, *item) for item in unique)
    findings.extend(_title_drift(path, title_positions))
    return sorted(findings, key=lambda f: (f.slide, f.code))


def _check_slide(
    slide: pptx.slide.Slide,
    kind: str,
    report: list[tuple[str, str, str]],
    *,
    allow_notes: bool,
) -> None:
    """Runs the per-slide rules."""
    title = _title_text(slide)
    if kind not in NO_CHROME_KINDS:
        if not title:
            report.append(
                ("ERROR", "title-missing", f"{kind} slide without a title")
            )
        else:
            _check_title(slide, title, report)
        if not _has_dash(slide):
            report.append(("ERROR", "chrome", "no accent dash under the title"))
        if not any(
            _placeholder(s) == "sldNum" for s in _shapes_with_text(slide)
        ):
            report.append(("ERROR", "chrome", "no slide number"))
    elif title and title.endswith("."):
        report.append(
            ("ERROR", "title-period", f"title ends with a period: {title!r}")
        )
    words = _check_text(slide, kind, report)
    if words > MAX_WORDS:
        report.append(("WARN", "words", f"{words} words (aim for 30 or fewer)"))
    root = slide._element  # noqa: SLF001 - no API.
    for frame in root.iter(ns.qn("a:graphicData")):
        if frame.get("uri") in _CHART_URIS:
            report.append(
                ("ERROR", "chart", "native chart or SmartArt; use a PNG figure")
            )
    visual = (
        any(True for _ in root.iter(ns.qn("p:pic")))
        or any(True for _ in root.iter(_A14_M))
        or any(True for _ in root.iter(ns.qn("p:graphicFrame")))
    )
    if (
        kind == "content"
        and not visual
        and len(list(root.iter(ns.qn("p:cxnSp")))) < 2
    ):
        report.append(
            ("WARN", "figure", "text-only content slide; lead with a figure")
        )
    if not allow_notes and slide.has_notes_slide:
        notes = slide.notes_slide.notes_text_frame
        if notes is not None and notes.text.strip():
            report.append(("ERROR", "notes", "speaker notes present"))


def _check_title(
    slide: pptx.slide.Slide, title: str, report: list[tuple[str, str, str]]
) -> None:
    """Checks a content-slide title."""
    shape = _title_shape(slide)
    if shape is None:
        return
    runs = [
        r
        for r in shape.iter(ns.qn("a:r"))
        if (r.findtext(ns.qn("a:t")) or "").strip()
    ]
    bold = [
        r
        for r in runs
        if r.find(ns.qn("a:rPr")) is not None
        and r.find(ns.qn("a:rPr")).get("b") == "1"
    ]
    if runs and len(bold) == len(runs):
        report.append(("ERROR", "title-bold", f"bold title: {title!r}"))
    if title.endswith("."):
        report.append(
            ("ERROR", "title-period", f"title ends with a period: {title!r}")
        )
    if not _is_title_case(title):
        report.append(("WARN", "title-case", f"not Title Case: {title!r}"))
    if len(title.split()) > MAX_TITLE_WORDS:
        report.append(
            ("WARN", "title-length", f"{len(title.split())}-word title")
        )


def main() -> None:
    """Parses arguments, checks each deck, prints findings, sets exit."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("decks", nargs="+", type=pathlib.Path)
    parser.add_argument(
        "--strict", action="store_true", help="fail on WARN too"
    )
    parser.add_argument("--allow-notes", action="store_true")
    parser.add_argument("--json", action="store_true", help="print JSON")
    args = parser.parse_args()
    findings: list[Finding] = []
    for deck in args.decks:
        findings.extend(check_deck(deck, allow_notes=args.allow_notes))
    if args.json:
        print(json.dumps([dataclasses.asdict(f) for f in findings], indent=1))
    else:
        for f in findings:
            where = f"slide {f.slide}" if f.slide else "deck"
            print(f"{f.deck}: {where}: {f.severity} {f.code}: {f.message}")
        errors = sum(f.severity == "ERROR" for f in findings)
        print(f"{len(findings)} findings, {errors} errors")
    failing = {"ERROR", "WARN"} if args.strict else {"ERROR"}
    sys.exit(1 if any(f.severity in failing for f in findings) else 0)


if __name__ == "__main__":
    main()
