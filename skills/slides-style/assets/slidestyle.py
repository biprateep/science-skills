r"""House slide style for PowerPoint decks, built with python-pptx.

Copy this file, template.pptx and profile.json next to the deck script and
import the module (never its names):

    import slidestyle

    deck = slidestyle.new_deck()
    slide = slidestyle.content_slide(deck, "Measuring Galaxy Redshift")
    slidestyle.figure(slide, "figs/spectrum.png", slidestyle.CONTENT_BOX,
                      alt="A galaxy spectrum with emission lines")
    slidestyle.text(slide, "**Very expensive!**", 8.5, 2.0, 4.0)
    slidestyle.save(deck, "talk.pptx")

Every length is in inches and every size in points. Text takes a small
markup: **bold**, *italic*, !!red emphasis!!, ==accent blue==,
[label](https://...) links and $LaTeX$ inline math; write \* for a literal
asterisk. Display equations go through equation(), which writes PowerPoint's
own editable equation (OMML, converted from LaTeX by pandoc) with a rendered
picture as the fallback that other readers show.

Requires python-pptx, lxml and Pillow; equations also need pandoc (on PATH,
or the pypandoc_binary wheel) and pdflatex with pdftocairo, or matplotlib as
a lower-fidelity fallback for the picture.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
import copy
import dataclasses
import importlib
import io
import json
import math
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
from typing import Any, TypeAlias
import warnings
import zipfile

from lxml import etree
from PIL import Image
import pptx
from pptx import util
from pptx.dml import color as dml_color
from pptx.enum import shapes as shape_enums
from pptx.enum import text as text_enums
from pptx.oxml import ns
import pptx.presentation
import pptx.shapes.base
import pptx.text.text

# ---------------------------------------------------------------------------
# The style, as numbers. Measured from the author's decks; see SKILL.md.
# ---------------------------------------------------------------------------

SLIDE_WIDTH = 12192000 / 914400  # 13.333 in, PowerPoint widescreen.
SLIDE_HEIGHT = 7.5

TITLE_SIZE = 40  # Content-slide titles.
TITLE_SLIDE_SIZE = 44  # The deck's own title.
STATEMENT_SIZE = 40  # One-sentence statement and section-break slides.
BODY_SIZE = 24  # Takeaways, summary items, most annotation labels.
LABEL_SIZE = 20  # Labels crowded around a figure.
SMALL_LABEL_SIZE = 18  # The floor for anything that is not a credit.
CAPTION_SIZE = 16  # Only on the acknowledgements slide.
CREDIT_SIZE = 10  # Image credits and citations.
EQUATION_SIZE = 28

BLACK = "000000"
WHITE = "FFFFFF"
ACCENT = "1973EB"  # The dash and accent words (theme accent 1).
RED = "C00000"  # The one emphasis colour (theme accent 2).
LINK = "1AC16E"  # Hyperlinks (theme hlink).

TITLE_BOX = (1.00, 0.30, 11.33, 0.75)
DASH = (1.083, 1.128, 1.070)  # left, top, length of the accent dash.
SLIDE_NUMBER_BOX = (11.82, 6.95, 0.79, 0.40)

# Where content goes on a content slide: below the dash, above the credit
# line. Figures run close to the slide edges, as in the author's decks.
CONTENT_BOX = (0.40, 1.40, 12.53, 5.55)
LEFT_HALF = (0.40, 1.40, 6.15, 5.55)
RIGHT_HALF = (6.78, 1.40, 6.15, 5.55)
CREDIT_TOP = 7.02
CREDIT_HEIGHT = 0.38

ARROW_WEIGHT = 1.5  # Thin black annotation arrows, in points.

_HERE = pathlib.Path(__file__).resolve().parent
TEMPLATE_PATH = _HERE / "template.pptx"
PROFILE_PATH = _HERE / "profile.json"
ASSETS_ENV = "SLIDES_STYLE_ASSETS"
DEFAULT_ASSETS_DIR = pathlib.Path("~/.config/slides-style/assets")

_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
_MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
_A14_NS = "http://schemas.microsoft.com/office/drawing/2010/main"
_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

# A python-pptx shape, or the raw element of an equation wrapper.
ShapeLike: TypeAlias = "pptx.shapes.base.BaseShape | etree._Element"  # noqa: SLF001 - lxml's element type.

_BENGALI = re.compile("[\u0980-\u09ff]")
_TOKEN = re.compile(r"(\\\*|\*\*|\*|!!|==|\[[^\]]+\]\([^)\s]+\)|\$[^$]+\$)")
_SMALL_WORDS = frozenset(
    "a an and as at but by for from in into of on or per the to via vs "
    "with".split()
)


@dataclasses.dataclass(frozen=True)
class Person:
    """A collaborator shown on the acknowledgements slide.

    Attributes:
        name: Full name, shown in bold.
        role: Position, e.g. "Assistant Professor".
        institution: Institution, shown under the role.
        photo: Path to a headshot; cropped to a circle.
    """

    name: str
    role: str
    institution: str
    photo: pathlib.Path | None = None


@dataclasses.dataclass
class _Run:
    """One run of parsed markup."""

    text: str
    bold: bool = False
    italic: bool = False
    color: str | None = None
    link: str | None = None
    math: str | None = None


# ---------------------------------------------------------------------------
# Profile and local assets.
# ---------------------------------------------------------------------------


def load_profile(path: pathlib.Path | None = None) -> dict[str, Any]:
    """Reads the committed text profile.

    Args:
        path: The profile JSON; defaults to profile.json beside this module.

    Returns:
        The profile as a dictionary (name, email, closing lines, logo keys).
    """
    with (path or PROFILE_PATH).open(encoding="utf-8") as handle:
        return json.load(handle)


def assets_dir() -> pathlib.Path:
    """Returns the local, uncommitted assets folder.

    It is $SLIDES_STYLE_ASSETS when set, else ~/.config/slides-style/assets.
    """
    return pathlib.Path(
        os.environ.get(ASSETS_ENV, str(DEFAULT_ASSETS_DIR))
    ).expanduser()


def _manifest() -> dict[str, dict[str, str]]:
    """Reads manifest.json from the assets folder, or {} if there is none."""
    path = assets_dir() / "manifest.json"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def asset(key: str) -> pathlib.Path:
    """Resolves an asset key (a logo, headshot or hero image) to a file.

    Args:
        key: A key of the local manifest, e.g. "logo/vector".

    Returns:
        The absolute path of the file.

    Raises:
        FileNotFoundError: The key is not in the manifest, or its file is
            missing. Add the file to the assets folder and the manifest.
    """
    entry = _manifest().get(key)
    if entry is None:
        raise FileNotFoundError(
            f"asset {key!r} is not in {assets_dir() / 'manifest.json'}"
        )
    path = assets_dir() / entry["file"]
    if not path.exists():
        raise FileNotFoundError(f"asset {key!r} points to missing {path}")
    return path


def person(key: str) -> Person:
    """Builds a Person from a "person/..." entry of the local manifest.

    Args:
        key: A manifest key such as "person/josh-speagle".

    Returns:
        The person, with the photo resolved to a path.

    Raises:
        FileNotFoundError: The key or its photo is missing.
    """
    entry = _manifest().get(key)
    if entry is None:
        raise FileNotFoundError(f"person {key!r} is not in the manifest")
    return Person(
        name=entry["name"],
        role=entry.get("role", ""),
        institution=entry.get("institution", ""),
        photo=asset(key),
    )


def _optional_assets(keys: Iterable[str]) -> list[pathlib.Path]:
    """Resolves asset keys, warning about and skipping missing ones."""
    paths = []
    for key in keys:
        try:
            paths.append(asset(key))
        except FileNotFoundError as error:
            warnings.warn(f"skipping asset: {error}", stacklevel=3)
    return paths


# ---------------------------------------------------------------------------
# Deck and slides.
# ---------------------------------------------------------------------------


def new_deck(
    template: pathlib.Path | None = None,
) -> pptx.presentation.Presentation:
    """Opens a new deck on the house template.

    Args:
        template: Another .pptx to start from (a collaboration template);
            defaults to template.pptx beside this module.

    Returns:
        An empty presentation with the Title, Content and Blank layouts.
    """
    deck = pptx.Presentation(str(template or TEMPLATE_PATH))
    profile = load_profile()
    deck.core_properties.author = str(profile.get("name", ""))
    deck.core_properties.title = ""
    return deck


def save(
    deck: pptx.presentation.Presentation, path: str | os.PathLike[str]
) -> None:
    """Writes the deck.

    Args:
        deck: The presentation.
        path: Output .pptx path.
    """
    pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
    deck.save(str(path))


def _layout(
    deck: pptx.presentation.Presentation, name: str
) -> pptx.slide.SlideLayout:
    """Finds a layout by name."""
    for layout in deck.slide_layouts:
        if layout.name == name:
            return layout
    raise KeyError(f"the template has no layout named {name!r}")


def _mark(slide: pptx.slide.Slide, kind: str) -> None:
    """Records the slide's kind as its internal name, for the checker."""
    slide._element.find(ns.qn("p:cSld")).set("name", kind)  # noqa: SLF001 - no API.


