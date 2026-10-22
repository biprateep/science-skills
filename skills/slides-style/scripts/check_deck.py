#!/usr/bin/env python3
"""Check a Claude Slides deck against the house style and its alignment.

    python check_deck.py <root> [--json] [--strict] [--tolerance 16]

<root> is the folder holding the deck's files as written for publishing:
project/deck.json and project/slides/<id>.html. Standard library only.

House rules (from SKILL.md):

  ERROR  background    a slide background other than white
  ERROR  font          a typeface other than Noto Sans (Noto Sans Bengali on
                       Bengali text, Latin Modern Math on math)
  ERROR  text-size     text under 36 px, except 24 px credits, citations and
                       slide numbers and 32 px captions on acknowledgements
  ERROR  title-bold    a bold content-slide title
  ERROR  title-period  a title ending in a period
  WARN   title-case    a title not in Title Case
  WARN   title-length  a title over 12 words
  WARN   title-wrap    a title too long for one line
  ERROR  bullets       a list outside summary / agenda / acknowledgements,
                       or more than five items
  ERROR  notes         speaker notes (<aside>)
  ERROR  chrome        a content slide without the dash or slide number
  ERROR  number        a slide number that is not the slide's position
  ERROR  placeholder   bracketed template text left, or an <img> with no src
  WARN   words         more than 60 words on a slide
  WARN   figure        a content slide with no figure
  WARN   table         a table (make it an image)
  WARN   color         a text colour outside the house palette

Alignment:

  ERROR  canvas        an element off the 1920 x 1080 canvas
  ERROR  drift         chrome (title, dash, number, credit) not at the same
                       place on every slide
  WARN   drift         a repeated element a few px off where it sits on
                       the other slides
  WARN   near-miss     edges or centres on one slide within --tolerance px
                       of each other (or of a guide line) but not equal
  WARN   spacing       a row of three or more like elements, unevenly spaced
  WARN   overlap       text boxes overlapping (text heights are estimated)
  WARN   arrow         an arrow whose tail is not at any label
  WARN   margin        content closer than 48 px to the canvas edge
  WARN   unmeasured    text in flow layout, which cannot be measured

Guide lines are the title's left edge (x = 144), the canvas centre
(x = 960) and the right edges of the title and slide number (x = 1776,
1816). Each slide gets an alignment score: the share of its content
elements that are aligned, meaning at least one horizontal edge (left,
centre or right, by alignment) exactly on another element's edge or a guide
line, or a place in an evenly spaced row of three or more like elements.
Every near-miss and drift finding names the exact value to set. Exit
status is 1 on any ERROR (with --strict, on any WARN too).
"""

import argparse
import collections
from collections.abc import Iterable, Sequence
import dataclasses
import html.parser
import json
import math
import pathlib
import re
import sys
from typing import TypeVar

CANVAS_WIDTH = 1920
CANVAS_HEIGHT = 1080
EDGE_MARGIN = 48
TITLE_LEFT = 144
CENTER_X = CANVAS_WIDTH // 2
BOTTOM_BAND = 950
CHAR_WIDTH = 0.55  # Noto Sans: average advance, in em.
MIN_TEXT_PX = 36
CREDIT_PX = 24
CAPTION_PX = 32
MAX_WORDS = 60
MAX_TITLE_WORDS = 12
MAX_ITEMS = 5
ROW_TOLERANCE = 4
GAP_TOLERANCE = 6
ARROW_REACH = 48

GUIDES = {
    "left": frozenset({float(TITLE_LEFT)}),
    "center": frozenset({float(CENTER_X)}),
    "right": frozenset({1776.0, 1816.0}),
    "top": frozenset(),
}
ALLOWED_FACES = frozenset({"noto sans", "latin modern math", "cambria math"})
BENGALI_FACE = "noto sans bengali"
PALETTE = frozenset({"#000000", "#c00000", "#1973eb", "#1ac16e", "#ffffff"})
WHITE = frozenset({"#fff", "#ffffff", "white", "rgb(255,255,255)"})
LIST_KINDS = frozenset({"summary", "agenda", "acknowledgements"})
CHROME_KINDS = frozenset({"content", "summary", "acknowledgements", "agenda"})
SMALL_WORDS = frozenset(
    "a an and as at but by for from in into of on or per the to via vs "
    "with".split()
)
HEADING_DEFAULTS = {
    "h1": (96.0, "600", 1.1),
    "h2": (64.0, "600", 1.15),
    "h3": (44.0, "600", 1.2),
}
TEXT_TAGS = frozenset({"h1", "h2", "h3", "p", "ul", "ol"})
BLOCK_TAGS = frozenset({"h1", "h2", "h3", "p", "li", "div"})
VOID_TAGS = frozenset({"img", "br", "hr", "x-icon", "x-shape"})
BOLD_WEIGHTS = frozenset({"bold", "600", "700", "800", "900"})

