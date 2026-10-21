#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["python-pptx>=1.0", "lxml>=5"]
# ///
"""Regenerate assets/template.pptx, the house slide template.

    uv run scripts/build_template.py [--output assets/template.pptx]

The template is derived from python-pptx's own default deck so that it can
be rebuilt from nothing: 16:9 at 13.333 x 7.5 in, the theme fonts set to
Aptos Display / Aptos, the theme colours set to the house palette, and three
layouts:

  Title    title slide: left title, accent dash, name line; no slide number
  Content  title top-left, accent dash under it, slide number bottom-right
  Blank    nothing; statement, quote and divider slides draw their own

Geometry is measured from the author's own Grandview theme (DashVTI): the
title box at (1.00, 0.30) in, the dash a 6 pt accent-1 line 1.07 in long at
(1.083, 1.128) in, the slide number at (11.82, 6.95) in.
"""

import argparse
import pathlib

from lxml import etree
import pptx
from pptx import util
from pptx.opc import constants
from pptx.oxml import ns
import pptx.presentation

# PowerPoint's widescreen size, exactly: 13.333... x 7.5 in.
SLIDE_WIDTH_EMU = 12192000
SLIDE_HEIGHT_EMU = 6858000

HEADING_FONT = "Aptos Display"
BODY_FONT = "Aptos"
BENGALI_FONT = "Vrinda"
THEME_NAME = "slides-style"

# Theme colours. accent1 is the Grandview dash blue, accent2 the house
# emphasis red; accents 3-6 are matplotlib's C0-C3 so drawn shapes can match
# the figures; hlink is the Grandview theme's link green.
THEME_COLORS = {
    "dk1": "000000",
    "lt1": "FFFFFF",
    "dk2": "1F1F1F",
    "lt2": "F2F2F2",
    "accent1": "1973EB",
    "accent2": "C00000",
    "accent3": "1F77B4",
    "accent4": "FF7F0E",
    "accent5": "2CA02C",
    "accent6": "9467BD",
    "hlink": "1AC16E",
    "folHlink": "1AC16E",
}

TITLE_SIZE_PT = 40
TITLE_SLIDE_SIZE_PT = 44
BODY_SIZE_PT = 24
SLIDE_NUMBER_SIZE_PT = 10

TITLE_BOX_IN = (1.00, 0.30, 11.33, 0.75)
DASH_IN = (1.083, 1.128, 1.070)
DASH_WEIGHT_PT = 6
SLIDE_NUMBER_BOX_IN = (11.82, 6.95, 0.79, 0.40)
BODY_BOX_IN = (1.00, 1.45, 11.33, 5.30)
TITLE_SLIDE_TITLE_IN = (1.00, 0.80, 6.90, 3.80)
TITLE_SLIDE_DASH_IN = (1.083, 4.85, 1.070)
TITLE_SLIDE_NAME_IN = (1.00, 4.98, 6.90, 0.60)

_P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"

_KEEP_LAYOUTS = {
    "Title Slide": "Title",
    "Title Only": "Content",
    "Blank": "Blank",
}


def _emu(inches: float) -> int:
    """Converts inches to whole EMU."""
    return int(round(inches * 914400))


def _set_theme(theme_xml: bytes) -> bytes:
    """Returns the theme with the house name, fonts and colours.

    Args:
        theme_xml: The default theme part, as bytes.

    Returns:
        The edited theme part, as bytes.
    """
    root = etree.fromstring(theme_xml)
    root.set("name", THEME_NAME)
    scheme = root.find(f".//{ns.qn('a:clrScheme')}")
    scheme.set("name", THEME_NAME)
    for slot, value in THEME_COLORS.items():
        element = scheme.find(ns.qn(f"a:{slot}"))
        for child in list(element):
            element.remove(child)
        etree.SubElement(element, ns.qn("a:srgbClr"), val=value)
    fonts = root.find(f".//{ns.qn('a:fontScheme')}")
    fonts.set("name", THEME_NAME)
    for tag, face in (
        ("a:majorFont", HEADING_FONT),
        ("a:minorFont", BODY_FONT),
    ):
        group = fonts.find(ns.qn(tag))
        group.find(ns.qn("a:latin")).set("typeface", face)
        for script_font in group.findall(ns.qn("a:font")):
            if script_font.get("script") == "Beng":
                script_font.set("typeface", BENGALI_FONT)
    return etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", standalone=True
    )


def _set_xfrm(shape_element: etree._Element, box: tuple[float, ...]) -> None:
    """Gives a shape an explicit position and size, in inches.

    Args:
        shape_element: A p:sp element.
        box: (left, top, width, height) in inches.
    """
    sp_pr = shape_element.find(ns.qn("p:spPr"))
    for old in sp_pr.findall(ns.qn("a:xfrm")):
        sp_pr.remove(old)
    xfrm = etree.Element(ns.qn("a:xfrm"))
    left, top, width, height = box
    etree.SubElement(xfrm, ns.qn("a:off"), x=str(_emu(left)), y=str(_emu(top)))
    etree.SubElement(
        xfrm, ns.qn("a:ext"), cx=str(_emu(width)), cy=str(_emu(height))
    )
    sp_pr.insert(0, xfrm)