def _add_slide_number(slide: pptx.slide.Slide) -> None:
    """Copies the layout's slide-number placeholder onto the slide.

    python-pptx does not clone date, footer or slide-number placeholders,
    and PowerPoint draws only placeholders present on the slide itself.
    """
    # python-pptx's placeholder collection mistypes __iter__ for mypy.
    for shape in slide.slide_layout.placeholders:  # type: ignore[misc]
        if (
            shape.placeholder_format.type
            == shape_enums.PP_PLACEHOLDER.SLIDE_NUMBER
        ):
            element = copy.deepcopy(shape._element)  # noqa: SLF001 - no API.
            tree = slide.shapes._spTree  # noqa: SLF001 - no API.
            element.find(f".//{ns.qn('p:cNvPr')}").set(
                "id", str(_next_id(slide))
            )
            sp_pr = element.find(ns.qn("p:spPr"))
            for child in list(sp_pr):
                sp_pr.remove(child)
            tree.append(element)
            return


def _next_id(slide: pptx.slide.Slide) -> int:
    """Returns an unused shape id on the slide."""
    ids = [
        int(value)
        for value in slide.shapes._spTree.xpath("//p:cNvPr/@id")  # noqa: SLF001 - no API.
    ]
    return max(ids, default=1) + 1


def content_slide(
    deck: pptx.presentation.Presentation, title: str
) -> pptx.slide.Slide:
    """Adds a content slide: title top-left, dash under it, slide number.

    Args:
        deck: The presentation.
        title: The slide title, in Title Case, no trailing period; one line
            (about 45 characters at 40 pt). Markup is allowed.

    Returns:
        The new slide.
    """
    slide = deck.slides.add_slide(_layout(deck, "Content"))
    _fill(slide.shapes.title.text_frame, title, size=None)
    _add_slide_number(slide)
    _mark(slide, "content")
    return slide


def blank_slide(
    deck: pptx.presentation.Presentation, kind: str = "blank"
) -> pptx.slide.Slide:
    """Adds a slide with no title, dash or number.

    Args:
        deck: The presentation.
        kind: The slide kind recorded for the checker.

    Returns:
        The new slide.
    """
    slide = deck.slides.add_slide(_layout(deck, "Blank"))
    _mark(slide, kind)
    return slide


def title_slide(
    deck: pptx.presentation.Presentation,
    title: str,
    *,
    subtitle: str | None = None,
    hero: str | os.PathLike[str] | None = None,
    hero_alt: str = "",
    hero_fit: str = "contain",
    hero_credit: str | None = None,
    logos: Sequence[str] | None = None,
) -> pptx.slide.Slide:
    """Adds the deck's title slide.

    Left: the title in two to four lines (bold a lead phrase with **...**,
    or colour one keyword with ==...==), the dash, the name line in Latin
    and Bengali, an optional subtitle line, the email, and a row of
    affiliation logos. Right: a hero image filling the right half.

    Args:
        deck: The presentation.
        title: The talk title, with markup.
        subtitle: A line under the name, e.g. "with Jeff Newman, on behalf
            of the DESI Collaboration".
        hero: Image for the right half.
        hero_alt: What the hero image shows.
        hero_fit: "contain" (cut-outs, maps) or "cover" (photographs).
        hero_credit: Credit line for the hero image.
        logos: Asset keys of the logos; defaults to the profile's
            title_logos. Missing assets are skipped with a warning.

    Returns:
        The new slide.
    """
    profile = load_profile()
    slide = deck.slides.add_slide(_layout(deck, "Title"))
    _mark(slide, "title")
    _fill(slide.shapes.title.text_frame, title, size=TITLE_SLIDE_SIZE)
    name_frame = slide.placeholders[1].text_frame
    _fill(name_frame, str(profile["name_line"]), size=BODY_SIZE)
    lines = []
    if subtitle:
        lines.append(subtitle)
    email = str(profile.get("email", ""))
    if email:
        lines.append(f"[{email}](mailto:{email})")
    if lines:
        text(slide, "\n".join(lines), 1.00, 5.55, 6.90, size=SMALL_LABEL_SIZE)
    keys = list(logos if logos is not None else profile.get("title_logos", []))
    logo_row(slide, _optional_assets(keys), 1.00, 6.50, 0.62, max_width=8.30)
    if hero is not None:
        figure(
            slide,
            hero,
            (7.55, 0.30, SLIDE_WIDTH - 7.75, 5.90),
            alt=hero_alt,
            fit=hero_fit,
        )
    if hero_credit:
        credit(slide, hero_credit, side="right")
    return slide