_BENGALI = re.compile("[ঀ-৿]")
_PLACEHOLDER = re.compile(r"\[[^\]]{2,}\]")
_CITATION = re.compile(
    r"(et al|arxiv|courtesy|credit|source|doi|\b(19|20)\d\d\b)", re.IGNORECASE
)
_LENGTH = re.compile(r"^(-?[\d.]+)(px|pt)?$")

_T = TypeVar("_T")
Report = list[tuple[str, str, str]]


@dataclasses.dataclass(eq=False)
class Node:
    r"""One element of a slide's markup.

    Attributes:
        tag: The tag name.
        attrs: The attributes.
        style: The inline style, parsed.
        parent: The enclosing node, or None for the root.
        children: Child nodes, in order.
        parts: Text strings and child nodes interleaved, in document
            order ("\\n" for <br>).
    """

    tag: str
    attrs: dict[str, str]
    style: dict[str, str]
    parent: "Node | None" = None
    children: list["Node"] = dataclasses.field(default_factory=list)
    parts: list["str | Node"] = dataclasses.field(default_factory=list)


@dataclasses.dataclass(eq=False)
class Box:
    """A measured element on a slide, in canvas px.

    Attributes:
        node: The element.
        kind: "text", "image" or "shape".
        left: Left edge.
        top: Top edge.
        width: Width.
        height: Height (estimated for text without one).
        font_size: Font size of text, or 0.
        align: text-align of text, or "".
        text: The element's text.
        role: "title", "dash", "number", "credit" or "content".
    """

    node: Node
    kind: str
    left: float
    top: float
    width: float
    height: float
    font_size: float = 0.0
    align: str = ""
    text: str = ""
    role: str = "content"

    @property
    def right(self) -> float:
        """The right edge."""
        return self.left + self.width

    @property
    def bottom(self) -> float:
        """The bottom edge."""
        return self.top + self.height

    @property
    def center_x(self) -> float:
        """The horizontal centre."""
        return self.left + self.width / 2

    def label(self) -> str:
        """A short name for messages."""
        snippet = self.text.replace("\n", " ") or self.node.attrs.get("alt", "")
        return f"{self.node.tag} '{snippet[:32]}'" if snippet else self.node.tag


@dataclasses.dataclass(frozen=True)
class Finding:
    """One problem found.

    Attributes:
        slide: The slide id.
        position: 1-based position of the slide in the deck.
        severity: "ERROR" or "WARN".
        code: The rule's code.
        message: What is wrong and, for alignment, the value to set.
    """

    slide: str
    position: int
    severity: str
    code: str
    message: str


@dataclasses.dataclass(eq=False)
class Slide:
    """A parsed slide.

    Attributes:
        slide_id: The slide id.
        position: 1-based position in the deck.
        root: The <section> node.
        kind: Inferred kind: title, content, summary, agenda,
            acknowledgements, statement, divider or blank.
        boxes: Measured elements.
        connectors: Arrows, as (x1, y1, x2, y2).
        unmeasured: Text elements in flow layout.
    """

    slide_id: str
    position: int
    root: Node
    kind: str = "blank"
    boxes: list[Box] = dataclasses.field(default_factory=list)
    connectors: list[tuple[float, float, float, float]] = dataclasses.field(
        default_factory=list
    )
    unmeasured: list[Node] = dataclasses.field(default_factory=list)


class _Parser(html.parser.HTMLParser):
    """Builds a Node tree from one slide file."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {}, {})
        self._current = self.root

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        values = {name: value or "" for name, value in attrs}
        node = Node(tag, values, parse_style(values.get("style", "")))
        node.parent = self._current
        self._current.children.append(node)
        self._current.parts.append(node)
        if tag == "br":
            self._current.parts.append("\n")
        elif tag not in VOID_TAGS:
            self._current = node

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS and tag != "br":
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        node = self._current
        while node.parent is not None and node.tag != tag:
            node = node.parent
        if node.parent is not None:
            self._current = node.parent

    def handle_data(self, data: str) -> None:
        # Source line breaks are spaces; only <br> breaks a line.
        self._current.parts.append(data.replace("\n", " "))


def parse_style(style: str) -> dict[str, str]:
    """Parses an inline style into lower-cased property -> value."""
    result = {}
    for declaration in style.split(";"):
        name, _, value = declaration.partition(":")
        if name.strip():
            result[name.strip().lower()] = value.strip()
    return result


def _length(value: str | None) -> float | None:
    """Converts "12px", "12" or "6pt" (2 px per pt) to px, else None."""
    if not value:
        return None
    match = _LENGTH.match(value.strip())
    if match is None:
        return None
    number = float(match.group(1))
    return number * 2 if match.group(2) == "pt" else number


def _inherited(node: Node, name: str) -> str | None:
    """Returns a style property from the node or its nearest ancestor."""
    current: Node | None = node
    while current is not None:
        if name in current.style:
            return current.style[name]
        current = current.parent
    return None


def all_text(node: Node) -> str:
    r"""Returns the text of a node and its descendants, "\n" for <br>."""
    direction = node.style.get("flex-direction", "row")
    in_row = node.style.get("display") == "flex" and direction.startswith("row")
    pieces = []
    for part in node.parts:
        if isinstance(part, str):
            pieces.append(part)
        else:
            # Block children start a new line, except side by side in a row.
            separator = ""
            if part.tag in BLOCK_TAGS and pieces:
                separator = " " if in_row else "\n"
            pieces.append(separator + all_text(part))
    joined = re.sub(r"[ \t\r]+", " ", "".join(pieces))
    return re.sub(r" ?\n ?", "\n", joined).strip()


def _walk(node: Node) -> Iterable[Node]:
    """Yields the node and every descendant, in document order."""
    yield node
    for child in node.children:
        yield from _walk(child)


def _font_size(node: Node) -> float:
    """Returns a text node's font size in px."""
    own = _length(node.style.get("font-size"))
    if own is not None:
        return own
    if node.tag in HEADING_DEFAULTS:
        return HEADING_DEFAULTS[node.tag][0]
    inherited = _length(_inherited(node, "font-size"))
    return inherited if inherited is not None else 32.0


