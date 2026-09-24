#!/usr/bin/env python3
"""Checks Python files against the Google style rules that ruff cannot see.

ruff, configured by assets/ruff.toml, enforces most of the Google Python Style
Guide. This script checks the rest: rules that need import resolution (only
modules are imported), knowledge of jupytext notebooks (which carry a title
cell instead of a module docstring), and rules that no ruff rule expresses.
Each finding names the guide section it enforces; `--list` prints them all.

Run it with the interpreter that runs the code (`uv run python ...` inside a
project) so that `from x import y` is resolved against the packages the code
really imports. Directories are searched for .py files.

A finding is suppressed by `# noqa: GS001` on any line of the offending
statement, or for a whole file by `# ruff: noqa: GS001`. ruff accepts these
codes because assets/ruff.toml declares them external.

Typical usage example:

  python check_code_style.py src/ notebooks/explore.py
  python check_code_style.py --strict --no-import analysis.py

Exit status is 1 if an error was found (or a warning, with --strict), 2 on bad
usage, and 0 otherwise.
"""

import argparse
import ast
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
import contextlib
import dataclasses
import functools
import importlib
import importlib.machinery
import importlib.util
import inspect
import io
import os
import pathlib
import re
import sys
import tokenize
from typing import Any
import warnings

if sys.version_info >= (3, 11):
    import tomllib


@dataclasses.dataclass(frozen=True)
class Rule:
    """One check this script performs.

    Attributes:
      code: The code used in reports and in noqa comments.
      is_error: Whether a finding fails the run; warnings fail only under
        --strict.
      section: The section of the Google Python Style Guide the rule enforces.
      summary: What the rule asks for, in a few words.
    """

    code: str
    is_error: bool
    section: str
    summary: str


_RULE_LIST = (
    Rule("GS001", True, "2.2", "import packages and modules, not members"),
    Rule("GS002", False, "2.2", "`import x as y` only for a standard alias"),
    Rule("GS003", False, "2.4", "raise for a bad argument; do not assert"),
    Rule("GS004", False, "2.5", "no public mutable module-level state"),
    Rule("GS005", False, "2.6", "nest a function only to close over a local"),
    Rule("GS006", True, "2.7", "one for and at most one if per comprehension"),
    Rule("GS007", False, "2.14", "implicit false for emptiness, not len()"),
    Rule("GS008", False, "2.14", "implicit false for emptiness, not == []"),
    Rule("GS009", False, "2.14", "`if x is None:`, not `x = x or default`"),
    Rule("GS010", False, "2.14", "compare an integer with 0 explicitly"),
    Rule("GS011", True, "2.17", "a module-level function, not @staticmethod"),
    Rule("GS012", False, "2.19", "no metaclasses, __del__ or frame hacks"),
    Rule("GS013", True, "3.5", "no blank line directly after a def line"),
    Rule("GS014", True, "3.8.2", "a module docstring, or a notebook title"),
    Rule("GS015", False, "3.8.2", "license boilerplate when one is declared"),
    Rule("GS016", False, "3.8.3", "Args:/Returns:/Raises:, not NumPy or reST"),
    Rule("GS017", False, "3.8.3", "a property docstring names the attribute"),
    Rule("GS018", False, "3.8.3", "a generator documents Yields:"),
    Rule("GS019", False, "3.8.4", "a class docstring says what it represents"),
    Rule("GS020", False, "3.10", "format with f-strings, % or format, not +"),
    Rule("GS021", False, "3.10", "collect parts and join, not += in a loop"),
    Rule("GS022", False, "3.11", "open resources in a with block"),
    Rule("GS023", False, "3.11", "close a figure once it is saved"),
    Rule("GS024", False, "3.12", "`# TODO: <link> - <explanation>`"),
    Rule("GS025", False, "3.16.1", "a name does not repeat its type"),
    Rule("GS026", False, "3.17", "program code in main(), behind the guard"),
    Rule("GS027", False, "3.18", "functions of about 40 lines at most"),
    Rule("GS028", False, "3.19.8", "annotations, not `# type:` comments"),
    Rule("GS029", False, "3.19.10", "descriptive public type variable names"),
    Rule("GS030", False, "3.16.1", "no one-letter parameters in a public API"),
)
RULES = {rule.code: rule for rule in _RULE_LIST}


@dataclasses.dataclass(frozen=True, order=True)
class Finding:
    """A rule violation at one place in a file.

    Attributes:
      line: The first line of the offending statement, counted from 1.
      code: The code of the violated rule.
      message: What is wrong and how to put it right.
      end_line: The last line of the statement; a noqa on any line from
        `line` to `end_line` suppresses the finding. 0 means `line`.
    """

    line: int
    code: str
    message: str
    end_line: int = 0


# §2.2.4.1: symbols from these modules may be imported directly.
_EXEMPT_FROM_IMPORTS = frozenset(
    {"__future__", "collections.abc", "typing", "typing_extensions"}
)
# ruff's default lint.flake8-import-conventions.aliases (ruff 0.16).
_RUFF_DEFAULT_ALIASES = {
    "altair": "alt",
    "holoviews": "hv",
    "matplotlib": "mpl",
    "matplotlib.pyplot": "plt",
    "numpy": "np",
    "numpy.typing": "npt",
    "pandas": "pd",
    "panel": "pn",
    "plotly.express": "px",
    "polars": "pl",
    "pyarrow": "pa",
    "seaborn": "sns",
    "tensorflow": "tf",
    "tkinter": "tk",
    "xml.etree.ElementTree": "ET",
}
_SKILL_RUFF_CONFIG = (
    pathlib.Path(__file__).resolve().parent.parent / "assets" / "ruff.toml"
)
_SKIPPED_DIRS = frozenset(
    {"__pycache__", "build", "dist", "node_modules", "site-packages", "venv"}
)
_MUTABLE_FACTORIES = frozenset(
    {
        "Counter",
        "OrderedDict",
        "bytearray",
        "defaultdict",
        "deque",
        "dict",
        "list",
        "set",
    }
)
# Openers whose result holds an OS resource until closed, matched on the last
# two components of the called name (`fits.open` matches astropy.io.fits).
_RESOURCE_OPENERS = frozenset(
    {
        "Image.open",
        "bz2.open",
        "fits.open",
        "fitsio.FITS",
        "futures.ProcessPoolExecutor",
        "futures.ThreadPoolExecutor",
        "gzip.open",
        "h5py.File",
        "lzma.open",
        "mmap.mmap",
        "mp.Pool",
        "multiprocessing.Pool",
        "netCDF4.Dataset",
        "pandas.HDFStore",
        "pd.HDFStore",
        "request.urlopen",
        "shelve.open",
        "socket.socket",
        "sqlite3.connect",
        "tables.open_file",
        "tarfile.open",
        "tempfile.NamedTemporaryFile",
        "tempfile.TemporaryDirectory",
        "tempfile.TemporaryFile",
        "xarray.open_dataarray",
        "xarray.open_dataset",
        "xarray.open_mfdataset",
        "xr.open_dataarray",
        "xr.open_dataset",
        "xr.open_mfdataset",
        "zipfile.ZipFile",
    }
)
_FIGURE_FACTORIES = frozenset(
    {
        "plt.figure",
        "plt.subplot_mosaic",
        "plt.subplots",
        "pyplot.figure",
        "pyplot.subplot_mosaic",
        "pyplot.subplots",
    }
)
_FIGURE_CLOSERS = frozenset({"plt.close", "pyplot.close"})
_CONTAINER_SUFFIXES = ("_dict", "_list", "_set", "_tuple")
_MAX_FUNCTION_LINES = 40
_MIRRORED_COMPARISONS = {
    ast.Gt: ast.Lt,
    ast.Lt: ast.Gt,
    ast.GtE: ast.LtE,
    ast.LtE: ast.GtE,
}

