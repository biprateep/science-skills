"""Observable preservation checks for scientific prose rewrites."""

import importlib.util
import pathlib

import pytest

SOURCE = pathlib.Path(__file__).resolve().parents[1] / "scripts/check_fixed.py"
SPEC = importlib.util.spec_from_file_location("check_fixed", SOURCE)
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


@pytest.mark.parametrize(
    ("before", "after", "kind"),
    [
        (r"Result \parencite{first}.", r"Result \parencite{second}.", "cite"),
        (r"\textcite[see][p. 4]{a,b}", r"\textcite[see][p. 4]{a,c}", "cite"),
        (r"\autocites[1]{a}[2]{b}", r"\autocites[1]{a}[2]{c}", "cite"),
        (r"\Citeauthor*{a}", r"\Citeauthor*{b}", "cite"),
        ("Velocity is -100.", "Velocity is +100.", "number"),
        ("Rate is 1e-3.", "Rate is 1e+3.", "number"),
        ("Rate is −0.01.", "Rate is +0.01.", "number"),
        ("Distance is 10 pc.", "Distance is 10 kpc.", "quantity"),
        (r"Distance is 10\,pc.", r"Distance is 10\,kpc.", "quantity"),
        (r"Flux is 10 \si{widgets}.", r"Flux is 10 \si{gadgets}.", "quantity"),
        (
            r"\begin{align*}x=y\end{align*}",
            r"\begin{align*}x=z\end{align*}",
            "math",
        ),
        (
            r"\begin{equation*}a=b\end{equation*}",
            r"\begin{equation*}a=c\end{equation*}",
            "math",
        ),
    ],
)
def test_scientific_change_fails(
    tmp_path: pathlib.Path, before: str, after: str, kind: str
) -> None:
    """Each audited semantic alteration changes the appropriate multiset."""
    first = tmp_path / "before.tex"
    second = tmp_path / "after.tex"
    first.write_text(before)
    second.write_text(after)
    assert (
        CHECKER.collect(str(first))[kind] != CHECKER.collect(str(second))[kind]
    )
    assert CHECKER.main([str(first), str(second)]) == 1


def test_prose_order_notes_and_unit_spacing_are_not_changes(
    tmp_path: pathlib.Path,
) -> None:
    """Permitted prose rewrites preserve fixed facts without matching words."""
    first = tmp_path / "before.tex"
    second = tmp_path / "after.tex"
    first.write_text(
        r"We measured 10 pc in 3 samples \parencite[see]{a,b}."
        "\n% 999 pc \\cite{ignored}\n"
    )
    second.write_text(
        r"The 3 observations gave 10\,pc \citep[discussion]{b,a}."
    )
    assert CHECKER.main([str(first), str(second)]) == 0


def test_allow_drop_still_rejects_replaced_values(
    tmp_path: pathlib.Path,
) -> None:
    """Author-approved cuts do not authorize adding a changed signed value."""
    first = tmp_path / "before.tex"
    second = tmp_path / "after.tex"
    first.write_text("The value is -100 pc.")
    second.write_text("The value is +100 pc.")
    assert CHECKER.main([str(first), str(second), "--allow-drop"]) == 1