def _line_height(node: Node, font_size: float) -> float:
    """Returns a text node's line height in px."""
    number = _length(_inherited(node, "line-height"))
    if number is not None:
        return number * font_size if number < 4 else number
    return HEADING_DEFAULTS.get(node.tag, (0.0, "400", 1.4))[2] * font_size


def _text_height(
    text: str, width: float, font_size: float, line: float
) -> float:
    """Estimates the height of wrapped text, in px."""
    per_line = max(width / (CHAR_WIDTH * font_size), 1.0)
    lines = sum(
        max(1, math.ceil(len(segment) / per_line))
        for segment in text.split("\n")
    )
    return lines * line


def _text_node(node: Node) -> Node | None:
    """Returns the first text element at or under a node, if any."""
    for candidate in _walk(node):
        if candidate.tag in TEXT_TAGS and all_text(candidate):
            return candidate
    return None


def _painted(node: Node) -> bool:
    """Whether a div is visible (background, border or shadow)."""
    return any(
        key in node.style for key in ("background", "border", "box-shadow")
    )


def _kind(node: Node, text_node: Node | None) -> str | None:
    """Classifies a pinned element as text, image or shape."""
    if node.tag in {"img", "svg"}:
        return "image"
    if node.tag in {"x-shape", "hr"}:
        return "shape"
    if text_node is not None:
        return "text"
    if node.tag == "div" and _painted(node):
        return "shape"
    return None


def _measure(node: Node, offset: tuple[float, float]) -> Box | None:
    """Measures a pinned element, or returns None if it cannot be."""
    text_node = None if node.tag in {"img", "svg"} else _text_node(node)
    kind = _kind(node, text_node)
    if kind is None:
        return None
    text = all_text(node) if text_node is not None else ""
    font_size = _font_size(text_node) if text_node is not None else 0.0
    width = _length(node.style.get("width"))
    if width is None:
        width = len(text) * CHAR_WIDTH * font_size
    height = _length(node.style.get("height"))
    if height is None:
        height = 0.0
        if text_node is not None:
            line = _line_height(text_node, font_size)
            height = _text_height(text, width, font_size, line)
    left = _length(node.style.get("left"))
    right = _length(node.style.get("right"))
    if left is None and right is not None:
        left = CANVAS_WIDTH - right - width
    top = _length(node.style.get("top"))
    bottom = _length(node.style.get("bottom"))
    if top is None and bottom is not None:
        top = CANVAS_HEIGHT - bottom - height
    if left is None or top is None:
        return None
    align = (_inherited(text_node, "text-align") or "left") if text_node else ""
    return Box(
        node,
        kind,
        left + offset[0],
        top + offset[1],
        width,
        height,
        font_size,
        align,
        text,
    )


def _connector(
    node: Node, offset: tuple[float, float]
) -> tuple[float, ...] | None:
    """Returns an x-connector's (x1, y1, x2, y2), offset, or None."""
    values = [_length(node.attrs.get(key)) for key in ("x1", "y1", "x2", "y2")]
    if any(value is None for value in values):
        return None
    x1, y1, x2, y2 = (float(value or 0.0) for value in values)
    return (x1 + offset[0], y1 + offset[1], x2 + offset[0], y2 + offset[1])


def _collect(
    slide: Slide, node: Node, offset: tuple[float, float], *, in_box: bool
) -> None:
    """Measures every pinned element under a node.

    Args:
        slide: The slide being filled.
        node: The node whose children to visit.
        offset: Canvas position of the node's coordinate origin.
        in_box: Whether the node is inside a measured box, so its flow
            text is already accounted for.
    """
    for child in node.children:
        if child.tag == "x-connector":
            coords = _connector(child, offset)
            if coords is not None:
                x1, y1, x2, y2 = coords
                slide.connectors.append((x1, y1, x2, y2))
            continue
        if child.tag == "aside":
            continue
        if child.style.get("position") == "absolute":
            box = _measure(child, offset)
            if box is not None:
                slide.boxes.append(box)
                _collect(slide, child, (box.left, box.top), in_box=True)
            else:
                _collect(slide, child, offset, in_box=in_box)
        elif not in_box and child.tag in TEXT_TAGS and all_text(child):
            slide.unmeasured.append(child)
        else:
            _collect(slide, child, offset, in_box=in_box)