_CODES = r"(?P<codes>[A-Z]+\d+(?:[\s,]+[A-Z]+\d+)*)"
_NOQA = re.compile(r"#\s*noqa:\s*" + _CODES)
_FILE_NOQA = re.compile(r"#\s*ruff\s*:\s*noqa:\s*" + _CODES)
_CELL_MARKER = re.compile(r"^# %%")
_NUMPY_SECTION = re.compile(
    r"^\s*(Parameters|Returns|Yields|Raises|Attributes|Other Parameters)"
    r"\s*\n\s*-{3,}\s*$",
    re.MULTILINE,
)
_REST_FIELD = re.compile(
    r"^\s*(:(param|parameter|arg|type|returns?|rtype|raises?|ivar)\b[^:]*:"
    r"|@(param|type|return|rtype|raise)\b)",
    re.MULTILINE,
)
_GETTER_PHRASE = re.compile(r"^(Returns?|Gets?)\b")
_CLASS_PHRASE = re.compile(r"^(Class\b|A class\b|This class\b|The class\b)")
_EXCEPTION_PHRASE = re.compile(
    r"^(Raised\b|Thrown\b|(An )?(exception|error) (raised|thrown)\b)",
    re.IGNORECASE,
)
_TODO = re.compile(r"#\s*TODO\b(?P<rest>.*)")
_LINK = re.compile(
    r"^(https?://\S+|#\d+|[\w.-]+/[\w./-]*#\d+|[\w-]+(\.[\w-]+)+/\S+"
    r"|[A-Z][A-Z0-9]+-\d+)$"
)
_TYPE_COMMENT = re.compile(r"#\s*type:\s*(?!ignore\b)\S")
_LICENSE_COMMENT = re.compile(
    r"#.*(SPDX-License-Identifier|Copyright|Licensed under)", re.IGNORECASE
)

_Function = ast.FunctionDef | ast.AsyncFunctionDef
_Comprehension = ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp


def _dotted_name(node: ast.expr) -> str:
    """Returns the dotted name of a call target, or "" for anything else."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value)
        return f"{base}.{node.attr}" if base else ""
    return ""


def _last_two(name: str) -> str:
    """Returns the last two components of a dotted name."""
    return ".".join(name.split(".")[-2:])


def _parameter_names(arguments: ast.arguments) -> set[str]:
    """Returns every parameter name of a function signature."""
    names = {
        arg.arg
        for arg in (
            *arguments.posonlyargs,
            *arguments.args,
            *arguments.kwonlyargs,
        )
    }
    for star in (arguments.vararg, arguments.kwarg):
        if star is not None:
            names.add(star.arg)
    return names


def _scope_nodes(scope: ast.AST) -> Iterator[ast.AST]:
    """Yields the nodes of one scope, skipping nested functions and classes."""
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda),
        ):
            stack.extend(ast.iter_child_nodes(node))


def _bound_names(function: _Function) -> set[str]:
    """Returns the names a function binds: parameters, assignments, defs."""
    names = _parameter_names(function.args)
    for node in _scope_nodes(function):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update(
                (alias.asname or alias.name).split(".")[0]
                for alias in node.names
            )
    return names


def _names_in(
    nodes: Iterable[ast.AST], context: type[ast.expr_context] = ast.expr_context
) -> set[str]:
    """Returns the names used anywhere under nodes, in the given context."""
    names = set()
    for node in nodes:
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and isinstance(child.ctx, context):
                names.add(child.id)
    return names


def _docstring(node: ast.AST) -> tuple[ast.Expr, str] | None:
    """Returns the docstring statement of a module, class or function.

    Args:
      node: The module, class or function.

    Returns:
      A tuple (statement, text), or None when there is no docstring.
    """
    body = getattr(node, "body", None)
    if not body or not isinstance(body[0], ast.Expr):
        return None
    value = body[0].value
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return body[0], value.value
    return None


def _is_empty_literal(node: ast.expr) -> bool:
    """Returns whether node is [], {}, (), '' or b''."""
    if isinstance(node, (ast.List, ast.Tuple)):
        return not node.elts
    if isinstance(node, ast.Dict):
        return not node.keys
    if isinstance(node, ast.Constant):
        return node.value in ("", b"")
    return False


def _is_len_call(node: ast.expr) -> bool:
    """Returns whether node is a call of the builtin len()."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "len"
    )


def _is_len_emptiness(left: ast.expr, op: ast.cmpop, right: ast.expr) -> bool:
    """Returns whether `left op right` tests emptiness through len()."""
    if _is_len_call(right) and not _is_len_call(left):
        left, right = right, left
        op = _MIRRORED_COMPARISONS.get(type(op), type(op))()
    if not _is_len_call(left) or not isinstance(right, ast.Constant):
        return False
    if isinstance(op, (ast.Eq, ast.NotEq, ast.Gt, ast.LtE)):
        return right.value == 0
    if isinstance(op, (ast.GtE, ast.Lt)):
        return right.value == 1
    return False


def _is_str_literal(node: ast.expr) -> bool:
    """Returns whether node is a string literal or an f-string."""
    if isinstance(node, ast.JoinedStr):
        return True
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _is_str_expression(node: ast.expr) -> bool:
    """Returns whether node is evidently a str: literal, format or str()."""
    if _is_str_literal(node):
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        return _is_str_literal(node.left)
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name) and func.id == "str":
            return True
        if isinstance(func, ast.Attribute) and func.attr == "format":
            return _is_str_literal(func.value)
    return False


