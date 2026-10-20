"""Static checker regressions for the audit's false passes."""

import importlib.util
import pathlib

import pytest

_ROOT = pathlib.Path(__file__).parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "check_plot_style", _ROOT / "scripts" / "check_plot_style.py"
)
checker = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(checker)

_PREAMBLE = (
    "import matplotlib.pyplot as plt\n"
    "import plotstyle\n"
    "plotstyle.use_style()\n"
    "fig, ax = plt.subplots(figsize=plotstyle.figsize())\n"
)


def _check(tmp_path, source, **options):
    path = tmp_path / "plot.py"
    path.write_text(source)
    return checker.check_file(path, **options)


def _codes(findings):
    return {finding[2] for finding in findings}


def test_audited_false_pass_now_reports_all_contradictions(tmp_path):
    findings = _check(
        tmp_path,
        "import matplotlib.pyplot as plt\n"
        "plt.style.use('ggplot')\n"
        "fig, ax = plt.subplots()\n"
        "ax.plot([0,1], [1,2], color='black')\n"
        "ax.legend()\n"
        "fig.savefig('fig.png', dpi=72)\n",
    )
    assert {
        "style",
        "no-style",
        "figsize",
        "color",
        "legend-frame",
        "savefig-args",
    } <= _codes(findings)


@pytest.mark.parametrize(
    "statement",
    [
        "fig.savefig('fig.png', dpi=72)",
        "fig.savefig('fig.png', bbox_inches=None)",
        "fig.savefig('fig.png', bbox_inches='standard')",
        "fig.savefig('fig.png', dpi=unknown)",
    ],
)
def test_explicit_output_override_cannot_hide_behind_style(tmp_path, statement):
    assert "savefig-args" in _codes(_check(tmp_path, _PREAMBLE + statement))


@pytest.mark.parametrize(
    "statement",
    [
        "plt.rcParams.update({'savefig.dpi':72})",
        "plt.rcParams['savefig.dpi'] = 72",
        "plt.rcParams['font.size'] = 24",
        "plt.rcParams['legend.frameon'] = True",
    ],
)
def test_rc_override_invalidates_recognized_style(tmp_path, statement):
    assert "style-override" in _codes(_check(tmp_path, _PREAMBLE + statement))


def test_unrelated_style_applied_after_house_style_invalidates_it(tmp_path):
    findings = _check(
        tmp_path,
        _PREAMBLE + "plt.style.use('ggplot')\nfig.savefig('fig.png')\n",
    )
    assert {"style", "savefig-args"} <= _codes(findings)


def test_style_must_precede_figure_creation(tmp_path):
    findings = _check(
        tmp_path,
        "import matplotlib.pyplot as plt\n"
        "import plotstyle\n"
        "fig, ax = plt.subplots(figsize=plotstyle.figsize())\n"
        "plotstyle.use_style()\n",
    )
    assert "no-style" in _codes(findings)


def test_approved_helper_alias_and_explicit_output_pass(tmp_path):
    assert not _check(
        tmp_path,
        "import matplotlib.pyplot as p\n"
        "import plotstyle as ps\n"
        "ps.use_style()\n"
        "fig, ax = p.subplots(figsize=ps.figsize())\n"
        "ax.plot([0,1],[1,2],color='C0')\n"
        "ax.legend()\n"
        "fig.savefig('fig.png',dpi=300,bbox_inches='tight')\n",
    )


def test_supplied_style_sheet_passes(tmp_path):
    assert not _check(
        tmp_path,
        "import matplotlib.pyplot as plt\n"
        "plt.style.use('assets/paper.mplstyle')\n"
        "fig, ax = plt.subplots(figsize=(COLUMN_WIDTH, COLUMN_WIDTH))\n"
        "ax.legend()\nfig.savefig('fig.png')",
    )


