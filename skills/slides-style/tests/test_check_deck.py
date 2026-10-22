"""Tests for check_deck.py (house rules and alignment) and latex_to_svg.py.

Run with:
    python -m pytest skills/slides-style/tests
"""

from collections.abc import Iterable
import importlib.util
import json
import pathlib
import shutil
import subprocess
import sys
import types
from typing import Any

import pytest

_ROOT = pathlib.Path(__file__).parents[1]
_TEMPLATE = _ROOT / "assets" / "claude-slides-template"
_EVAL_DECKS = _ROOT / "evals" / "review-decks" / "input"
_FONT = "font-family:'Noto Sans', Arial, sans-serif"


def _load(name: str, path: pathlib.Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


checker = _load("check_deck", _ROOT / "scripts" / "check_deck.py")
svg_tool = _load("latex_to_svg", _ROOT / "scripts" / "latex_to_svg.py")


def _deck(tmp_path: pathlib.Path, slides: dict[str, str]) -> pathlib.Path:
    """Writes a deck folder from slide id -> section body markup."""
    base = tmp_path / "project"
    (base / "slides").mkdir(parents=True)
    index = {"v": 4, "order": list(slides)}
    (base / "deck.json").write_text(json.dumps(index))
    for slide_id, body in slides.items():
        style = f"background:#ffffff; {_FONT}"
        html = f'<section id="{slide_id}" style="{style}">{body}</section>'
        (base / "slides" / f"{slide_id}.html").write_text(html)
    return tmp_path


def _chrome(title: str, number: int, left: int = 144) -> str:
    return (
        f'<h2 style="position:absolute; left:{left}px; top:48px; width:1632px; '
        f'font-size:80px; font-weight:400">{title}</h2>'
        '<div style="position:absolute; left:156px; top:156px; width:154px; '
        'height:12px; background:#1973eb"></div>'
        '<p style="position:absolute; left:1702px; top:1000px; width:114px; '
        f'font-size:24px; text-align:right">{number}</p>'
    )


def _text(
    text: str, left: float, top: float, width: float = 600, size: int = 40
) -> str:
    return (
        f'<p style="position:absolute; left:{left}px; top:{top}px; '
        f'width:{width}px; font-size:{size}px">{text}</p>'
    )


def _image(
    left: float, top: float, width: float = 300, height: float = 300
) -> str:
    return (
        f'<img src="/_blob/x" alt="figure" style="position:absolute; '
        f'left:{left}px; top:{top}px; width:{width}px; height:{height}px">'
    )


def _codes(findings: Iterable[Any], severity: str | None = None) -> set[str]:
    return {
        f.code for f in findings if severity is None or f.severity == severity
    }


def test_template_is_aligned_and_only_has_placeholders():
    findings, scores = checker.check(_TEMPLATE)
    assert _codes(findings) == {"placeholder"}
    assert all(score == 1.0 for score in scores.values() if score is not None)


@pytest.mark.parametrize(
    ("deck", "expected"),
    [
        ("A", set()),
        (
            "B",
            {
                "bullets",
                "font",
                "notes",
                "placeholder",
                "text-size",
                "title-bold",
            },
        ),
        ("C", {"chrome", "drift", "near-miss", "title-period"}),
    ],
)
def test_eval_decks_match_the_reference(deck, expected):
    findings, _ = checker.check(_EVAL_DECKS / deck)
    assert _codes(findings) == expected
    reference = json.loads(
        (_EVAL_DECKS.parent / "reference" / "response.txt").read_text()
    )
    assert sorted(expected) == reference[deck]


def test_near_miss_names_the_exact_fix(tmp_path):
    body = (
        _chrome("Results", 2)
        + _image(144, 202)
        + _text("Label", 1066, 290)
        + _text("Takeaway", 1080, 640)
    )
    root = _deck(tmp_path, {"cover": "", "results": body})
    findings, scores = checker.check(root)
    messages = [f.message for f in findings if f.code == "near-miss"]
    assert messages == [
        "p 'Takeaway': left 1080 px is 14 px off 1066; set left:1066px"
    ]
    assert scores["results"] == pytest.approx(1 / 3)


def test_guides_win_over_other_elements(tmp_path):
    body = _chrome("Results", 2) + _image(150, 202, 400, 300)
    root = _deck(tmp_path, {"cover": "", "results": body})
    findings, _ = checker.check(root)
    assert [f.message for f in findings if f.code == "near-miss"] == [
        "img 'figure': left 150 px is 6 px off 144; set left:144px"
    ]


def test_centred_text_snaps_to_the_canvas_centre(tmp_path):
    statement = (
        '<p style="position:absolute; left:190px; top:400px; width:1560px; '
        'font-size:80px; text-align:center">Why?</p>'
    )
    root = _deck(tmp_path, {"cover": "", "why": statement})
    findings, _ = checker.check(root)
    assert any(
        f.code == "near-miss"
        and "center 970 px" in f.message
        and "left:180px" in f.message
        for f in findings
    )


def test_uneven_row_and_even_row(tmp_path):
    uneven = _chrome("Acknowledgements", 2) + "".join(
        _image(left, 266, 208, 208) for left in (264, 840, 1448)
    )
    even = _chrome("Acknowledgements", 3) + "".join(
        _image(left, 266, 208, 208) for left in (264, 856, 1448)
    )
    root = _deck(tmp_path, {"cover": "", "uneven": uneven, "even": even})
    findings, scores = checker.check(root)
    spacing = [f for f in findings if f.code == "spacing"]
    assert [f.slide for f in spacing] == ["uneven"]
    assert "make each 384 px" in spacing[0].message
    assert scores["even"] == 1.0


def test_drift_of_chrome_across_slides(tmp_path):
    slides = {
        "cover": "",
        "one": _chrome("First Slide", 2) + _image(144, 202),
        "two": _chrome("Second Slide", 3) + _image(144, 202),
        "three": _chrome("Third Slide", 4, left=150) + _image(144, 202),
    }
    findings, _ = checker.check(_deck(tmp_path, slides))
    drift = [f for f in findings if f.code == "drift"]
    assert [(f.slide, f.severity) for f in drift] == [("three", "ERROR")]
    assert drift[0].message.endswith("set left:144px")


def test_number_overlap_and_arrow(tmp_path):
    body = "".join(
        [
            _chrome("Results", 7),
            _image(144, 202),
            _text(
                "A long label that wraps onto two lines here", 1080, 290, 400
            ),
            _text("Second label", 1080, 330, 400),
            '<x-connector x1="600" y1="700" x2="700" y2="800" head="end">',
            "</x-connector>",
        ]
    )
    findings, _ = checker.check(_deck(tmp_path, {"cover": "", "results": body}))
    assert {"number", "overlap", "arrow"} <= _codes(findings)


def test_house_exceptions_pass(tmp_path):
    acks = (
        _chrome("Acknowledgements", 2)
        + _text("<b>Name</b><br>Role<br><b>Place</b>", 72, 494, 592, 32)
        + _text("Image courtesy: Someone", 144, 1000, 1200, 24)
    )
    cover = (
        '<p style="position:absolute; left:144px; top:718px; width:400px; '
        "font-family:'Noto Sans Bengali'; font-size:48px\">বিপ্রতীপ দে</p>"
    )
    findings, _ = checker.check(_deck(tmp_path, {"cover": cover, "acks": acks}))
    assert not _codes(findings, "ERROR")


def test_cli_exit_status(tmp_path):
    body = _chrome("Bold Title", 2).replace(
        "font-weight:400", "font-weight:700"
    )
    root = _deck(tmp_path, {"cover": "", "bold": body + _image(144, 202)})
    result = subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "check_deck.py"), str(root)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "title-bold" in result.stdout
    assert "deck alignment" in result.stdout


@pytest.mark.skipif(
    not (shutil.which("latex") and shutil.which("dvisvgm")),
    reason="needs latex",
)
def test_latex_to_svg_writes_outlines(tmp_path):
    output = tmp_path / "eq.svg"
    width, height = svg_tool.render(r"\frac{a}{b}", output, 28)
    assert "<text" not in output.read_text()
    assert width > 0
    assert height > 0