def _is_main_guard(node: ast.If) -> bool:
    """Returns whether node is `if __name__ == "__main__":`."""
    if not isinstance(node.test, ast.Compare):
        return False
    test = node.test
    sides = [test.left, *test.comparators]
    return (
        len(test.ops) == 1
        and isinstance(test.ops[0], ast.Eq)
        and any(isinstance(s, ast.Name) and s.id == "__name__" for s in sides)
        and any(
            isinstance(s, ast.Constant) and s.value == "__main__" for s in sides
        )
    )


def _is_single_call(node: ast.stmt) -> bool:
    """Returns whether node is `main()`, `sys.exit(main())` or the like."""
    if isinstance(node, ast.Expr):
        return isinstance(node.value, ast.Call)
    if isinstance(node, ast.Raise):
        return isinstance(node.exc, ast.Call)
    return False


def _is_private(name: str) -> bool:
    """Returns whether name is internal: one leading underscore, no dunder."""
    return name.startswith("_") and not (
        name.startswith("__") and name.endswith("__")
    )


def _is_test_file(path: pathlib.Path) -> bool:
    """Returns whether path is a test module by name or by directory."""
    name = path.name
    if name == "conftest.py" or name.startswith("test_"):
        return True
    if name.endswith("_test.py"):
        return True
    return any(part in ("test", "tests") for part in path.parent.parts)


@contextlib.contextmanager
def _quiet() -> Iterator[None]:
    """Silences output and warnings while a package is imported."""
    sink = io.StringIO()
    with (
        contextlib.redirect_stdout(sink),
        contextlib.redirect_stderr(sink),
        warnings.catch_warnings(),
    ):
        warnings.simplefilter("ignore")
        yield


def _find_spec(dotted: str) -> importlib.machinery.ModuleSpec | None:
    """Finds a module's spec without running any package's __init__.

    Args:
      dotted: An absolute module name, like "scipy.optimize".

    Returns:
      The spec, or None when the module is not installed.

    Raises:
      ImportError: If a finder fails.
      ValueError: If a module in sys.modules has no spec.
    """
    parts = dotted.split(".")
    spec = importlib.util.find_spec(parts[0])
    for depth in range(2, len(parts) + 1):
        if spec is None or spec.submodule_search_locations is None:
            return None
        spec = importlib.machinery.PathFinder.find_spec(
            ".".join(parts[:depth]), list(spec.submodule_search_locations)
        )
    return spec


class ImportResolver:
    """Decides whether `from package import name` imports a module.

    The file system is asked first, which runs no code. A package is imported
    only when the name is not a submodule on disk: then it is either a member
    (the violation) or a module the package exposes as an attribute, like
    os.path.
    """

    def __init__(self, allow_import: bool = True) -> None:
        """Initializes the resolver.

        Args:
          allow_import: Whether a package may be imported when the file
            system cannot decide. Without it such names count as members.
        """
        self._allow_import = allow_import
        self._cache: dict[tuple[str, str], tuple[str, str]] = {}

    def classify(self, package: str, name: str) -> tuple[str, str]:
        """Classifies one name imported from a package.

        Args:
          package: The absolute module name after `from`.
          name: One of the names after `import`.

        Returns:
          A tuple (kind, reason). kind is "module", "member" or "unknown";
          reason says why an "unknown" could not be decided.
        """
        key = (package, name)
        if key not in self._cache:
            self._cache[key] = self._classify(package, name)
        return self._cache[key]

    def _classify(self, package: str, name: str) -> tuple[str, str]:
        """Classifies a name without the cache; see classify."""
        try:
            spec = _find_spec(package)
        except (ImportError, ValueError) as error:
            return "unknown", f"cannot locate {package!r}: {error}"
        if spec is None:
            return "unknown", f"{package!r} is not installed here"
        locations = spec.submodule_search_locations
        if locations is not None:
            submodule = importlib.machinery.PathFinder.find_spec(
                f"{package}.{name}", list(locations)
            )
            if submodule is not None:
                return "module", ""
        if not self._allow_import:
            return "member", ""
        try:
            with _quiet():
                module = importlib.import_module(package)
                value = getattr(module, name, None)
        except (Exception, SystemExit) as error:  # noqa: BLE001 - an isolation point: a package that fails to import must not stop the check.
            return "unknown", f"importing {package!r} failed: {error!r}"
        if inspect.ismodule(value):
            return "module", ""
        if value is None and not hasattr(module, name):
            return "unknown", f"{package!r} has no attribute {name!r}"
        return "member", ""


@functools.cache
def _read_toml(path: pathlib.Path) -> dict[str, Any] | None:
    """Parses a TOML file, or returns None when that is not possible."""
    if sys.version_info < (3, 11) or not path.is_file():
        return None
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return None


def _nested(table: object, *keys: str) -> object:
    """Returns table[k1][k2]... or None when any level is missing."""
    for key in keys:
        if not isinstance(table, dict):
            return None
        table = table.get(key)
    return table


def _ruff_settings(path: pathlib.Path) -> dict[str, Any] | None:
    """Returns the ruff settings a config file holds, or None if it has none."""
    data = _read_toml(path)
    if data is None or path.name != "pyproject.toml":
        return data
    settings = _nested(data, "tool", "ruff")
    return settings if isinstance(settings, dict) else None


def find_ruff_config(start: pathlib.Path) -> pathlib.Path:
    """Finds the ruff configuration that governs a file, as ruff does.

    Args:
      start: The file (or directory) being checked.

    Returns:
      The nearest .ruff.toml, ruff.toml or pyproject.toml with a [tool.ruff]
      table above start, or this skill's assets/ruff.toml when there is none.
    """
    directory = start.resolve()
    if not directory.is_dir():
        directory = directory.parent
    for folder in (directory, *directory.parents):
        for name in (".ruff.toml", "ruff.toml", "pyproject.toml"):
            candidate = folder / name
            if _ruff_settings(candidate) is not None:
                return candidate
    return _SKILL_RUFF_CONFIG