def _assign_roles(slide: Slide) -> None:
    """Marks the title, dash, slide number and credits."""
    for box in slide.boxes:
        if (
            box.kind == "shape"
            and 120 <= box.width <= 190
            and 8 <= box.height <= 16
        ):
            box.role = "dash"
        elif (
            box.kind == "text" and box.text.isdigit() and box.top >= BOTTOM_BAND
        ):
            box.role = "number"
        elif (
            box.kind == "text"
            and box.font_size <= CREDIT_PX
            and box.top >= BOTTOM_BAND - 40
        ):
            box.role = "credit"
        elif (
            box.node.tag in {"h1", "h2"}
            and box.top <= 120
            and box.font_size >= 64
        ):
            box.role = "title"


def _infer_kind(slide: Slide) -> str:
    """Infers the slide's kind from its elements."""
    if slide.position == 1:
        return "title"
    title = next((b for b in slide.boxes if b.role == "title"), None)
    if title is None:
        texts = [
            b for b in slide.boxes if b.kind == "text" and b.role == "content"
        ]
        if any(b.text.strip().upper() == "EXTRA SLIDES" for b in texts):
            return "divider"
        return "statement" if texts else "blank"
    words = title.text.lower()
    if re.match(r"(summary|conclusions?)\b", words):
        return "summary"
    if re.match(r"(outline|agenda|this talk)\b", words):
        return "agenda"
    if re.match(r"acknowledge?ments?\b", words):
        return "acknowledgements"
    return "content"


def load_deck(root: pathlib.Path) -> list[Slide]:
    """Parses the deck under a root folder.

    Args:
        root: The folder holding project/deck.json and project/slides/.

    Returns:
        The slides, in deck order.

    Raises:
        FileNotFoundError: The index or a slide it lists is missing.
        json.JSONDecodeError: The index is not valid JSON.
    """
    with (root / "project" / "deck.json").open(encoding="utf-8") as handle:
        order = json.load(handle).get("order", [])
    slides = []
    for position, slide_id in enumerate(order, start=1):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", str(slide_id)):
            continue
        path = root / "project" / "slides" / f"{slide_id}.html"
        parser = _Parser()
        parser.feed(path.read_text(encoding="utf-8"))
        section = next(
            (n for n in _walk(parser.root) if n.tag == "section"), parser.root
        )
        slide = Slide(slide_id, position, section)
        _collect(slide, section, (0.0, 0.0), in_box=False)
        _assign_roles(slide)
        slide.kind = _infer_kind(slide)
        slides.append(slide)
    return slides


# ---------------------------------------------------------------------------
# House rules.
# ---------------------------------------------------------------------------


def _first_face(node: Node) -> str:
    """Returns the first family of a node's font stack, lower case."""
    stack = _inherited(node, "font-family") or ""
    return stack.split(",")[0].strip().strip("'\"").lower()


def _is_title_case(title: str) -> bool:
    """Whether every word of four letters or more is capitalized."""
    for index, word in enumerate(title.split()):
        bare = word.strip("“”\"'(),:?![]")
        if not bare or not bare[0].isalpha():
            continue
        if any(char.isdigit() or char in "._()" for char in bare):
            continue
        if index > 0 and bare.lower() in SMALL_WORDS:
            continue
        if len(bare) >= 4 and bare[0].islower():
            return False
    return True


def check_style(slide: Slide) -> Report:
    """Checks one slide against the house rules.

    Args:
        slide: The parsed slide.

    Returns:
        (severity, code, message) tuples.
    """
    report: Report = []
    background = slide.root.style.get("background", "").replace(" ", "").lower()
    if background not in WHITE:
        report.append(
            (
                "ERROR",
                "background",
                f"background {background or 'unset'}; use #ffffff",
            )
        )
    for node in _walk(slide.root):
        _check_node(slide, node, report)
    _check_title(slide, report)
    _check_chrome(slide, report)
    words = len(all_text(slide.root).split())
    if words > MAX_WORDS:
        report.append(("WARN", "words", f"{words} words; aim for 30 or fewer"))
    if slide.kind == "content" and not any(
        b.kind == "image" for b in slide.boxes
    ):
        report.append(("WARN", "figure", "no figure; lead with one"))
    return report