def _placeholder_type(shape_element: etree._Element) -> str | None:
    """Returns the placeholder type of a p:sp, or None if it is not one."""
    ph = shape_element.find(f".//{ns.qn('p:ph')}")
    if ph is None:
        return None
    return ph.get("type", "body")


def _dash_xml(shape_id: int, left: float, top: float, width: float) -> str:
    """Returns the p:cxnSp markup of the accent dash."""
    return (
        f'<p:cxnSp xmlns:p="{_P_NS}" xmlns:a="{_A_NS}">'
        f'<p:nvCxnSpPr><p:cNvPr id="{shape_id}" name="Accent Dash"/>'
        '<p:cNvCxnSpPr/><p:nvPr userDrawn="1"/></p:nvCxnSpPr>'
        f'<p:spPr><a:xfrm><a:off x="{_emu(left)}" y="{_emu(top)}"/>'
        f'<a:ext cx="{_emu(width)}" cy="0"/></a:xfrm>'
        '<a:prstGeom prst="line"><a:avLst/></a:prstGeom>'
        f'<a:ln w="{DASH_WEIGHT_PT * 12700}">'
        '<a:solidFill><a:schemeClr val="accent1"/></a:solidFill></a:ln>'
        "</p:spPr></p:cxnSp>"
    )


def _add_dash(
    layout_element: etree._Element, left: float, top: float, width: float
) -> None:
    """Appends the accent dash to a layout's shape tree."""
    tree = layout_element.find(f".//{ns.qn('p:spTree')}")
    ids = [int(e.get("id")) for e in tree.iter(ns.qn("p:cNvPr"))]
    tree.append(etree.fromstring(_dash_xml(max(ids) + 1, left, top, width)))


def _set_level(
    level: etree._Element, size_pt: int, *, bullet: bool, font: str
) -> None:
    """Rewrites one a:lvlNpPr of a master text style.

    Args:
        level: The a:lvl1pPr (or deeper) element.
        size_pt: The level's default size, in points.
        bullet: Whether the level carries a bullet character.
        font: The theme font reference, "+mj-lt" or "+mn-lt".
    """
    level.set("algn", "l")
    for child in list(level):
        if etree.QName(child).localname in {
            "buNone",
            "buChar",
            "buFont",
            "buAutoNum",
            "buSzPct",
        }:
            level.remove(child)
    def_rpr = level.find(ns.qn("a:defRPr"))
    if def_rpr is None:
        def_rpr = etree.SubElement(level, ns.qn("a:defRPr"))
    def_rpr.set("sz", str(size_pt * 100))
    def_rpr.set("b", "0")
    latin = def_rpr.find(ns.qn("a:latin"))
    if latin is not None:
        latin.set("typeface", font)
    index = list(level).index(def_rpr)
    if bullet:
        level.insert(index, etree.Element(ns.qn("a:buChar"), char="•"))
        level.insert(index, etree.Element(ns.qn("a:buFont"), typeface="Arial"))
    else:
        level.insert(index, etree.Element(ns.qn("a:buNone")))


def _style_master(master: pptx.slide.SlideMaster) -> None:
    """Sets the master's text styles, placeholder boxes and background."""
    element = master._element  # noqa: SLF001 - python-pptx exposes no API.
    tx_styles = element.find(ns.qn("p:txStyles"))
    title_level = tx_styles.find(ns.qn("p:titleStyle")).find(ns.qn("a:lvl1pPr"))
    _set_level(title_level, TITLE_SIZE_PT, bullet=False, font="+mj-lt")
    body = tx_styles.find(ns.qn("p:bodyStyle"))
    for depth, level in enumerate(body.findall("*")):
        if etree.QName(level).localname.startswith("lvl"):
            size = BODY_SIZE_PT if depth == 0 else BODY_SIZE_PT - 4
            _set_level(level, size, bullet=True, font="+mn-lt")
    boxes = {
        "title": TITLE_BOX_IN,
        "body": BODY_BOX_IN,
        "sldNum": SLIDE_NUMBER_BOX_IN,
        "dt": (1.00, 6.95, 3.00, 0.40),
        "ftr": (4.50, 6.95, 4.33, 0.40),
    }
    for shape in element.iter(ns.qn("p:sp")):
        kind = _placeholder_type(shape)
        if kind in boxes:
            _set_xfrm(shape, boxes[kind])
        if kind == "title":
            body_pr = shape.find(f".//{ns.qn('a:bodyPr')}")
            body_pr.set("anchor", "b")
            body_pr.set("wrap", "square")
        if kind == "sldNum":
            for def_rpr in shape.iter(ns.qn("a:defRPr")):
                def_rpr.set("sz", str(SLIDE_NUMBER_SIZE_PT * 100))
            for para in shape.iter(ns.qn("a:pPr")):
                para.set("algn", "r")