@functools.cache
def load_aliases(config: pathlib.Path) -> Mapping[str, str]:
    """Returns the standard import aliases a ruff config allows.

    Args:
      config: A ruff.toml, .ruff.toml or pyproject.toml.

    Returns:
      Module name to alias: ruff's defaults, replaced by `aliases` and
      extended by `extend-aliases` from the config.
    """
    aliases = dict(_RUFF_DEFAULT_ALIASES)
    settings = _ruff_settings(config) or {}
    table = _nested(settings, "lint", "flake8-import-conventions")
    if not isinstance(table, dict):
        table = _nested(settings, "flake8-import-conventions")
    if isinstance(table, dict):
        replacement = table.get("aliases")
        if isinstance(replacement, dict):
            aliases = {str(k): str(v) for k, v in replacement.items()}
        extension = table.get("extend-aliases")
        if isinstance(extension, dict):
            aliases.update({str(k): str(v) for k, v in extension.items()})
    return aliases


@functools.cache
def _project_declares_license(directory: pathlib.Path) -> bool:
    """Returns whether the project that holds directory declares a license."""
    for folder in (directory, *directory.parents):
        pyproject = folder / "pyproject.toml"
        if not pyproject.is_file() and not (folder / ".git").exists():
            continue
        if any(
            entry.is_file()
            and entry.name.upper().startswith(("LICENSE", "LICENCE", "COPYING"))
            for entry in folder.iterdir()
        ):
            return True
        return _nested(_read_toml(pyproject), "project", "license") is not None
    return False


@dataclasses.dataclass
class _Context:
    """What the checks need to know about one file.

    Attributes:
      path: The file.
      lines: Its source lines, without line endings.
      tree: Its parsed syntax tree.
      is_notebook: Whether it is a jupytext percent-format notebook.
      is_test: Whether it is a test module.
    """

    path: pathlib.Path
    lines: list[str]
    tree: ast.Module
    is_notebook: bool
    is_test: bool


def _figure_findings(scope: ast.AST) -> list[Finding]:
    """GS023: a figure that is saved must also be closed."""
    created: list[ast.Call] = []
    figure_names: set[str] = set()
    saves = closes = False
    nodes = list(_scope_nodes(scope))
    for node in nodes:
        if isinstance(node, ast.Call):
            name = _dotted_name(node.func)
            if _last_two(name) in _FIGURE_FACTORIES:
                created.append(node)
            elif name.endswith("savefig") or name == "plotstyle.save":
                saves = True
            elif _last_two(name) in _FIGURE_CLOSERS:
                closes = True
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            if _last_two(_dotted_name(node.value.func)) in _FIGURE_FACTORIES:
                figure_names |= _names_in(node.targets)
    returned = [
        node.value
        for node in nodes
        if isinstance(node, ast.Return) and node.value is not None
    ]
    returns_figure = bool(figure_names & _names_in(returned))
    if not created or not saves or closes or returns_figure:
        return []
    return [
        Finding(
            created[0].lineno,
            "GS023",
            "the figure is saved but never closed: call plt.close(fig) once"
            " it is written",
        )
    ]


