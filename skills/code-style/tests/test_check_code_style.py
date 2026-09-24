"""Tests for scripts/check_code_style.py and for the skill's own examples.

Run from the repository root:

  uvx --with numpy pytest skills/code-style/tests
"""

import importlib.util
import pathlib
import shutil
import subprocess
import sys
import textwrap
import types

import pytest

_SKILL = pathlib.Path(__file__).resolve().parent.parent
_CHECKER_PATH = _SKILL / "scripts" / "check_code_style.py"
_RUFF_CONFIG = _SKILL / "assets" / "ruff.toml"
_EXAMPLES = sorted((_SKILL / "examples").glob("*.py"))


@pytest.fixture(scope="module")
def checker() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_code_style", _CHECKER_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_code_style"] = module
    spec.loader.exec_module(module)
    return module


def _codes(
    checker: types.ModuleType,
    source: str,
    path: pathlib.Path,
    allow_import: bool = True,
) -> list[str]:
    resolver = checker.ImportResolver(allow_import=allow_import)
    aliases = checker.load_aliases(_RUFF_CONFIG)
    findings, _ = checker.check_source(
        textwrap.dedent(source), path, resolver, aliases
    )
    return [finding.code for finding in findings]


# Each case: the rule, a snippet that breaks it, a snippet that keeps it.
_CASES = [
    (
        "GS001",
        "from json import loads\n",
        "from os import path\nfrom xml.etree import ElementTree\n"
        "from typing import Any\nfrom collections.abc import Sequence\n",
    ),
    ("GS002", "import pickle as pkl\n", "import numpy as np\nimport pickle\n"),
    (
        "GS003",
        '''
        def scale(x: float) -> float:
            """Doubles x."""
            assert x > 0, "x must be positive"
            return 2 * x
        ''',
        '''
        def scale(x: float) -> float:
            """Doubles x."""
            if x <= 0:
                raise ValueError(f"x must be positive, got {x=}")
            doubled = 2 * x
            assert doubled > x
            return doubled
        ''',
    ),
    (
        "GS004",
        "cache = {}\n",
        "_cache = {}  # Memoizes lookups.\nDEFAULTS = {'window': 101}\n",
    ),
    (
        "GS005",
        '''
        def outer(values: list[int]) -> int:
            """Sums values."""

            def helper(x: int) -> int:
                return x + 1

            return sum(map(helper, values))
        ''',
        '''
        def logged(func):
            """Decorates func."""

            def wrapper(*args):
                return func(*args)

            return wrapper
        ''',
    ),
    (
        "GS006",
        "pairs = [(a, b) for a in range(3) for b in range(3)]\n",
        "evens = [a for a in range(9) if a % 2 == 0]\n",
    ),
    (
        "GS007",
        "items = [1]\nempty = len(items) == 0\n",
        "items = [1]\nempty = not items\nthree = len(items) == 3\n",
    ),
    ("GS008", "items = [1]\nempty = items == []\n", "empty = not [1]\n"),
    (
        "GS009",
        '''
        def fill(values=None):
            """Fills."""
            values = values or []
            return values
        ''',
        '''
        def fill(values=None):
            """Fills."""
            if values is None:
                values = []
            return values
        ''',
    ),
    (
        "GS010",
        "i = 20\nround_ = not i % 10\n",
        "i = 20\nround_ = i % 10 == 0\n",
    ),
    (
        "GS011",
        '''
        class Grid:
            """A grid."""

            @staticmethod
            def spacing(n: int) -> float:
                return 1 / n
        ''',
        '''
        def spacing(n: int) -> float:
            """The spacing of an n-point grid."""
            return 1 / n
        ''',
    ),
    (
        "GS012",
        '''
        class Plugin(metaclass=Registry):
            """A plugin."""
        ''',
        '''
        import abc


        class Plugin(metaclass=abc.ABCMeta):
            """A plugin."""
        ''',
    ),
    (
        "GS013",
        """
        def f() -> None:

            print("x")
        """,
        """
        def f() -> None:
            print("x")
        """,
    ),
    ("GS014", "x = 1\n", '"""A module."""\n\nx = 1\n'),
    (
        "GS016",
        '''
        def snr(flux, noise):
            """Signal-to-noise ratio.

            Parameters
            ----------
            flux : ndarray
                Flux.
            """
        ''',
        '''
        def snr(flux, noise):
            """Signal-to-noise ratio.

            Args:
              flux: Flux.
              noise: Noise.
            """
        ''',
    ),
    (
        "GS017",
        '''
        class Spectrum:
            """A spectrum."""

            @property
            def size(self) -> int:
                """Returns the number of pixels."""
                return 1
        ''',
        '''
        class Spectrum:
            """A spectrum."""

            @property
            def size(self) -> int:
                """The number of pixels."""
                return 1
        ''',
    ),
    (
        "GS018",
        '''
        def chunks(n):
            """Splits.

            Returns:
              Chunks.
            """
            yield n
        ''',
        '''
        def chunks(n):
            """Splits.

            Yields:
              One chunk at a time.
            """
            yield n
        ''',
    ),
    (
        "GS019",
        '''
        class OutOfRangeError(ValueError):
            """Raised when a value leaves the grid."""
        ''',
        '''
        class OutOfRangeError(ValueError):
            """A value lies outside the grid."""
        ''',
    ),
    (
        "GS020",
        'name = "x"\nlabel = "name: " + name + "!"\n',
        'a = "x"\nb = "y"\njoined = a + b\ntotal = 1 + 2 + 3\n',
    ),
    (
        "GS021",
        '''
        def csv(parts):
            """Joins."""
            text = ""
            for part in parts:
                text += f"{part},"
            return text
        ''',
        '''
        def total(parts):
            """Sums."""
            value = 0
            for part in parts:
                value += part
            return value
        ''',
    ),
    (
        "GS022",
        '''
        import h5py

        def read(path):
            """Reads."""
            handle = h5py.File(path)
            return handle["x"][:]
        ''',
        '''
        import h5py

        def read(path):
            """Reads."""
            with h5py.File(path) as handle:
                return handle["x"][:]
        ''',
    ),
    (
        "GS023",
        '''
        import matplotlib.pyplot as plt

        def draw(path):
            """Draws."""
            fig, ax = plt.subplots()
            ax.plot([1, 2])
            fig.savefig(path)
        ''',
        '''
        import matplotlib.pyplot as plt

        def draw(path):
            """Draws."""
            fig, ax = plt.subplots()
            ax.plot([1, 2])
            fig.savefig(path)
            plt.close(fig)
        ''',
    ),
    (
        "GS024",
        "# TODO(someone): Vectorize.\n# TODO: #12 vectorize this\n",
        "# TODO: #12 - Vectorize this.\n"
        "# TODO: https://github.com/o/r/issues/3 - Cache the grid.\n",
    ),
    (
        "GS025",
        "def f() -> None:\n    names_list = ['a']\n    print(names_list)\n",
        "def f() -> None:\n    names = ['a']\n    print(names)\n",
    ),
    (
        "GS026",
        'print("running")\n',
        '''
        def main() -> None:
            """Runs."""


        if __name__ == "__main__":
            main()
        ''',
    ),
    (
        "GS027",
        "def long() -> None:\n    x = 0\n" + "    x += 1\n" * 41,
        "def short() -> None:\n    x = 0\n" + "    x += 1\n" * 30,
    ),
    (
        "GS028",
        "values = []  # type: list[int]\n",
        "values: list[int] = []\nother = f()  # type: ignore[name-defined]\n",
    ),
    (
        "GS029",
        'from typing import TypeVar\nT = TypeVar("T")\n',
        'from typing import TypeVar\n_T = TypeVar("_T")\n'
        'Scalar = TypeVar("Scalar", int, float)\n',
    ),
    (
        "GS030",
        '''
        def measure(image, x, y, r):
            """Measures one source."""
        ''',
        '''
        def measure(image, x_center, y_center, radius):
            """Measures one source."""


        def _distance(x, y):
            """Returns the distance from the origin."""
            return (x * x + y * y) ** 0.5


        class Model:
            """A model."""

            def __call__(self, wavelength):
                """Evaluates the model."""

                def inner(t):
                    return t

                return inner(wavelength)
        ''',
    ),
]