def statement_slide(
    deck: pptx.presentation.Presentation,
    content: str,
    *,
    size: int = STATEMENT_SIZE,
) -> pptx.slide.Slide:
    """Adds a one-sentence statement or question, centred on an empty slide.

    Used as section breaks and beats: "What if we learn these
    transformations?". No title, dash or slide number.

    Args:
        deck: The presentation.
        content: The sentence, with markup; a line break is allowed.
        size: Font size; 36-44 pt.

    Returns:
        The new slide.
    """
    slide = blank_slide(deck, "statement")
    text(
        slide,
        content,
        1.25,
        1.50,
        SLIDE_WIDTH - 2.50,
        4.50,
        size=size,
        align="center",
        anchor="middle",
    )
    return slide


def quote_slide(
    deck: pptx.presentation.Presentation, quote: str, attribution: str
) -> pptx.slide.Slide:
    """Adds a centred quotation with its attribution.

    Args:
        deck: The presentation.
        quote: The quotation, without quotation marks.
        attribution: Who said it, e.g. "John McCarthy (1956)".

    Returns:
        The new slide.
    """
    slide = blank_slide(deck, "quote")
    text(
        slide,
        f"\u201c{quote}\u201d\n\u2014 {attribution}",
        1.50,
        1.75,
        SLIDE_WIDTH - 3.00,
        4.00,
        size=28,
        align="center",
        anchor="middle",
    )
    return slide


def divider_slide(
    deck: pptx.presentation.Presentation, label: str = "EXTRA SLIDES"
) -> pptx.slide.Slide:
    """Adds the divider before the backup slides.

    Args:
        deck: The presentation.
        label: The divider text.

    Returns:
        The new slide.
    """
    slide = blank_slide(deck, "divider")
    line(
        slide,
        (DASH[0], DASH[1]),
        (DASH[0] + DASH[2], DASH[1]),
        color=ACCENT,
        weight=6,
    )
    text(slide, label, 1.00, 1.35, 11.33, size=32)
    return slide


def summary_slide(
    deck: pptx.presentation.Presentation,
    takeaways: Sequence[str],
    *,
    title: str = "Summary",
    references: Sequence[str] = (),
    qr_url: str | None = None,
    qr_label: str | None = None,
) -> pptx.slide.Slide:
    """Adds the summary slide with the closing formula.

    Args:
        deck: The presentation.
        takeaways: Three or four one-sentence takeaways, each with a bold
            key phrase.
        title: "Summary" or "Summary: <section>".
        references: Lines such as "Dey et al. 2022
            ([arXiv:2205.14568](https://arxiv.org/abs/2205.14568))".
        qr_url: A link (usually the paper) to show as a QR code; needs the
            segno package.
        qr_label: Caption under the QR code, e.g. "arXiv:2606.09576".

    Returns:
        The new slide.
    """
    profile = load_profile()
    slide = content_slide(deck, title)
    _mark(slide, "summary")
    width = 8.70 if qr_url else 11.33
    bullets(slide, takeaways, 1.00, 1.50, width)
    top = 1.50 + 0.95 * len(takeaways)
    if references:
        refs = "References:\n" + "\n".join(references)
        text(slide, refs, 1.00, top + 0.15, width, size=SMALL_LABEL_SIZE)
    closing = list(profile.get("closing", []))
    email = str(profile.get("email", ""))
    closing.append(f"Contact: [{email}](mailto:{email})")
    text(
        slide,
        "\n".join(closing),
        1.00,
        5.45,
        9.50,
        size=LABEL_SIZE,
        bold=True,
    )
    if qr_url:
        qr_image(slide, qr_url, 10.30, 1.80, 2.20)
        if qr_label:
            text(
                slide,
                qr_label,
                9.80,
                4.05,
                3.20,
                size=SMALL_LABEL_SIZE,
                align="center",
            )
    return slide


def acknowledgements_slide(
    deck: pptx.presentation.Presentation,
    people: Sequence[Person | str],
    *,
    funders: Sequence[str] | None = None,
    title: str = "Acknowledgements",
    intro: str = "In collaboration with:",
) -> pptx.slide.Slide:
    """Adds slide 2: collaborators in circular headshots, then funders.

    Args:
        deck: The presentation.
        people: Person objects, or "person/..." manifest keys; up to six.
        funders: Asset keys of funder logos; defaults to the profile's
            funder_logos.
        title: Slide title.
        intro: Line above the headshots.

    Returns:
        The new slide.
    """
    profile = load_profile()
    slide = content_slide(deck, title)
    _mark(slide, "acknowledgements")
    resolved = [p if isinstance(p, Person) else person(p) for p in people]
    text(slide, intro, 1.00, 1.32, 8.0, size=LABEL_SIZE)
    if resolved:
        column = 12.33 / len(resolved)
        diameter = min(1.45, column - 0.35)
        for index, member in enumerate(resolved):
            left = 0.50 + index * column
            if member.photo is not None:
                photo(
                    slide,
                    member.photo,
                    left + (column - diameter) / 2,
                    1.85,
                    diameter,
                    alt=member.name,
                )
            caption = (
                f"**{member.name}**\n{member.role}\n**{member.institution}**"
            )
            text(
                slide,
                caption,
                left,
                1.95 + diameter,
                column,
                size=CAPTION_SIZE,
                align="center",
            )
    keys = list(
        funders if funders is not None else profile.get("funder_logos", [])
    )
    logo_paths = _optional_assets(keys)
    if logo_paths:
        text(slide, "Funded by:", 1.00, 5.45, 4.0, size=LABEL_SIZE)
        logo_row(slide, logo_paths, 1.10, 5.85, 0.95, max_width=10.5)
    fellowship = profile.get("fellowship")
    if fellowship:
        credit(slide, str(fellowship))
    return slide


def hide(slide: pptx.slide.Slide) -> None:
    """Hides a slide in the slide show (backup slides kept for questions)."""
    slide._element.set("show", "0")  # noqa: SLF001 - python-pptx has no API.


# ---------------------------------------------------------------------------
# Text.
# ---------------------------------------------------------------------------


def _parse(markup: str) -> list[_Run]:
    """Splits one line of markup into styled runs.

    Args:
        markup: Text with **bold**, *italic*, !!red!!, ==accent==,
            [label](url) and $math$.

    Returns:
        The runs, in order.
    """
    runs: list[_Run] = []
    bold = italic = red = accent = False
    for piece in _TOKEN.split(markup):
        if not piece:
            continue
        color = RED if red else ACCENT if accent else None
        if piece == "\\*":
            runs.append(_Run("*", bold, italic, color))
        elif piece == "**":
            bold = not bold
        elif piece == "*":
            italic = not italic
        elif piece == "!!":
            red = not red
        elif piece == "==":
            accent = not accent
        elif piece.startswith("[") and piece.endswith(")"):
            label, url = piece[1:].split("](", 1)
            runs.append(_Run(label, bold, italic, color, link=url[:-1]))
        elif piece.startswith("$") and piece.endswith("$") and len(piece) > 2:
            runs.append(_Run("", bold, italic, color, math=piece[1:-1]))
        else:
            runs.append(_Run(piece, bold, italic, color))
    return runs