class _Walker:
    """Walks one syntax tree and runs the checks that look at single nodes.

    Each handler checks its node and then walks the node's children itself,
    so that it can keep track of the enclosing scopes and loops.
    """

    def __init__(
        self,
        context: _Context,
        resolver: ImportResolver,
        aliases: Mapping[str, str],
    ) -> None:
        """Initializes the walker for one file.

        Args:
          context: The file being checked.
          resolver: Decides what `from x import y` imports.
          aliases: The standard import aliases, module name to alias.
        """
        self.findings: list[Finding] = []
        self.notes: list[str] = []
        self._context = context
        self._resolver = resolver
        self._aliases = aliases
        self._scopes: list[ast.AST] = []
        self._loop_depth = 0
        self._managed: set[int] = set()
        self._concatenations: set[int] = set()
        self._named: set[str] = set()
        self._handlers: dict[type[ast.AST], Callable[[Any], None]] = {
            ast.AnnAssign: self._on_ann_assign,
            ast.Assign: self._on_assign,
            ast.AsyncFor: self._on_loop,
            ast.AsyncFunctionDef: self._on_function,
            ast.AsyncWith: self._on_with,
            ast.AugAssign: self._on_aug_assign,
            ast.BinOp: self._on_bin_op,
            ast.Call: self._on_call,
            ast.ClassDef: self._on_class,
            ast.Compare: self._on_compare,
            ast.DictComp: self._on_comprehension,
            ast.For: self._on_loop,
            ast.FunctionDef: self._on_function,
            ast.GeneratorExp: self._on_comprehension,
            ast.Import: self._on_import,
            ast.ImportFrom: self._on_import_from,
            ast.ListComp: self._on_comprehension,
            ast.Name: self._on_name,
            ast.Return: self._on_return,
            ast.SetComp: self._on_comprehension,
            ast.UnaryOp: self._on_unary_op,
            ast.While: self._on_loop,
            ast.With: self._on_with,
        }

    def walk(self, node: ast.AST) -> None:
        """Checks node and everything below it."""
        handler = self._handlers.get(type(node))
        if handler is None:
            self._walk_children(node)
        else:
            handler(node)

    def _walk_children(self, node: ast.AST) -> None:
        """Checks everything below node."""
        for child in ast.iter_child_nodes(node):
            self.walk(child)

    def _walk_scope(self, node: ast.ClassDef | _Function) -> None:
        """Walks a class or function body as a new scope, outside any loop."""
        self._scopes.append(node)
        loop_depth, self._loop_depth = self._loop_depth, 0
        self._walk_children(node)
        self._loop_depth = loop_depth
        self._scopes.pop()

    def _report(self, node: ast.AST, code: str, message: str) -> None:
        """Records a finding that spans node."""
        line = getattr(node, "lineno", 1)
        end_line = getattr(node, "end_lineno", None) or line
        self.findings.append(Finding(line, code, message, end_line))

    def _on_import_from(self, node: ast.ImportFrom) -> None:
        """GS001: only modules may follow `from package import`."""
        package = node.module
        if node.level or package is None or package in _EXEMPT_FROM_IMPORTS:
            return
        for alias in node.names:
            if alias.name == "*":
                continue
            kind, reason = self._resolver.classify(package, alias.name)
            if kind == "member":
                parent, _, last = package.rpartition(".")
                form = f"from {parent} import {last}" if parent else None
                self._report(
                    node,
                    "GS001",
                    f"`from {package} import {alias.name}` imports a member;"
                    f" use `{form or 'import ' + package}` and write"
                    f" `{last}.{alias.name}`",
                )
            elif kind == "unknown":
                self.notes.append(
                    f"{self._context.path}:{node.lineno}: NOTE could not"
                    f" verify `from {package} import {alias.name}` ({reason})"
                )

    def _on_import(self, node: ast.Import) -> None:
        """GS002: an alias must be a standard abbreviation."""
        for alias in node.names:
            name, asname = alias.name, alias.asname
            if asname is None or name in self._aliases:
                continue  # ICN001 checks modules that have a standard alias.
            if asname in (name, name.rpartition(".")[2]):
                continue  # PLC0414 and PLR0402 report these.
            self._report(
                node,
                "GS002",
                f"`import {name} as {asname}`: {asname} is not a standard"
                " abbreviation; import the module under its own name, or add"
                " the alias to the ruff config if the field always uses it",
            )

    def _on_class(self, node: ast.ClassDef) -> None:
        """GS012 custom metaclasses and GS019 class docstrings."""
        for keyword in node.keywords:
            name = _dotted_name(keyword.value)
            if keyword.arg == "metaclass" and not name.endswith(
                ("ABCMeta", "EnumMeta", "EnumType")
            ):
                self._report(
                    node,
                    "GS012",
                    f"custom metaclass {name or '...'}: a power feature; use"
                    " plain classes, dataclasses or abc",
                )
        docstring = _docstring(node)
        if docstring is not None:
            statement, text = docstring
            summary = text.strip()
            is_exception = any(
                _dotted_name(base).endswith(("Error", "Exception", "Warning"))
                for base in node.bases
            )
            if _CLASS_PHRASE.match(summary) or (
                is_exception and _EXCEPTION_PHRASE.match(summary)
            ):
                what = "the error" if is_exception else "an instance"
                self._report(
                    statement,
                    "GS019",
                    f"class docstring of {node.name}: say what {what}"
                    " represents, not that it is a class or when it is raised",
                )
        self._walk_scope(node)

    def _on_function(self, node: _Function) -> None:
        """Runs the function-level checks, then walks the body."""
        enclosing = self._scopes[-1] if self._scopes else None
        in_class = isinstance(enclosing, ast.ClassDef)
        for decorator in node.decorator_list:
            if _dotted_name(decorator).endswith("staticmethod"):
                self._report(
                    decorator,
                    "GS011",
                    f"@staticmethod on {node.name}: write a module-level"
                    " function instead, unless an existing API demands it",
                )
        if in_class and node.name == "__del__":
            self._report(
                node,
                "GS012",
                "__del__ runs at an unpredictable time: release resources"
                " with a context manager or an explicit close()",
            )
        if isinstance(enclosing, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self._check_nested(node, enclosing)
        self._check_arguments(node)
        self._check_public_parameters(node)
        self._check_docstring(node, in_class)
        self._check_length(node)
        self.findings.extend(_figure_findings(node))
        self._walk_scope(node)

    def _check_nested(self, node: _Function, enclosing: _Function) -> None:
        """GS005: a nested function must close over an enclosing local."""
        outer = _bound_names(enclosing) - {"self", "cls"}
        parts = [
            *node.decorator_list,
            *node.args.defaults,
            *(d for d in node.args.kw_defaults if d is not None),
            *node.body,
        ]
        loads = _names_in(parts, ast.Load)
        if not loads & (outer - _bound_names(node)):
            self._report(
                node,
                "GS005",
                f"nested function {node.name} uses no local of"
                f" {enclosing.name}: define it at module level as"
                f" _{node.name.lstrip('_')} so tests can reach it",
            )

    def _check_arguments(self, node: _Function) -> None:
        """GS003 leading asserts, GS009 `x = x or default`, GS025 names."""
        parameters = _parameter_names(node.args)
        for name in sorted(parameters):
            self._check_name(node, name)
        body = node.body[1:] if _docstring(node) else node.body
        for statement in body if not self._context.is_test else ():
            if not isinstance(statement, ast.Assert):
                break
            used = _names_in([statement.test])
            checked = sorted(used & parameters - {"self", "cls"})
            if checked:
                self._report(
                    statement,
                    "GS003",
                    f"assert validates argument {checked[0]}: raise"
                    " ValueError (or TypeError) instead; python -O strips"
                    " asserts",
                )
        for child in _scope_nodes(node):
            if not (
                isinstance(child, ast.Assign)
                and len(child.targets) == 1
                and isinstance(child.targets[0], ast.Name)
                and isinstance(child.value, ast.BoolOp)
                and isinstance(child.value.op, ast.Or)
            ):
                continue
            name = child.targets[0].id
            first = child.value.values[0]
            if name in parameters and isinstance(first, ast.Name):
                if first.id == name:
                    self._report(
                        child,
                        "GS009",
                        f"`{name} = {name} or ...` also replaces 0, '' and"
                        f" []: write `if {name} is None:`",
                    )

    def _check_public_parameters(self, node: _Function) -> None:
        """GS030: a public function's parameters have descriptive names.

        Tests and notebooks are not a public API, and nor is a function
        that is private, nested in another function, or a method of a
        private class.
        """
        if self._context.is_test or self._context.is_notebook:
            return
        hidden = _is_private(node.name) or any(
            isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef))
            or (isinstance(scope, ast.ClassDef) and _is_private(scope.name))
            for scope in self._scopes
        )
        if hidden:
            return
        short = sorted(
            name
            for name in _parameter_names(node.args)
            if len(name) == 1 and name != "_"
        )
        if short:
            names = ", ".join(short)
            self._report(
                node,
                "GS030",
                f"{node.name} is public, so its parameters need descriptive"
                f" names, not {names}; keep a paper's notation for internal"
                " code, with the source cited",
            )

    def _check_docstring(self, node: _Function, in_class: bool) -> None:
        """GS016 docstring style, GS017 properties, GS018 generators."""
        docstring = _docstring(node)
        if docstring is None:
            return
        statement, text = docstring
        if _NUMPY_SECTION.search(text) or _REST_FIELD.search(text):
            self._report(
                statement,
                "GS016",
                f"docstring of {node.name}: use Google sections (Args:,"
                " Returns:, Raises:), not NumPy underlines or reST fields",
            )
        decorators = {
            _dotted_name(d).rpartition(".")[2] for d in node.decorator_list
        }
        is_property = bool(decorators & {"property", "cached_property"})
        if in_class and is_property and _GETTER_PHRASE.match(text.strip()):
            self._report(
                statement,
                "GS017",
                f"property {node.name}: describe the attribute (`The ...`),"
                " not the act of returning it",
            )
        is_generator = any(
            isinstance(child, (ast.Yield, ast.YieldFrom))
            for child in _scope_nodes(node)
        )
        has_returns = re.search(r"^\s*Returns:", text, re.MULTILINE)
        has_yields = re.search(r"^\s*Yields:", text, re.MULTILINE)
        if is_generator and has_returns and not has_yields:
            self._report(
                statement,
                "GS018",
                f"generator {node.name}: document what next() gives under"
                " Yields:, not Returns:",
            )

    def _check_length(self, node: _Function) -> None:
        """GS027: a function body of more than about 40 lines."""
        body = node.body[1:] if _docstring(node) else node.body
        if not body:
            return
        length = (node.end_lineno or body[-1].lineno) - body[0].lineno + 1
        if length > _MAX_FUNCTION_LINES:
            self._report(
                node,
                "GS027",
                f"{node.name} has a {length}-line body: see whether it splits"
                " into smaller functions without harming its structure",
            )

    def _check_name(self, node: ast.AST, name: str) -> None:
        """GS025: a name that ends in its container type, once per name."""
        if name in self._named or not name.endswith(_CONTAINER_SUFFIXES):
            return
        self._named.add(name)
        self._report(
            node,
            "GS025",
            f"{name} repeats its type; name what it holds (`names`, not"
            " `names_list`)",
        )

    def _on_name(self, node: ast.Name) -> None:
        """GS025 on assignment targets."""
        if isinstance(node.ctx, ast.Store):
            self._check_name(node, node.id)

    def _on_loop(self, node: ast.For | ast.AsyncFor | ast.While) -> None:
        """Walks a loop one level deeper, for GS021."""
        self._loop_depth += 1
        self._walk_children(node)
        self._loop_depth -= 1

    def _on_aug_assign(self, node: ast.AugAssign) -> None:
        """GS021: accumulating a string with += inside a loop."""
        if (
            self._loop_depth
            and isinstance(node.op, ast.Add)
            and _is_str_expression(node.value)
        ):
            self._report(
                node,
                "GS021",
                "building a string with += in a loop can take quadratic"
                " time: append the parts to a list and ''.join() it",
            )
        self._walk_children(node)

    def _on_bin_op(self, node: ast.BinOp) -> None:
        """GS020: formatting a string with a chain of +."""
        if isinstance(node.op, ast.Add) and id(node) not in (
            self._concatenations
        ):
            operands = []
            pending: list[ast.expr] = [node]
            while pending:
                current = pending.pop()
                if isinstance(current, ast.BinOp) and isinstance(
                    current.op, ast.Add
                ):
                    self._concatenations.add(id(current))
                    pending.extend((current.right, current.left))
                else:
                    operands.append(current)
            if len(operands) >= 3 and any(map(_is_str_literal, operands)):
                self._report(
                    node,
                    "GS020",
                    "string built with +: use an f-string (or % or str.format)",
                )
        self._walk_children(node)

    def _on_compare(self, node: ast.Compare) -> None:
        """GS007 len() compared with 0, GS008 comparison with []."""
        if len(node.ops) == 1:
            left, op, right = node.left, node.ops[0], node.comparators[0]
            if _is_len_emptiness(left, op, right):
                self._report(
                    node,
                    "GS007",
                    "emptiness via len(): write `if seq:` or `if not seq:`"
                    " (for a NumPy array, test `.size`)",
                )
            if isinstance(op, (ast.Eq, ast.NotEq)) and (
                _is_empty_literal(left) or _is_empty_literal(right)
            ):
                self._report(
                    node,
                    "GS008",
                    "comparison with an empty literal: write `if not x:` or"
                    " `if x:`",
                )
        self._walk_children(node)

    def _on_unary_op(self, node: ast.UnaryOp) -> None:
        """GS010: `not x % n` hides an integer comparison."""
        operand = node.operand
        if (
            isinstance(node.op, ast.Not)
            and isinstance(operand, ast.BinOp)
            and isinstance(operand.op, ast.Mod)
        ):
            self._report(
                node,
                "GS010",
                "`not x % n`: compare the integer explicitly, `x % n == 0`",
            )
        self._walk_children(node)

    def _on_comprehension(self, node: _Comprehension) -> None:
        """GS006: several for clauses, or several if filters."""
        if len(node.generators) > 1 or any(
            len(generator.ifs) > 1 for generator in node.generators
        ):
            self._report(
                node,
                "GS006",
                "comprehension with several for clauses or filters: write"
                " the loops out",
            )
        self._walk_children(node)

    def _on_with(self, node: ast.With | ast.AsyncWith) -> None:
        """Marks context managers, which GS022 accepts."""
        self._managed.update(id(item.context_expr) for item in node.items)
        self._walk_children(node)

    def _on_return(self, node: ast.Return) -> None:
        """A returned resource is the caller's to close (GS022)."""
        if node.value is not None:
            self._managed.add(id(node.value))
        self._walk_children(node)

    def _on_call(self, node: ast.Call) -> None:
        """GS022 resources outside `with`, GS012 frame and import hacks."""
        name = _dotted_name(node.func)
        if name.endswith(("closing", "enter_context")):
            self._managed.update(id(arg) for arg in node.args)
        if _last_two(name) in _RESOURCE_OPENERS and id(node) not in (
            self._managed
        ):
            self._report(
                node,
                "GS022",
                f"{name}() holds a resource until closed: open it in a"
                " `with` block, or document how its lifetime is managed",
            )
        if name in ("compile", "__import__", "sys._getframe"):
            self._report(
                node,
                "GS012",
                f"{name}(): a power feature; find a plain way to do this",
            )
        self._walk_children(node)

    def _on_assign(self, node: ast.Assign) -> None:
        """GS012 reparenting and GS029 type variable names."""
        for target in node.targets:
            if isinstance(target, ast.Attribute) and target.attr in (
                "__class__",
                "__bases__",
            ):
                self._report(
                    node,
                    "GS012",
                    f"assigning {target.attr}: a power feature (object"
                    " reparenting or dynamic inheritance)",
                )
        if (
            len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Call)
        ):
            self._check_type_variable(node.targets[0].id, node.value)
        self._walk_children(node)

    def _on_ann_assign(self, node: ast.AnnAssign) -> None:
        """GS029 on annotated assignments of type variables."""
        if isinstance(node.target, ast.Name) and isinstance(
            node.value, ast.Call
        ):
            self._check_type_variable(node.target.id, node.value)
        self._walk_children(node)

    def _check_type_variable(self, name: str, call: ast.Call) -> None:
        """GS029: one-letter names only for private, free type variables."""
        kind = _dotted_name(call.func).rpartition(".")[2]
        if kind not in ("TypeVar", "ParamSpec", "TypeVarTuple"):
            return
        letters = name.lstrip("_")
        short = len(letters) == 1 or (
            len(letters) == 2 and letters[1].isdigit()
        )
        constrained = len(call.args) > 1 or any(
            keyword.arg == "bound" for keyword in call.keywords
        )
        if short and (not name.startswith("_") or constrained):
            self._report(
                call,
                "GS029",
                f"{kind} {name}: only a private, unconstrained type variable"
                " may have a one-letter name",
            )