def _strip_placeholders(layout_element: etree._Element, drop: set[str]) -> None:
    """Removes the named placeholder types from a layout."""
    tree = layout_element.find(f".//{ns.qn('p:spTree')}")
    for shape in list(tree.findall(ns.qn("p:sp"))):
        if _placeholder_type(shape) in drop:
            tree.remove(shape)


def _style_layouts(presentation: pptx.presentation.Presentation) -> None:
    """Keeps, renames and reshapes the three house layouts."""
    layouts = presentation.slide_master.slide_layouts
    for layout in list(layouts):
        if layout.name not in _KEEP_LAYOUTS:
            layouts.remove(layout)
    for layout in layouts:
        element = layout._element  # noqa: SLF001 - no public API for this.
        new_name = _KEEP_LAYOUTS[layout.name]
        element.find(ns.qn("p:cSld")).set("name", new_name)
        if new_name == "Title":
            _strip_placeholders(element, {"dt", "ftr", "sldNum"})
            for shape in element.iter(ns.qn("p:sp")):
                kind = _placeholder_type(shape)
                if kind == "ctrTitle":
                    _set_xfrm(shape, TITLE_SLIDE_TITLE_IN)
                    _title_slide_text(shape, TITLE_SLIDE_SIZE_PT, anchor="b")
                elif kind == "subTitle":
                    _set_xfrm(shape, TITLE_SLIDE_NAME_IN)
                    _title_slide_text(shape, BODY_SIZE_PT, anchor="t")
            _add_dash(element, *TITLE_SLIDE_DASH_IN)
        elif new_name == "Content":
            _strip_placeholders(element, {"dt", "ftr"})
            for shape in element.iter(ns.qn("p:sp")):
                if _placeholder_type(shape) == "title":
                    _set_xfrm(shape, TITLE_BOX_IN)
                elif _placeholder_type(shape) == "sldNum":
                    _set_xfrm(shape, SLIDE_NUMBER_BOX_IN)
            _add_dash(element, *DASH_IN)
        else:
            _strip_placeholders(element, {"dt", "ftr", "sldNum"})


def _title_slide_text(
    shape_element: etree._Element, size_pt: int, *, anchor: str
) -> None:
    """Left-aligns a title-slide placeholder at a fixed size, no bullet."""
    body_pr = shape_element.find(f".//{ns.qn('a:bodyPr')}")
    body_pr.set("anchor", anchor)
    for child in list(body_pr):
        body_pr.remove(child)
    etree.SubElement(body_pr, ns.qn("a:noAutofit"))
    list_style = shape_element.find(f".//{ns.qn('a:lstStyle')}")
    for child in list(list_style):
        list_style.remove(child)
    level = etree.SubElement(
        list_style, ns.qn("a:lvl1pPr"), algn="l", indent="0"
    )
    level.set("marL", "0")
    etree.SubElement(level, ns.qn("a:buNone"))
    etree.SubElement(level, ns.qn("a:defRPr"), sz=str(size_pt * 100), b="0")


def _set_background(master: pptx.slide.SlideMaster) -> None:
    """Gives the master an explicit white background."""
    c_sld = master._element.find(ns.qn("p:cSld"))  # noqa: SLF001 - no API.
    for old in c_sld.findall(ns.qn("p:bg")):
        c_sld.remove(old)
    background = etree.fromstring(
        f'<p:bg xmlns:p="{_P_NS}" xmlns:a="{_A_NS}">'
        '<p:bgPr><a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill>'
        "<a:effectLst/></p:bgPr></p:bg>"
    )
    c_sld.insert(0, background)


def build(output: pathlib.Path) -> None:
    """Writes the house template.

    Args:
        output: Where to write the .pptx.
    """
    presentation = pptx.Presentation()
    presentation.slide_width = util.Emu(SLIDE_WIDTH_EMU)
    presentation.slide_height = util.Emu(SLIDE_HEIGHT_EMU)
    master = presentation.slide_master
    theme = master.part.part_related_by(constants.RELATIONSHIP_TYPE.THEME)
    theme._blob = _set_theme(theme.blob)  # noqa: SLF001 - parts are opaque.
    _style_master(master)
    _set_background(master)
    _style_layouts(presentation)
    presentation.core_properties.title = "slides-style template"
    presentation.core_properties.author = ""
    output.parent.mkdir(parents=True, exist_ok=True)
    presentation.save(str(output))


def main() -> None:
    """Parses arguments and writes the template."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    default = pathlib.Path(__file__).parents[1] / "assets" / "template.pptx"
    parser.add_argument("--output", type=pathlib.Path, default=default)
    args = parser.parse_args()
    build(args.output)
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