def _fill(
    frame: pptx.text.text.TextFrame,
    markup: str,
    *,
    size: int | None,
    align: str = "left",
    bold: bool = False,
    color: str | None = None,
) -> bool:
    """Writes markup into a text frame, one paragraph per line.

    Args:
        frame: The text frame to fill; its old text is discarded.
        markup: The text, with markup and line breaks.
        size: Font size in points, or None to inherit (placeholders).
        align: "left", "center" or "right".
        bold: Make every run bold.
        color: Default colour (hex) for runs without their own.

    Returns:
        True if any run is inline math, so the shape needs an equation
        wrapper.
    """
    frame.clear()
    has_math = False
    alignment = {
        "left": text_enums.PP_ALIGN.LEFT,
        "center": text_enums.PP_ALIGN.CENTER,
        "right": text_enums.PP_ALIGN.RIGHT,
    }[align]
    for index, line_markup in enumerate(markup.split("\n")):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.alignment = alignment
        for run_spec in _parse(line_markup):
            if run_spec.math is not None:
                _append_inline_math(paragraph, run_spec.math, size)
                has_math = True
                continue
            run = paragraph.add_run()
            run.text = run_spec.text
            font = run.font
            if size is not None:
                font.size = util.Pt(size)
            if bold or run_spec.bold:
                font.bold = True
            if run_spec.italic:
                font.italic = True
            hex_color = run_spec.color or color
            if run_spec.link:
                run.hyperlink.address = run_spec.link
                hex_color = hex_color or LINK
            if hex_color:
                font.color.rgb = dml_color.RGBColor.from_string(hex_color)
            if _BENGALI.search(run_spec.text):
                run._r.get_or_add_rPr().set("lang", "bn-BD")  # noqa: SLF001 - no API.
    return has_math


def _estimate_height(markup: str, width: float, size: float) -> float:
    """Estimates a text box height in inches (about 0.5 em per character)."""
    usable = max(width - 0.2, 0.5)
    lines = 0
    for line_markup in markup.split("\n"):
        plain = "".join(run.text or "xx" for run in _parse(line_markup))
        chars_per_line = max(usable * 72 / (0.5 * size), 1)
        lines += max(1, math.ceil(len(plain) / chars_per_line))
    return lines * size * 1.2 / 72 + 0.1


def text(
    slide: pptx.slide.Slide,
    content: str,
    left: float,
    top: float,
    width: float,
    height: float | None = None,
    *,
    size: int = BODY_SIZE,
    align: str = "left",
    anchor: str = "top",
    bold: bool = False,
    color: str | None = None,
) -> pptx.shapes.autoshape.Shape | etree._Element:
    r"""Adds a free text box: a label, takeaway or note.

    Text lives in free boxes, not placeholders, and the box grows to fit
    (it never shrinks the text). Keep labels to 2-8 words.

    Args:
        slide: The slide.
        content: Text with markup; "\n" starts a new paragraph.
        left: Left edge, in inches.
        top: Top edge, in inches.
        width: Box width, in inches.
        height: Box height; estimated from the text when None.
        size: Font size, at least 18 pt except credits.
        align: "left", "center" or "right".
        anchor: "top", "middle" or "bottom".
        bold: Bold every run.
        color: Default text colour, hex.

    Returns:
        The shape, or its equation wrapper element when the text holds
        inline math.
    """
    box_height = height or _estimate_height(content, width, size)
    shape = slide.shapes.add_textbox(
        util.Inches(left),
        util.Inches(top),
        util.Inches(width),
        util.Inches(box_height),
    )
    frame = shape.text_frame
    frame.word_wrap = True
    frame.auto_size = (
        text_enums.MSO_AUTO_SIZE.SHAPE_TO_FIT_TEXT
        if height is None
        else text_enums.MSO_AUTO_SIZE.NONE
    )
    frame.vertical_anchor = {
        "top": text_enums.MSO_ANCHOR.TOP,
        "middle": text_enums.MSO_ANCHOR.MIDDLE,
        "bottom": text_enums.MSO_ANCHOR.BOTTOM,
    }[anchor]
    has_math = _fill(
        frame, content, size=size, align=align, bold=bold, color=color
    )
    if has_math:
        fallback = copy.deepcopy(shape._element)  # noqa: SLF001 - no API.
        _math_to_text(fallback)
        return _wrap_alternate(shape._element, fallback)  # noqa: SLF001 - no API.
    return shape


def bullets(
    slide: pptx.slide.Slide,
    items: Sequence[str],
    left: float,
    top: float,
    width: float,
    *,
    size: int = BODY_SIZE,
    space_after: int = 14,
) -> pptx.shapes.autoshape.Shape | etree._Element:
    """Adds a one-level bulleted list (summary, agenda, outline only).

    Args:
        slide: The slide.
        items: Three to five one-sentence items, each with a bold key phrase.
        left: Left edge, in inches.
        top: Top edge, in inches.
        width: Box width, in inches.
        size: Font size.
        space_after: Space after each item, in points.

    Returns:
        The text shape.
    """
    shape = text(slide, "\n".join(items), left, top, width, size=size)
    element = shape if isinstance(shape, etree._Element) else shape._element  # noqa: SLF001 - no API.
    for paragraph in element.iter(ns.qn("a:p")):
        p_pr = paragraph.find(ns.qn("a:pPr"))
        if p_pr is None:
            p_pr = etree.Element(ns.qn("a:pPr"))
            paragraph.insert(0, p_pr)
        p_pr.set("marL", str(util.Inches(0.32)))
        p_pr.set("indent", str(-util.Inches(0.32)))
        spacing = etree.SubElement(p_pr, ns.qn("a:spcAft"))
        etree.SubElement(spacing, ns.qn("a:spcPts"), val=str(space_after * 100))
        etree.SubElement(p_pr, ns.qn("a:buFont"), typeface="Arial")
        etree.SubElement(p_pr, ns.qn("a:buChar"), char="\u2022")
    return shape


def credit(
    slide: pptx.slide.Slide,
    content: str,
    *,
    side: str = "left",
    box: tuple[float, float, float] | None = None,
    size: int = CREDIT_SIZE,
) -> pptx.shapes.autoshape.Shape | etree._Element:
    """Adds an image credit or citation at 8-11 pt.

    Default placement is the credit line along the bottom edge, left or
    right of centre; pass box=(left, top, width) to sit a citation next to
    its figure instead ("Dey et al. 2022, arXiv:2112.03939").

    Args:
        slide: The slide.
        content: "Image courtesy: <source>" or a citation; links allowed.
        side: "left" or "right" when box is None.
        box: (left, top, width) in inches, overriding side.
        size: Font size, 8-11 pt.

    Returns:
        The text shape.
    """
    if box is not None:
        left, top, width = box
        align = "left"
    elif side == "left":
        left, top, width, align = 0.90, CREDIT_TOP, 6.40, "left"
    else:
        left, top, width, align = 5.30, CREDIT_TOP, 6.40, "right"
    return text(
        slide,
        content,
        left,
        top,
        width,
        CREDIT_HEIGHT,
        size=size,
        align=align,
        anchor="top",
    )