def _check_module(context: _Context) -> list[Finding]:
    """Runs the checks that look at the module as a whole."""
    if not context.tree.body:
        return []
    findings = _module_docstring_findings(context) + _license_findings(context)
    if context.is_notebook or context.is_test:
        return findings
    findings += _figure_findings(context.tree)
    for statement in context.tree.body:
        if isinstance(statement, ast.If) and _is_main_guard(statement):
            findings += _main_guard_findings(statement)
        else:
            findings += _top_level_code_findings(statement)
            findings += _mutable_global_findings(statement)
    return findings


def _module_docstring_findings(context: _Context) -> list[Finding]:
    """GS014: a module docstring, or a title cell in a notebook."""
    if context.is_test or context.path.name == "__init__.py":
        return []
    if _docstring(context.tree) is not None:
        return []
    if not context.is_notebook:
        message = (
            "no module docstring: start the file with one that says what it"
            " contains and how to use it"
        )
    elif not _has_title_cell(context.lines):
        message = (
            "notebook without a title cell: open it with a `# %% [markdown]`"
            " cell that says what it does (it stands in for the module"
            " docstring)"
        )
    else:
        return []
    return [Finding(1, "GS014", message)]


def _license_findings(context: _Context) -> list[Finding]:
    """GS015: license boilerplate in a project that declares a license."""
    if not _project_declares_license(context.path.resolve().parent):
        return []
    if any(_LICENSE_COMMENT.match(line) for line in context.lines[:50]):
        return []
    return [
        Finding(
            1,
            "GS015",
            "the project declares a license: put its boilerplate, e.g."
            " `# SPDX-License-Identifier: MIT`, at the top of the file",
        )
    ]