@pytest.mark.parametrize(("code", "bad", "good"), _CASES)
def test_rule_flags_bad_and_accepts_good(checker, tmp_path, code, bad, good):
    path = tmp_path / "module.py"
    assert code in _codes(checker, bad, path)
    assert code not in _codes(checker, good, path)


def test_every_rule_has_a_case(checker):
    covered = {case[0] for case in _CASES} | {"GS015"}
    assert covered == set(checker.RULES)


def test_del_and_metaclass_and_frame_hacks_are_power_features(
    checker, tmp_path
):
    source = """
    import sys


    class Buffer:
        \"\"\"A buffer.\"\"\"

        def __del__(self):
            pass


    frame = sys._getframe()
    """
    codes = _codes(checker, source, tmp_path / "module.py")
    assert codes.count("GS012") == 2


def test_resolver_classifies_modules_and_members(checker):
    resolver = checker.ImportResolver()
    assert resolver.classify("os", "path")[0] == "module"
    assert resolver.classify("xml.etree", "ElementTree")[0] == "module"
    assert resolver.classify("json", "loads")[0] == "member"
    assert resolver.classify("collections", "OrderedDict")[0] == "member"
    kind, reason = resolver.classify("no_such_package_xyz", "thing")
    assert kind == "unknown"
    assert "not installed" in reason