# ---------------------------------------------------------------------------
# Pictures and lines.
# ---------------------------------------------------------------------------


def figure(
    slide: pptx.slide.Slide,
    path: str | os.PathLike[str],
    box: tuple[float, float, float, float] = CONTENT_BOX,
    *,
    alt: str,
    fit: str = "contain",
    align: str = "center",
) -> pptx.shapes.picture.Picture:
    """Places a figure in a box, keeping its aspect ratio.

    The figure is the slide: give it a third to a half of the slide, run it
    close to the edges, and annotate it rather than describe it.

    Args:
        slide: The slide.
        path: PNG or JPEG file.
        box: (left, top, width, height) in inches.
        alt: What the figure shows, for screen readers.
        fit: "contain" fits inside the box; "cover" fills it and crops.
        align: Horizontal placement for "contain": "left", "center" or
            "right".

    Returns:
        The picture shape.
    """
    left, top, width, height = box
    with Image.open(path) as image:
        aspect = image.width / image.height
    if fit == "cover":
        picture = slide.shapes.add_picture(
            str(path),
            util.Inches(left),
            util.Inches(top),
            util.Inches(width),
            util.Inches(height),
        )
        box_aspect = width / height
        if aspect > box_aspect:
            excess = 1 - box_aspect / aspect
            picture.crop_left = picture.crop_right = excess / 2
        else:
            excess = 1 - aspect / box_aspect
            picture.crop_top = picture.crop_bottom = excess / 2
    else:
        shown_width = min(width, height * aspect)
        shown_height = shown_width / aspect
        offset = {"left": 0.0, "center": 0.5, "right": 1.0}[align]
        picture = slide.shapes.add_picture(
            str(path),
            util.Inches(left + offset * (width - shown_width)),
            util.Inches(top + (height - shown_height) / 2),
            util.Inches(shown_width),
            util.Inches(shown_height),
        )
    picture._element.find(f".//{ns.qn('p:cNvPr')}").set("descr", alt)  # noqa: SLF001 - no API.
    return picture


def photo(
    slide: pptx.slide.Slide,
    path: str | os.PathLike[str],
    left: float,
    top: float,
    diameter: float,
    *,
    alt: str,
) -> pptx.shapes.picture.Picture:
    """Places a headshot cropped to a circle.

    Args:
        slide: The slide.
        path: The headshot.
        left: Left edge, in inches.
        top: Top edge, in inches.
        diameter: Circle diameter, in inches.
        alt: Who it is.

    Returns:
        The picture shape.
    """
    picture = figure(
        slide, path, (left, top, diameter, diameter), alt=alt, fit="cover"
    )
    picture.auto_shape_type = shape_enums.MSO_SHAPE.OVAL
    return picture


def logo_row(
    slide: pptx.slide.Slide,
    paths: Sequence[pathlib.Path],
    left: float,
    top: float,
    height: float,
    *,
    max_width: float,
    gap: float = 0.30,
) -> list[pptx.shapes.picture.Picture]:
    """Places logos in a row at a common height, shrinking to fit.

    Args:
        slide: The slide.
        paths: Logo files, left to right.
        left: Left edge of the row, in inches.
        top: Top edge, in inches.
        height: Logo height, in inches.
        max_width: Width the row may not exceed, in inches.
        gap: Space between logos, in inches.

    Returns:
        The picture shapes.
    """
    if not paths:
        return []
    aspects = []
    for path in paths:
        with Image.open(path) as image:
            aspects.append(image.width / image.height)
    total = height * sum(aspects) + gap * (len(paths) - 1)
    scale = min(1.0, max_width / total)
    pictures = []
    cursor = left
    for path, aspect in zip(paths, aspects, strict=True):
        width = height * scale * aspect
        pictures.append(
            figure(
                slide,
                path,
                (cursor, top + height * (1 - scale) / 2, width, height * scale),
                alt=path.stem,
                align="left",
            )
        )
        cursor += width + gap * scale
    return pictures


def qr_image(
    slide: pptx.slide.Slide, url: str, left: float, top: float, size: float
) -> pptx.shapes.picture.Picture:
    """Places a QR code for a link (needs the segno package).

    Args:
        slide: The slide.
        url: The link to encode.
        left: Left edge, in inches.
        top: Top edge, in inches.
        size: Side length, in inches.

    Returns:
        The picture shape.
    """
    segno = importlib.import_module("segno")
    buffer = io.BytesIO()
    segno.make(url, error="m").save(buffer, kind="png", scale=12, border=1)
    buffer.seek(0)
    picture = slide.shapes.add_picture(
        buffer,
        util.Inches(left),
        util.Inches(top),
        util.Inches(size),
        util.Inches(size),
    )
    c_nv_pr = picture._element.find(f".//{ns.qn('p:cNvPr')}")  # noqa: SLF001 - no API.
    c_nv_pr.set("descr", f"QR code: {url}")
    return picture


def line(
    slide: pptx.slide.Slide,
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    head: str = "none",
    weight: float = ARROW_WEIGHT,
    color: str = BLACK,
    dashed: bool = False,
) -> pptx.shapes.connector.Connector:
    """Draws a straight line or arrow.

    Args:
        slide: The slide.
        start: (x, y) in inches.
        end: (x, y) in inches.
        head: "none", "end", "start" or "both".
        weight: Line width, in points.
        color: Line colour, hex.
        dashed: Draw a dashed line.

    Returns:
        The connector shape.
    """
    connector = slide.shapes.add_connector(
        shape_enums.MSO_CONNECTOR.STRAIGHT,
        util.Inches(start[0]),
        util.Inches(start[1]),
        util.Inches(end[0]),
        util.Inches(end[1]),
    )
    connector.line.width = util.Pt(weight)
    connector.line.color.rgb = dml_color.RGBColor.from_string(color)
    outline_element = connector.line._get_or_add_ln()  # noqa: SLF001 - no API.
    if dashed:
        etree.SubElement(outline_element, ns.qn("a:prstDash"), val="dash")
    if head in {"start", "both"}:
        etree.SubElement(outline_element, ns.qn("a:headEnd"), type="triangle")
    if head in {"end", "both"}:
        etree.SubElement(outline_element, ns.qn("a:tailEnd"), type="triangle")
    return connector