def _main_guard_findings(guard: ast.If) -> list[Finding]:
    """GS026: the __main__ guard holds one call and nothing else."""
    if len(guard.body) == 1 and _is_single_call(guard.body[0]):
        return []
    return [
        Finding(
            guard.lineno,
            "GS026",
            "the __main__ guard holds program logic: move it into main() and"
            " leave only the call",
            guard.end_lineno or guard.lineno,
        )
    ]


def _top_level_code_findings(statement: ast.stmt) -> list[Finding]:
    """GS026: a call or a loop at module level runs on import."""
    is_call = isinstance(statement, ast.Expr) and isinstance(
        statement.value, ast.Call
    )
    if not is_call and not isinstance(
        statement, (ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith)
    ):
        return []
    return [
        Finding(
            statement.lineno,
            "GS026",
            "top-level code runs whenever the module is imported: move it"
            " into main(), called from `if __name__ == '__main__':`",
            statement.end_lineno or statement.lineno,
        )
    ]


def _is_mutable_container(node: ast.expr) -> bool:
    """Returns whether node builds a list, a dict, a set or the like."""
    displays = (
        ast.Dict,
        ast.DictComp,
        ast.List,
        ast.ListComp,
        ast.Set,
        ast.SetComp,
    )
    if isinstance(node, displays):
        return True
    if not isinstance(node, ast.Call):
        return False
    return _dotted_name(node.func).rpartition(".")[2] in _MUTABLE_FACTORIES


def _mutable_global_findings(statement: ast.stmt) -> list[Finding]:
    """GS004: a public module-level name bound to a mutable container."""
    if isinstance(statement, ast.Assign):
        targets, value = statement.targets, statement.value
    elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
        targets, value = [statement.target], statement.value
    else:
        return []
    if not _is_mutable_container(value):
        return []
    return [
        Finding(
            statement.lineno,
            "GS004",
            f"{target.id} is public mutable global state: make it a constant,"
            f" or internal (_{target.id}) with a comment saying why",
            statement.end_lineno or statement.lineno,
        )
        for target in targets
        if isinstance(target, ast.Name)
        and not target.id.startswith("_")
        and not target.id.isupper()
    ]


def _has_title_cell(lines: Sequence[str]) -> bool:
    """Returns whether a notebook's first cell is a non-empty markdown cell."""
    start = 0
    if lines and lines[0].strip() == "# ---":
        closing = [i for i, line in enumerate(lines[1:], 1) if line == "# ---"]
        start = closing[0] + 1 if closing else 0
    markers = [
        index
        for index in range(start, len(lines))
        if _CELL_MARKER.match(lines[index])
    ]
    if not markers or "[markdown]" not in lines[markers[0]]:
        return False
    end = markers[1] if len(markers) > 1 else len(lines)
    return any(
        re.match(r"#\s*\S", line) or not line.startswith("#") and line.strip()
        for line in lines[markers[0] + 1 : end]
    )


def _check_tokens(source: str, lines: Sequence[str]) -> list[Finding]:
    """GS013 blank line after def, GS024 TODO layout, GS028 type comments."""
    findings: list[Finding] = []
    tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    for index, token in enumerate(tokens):
        if token.type == tokenize.COMMENT:
            findings.extend(_check_comment(token))
        elif token.type == tokenize.NAME and token.string == "def":
            blank = _blank_after_def(tokens, index, lines)
            if blank:
                findings.append(
                    Finding(
                        token.start[0],
                        "GS013",
                        f"line {blank} is blank directly after the def line:"
                        " remove it",
                        blank,
                    )
                )
    return findings


def _blank_after_def(
    tokens: Sequence[tokenize.TokenInfo], index: int, lines: Sequence[str]
) -> int:
    """Returns the blank line after a def header, or 0 if there is none."""
    depth = 0
    for position in range(index + 1, len(tokens)):
        token = tokens[position]
        if token.type != tokenize.OP:
            continue
        if token.string in "([{":
            depth += 1
        elif token.string in ")]}":
            depth -= 1
        elif token.string == ":" and depth == 0:
            header_end, column = token.end
            rest = lines[header_end - 1][column:].strip()
            if rest and not rest.startswith("#"):
                return 0  # The body shares the def line.
            if header_end < len(lines) and not lines[header_end].strip():
                return header_end + 1
            return 0
    return 0