def _check_node(slide: Slide, node: Node, report: Report) -> None:
    """Checks one element: notes, lists, placeholders, colours."""
    if node.tag == "aside":
        report.append(("ERROR", "notes", "speaker notes present"))
    elif node.tag == "table":
        report.append(("WARN", "table", "a table; place it as an image"))
    elif node.tag in {"ul", "ol"}:
        items = sum(1 for child in node.children if child.tag == "li")
        if slide.kind not in LIST_KINDS:
            report.append(
                (
                    "ERROR",
                    "bullets",
                    f"a {items}-item list on a {slide.kind} slide",
                )
            )
        elif items > MAX_ITEMS:
            report.append(
                ("ERROR", "bullets", f"{items} items; at most {MAX_ITEMS}")
            )
    elif node.tag == "img" and not node.attrs.get("src"):
        alt = node.attrs.get("alt", "")
        report.append(
            ("ERROR", "placeholder", f"image slot with no src: {alt[:40]!r}")
        )
    color = node.style.get("color", "").lower()
    if color and color not in PALETTE:
        report.append(("WARN", "color", f"text colour {color}"))
    if node.tag in TEXT_TAGS:
        _check_text(slide, node, report)


def _check_text(slide: Slide, node: Node, report: Report) -> None:
    """Checks a text element's placeholders, typeface and size."""
    text = all_text(node)
    if not text:
        return
    if node.tag in {"h1", "h2", "h3", "p"}:
        for match in _PLACEHOLDER.finditer(text):
            report.append(
                (
                    "ERROR",
                    "placeholder",
                    f"template text left: {match.group(0)[:40]!r}",
                )
            )
    face = _first_face(node)
    bengali_ok = face == BENGALI_FACE and _BENGALI.search(text)
    if face and face not in ALLOWED_FACES and not bengali_ok:
        report.append(("ERROR", "font", f"typeface {face!r}; use Noto Sans"))
    size = _font_size(node)
    if size >= MIN_TEXT_PX:
        return
    credit_ok = size == CREDIT_PX and (
        _CITATION.search(text) or text.isdigit() or _in_bottom_band(slide, node)
    )
    caption_ok = size == CAPTION_PX and slide.kind == "acknowledgements"
    if not (credit_ok or caption_ok):
        report.append(
            (
                "ERROR",
                "text-size",
                f"{size:g} px text {text[:30]!r} (credits 24, else ≥ 36)",
            )
        )


def _in_bottom_band(slide: Slide, node: Node) -> bool:
    """Whether a node is (inside) a box on the bottom credit band."""
    return any(
        box.top >= BOTTOM_BAND - 40 and node in _walk(box.node)
        for box in slide.boxes
    )


def _check_title(slide: Slide, report: Report) -> None:
    """Checks a slide title: weight, period, case, length, fit."""
    title = next((b for b in slide.boxes if b.role == "title"), None)
    if title is None or slide.kind == "title":
        return
    node = title.node
    default_weight = HEADING_DEFAULTS.get(node.tag, (0.0, "400", 1.0))[1]
    weight = node.style.get("font-weight", default_weight)
    bold = [c for c in node.children if c.tag in {"b", "strong"}]
    if weight in BOLD_WEIGHTS or (bold and all_text(bold[0]) == title.text):
        report.append(("ERROR", "title-bold", f"bold title {title.text!r}"))
    if title.text.endswith("."):
        report.append(
            (
                "ERROR",
                "title-period",
                f"title ends with a period: {title.text!r}",
            )
        )
    if not _is_title_case(title.text):
        report.append(("WARN", "title-case", f"not Title Case: {title.text!r}"))
    words = len(title.text.split())
    if words > MAX_TITLE_WORDS:
        report.append(("WARN", "title-length", f"{words}-word title"))
    needed = len(title.text) * CHAR_WIDTH * title.font_size
    if needed > title.width:
        report.append(
            (
                "WARN",
                "title-wrap",
                f"title needs about {needed:.0f} px of {title.width:.0f};"
                " shorten it",
            )
        )


def _check_chrome(slide: Slide, report: Report) -> None:
    """Checks the dash and the slide number."""
    roles = {box.role for box in slide.boxes}
    number = next((b for b in slide.boxes if b.role == "number"), None)
    if slide.kind in CHROME_KINDS:
        if "dash" not in roles:
            report.append(("ERROR", "chrome", "no blue dash under the title"))
        if number is None:
            report.append(("ERROR", "chrome", "no slide number"))
    if number is not None and int(number.text) != slide.position:
        report.append(
            (
                "ERROR",
                "number",
                f"slide number reads {number.text};"
                f" it is slide {slide.position}",
            )
        )


# ---------------------------------------------------------------------------
# Alignment.
# ---------------------------------------------------------------------------


def _clusters(
    values: Sequence[tuple[float, _T]], tolerance: float
) -> list[list[tuple[float, _T]]]:
    """Groups (value, item) pairs whose sorted values chain within tolerance."""
    groups: list[list[tuple[float, _T]]] = []
    for value, item in sorted(values, key=lambda pair: pair[0]):
        if groups and value - groups[-1][-1][0] <= tolerance:
            groups[-1].append((value, item))
        else:
            groups.append([(value, item)])
    return groups


def _snap_target(values: Sequence[float], guides: Iterable[float]) -> int:
    """Picks the value a near-miss group snaps to: a guide, else the mode."""
    counts = collections.Counter(round(value) for value in values)
    guide_lines = {round(guide) for guide in guides}
    in_group = [value for value in counts if value in guide_lines]
    if in_group:
        return in_group[0]
    return max(counts, key=lambda value: (counts[value], -value))