def arrow(
    slide: pptx.slide.Slide,
    start: tuple[float, float],
    end: tuple[float, float],
    **options: Any,
) -> pptx.shapes.connector.Connector:
    """Draws a thin black annotation arrow pointing at end.

    Args:
        slide: The slide.
        start: Tail (x, y), next to the label, in inches.
        end: Head (x, y), on the feature, in inches.
        **options: Passed to line() (weight, color, dashed, head).

    Returns:
        The connector shape.
    """
    options.setdefault("head", "end")
    return line(slide, start, end, **options)


def outline(
    slide: pptx.slide.Slide,
    left: float,
    top: float,
    width: float,
    height: float,
    *,
    color: str = RED,
    weight: float = 2.25,
    rounded: bool = False,
) -> pptx.shapes.autoshape.Shape:
    """Draws an unfilled box around something to point at it.

    Used to red-box a paper's title on a screenshot, or to ring one panel
    of a figure.

    Args:
        slide: The slide.
        left: Left edge, in inches.
        top: Top edge, in inches.
        width: Width, in inches.
        height: Height, in inches.
        color: Outline colour, hex.
        weight: Outline width, in points.
        rounded: Round the corners.

    Returns:
        The shape.
    """
    kind = (
        shape_enums.MSO_SHAPE.ROUNDED_RECTANGLE
        if rounded
        else shape_enums.MSO_SHAPE.RECTANGLE
    )
    shape = slide.shapes.add_shape(
        kind,
        util.Inches(left),
        util.Inches(top),
        util.Inches(width),
        util.Inches(height),
    )
    shape.fill.background()
    shape.line.width = util.Pt(weight)
    shape.line.color.rgb = dml_color.RGBColor.from_string(color)
    shape.shadow.inherit = False
    return shape


# ---------------------------------------------------------------------------
# Builds.
# ---------------------------------------------------------------------------


def _shape_id(shape: ShapeLike) -> int:
    """Returns the id of a python-pptx shape or a raw shape element."""
    if isinstance(shape, pptx.shapes.base.BaseShape):
        return int(shape.shape_id)
    return int(next(shape.iter(ns.qn("p:cNvPr"))).get("id"))


_EFFECT_XML = (
    '<p:par><p:cTn id="{effect}" presetID="1" presetClass="entr" '
    'presetSubtype="0" fill="hold" grpId="0" nodeType="{node}">'
    '<p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst><p:set>'
    '<p:cBhvr><p:cTn id="{behaviour}" dur="1" fill="hold"><p:stCondLst>'
    '<p:cond delay="0"/></p:stCondLst></p:cTn><p:tgtEl>'
    '<p:spTgt spid="{spid}"/></p:tgtEl><p:attrNameLst>'
    "<p:attrName>style.visibility</p:attrName></p:attrNameLst></p:cBhvr>"
    '<p:to><p:strVal val="visible"/></p:to></p:set></p:childTnLst></p:cTn>'
    "</p:par>"
)
_CLICK_XML = (
    '<p:par><p:cTn id="{outer}" fill="hold"><p:stCondLst>'
    '<p:cond delay="indefinite"/></p:stCondLst><p:childTnLst><p:par>'
    '<p:cTn id="{inner}" fill="hold"><p:stCondLst><p:cond delay="0"/>'
    "</p:stCondLst><p:childTnLst>{effects}</p:childTnLst></p:cTn></p:par>"
    "</p:childTnLst></p:cTn></p:par>"
)
_TIMING_XML = (
    '<p:timing xmlns:p="{namespace}"><p:tnLst><p:par>'
    '<p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot">'
    '<p:childTnLst><p:seq concurrent="1" nextAc="seek">'
    '<p:cTn id="2" dur="indefinite" nodeType="mainSeq"><p:childTnLst>'
    "{clicks}</p:childTnLst></p:cTn><p:prevCondLst>"
    '<p:cond evt="onPrev" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl>'
    "</p:cond></p:prevCondLst><p:nextCondLst>"
    '<p:cond evt="onNext" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl>'
    "</p:cond></p:nextCondLst></p:seq></p:childTnLst></p:cTn></p:par>"
    "</p:tnLst>{builds}</p:timing>"
)


def _click_xml(
    group: Sequence[ShapeLike], counter: Iterator[int]
) -> tuple[str, list[int]]:
    """Returns one click's timing markup and the ids of its text shapes.

    Args:
        group: Shapes appearing together on this click.
        counter: Supplies unused timing-node ids.

    Returns:
        A tuple (xml, text_ids).
    """
    effects = []
    text_ids = []
    for position, shape in enumerate(group):
        spid = _shape_id(shape)
        effects.append(
            _EFFECT_XML.format(
                effect=next(counter),
                behaviour=next(counter),
                node="clickEffect" if position == 0 else "withEffect",
                spid=spid,
            )
        )
        if _has_text(shape):
            text_ids.append(spid)
    xml = _CLICK_XML.format(
        outer=next(counter), inner=next(counter), effects="".join(effects)
    )
    return xml, text_ids


def appear(
    slide: pptx.slide.Slide, steps: Sequence[ShapeLike | Sequence[ShapeLike]]
) -> None:
    """Makes shapes appear one click at a time (the Appear effect).

    The author's builds are mostly duplicated slides; use this for a few
    labels or arrows that arrive on one figure.

    Args:
        slide: The slide.
        steps: One entry per click: a shape, or a sequence of shapes that
            appear together.
    """
    counter = iter(range(3, 100000))
    clicks = []
    text_ids: list[int] = []
    for step in steps:
        group = list(step) if isinstance(step, (list, tuple)) else [step]
        xml, ids = _click_xml(group, counter)
        clicks.append(xml)
        text_ids.extend(ids)
    builds = "".join(
        f'<p:bldP spid="{spid}" grpId="0"/>' for spid in dict.fromkeys(text_ids)
    )
    timing = etree.fromstring(
        _TIMING_XML.format(
            namespace=_P_NS,
            clicks="".join(clicks),
            builds=f"<p:bldLst>{builds}</p:bldLst>" if builds else "",
        )
    )
    root = slide._element  # noqa: SLF001 - python-pptx has no timing API.
    for old in root.findall(ns.qn("p:timing")):
        root.remove(old)
    ext = root.find(ns.qn("p:extLst"))
    if ext is not None:
        ext.addprevious(timing)
    else:
        root.append(timing)


def _has_text(shape: ShapeLike) -> bool:
    """Whether a shape carries a text body (needs a build entry)."""
    element = (
        shape._element  # noqa: SLF001 - python-pptx has no API for this.
        if isinstance(shape, pptx.shapes.base.BaseShape)
        else shape
    )
    return any(True for _ in element.iter(ns.qn("a:t")))


# ---------------------------------------------------------------------------
# Equations: LaTeX -> OMML (editable in PowerPoint) + picture fallback.
# ---------------------------------------------------------------------------


def _pandoc() -> str:
    """Finds pandoc: on PATH, else from the pypandoc_binary wheel.

    Returns:
        The pandoc executable.

    Raises:
        FileNotFoundError: Neither is installed.
    """
    found = shutil.which("pandoc")
    if found:
        return found
    try:
        pypandoc = importlib.import_module("pypandoc")
    except ModuleNotFoundError as error:
        raise FileNotFoundError(
            "equations need pandoc: install it, or run with "
            "`uv run --with pypandoc_binary`"
        ) from error
    return str(pypandoc.get_pandoc_path())