def _check_comment(token: tokenize.TokenInfo) -> list[Finding]:
    """GS024 TODO layout and GS028 type comments in one comment token."""
    line = token.start[0]
    comment = token.string
    if _TYPE_COMMENT.match(comment):
        return [
            Finding(
                line,
                "GS028",
                "`# type:` comment: annotate the variable instead"
                " (`name: Type = value`)",
            )
        ]
    todo = _TODO.match(comment)
    if todo is None:
        return []
    rest = todo.group("rest")
    if rest.startswith("("):
        return [
            Finding(
                line,
                "GS024",
                "old-style TODO(...): write `# TODO: <link> - <explanation>`"
                " with an issue link, not a person",
            )
        ]
    words = rest.lstrip(":").split()
    has_link = rest.startswith(":") and words and _LINK.match(words[0])
    if has_link and (len(words) < 3 or words[1] != "-"):
        return [
            Finding(
                line,
                "GS024",
                f"separate the link from the explanation: `# TODO: {words[0]}"
                " - <what to do>`",
            )
        ]
    return []


def _suppressions(source: str) -> tuple[dict[int, set[str]], set[str]]:
    """Returns the codes suppressed per line and for the whole file."""
    per_line: dict[int, set[str]] = {}
    whole_file: set[str] = set()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.COMMENT:
            continue
        file_match = _FILE_NOQA.match(token.string)
        if file_match:
            whole_file.update(re.findall(r"[A-Z]+\d+", file_match["codes"]))
            continue
        line_match = _NOQA.search(token.string)
        if line_match:
            codes = set(re.findall(r"[A-Z]+\d+", line_match["codes"]))
            per_line.setdefault(token.start[0], set()).update(codes)
    return per_line, whole_file


def check_source(
    source: str,
    path: pathlib.Path,
    resolver: ImportResolver,
    aliases: Mapping[str, str],
) -> tuple[list[Finding], list[str]]:
    """Checks the source of one file.

    Args:
      source: The file's contents.
      path: Where the file lives, which decides whether it is a test module
        and whether its project declares a license.
      resolver: Decides what `from x import y` imports.
      aliases: Standard import aliases, module name to alias.

    Returns:
      A tuple (findings, notes): the findings no noqa suppresses, in line
      order, and a note for each import that could not be verified.

    Raises:
      SyntaxError: If the source does not parse.
    """
    tree = ast.parse(source, filename=str(path))
    lines = source.splitlines()
    context = _Context(
        path=path,
        lines=lines,
        tree=tree,
        is_notebook=any(_CELL_MARKER.match(line) for line in lines),
        is_test=_is_test_file(path),
    )
    walker = _Walker(context, resolver, aliases)
    walker.walk(tree)
    findings = walker.findings + _check_module(context)
    findings += _check_tokens(source, lines)
    per_line, whole_file = _suppressions(source)
    kept = {
        finding
        for finding in findings
        if finding.code not in whole_file
        and not any(
            finding.code in per_line.get(line, ())
            for line in range(
                finding.line, max(finding.line, finding.end_line) + 1
            )
        )
    }
    return sorted(kept), walker.notes


def _python_files(paths: Sequence[str]) -> Iterator[pathlib.Path]:
    """Yields the .py files named by paths, searching directories."""
    for name in paths:
        path = pathlib.Path(name)
        if not path.is_dir():
            yield path
            continue
        for candidate in sorted(path.rglob("*.py")):
            folders = candidate.relative_to(path).parts[:-1]
            if not any(
                part.startswith(".") or part in _SKIPPED_DIRS
                for part in folders
            ):
                yield candidate


def _parse_arguments(argv: Sequence[str]) -> argparse.Namespace:
    """Parses the command line."""
    parser = argparse.ArgumentParser(
        description="Checks Python files against the Google style rules that"
        " ruff cannot see."
    )
    parser.add_argument("paths", nargs="*", help="files or directories")
    parser.add_argument(
        "--strict", action="store_true", help="fail on warnings too"
    )
    parser.add_argument(
        "--no-import",
        action="store_true",
        help="never import a package to classify `from x import y`",
    )
    parser.add_argument(
        "--config",
        type=pathlib.Path,
        help="ruff config for the standard aliases (default: the nearest)",
    )
    parser.add_argument(
        "--list", action="store_true", help="list the rules and exit"
    )
    return parser.parse_args(argv)


def _print_rules() -> None:
    """Prints one line per rule: code, level, guide section, summary."""
    for rule in _RULE_LIST:
        level = "error" if rule.is_error else "warning"
        section = f"§{rule.section}"
        print(f"{rule.code}  {level:<7}  {section:<8}  {rule.summary}")


def _check_file(
    path: pathlib.Path, config: pathlib.Path | None, resolver: ImportResolver
) -> tuple[int, int, int]:
    """Checks one file and prints what it finds.

    Args:
      path: The file.
      config: The ruff config that names the standard aliases, or None for
        the one nearest the file.
      resolver: Decides what `from x import y` imports.

    Returns:
      A tuple (errors, warnings, unverified imports).
    """
    aliases = load_aliases(config or find_ruff_config(path))
    try:
        source = path.read_text(encoding="utf-8")
        findings, notes = check_source(source, path, resolver, aliases)
    except (OSError, SyntaxError, UnicodeDecodeError) as error:
        print(f"{path}: ERROR cannot check: {error}")
        return 1, 0, 0
    errors = 0
    for finding in findings:
        rule = RULES[finding.code]
        errors += rule.is_error
        level = "ERROR" if rule.is_error else "WARN"
        print(
            f"{path}:{finding.line}: {level} {finding.code}"
            f" {finding.message} (§{rule.section})"
        )
    for note in notes:
        print(note)
    if not findings:
        print(f"{path}: OK")
    return errors, len(findings) - errors, len(notes)


def main(argv: Sequence[str] | None = None) -> int:
    """Checks the files named on the command line and prints the findings.

    Args:
      argv: The arguments after the program name; None reads sys.argv.

    Returns:
      The exit status: 1 for errors (or warnings under --strict), 2 for bad
      usage, 0 otherwise.
    """
    arguments = _parse_arguments(sys.argv[1:] if argv is None else argv)
    if arguments.list:
        _print_rules()
        return 0
    if not arguments.paths:
        print("no files given (try --help)", file=sys.stderr)
        return 2
    if os.getcwd() not in sys.path:
        sys.path.insert(0, os.getcwd())
    resolver = ImportResolver(allow_import=not arguments.no_import)
    errors = warnings_found = unverified = 0
    for path in _python_files(arguments.paths):
        counts = _check_file(path, arguments.config, resolver)
        errors += counts[0]
        warnings_found += counts[1]
        unverified += counts[2]
    print(
        f"\n{errors} error(s), {warnings_found} warning(s),"
        f" {unverified} unverified import(s)"
    )
    return 1 if errors or (arguments.strict and warnings_found) else 0


if __name__ == "__main__":
    sys.exit(main())