def _edges(box: Box) -> dict[str, float]:
    """Returns the horizontal edges alignment should compare, by axis."""
    if box.kind != "text":
        return {"left": box.left, "center": box.center_x, "right": box.right}
    if box.align == "center":
        return {"center": box.center_x}
    if box.align in {"right", "end"}:
        return {"right": box.right}
    return {"left": box.left}


def _guides(axis: str, title: Box | None) -> set[float]:
    """Returns the guide lines for an axis on a slide."""
    guides = set(GUIDES[axis])
    if title is not None and axis == "left":
        guides.add(title.left)
    return guides


def check_alignment(
    slide: Slide, tolerance: float
) -> tuple[Report, float | None, set[tuple[int, str]]]:
    """Checks one slide's geometry.

    Args:
        slide: The parsed slide.
        tolerance: Edges closer than this, in px, should coincide.

    Returns:
        A tuple (report, score, flagged): (severity, code, message)
        tuples; the share of content edges on a shared line, or None when
        there are none; and (id(box), axis) pairs already flagged, so the
        cross-slide pass does not repeat them.
    """
    report: Report = []
    for box in slide.boxes:
        off_canvas = (
            box.left < -0.5
            or box.top < -0.5
            or box.right > CANVAS_WIDTH + 0.5
            or box.bottom > CANVAS_HEIGHT + 0.5
        )
        near_edge = (
            box.left < EDGE_MARGIN
            or box.top < EDGE_MARGIN
            or box.right > CANVAS_WIDTH - EDGE_MARGIN
        )
        if off_canvas:
            report.append(
                ("ERROR", "canvas", f"{box.label()} runs off the canvas")
            )
        elif box.role == "content" and near_edge:
            report.append(
                (
                    "WARN",
                    "margin",
                    f"{box.label()} is within {EDGE_MARGIN} px of the edge",
                )
            )
    for node in slide.unmeasured:
        report.append(
            (
                "WARN",
                "unmeasured",
                f"{node.tag} {all_text(node)[:30]!r} is in flow layout; pin it",
            )
        )
    content = [b for b in slide.boxes if b.role == "content"]
    aligned = [b for b in slide.boxes if b.role in {"content", "credit"}]
    title = next((b for b in slide.boxes if b.role == "title"), None)
    misses, flagged = _near_misses(aligned, title, tolerance)
    report.extend(misses)
    report.extend(_spacing(content))
    report.extend(_overlaps(content))
    report.extend(_arrows(slide))
    return report, _score(content, title), flagged


def _near_misses(
    boxes: Sequence[Box], title: Box | None, tolerance: float
) -> tuple[Report, set[tuple[int, str]]]:
    """Reports elements with no aligned edge that nearly line up with one.

    An element is aligned when one of its horizontal edges (left, centre or
    right, by its alignment) is exactly on another element's edge or a
    guide line. An element that is not gets one finding: its nearest miss
    within tolerance, a guide line first. Between two elements that miss
    each other, the later one in the file moves. Tops of content elements within
    tolerance of an earlier element's top are reported the same way.

    Args:
        boxes: Content and credit boxes, in file order.
        title: The slide's title box, if any.
        tolerance: The largest offset, in px, that counts as a near-miss.

    Returns:
        A tuple (report, flagged) of findings and (id(box), axis) pairs.
    """
    report: Report = []
    flagged: set[tuple[int, str]] = set()
    for index, box in enumerate(boxes):
        if _aligned(box, boxes, title):
            continue
        best: tuple[bool, float, str, float] | None = None
        for axis, value in _edges(box).items():
            guides = _guides(axis, title)
            for target in _anchors(axis, index, boxes, title):
                offset = abs(value - target)
                rank = (target not in guides, offset, axis, target)
                if 0.5 < offset <= tolerance and (best is None or rank < best):
                    best = rank
        if best is not None:
            _, offset, axis, target = best
            flagged.add((id(box), axis))
            report.append(
                (
                    "WARN",
                    "near-miss",
                    f"{box.label()}: {axis} {_edges(box)[axis]:.0f} px"
                    f" is {offset:.0f} px "
                    f"off {target:.0f}; {_fix(axis, box, target)}",
                )
            )
    for index, box in enumerate(boxes):
        if box.role != "content":
            continue
        for earlier in boxes[:index]:
            offset = abs(box.top - earlier.top)
            if earlier.role == "content" and 0.5 < offset <= tolerance:
                flagged.add((id(box), "top"))
                report.append(
                    (
                        "WARN",
                        "near-miss",
                        f"{box.label()}: top {box.top:.0f} px is {offset:.0f}"
                        f" px off {earlier.label()} at {earlier.top:.0f};"
                        f" set top:{earlier.top:.0f}px",
                    )
                )
                break
    return report, flagged