def test_resolver_without_import_uses_the_file_system_only(checker):
    resolver = checker.ImportResolver(allow_import=False)
    assert resolver.classify("xml.etree", "ElementTree")[0] == "module"
    assert resolver.classify("json", "loads")[0] == "member"


def test_unresolvable_import_is_a_note_not_a_finding(checker, tmp_path):
    source = '"""A module."""\n\nfrom no_such_package_xyz import thing\n'
    resolver = checker.ImportResolver()
    findings, notes = checker.check_source(
        source, tmp_path / "module.py", resolver, {}
    )
    assert not findings
    assert len(notes) == 1
    assert "NOTE" in notes[0]


_NOTEBOOK_HEADER = """\
# ---
# jupyter:
#   kernelspec:
#     name: python3
# ---

"""


def test_notebook_title_cell_replaces_module_docstring(checker, tmp_path):
    notebook = _NOTEBOOK_HEADER + (
        "# %% [markdown]\n# # Fit the lines\n\n# %% Imports\nimport math\n\n"
        "# %%\nprint(math.pi)\n"
    )
    codes = _codes(checker, notebook, tmp_path / "fit.py")
    assert "GS014" not in codes
    assert "GS026" not in codes


def test_notebook_without_title_cell_is_flagged(checker, tmp_path):
    notebook = _NOTEBOOK_HEADER + "# %% Imports\nimport math\n"
    assert "GS014" in _codes(checker, notebook, tmp_path / "fit.py")


def test_test_modules_need_no_docstring_and_may_assert(checker, tmp_path):
    source = "def test_scale(x=1):\n    assert x > 0\n"
    codes = _codes(checker, source, tmp_path / "tests" / "test_scale.py")
    assert "GS014" not in codes
    assert "GS003" not in codes


def test_noqa_suppresses_on_any_line_of_the_statement(checker, tmp_path):
    source = (
        '"""A module."""\n\n'
        "from json import loads  # noqa: GS001 - demonstration.\n"
        "from json import (\n    dumps,  # noqa: GS001\n)\n"
    )
    assert "GS001" not in _codes(checker, source, tmp_path / "module.py")


def test_file_level_noqa_suppresses_everywhere(checker, tmp_path):
    source = (
        '"""A module."""\n\n# ruff: noqa: GS001\n\nfrom json import loads\n'
    )
    assert "GS001" not in _codes(checker, source, tmp_path / "module.py")