def _run_pandoc(source: str, target: str) -> bytes:
    """Runs pandoc on a LaTeX snippet and returns the output bytes."""
    with tempfile.TemporaryDirectory() as workdir:
        source_path = pathlib.Path(workdir) / "in.tex"
        output_path = pathlib.Path(workdir) / f"out.{target}"
        source_path.write_text(source, encoding="utf-8")
        target_format = "docx" if target == "docx" else "plain"
        subprocess.run(
            [
                _pandoc(),
                "-f",
                "latex",
                "-t",
                target_format,
                "--wrap=none",
                str(source_path),
                "-o",
                str(output_path),
            ],
            check=True,
            capture_output=True,
        )
        return output_path.read_bytes()


def latex_to_omml(latex: str, *, display: bool = True) -> etree._Element:
    """Converts LaTeX math to an OMML element through pandoc.

    Args:
        latex: The math, without $ delimiters.
        display: Return m:oMathPara (a display equation) rather than an
            inline m:oMath.

    Returns:
        The m:oMathPara or m:oMath element, still with Word's bare m:r runs.

    Raises:
        ValueError: pandoc produced no math (the LaTeX did not parse).
    """
    wrapped = f"$${latex}$$" if display else f"${latex}$"
    docx = _run_pandoc(wrapped, "docx")
    with zipfile.ZipFile(io.BytesIO(docx)) as archive:
        document = etree.fromstring(archive.read("word/document.xml"))
    tag = "oMathPara" if display else "oMath"
    found = document.find(f".//{{{_M_NS}}}{tag}")
    if found is None:
        raise ValueError(f"pandoc produced no {tag} for {latex!r}")
    return found


def _drawingml_math(omml: etree._Element, size: float) -> etree._Element:
    """Gives every m:r the a:rPr PowerPoint expects (Cambria Math, size).

    Args:
        omml: An m:oMathPara or m:oMath from latex_to_omml().
        size: Font size, in points.

    Returns:
        A copy of the element, ready to sit inside a14:m.
    """
    result = copy.deepcopy(omml)
    for word_element in result.xpath(".//*[namespace-uri()=$w]", w=_W_NS):
        word_element.getparent().remove(word_element)
    for run in result.iter(f"{{{_M_NS}}}r"):
        style = run.find(f"{{{_M_NS}}}rPr/{{{_M_NS}}}sty")
        value = style.get(f"{{{_M_NS}}}val") if style is not None else "i"
        r_pr = etree.Element(
            f"{{{_A_NS}}}rPr",
            lang="en-US",
            sz=str(int(size * 100)),
            i="1" if "i" in value else "0",
            b="1" if "b" in value else "0",
        )
        etree.SubElement(r_pr, f"{{{_A_NS}}}latin", typeface="Cambria Math")
        etree.SubElement(r_pr, f"{{{_A_NS}}}ea", typeface="Cambria Math")
        math_r_pr = run.find(f"{{{_M_NS}}}rPr")
        if math_r_pr is not None:
            math_r_pr.addnext(r_pr)
        else:
            run.insert(0, r_pr)
    return result


def latex_to_unicode(latex: str) -> str:
    """Renders LaTeX math as plain Unicode text through pandoc.

    Args:
        latex: The math, without $ delimiters.

    Returns:
        A one-line Unicode approximation, e.g. "F̃(z ∣ 𝐱)".
    """
    return _run_pandoc(f"${latex}$", "plain").decode("utf-8").strip()


def _append_inline_math(
    paragraph: pptx.text.text._Paragraph, latex: str, size: float | None
) -> None:
    """Appends inline math to a paragraph as a14:m (fallback added later)."""
    omml = _drawingml_math(
        latex_to_omml(latex, display=False), size or BODY_SIZE
    )
    holder = etree.Element(f"{{{_A14_NS}}}m", nsmap={"a14": _A14_NS})
    holder.append(omml)
    holder.set("data-latex", latex)
    paragraph._p.append(holder)  # noqa: SLF001 - python-pptx has no math API.


def _math_to_text(shape_element: etree._Element) -> None:
    """Replaces each a14:m in a shape copy with a Unicode text run."""
    for holder in list(shape_element.iter(f"{{{_A14_NS}}}m")):
        latex = holder.get("data-latex", "")
        run = etree.Element(f"{{{_A_NS}}}r")
        r_pr = holder.find(f".//{{{_A_NS}}}rPr")
        if r_pr is not None:
            fallback_r_pr = copy.deepcopy(r_pr)
            for child in list(fallback_r_pr):
                fallback_r_pr.remove(child)
            run.append(fallback_r_pr)
        etree.SubElement(run, f"{{{_A_NS}}}t").text = latex_to_unicode(latex)
        holder.addprevious(run)
        holder.getparent().remove(holder)
    for holder in shape_element.iter(f"{{{_A14_NS}}}m"):
        del holder.attrib["data-latex"]


def _wrap_alternate(
    choice: etree._Element, fallback: etree._Element
) -> etree._Element:
    """Wraps a math-bearing shape in mc:AlternateContent, as PowerPoint does.

    Args:
        choice: The shape holding a14:m math; replaced in its tree.
        fallback: The same shape for readers without equation support.

    Returns:
        The mc:AlternateContent element.
    """
    for holder in choice.iter(f"{{{_A14_NS}}}m"):
        holder.attrib.pop("data-latex", None)
    wrapper = etree.Element(
        f"{{{_MC_NS}}}AlternateContent", nsmap={"mc": _MC_NS, "a14": _A14_NS}
    )
    choice.addprevious(wrapper)
    choice_branch = etree.SubElement(
        wrapper, f"{{{_MC_NS}}}Choice", Requires="a14"
    )
    choice_branch.append(choice)
    fallback_branch = etree.SubElement(wrapper, f"{{{_MC_NS}}}Fallback")
    fallback_branch.append(fallback)
    return wrapper


def render_latex(
    latex: str, size: float, *, dpi: int = 300
) -> tuple[bytes, float, float]:
    """Renders display math to a transparent PNG at its natural size.

    Uses pdflatex + pdftocairo (Computer Modern, true LaTeX) when both are
    installed, else matplotlib's mathtext (Computer Modern, a LaTeX
    subset).

    Args:
        latex: The math, without $ delimiters.
        size: Font size the math is set at, in points.
        dpi: Pixel density of the result at that size.

    Returns:
        A tuple (png, width, height) with the PNG bytes and the size the
        picture should be shown at, in inches.
    """
    if shutil.which("pdflatex") and shutil.which("pdftocairo"):
        return _render_with_latex(latex, size, dpi)
    return _render_with_matplotlib(latex, size, dpi)