def _even_rows(boxes: Sequence[Box]) -> frozenset[int]:
    """Ids of boxes in rows of three or more like, evenly spaced elements."""
    members: set[int] = set()
    for kind in ("image", "shape", "text"):
        candidates = [(box.top, box) for box in boxes if box.kind == kind]
        for row in _clusters(candidates, ROW_TOLERANCE):
            if len(row) < 3:
                continue
            ordered = sorted((box for _, box in row), key=lambda box: box.left)
            gaps = [b.left - a.right for a, b in zip(ordered, ordered[1:])]
            if min(gaps) >= 0 and max(gaps) - min(gaps) <= GAP_TOLERANCE:
                members.update(id(box) for box in ordered)
    return frozenset(members)


def _aligned(box: Box, boxes: Sequence[Box], title: Box | None) -> bool:
    """Whether a box sits in an even row or has an edge exactly on a line."""
    if id(box) in _even_rows(boxes):
        return True
    for axis, value in _edges(box).items():
        lines = {round(guide) for guide in _guides(axis, title)}
        for other in boxes:
            if other is not box and axis in _edges(other):
                lines.add(round(_edges(other)[axis]))
        if round(value) in lines:
            return True
    return False


def _anchors(
    axis: str, index: int, boxes: Sequence[Box], title: Box | None
) -> list[float]:
    """Lines a box may snap to: guides, aligned boxes, earlier boxes."""
    anchors = list(_guides(axis, title))
    for position, other in enumerate(boxes):
        if position == index or axis not in _edges(other):
            continue
        if position < index or _aligned(other, boxes, title):
            anchors.append(_edges(other)[axis])
    return anchors


def _fix(axis: str, box: Box, target: float) -> str:
    """Says how to move a box so the given edge lands on target."""
    if axis == "top":
        return f"set top:{target:.0f}px"
    shift = {"left": 0.0, "center": box.width / 2, "right": box.width}[axis]
    return f"set left:{target - shift:.0f}px"


def _spacing(content: Sequence[Box]) -> Report:
    """Reports rows of three or more like elements with uneven gaps."""
    report: Report = []
    for kind in ("image", "shape", "text"):
        boxes = [(box.top, box) for box in content if box.kind == kind]
        for row in _clusters(boxes, ROW_TOLERANCE):
            if len(row) < 3:
                continue
            ordered = sorted((box for _, box in row), key=lambda box: box.left)
            gaps = [
                round(b.left - a.right) for a, b in zip(ordered, ordered[1:])
            ]
            if min(gaps) >= 0 and max(gaps) - min(gaps) > GAP_TOLERANCE:
                even = sum(gaps) / len(gaps)
                report.append(
                    (
                        "WARN",
                        "spacing",
                        f"{len(ordered)} {kind}s in a row at top"
                        f" {ordered[0].top:.0f} "
                        f"have gaps {gaps} px; make each {even:.0f} px",
                    )
                )
    return report


def _overlaps(content: Sequence[Box]) -> Report:
    """Reports text boxes that overlap each other."""
    report: Report = []
    texts = [box for box in content if box.kind == "text"]
    for index, first in enumerate(texts):
        for second in texts[index + 1 :]:
            across = min(first.right, second.right) - max(
                first.left, second.left
            )
            down = min(first.bottom, second.bottom) - max(first.top, second.top)
            if across > 8 and down > 8:
                report.append(
                    (
                        "WARN",
                        "overlap",
                        f"{first.label()} and {second.label()} overlap"
                        f" by about {down:.0f} px",
                    )
                )
    return report


def _arrows(slide: Slide) -> Report:
    """Reports arrows whose tail is not at any text box."""
    report: Report = []
    texts = [b for b in slide.boxes if b.kind == "text" and b.role == "content"]
    for x1, y1, x2, y2 in slide.connectors:
        at_label = any(
            box.left - ARROW_REACH <= x1 <= box.right + ARROW_REACH
            and box.top - ARROW_REACH <= y1 <= box.bottom + ARROW_REACH
            for box in texts
        )
        if not at_label:
            report.append(
                (
                    "WARN",
                    "arrow",
                    f"arrow ({x1:.0f}, {y1:.0f}) to ({x2:.0f}, {y2:.0f})"
                    " starts at no label",
                )
            )
    return report


def _score(content: Sequence[Box], title: Box | None) -> float | None:
    """Share of content elements aligned (an edge on a line, or an even row)."""
    if not content:
        return None
    return sum(_aligned(box, content, title) for box in content) / len(content)