def test_license_boilerplate_required_when_project_declares_one(
    checker, tmp_path
):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    (tmp_path / "LICENSE").write_text("MIT License\n")
    package = tmp_path / "src"
    package.mkdir()
    source = '"""A module."""\n\nx = 1\n'
    assert "GS015" in _codes(checker, source, package / "module.py")
    licensed = "# SPDX-License-Identifier: MIT\n" + source
    assert "GS015" not in _codes(checker, licensed, package / "module.py")


def test_aliases_merge_ruff_defaults_and_config(checker, tmp_path):
    aliases = checker.load_aliases(_RUFF_CONFIG)
    assert aliases["numpy"] == "np"
    assert aliases["astropy.units"] == "u"
    config = tmp_path / "ruff.toml"
    config.write_text(
        '[lint.flake8-import-conventions.extend-aliases]\n"emcee" = "mc"\n'
    )
    assert checker.load_aliases(config)["emcee"] == "mc"


def test_nearest_ruff_config_wins(checker, tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nline-length = 80\n")
    nested = tmp_path / "pkg"
    nested.mkdir()
    target = nested / "module.py"
    target.write_text('"""A module."""\n')
    assert checker.find_ruff_config(target) == tmp_path / "pyproject.toml"
    lonely = tmp_path / "lonely.py"
    assert checker.find_ruff_config(lonely) == tmp_path / "pyproject.toml"


def test_command_line(checker, tmp_path, capsys):
    assert checker.main(["--list"]) == 0
    assert "GS001" in capsys.readouterr().out
    assert checker.main([]) == 2
    bad = tmp_path / "bad.py"
    bad.write_text("from json import loads\n")
    assert checker.main([str(bad)]) == 1
    good = tmp_path / "good.py"
    good.write_text('"""A module."""\n\nimport json\n')
    assert checker.main([str(good)]) == 0


@pytest.mark.parametrize(
    "path",
    [_CHECKER_PATH, pathlib.Path(__file__), *_EXAMPLES],
    ids=lambda path: path.name,
)
def test_skill_files_pass_the_checker(checker, path):
    resolver = checker.ImportResolver()
    aliases = checker.load_aliases(_RUFF_CONFIG)
    source = path.read_text(encoding="utf-8")
    findings, _ = checker.check_source(source, path, resolver, aliases)
    assert not findings


def _ruff() -> list[str]:
    if shutil.which("ruff"):
        return ["ruff"]
    if shutil.which("uvx"):
        return ["uvx", "ruff"]
    pytest.skip("neither ruff nor uvx is installed")
    return []


@pytest.mark.parametrize(
    "path",
    [_CHECKER_PATH, pathlib.Path(__file__), *_EXAMPLES],
    ids=lambda path: path.name,
)
def test_skill_files_pass_ruff(path):
    ruff = _ruff()
    config = ["--config", str(_RUFF_CONFIG), "--no-cache"]
    lint = subprocess.run(
        [*ruff, "check", *config, str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert lint.returncode == 0, lint.stdout + lint.stderr
    formatted = subprocess.run(
        [*ruff, "format", "--check", *config, str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert formatted.returncode == 0, formatted.stdout + formatted.stderr


def test_notebook_example_runs(tmp_path):
    pytest.importorskip("numpy")
    result = subprocess.run(
        [sys.executable, str(_SKILL / "examples" / "notebook.py")],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "depth 0.6" in result.stdout


def test_continuum_example_round_trip(tmp_path):
    np = pytest.importorskip("numpy")
    wavelength = np.linspace(4000.0, 7000.0, 500)
    flux = 2.0 + 1e-3 * (wavelength - 4000.0)
    ivar = np.ones_like(flux)
    ivar[10] = 0.0
    source = tmp_path / "source.npz"
    np.savez(source, wavelength=wavelength, flux=flux, ivar=ivar)
    destination = tmp_path / "normalized.npz"
    example = _SKILL / "examples" / "continuum.py"
    result = subprocess.run(
        [sys.executable, str(example), str(source), str(destination)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    with np.load(destination) as arrays:
        np.testing.assert_allclose(arrays["flux"], 1.0, rtol=1e-3)
        assert arrays["ivar"][10] == 0.0