def _render_with_latex(
    latex: str, size: float, dpi: int
) -> tuple[bytes, float, float]:
    """render_latex() through pdflatex and pdftocairo."""
    document = (
        "\\documentclass[10pt,border=1pt]{standalone}\n"
        "\\usepackage{amsmath,amssymb,bm}\n"
        "\\begin{document}\n"
        f"$\\displaystyle {latex}$\n"
        "\\end{document}\n"
    )
    scale = size / 10
    with tempfile.TemporaryDirectory() as workdir:
        root = pathlib.Path(workdir)
        (root / "eq.tex").write_text(document, encoding="utf-8")
        subprocess.run(
            [
                "pdflatex",
                "-interaction=nonstopmode",
                "-halt-on-error",
                "eq.tex",
            ],
            cwd=root,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "pdftocairo",
                "-png",
                "-singlefile",
                "-transp",
                "-r",
                str(int(dpi * scale)),
                "eq.pdf",
                "eq",
            ],
            cwd=root,
            check=True,
            capture_output=True,
        )
        png = (root / "eq.png").read_bytes()
    with Image.open(io.BytesIO(png)) as image:
        return png, image.width / dpi, image.height / dpi


def _render_with_matplotlib(
    latex: str, size: float, dpi: int
) -> tuple[bytes, float, float]:
    """render_latex() through matplotlib's mathtext."""
    plt = importlib.import_module("matplotlib.pyplot")
    with plt.rc_context({"mathtext.fontset": "cm"}):
        fig = plt.figure(figsize=(0.01, 0.01))
        fig.text(0, 0, f"${latex}$", fontsize=size)
        buffer = io.BytesIO()
        fig.savefig(
            buffer,
            format="png",
            dpi=dpi,
            transparent=True,
            bbox_inches="tight",
            pad_inches=0.02,
        )
        plt.close(fig)
    png = buffer.getvalue()
    with Image.open(io.BytesIO(png)) as image:
        return png, image.width / dpi, image.height / dpi


def equation(
    slide: pptx.slide.Slide,
    latex: str,
    left: float,
    top: float,
    *,
    size: int = EQUATION_SIZE,
    width: float | None = None,
    align: str = "left",
) -> etree._Element:
    """Adds a display equation PowerPoint can edit.

    The equation is OMML inside a text box; readers without equation support
    (LibreOffice, previews) show the LaTeX-rendered fallback picture, which
    is also what sets the box size. Annotate the terms with text() labels
    and line() leaders, as the author does.

    Args:
        slide: The slide.
        latex: The math, without $ delimiters.
        left: Left edge, in inches.
        top: Top edge, in inches.
        size: Font size, in points.
        width: Box width, in inches; the natural width plus 15 % when None.
        align: "left", "center" or "right" inside the box.

    Returns:
        The mc:AlternateContent element (its id works with appear()).
    """
    png, natural_width, natural_height = render_latex(latex, size)
    box_width = width or natural_width * 1.15
    box_height = natural_height * 1.25
    shape = slide.shapes.add_textbox(
        util.Inches(left),
        util.Inches(top),
        util.Inches(box_width),
        util.Inches(box_height),
    )
    frame = shape.text_frame
    frame.word_wrap = True
    for side in ("left", "right", "top", "bottom"):
        setattr(frame, f"margin_{side}", 0)
    paragraph = frame.paragraphs[0]
    paragraph.alignment = {
        "left": text_enums.PP_ALIGN.LEFT,
        "center": text_enums.PP_ALIGN.CENTER,
        "right": text_enums.PP_ALIGN.RIGHT,
    }[align]
    omml = _drawingml_math(latex_to_omml(latex, display=True), size)
    jc = omml.find(f"{{{_M_NS}}}oMathParaPr/{{{_M_NS}}}jc")
    if jc is not None:
        jc.set(
            f"{{{_M_NS}}}val",
            {"left": "left", "center": "center", "right": "right"}[align],
        )
    holder = etree.Element(f"{{{_A14_NS}}}m", nsmap={"a14": _A14_NS})
    holder.append(omml)
    paragraph._p.append(holder)  # noqa: SLF001 - python-pptx has no math API.
    choice = shape._element  # noqa: SLF001 - python-pptx has no math API.
    fallback = copy.deepcopy(choice)
    _picture_fallback(slide, fallback, png, natural_width, box_width, align)
    return _wrap_alternate(choice, fallback)


def _picture_fallback(
    slide: pptx.slide.Slide,
    shape_element: etree._Element,
    png: bytes,
    natural_width: float,
    box_width: float,
    align: str,
) -> None:
    """Turns a shape copy into a picture-filled box showing the equation."""
    _, relationship_id = slide.part.get_or_add_image_part(io.BytesIO(png))
    sp_pr = shape_element.find(ns.qn("p:spPr"))
    for old in sp_pr.findall(ns.qn("a:noFill")):
        sp_pr.remove(old)
    spare = max(box_width - natural_width, 0) / box_width
    left_pad = {"left": 0.0, "center": spare / 2, "right": spare}[align]
    right_pad = spare - left_pad
    blip_fill = etree.fromstring(
        f'<a:blipFill xmlns:a="{_A_NS}" xmlns:r="{_R_NS}">'
        f'<a:blip r:embed="{relationship_id}"/><a:stretch>'
        f'<a:fillRect l="{int(left_pad * 100000)}" '
        f'r="{int(right_pad * 100000)}" t="10000" b="10000"/>'
        "</a:stretch></a:blipFill>"
    )
    geometry = sp_pr.find(ns.qn("a:prstGeom"))
    geometry.addnext(blip_fill)
    body = shape_element.find(ns.qn("p:txBody"))
    for paragraph in body.findall(ns.qn("a:p")):
        body.remove(paragraph)
    body.append(
        etree.fromstring(
            f'<a:p xmlns:a="{_A_NS}"><a:endParaRPr lang="en-US"/></a:p>'
        )
    )


# ---------------------------------------------------------------------------
# Title helpers.
# ---------------------------------------------------------------------------


def title_case(title: str) -> str:
    """Capitalizes a title in the author's Title Case.

    Words of four letters or more and every first word are capitalized;
    short function words stay lower case; tokens with digits, dots, or
    inner capitals (photo-z, TabPFN, model.fit()) are left alone.

    Args:
        title: The title text.

    Returns:
        The title in Title Case.
    """
    words = title.split(" ")
    result = []
    for index, word in enumerate(words):
        bare = word.strip("“”\"'(:")
        keep = (
            not bare
            or any(char.isdigit() or char in "._()" for char in bare)
            or any(char.isupper() for char in bare[1:])
        )
        if keep:
            result.append(word)
        elif index > 0 and bare.lower() in _SMALL_WORDS:
            result.append(word.lower())
        else:
            position = word.find(bare[0])
            result.append(
                word[:position] + word[position].upper() + word[position + 1 :]
            )
    return " ".join(result)