def check_drift(
    slides: Sequence[Slide], tolerance: float, flagged: set[tuple[int, str]]
) -> list[Finding]:
    """Checks that chrome and repeated elements keep their places.

    Args:
        slides: The parsed slides, in order.
        tolerance: Cross-slide offsets up to this, in px, count as drift.
        flagged: (id(box), axis) pairs already reported as near-misses.

    Returns:
        The findings.
    """
    findings: list[Finding] = []
    chrome = [s for s in slides if s.kind in CHROME_KINDS]
    for role in ("title", "dash", "number", "credit"):
        for axis in ("left",) if role == "credit" else ("left", "top"):
            entries: list[tuple[float, tuple[Slide, Box]]] = []
            for slide in chrome:
                entries.extend(
                    (getattr(box, axis), (slide, box))
                    for box in slide.boxes
                    if box.role == role
                )
            findings.extend(
                _drift(entries, axis, role, math.inf, "ERROR", flagged)
            )
    lefts: dict[
        tuple[str, str, float, str], list[tuple[float, tuple[Slide, Box]]]
    ]
    lefts = collections.defaultdict(list)
    tops: dict[
        tuple[str, str, float, str], list[tuple[float, tuple[Slide, Box]]]
    ]
    tops = collections.defaultdict(list)
    for slide in slides:
        for box in slide.boxes:
            if box.role != "content":
                continue
            key = (box.kind, box.node.tag, box.font_size, box.align)
            lefts[key].append((box.left, (slide, box)))
            if box.kind == "image":
                tops[key].append((box.top, (slide, box)))
    for entries in lefts.values():
        findings.extend(_drift(entries, "left", "", tolerance, "WARN", flagged))
    for entries in tops.values():
        findings.extend(_drift(entries, "top", "", tolerance, "WARN", flagged))
    return findings


def _drift(
    entries: Sequence[tuple[float, tuple[Slide, Box]]],
    axis: str,
    role: str,
    tolerance: float,
    severity: str,
    flagged: set[tuple[int, str]],
) -> list[Finding]:
    """Flags entries near, but not at, their group's most common value."""
    findings = []
    for group in _clusters(entries, tolerance):
        counts = collections.Counter(round(value) for value, _ in group)
        if len(counts) < 2 or len({id(slide) for _, (slide, _) in group}) < 2:
            continue
        target = counts.most_common(1)[0][0]
        for value, (slide, box) in group:
            if round(value) == target or (id(box), axis) in flagged:
                continue
            findings.append(
                Finding(
                    slide.slide_id,
                    slide.position,
                    severity,
                    "drift",
                    f"{role or box.label()}: {axis} {value:.0f} px here,"
                    f" {target} px "
                    f"on the other slides; set {axis}:{target}px",
                )
            )
    return findings


def check(
    root: pathlib.Path, tolerance: float = 16.0
) -> tuple[list[Finding], dict[str, float | None]]:
    """Checks a whole deck.

    Args:
        root: The folder holding project/deck.json and project/slides/.
        tolerance: Near-miss tolerance, in px.

    Returns:
        A tuple (findings, scores): the findings in slide order, and each
        slide's alignment score (0-1, or None) by slide id.
    """
    slides = load_deck(root)
    findings: list[Finding] = []
    scores: dict[str, float | None] = {}
    flagged: set[tuple[int, str]] = set()
    for slide in slides:
        style = check_style(slide)
        alignment, scores[slide.slide_id], seen = check_alignment(
            slide, tolerance
        )
        flagged |= seen
        for item in dict.fromkeys(style + alignment):
            findings.append(Finding(slide.slide_id, slide.position, *item))
    findings.extend(check_drift(slides, tolerance, flagged))
    findings.sort(key=lambda f: (f.position, f.severity != "ERROR", f.code))
    return findings, scores


def deck_score(scores: dict[str, float | None]) -> float | None:
    """Returns the mean alignment score over slides that have one."""
    measured = [score for score in scores.values() if score is not None]
    return sum(measured) / len(measured) if measured else None


def main() -> None:
    """Parses arguments, checks the deck, prints the report."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", type=pathlib.Path)
    parser.add_argument("--tolerance", type=float, default=16.0)
    parser.add_argument(
        "--strict", action="store_true", help="fail on WARN too"
    )
    parser.add_argument("--json", action="store_true", help="print JSON")
    args = parser.parse_args()
    try:
        findings, scores = check(args.root, args.tolerance)
    except (FileNotFoundError, json.JSONDecodeError) as error:
        print(f"check_deck failed: {error}", file=sys.stderr)
        sys.exit(2)
    overall = deck_score(scores)
    if args.json:
        payload = {
            "findings": [dataclasses.asdict(f) for f in findings],
            "scores": scores,
            "deck_score": overall,
        }
        print(json.dumps(payload, indent=1, ensure_ascii=False))
    else:
        for f in findings:
            print(
                f"slide {f.position} ({f.slide}): {f.severity} {f.code}:"
                f" {f.message}"
            )
        for slide_id, score in scores.items():
            if score is not None:
                print(f"alignment {slide_id}: {score:.0%}")
        errors = sum(f.severity == "ERROR" for f in findings)
        prefix = (
            f"deck alignment {overall:.0%}; " if overall is not None else ""
        )
        print(f"{prefix}{len(findings)} findings, {errors} errors")
    failing = {"ERROR", "WARN"} if args.strict else {"ERROR"}
    sys.exit(1 if any(f.severity in failing for f in findings) else 0)


if __name__ == "__main__":
    main()