def test_inline_preamble_is_checked_and_has_no_output_coverage(tmp_path):
    source = (
        "import matplotlib.pyplot as plt\n"
        f"RC_PARAMS = {checker._INLINE_RC!r}\n"
        "plt.rcParams.update(RC_PARAMS)\n"
        "fig, ax = plt.subplots(figsize=(COLUMN_WIDTH, COLUMN_WIDTH))\n"
    )
    assert not _check(
        tmp_path,
        source + "ax.legend(frameon=False)\n"
        "fig.savefig('fig.png',dpi=300,bbox_inches='tight')\n",
    )
    assert {"legend-frame", "savefig-args"} <= _codes(
        _check(tmp_path, source + "ax.legend()\nfig.savefig('fig.png')")
    )
    assert "no-style" in _codes(
        _check(tmp_path, source.replace("'font.size': 10", "'font.size': 24"))
    )


def test_arbitrary_rc_update_is_not_house_style(tmp_path):
    findings = _check(
        tmp_path,
        "import matplotlib.pyplot as plt\n"
        "plt.rcParams.update({'axes.grid': True})\n",
    )
    assert "no-style" in _codes(findings)


@pytest.mark.parametrize(
    "statement",
    ["fig.savefig('fig.pdf')", "fig.savefig('fig', format='svg')"],
)
def test_vector_output_requires_explicit_user_exception(tmp_path, statement):
    assert "savefig-format" in _codes(_check(tmp_path, _PREAMBLE + statement))
    assert not _check(tmp_path, _PREAMBLE + statement, allow_vector=True)


def test_user_palette_exception_preserves_other_checks(tmp_path):
    source = _PREAMBLE + (
        "import seaborn as sns\nsns.set_palette('deep')\n"
        "ax.plot([0,1],[1,2],color='steelblue')\n"
        "fig.savefig('fig.png',dpi=72)\n"
    )
    assert {"palette", "color", "savefig-args"} <= _codes(
        _check(tmp_path, source)
    )
    assert _codes(_check(tmp_path, source, allow_palette=True)) == {
        "savefig-args"
    }


def test_house_palette_helpers_and_reference_lines_pass(tmp_path):
    assert not _check(
        tmp_path,
        _PREAMBLE + "plotstyle.set_palette(['red','blue'])\n"
        "ax.axhline(1,color='k',ls='--')\n"
        "ax.plot(x,x,color='black',ls='--')\n"
        "ax.hist(data,color='white',histtype='step')\n",
    )


def test_missing_size_with_house_style_still_fails(tmp_path):
    findings = _check(tmp_path, _PREAMBLE + "plt.subplots()\n")
    assert "figsize" in _codes(findings)


def test_unrelated_figsize_helper_is_not_approved(tmp_path):
    findings = _check(
        tmp_path, _PREAMBLE + "plt.subplots(figsize=other.figsize())"
    )
    assert "figsize" in _codes(findings)


@pytest.mark.parametrize("fmt", ["k--", "--k", "r.", "b"])
def test_plot_format_colors_are_checked(tmp_path, fmt):
    findings = _check(tmp_path, _PREAMBLE + f"ax.plot(x,y,{fmt!r})")
    assert "color" in _codes(findings)
    assert not _check(tmp_path, _PREAMBLE + "ax.plot(x,x,'k--')")
    assert not _check(tmp_path, _PREAMBLE + "ax.plot(x,y,'C0--')")


def test_examples_continue_to_pass():
    assert not checker.check_file(_ROOT / "examples" / "example_figures.py")


def test_cli_rejects_unknown_flags_and_supports_requested_exceptions(
    tmp_path,
):
    path = tmp_path / "plot.py"
    path.write_text(_PREAMBLE + "fig.savefig('fig.pdf')\n")
    assert checker.main([str(path)]) == 1
    assert checker.main([str(path), "--allow-vector", "--strict"]) == 0
    with pytest.raises(SystemExit) as error:
        checker.main([str(path), "--allow-vecotr"])
    assert error.value.code == 2
