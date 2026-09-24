---
name: code-style
description: >-
  Write, edit and review Python to the Google Python Style Guide: import
  packages and modules, never their members; Google docstrings (Args:,
  Returns:, Raises:) with shapes and units; annotated signatures (X | None);
  80-column lines; the guide's rules on exceptions, defaults, truthiness,
  resources, naming and main(). ruff replaces pylint and Black, mypy
  replaces pytype, uv manages Python, environments and dependencies, and a
  bundled checker covers what ruff cannot. The DEFAULT for all Python you
  write or change, notebooks and tests included, unless the user explicitly
  asks otherwise. Use whenever creating, editing, refactoring or reviewing a
  .py file, or when the user mentions code style, Google style, PEP 8, lint,
  format, ruff, pylint, black, mypy, type hints, docstrings, imports, uv,
  pip, dependencies or pyproject. NOT for other languages, figure styling
  (plot-style) or notebook cell layout (jupytext).
license: MIT
metadata:
  version: "1.0.1"
---

# Code Style: Google Python, with ruff and uv

## Overview

All Python follows the [Google Python Style Guide][guide]. Every one of its
rules is restated, section by section, in
[references/rules.md](references/rules.md), each with its reason, an example
and the check that enforces it. This file is the working digest. Section
numbers (§) are the guide's.

The rules are the guide's; the tools are not:

| The guide uses | This skill uses |
|---|---|
| pylint with Google's pylintrc | `ruff check` with [assets/ruff.toml](assets/ruff.toml), every rule mapped to a guide section or to the pylint check it replaces |
| Black or Pyink | `ruff format` (80 columns, 4-space indents, double quotes) |
| pytype (now discontinued) | mypy with [assets/mypy.ini](assets/mypy.ini) |
| nothing on packaging | uv for Python versions, environments, dependencies and lockfiles |
| — | [scripts/check_code_style.py](scripts/check_code_style.py): codes GS001–GS030, the rules no ruff rule expresses |

One deliberate tightening: the guide requires annotations on public APIs;
code written under this skill annotates **every** function signature.

This skill is **harness-agnostic**. The rules need only a way to write files;
the checks need a shell with uv, or with ruff, mypy and Python 3.10+.

---

## When to Apply

<HARD-RULE>
These rules are the DEFAULT for every Python file you write or edit —
modules, scripts, jupytext notebooks, tests. Apply them unless the user
explicitly asks for something else.
</HARD-RULE>

- **Writing new code**: every rule, every time.
- **Editing existing code** (§4): the code you add or change follows the
  rules; where the guide leaves a choice open, match the file. Do not
  restyle untouched code, reformat a whole file that was not formatted
  before, or fix old lint findings, unless asked; mention them once instead.
- **Reviewing**: report findings with the rule's section number and a
  concrete fix.
- **Tooling**: new projects and standalone scripts use uv. A project that
  already uses conda, pip, poetry or its own ruff/mypy configuration keeps
  it; offer to change it, and change it only on a yes.

Not for other languages, for how figures look (plot-style), or for the cell
layout of a notebook (jupytext) — though the code inside the cells follows
this skill.

---

## Toolchain

Full commands, configuration and edge cases are in
[references/tooling.md](references/tooling.md). The short form:

```bash
# A new project: package layout, dev tools, the skill's configs.
uv init --package myproject --python 3.12
cd myproject
uv add numpy scipy
uv add --dev ruff mypy pytest
cp <skill-dir>/assets/ruff.toml <skill-dir>/assets/mypy.ini .

# A standalone script: dependencies declared inside the file (PEP 723).
uv add --script reduce.py numpy astropy
uv run reduce.py
```

- `uv init --package` leaves a hello-world `main()` without a docstring in
  `src/<package>/__init__.py` and points `[project.scripts]` at it: replace
  both (a package docstring; your real entry point), then check the whole
  new project, not just the files you wrote.
- Dependencies change only through `uv add` / `uv remove`. `pyproject.toml`,
  `uv.lock` and `.python-version` belong under version control (commit only
  when the user asks). Never `pip install` into a uv environment or the
  system Python.
- Only a **standalone** script or notebook carries a `# /// script` block;
  inside a uv project the dependencies live in `pyproject.toml`. In a
  standalone jupytext notebook the block goes at the top of the imports
  cell, never above the jupytext header (the first `uv add --script` puts it
  at the very top: move it once).
- A project's own ruff/mypy config wins. With none, pass the skill's:
  `uvx ruff check --config <skill-dir>/assets/ruff.toml <files>`.

---

## The Rules

Every section of the guide, in one or two lines. The codes after each rule
are what catches a violation: ruff rules, `GS` checker codes, `format` for
the formatter, `mypy`. Read [references/rules.md](references/rules.md) when
writing docstrings or annotations, and whenever a rule's scope is unclear.

### Language rules (§2)

- **§2.1 Lint.** Lint everything. Suppress one rule on one line, with the
  reason: `# noqa: N802 - name fixed by http.server.` Never a bare `noqa`.
  An argument you must accept but do not use: `del logs  # Unused.` at the
  top of the body. *PGH004, RUF100, ARG*
- **§2.2 Imports.** Import packages and modules only: `import pathlib` then
  `pathlib.Path`; `import dataclasses` then `@dataclasses.dataclass`;
  `from scipy import optimize` then `optimize.curve_fit`;
  `from astropy import coordinates` then `coordinates.SkyCoord`. Alias only
  to the standard abbreviation (`np`, `pd`, `plt`, `u`, `xr`, `jnp`), or
  with `from x import y as z` when `y` collides or is too generic. Symbols
  from `typing`, `collections.abc` and `typing_extensions` are imported
  directly. No relative imports. *GS001, GS002, ICN001, PLR0402, TID252*
- **§2.3 Packages.** Import by the full package path; never rely on the
  script's directory being on `sys.path` (install the project instead).
- **§2.4 Exceptions.** Raise built-in exceptions where they fit
  (`ValueError` for a bad argument). Own exceptions inherit from one, end in
  `Error`, and do not repeat the module name. No `except:` or
  `except Exception` unless re-raising or at an isolation point that records
  the error. Small `try` bodies; `finally` or `with` for cleanup; `raise ...
  from error` when translating. Never `assert` to validate arguments —
  `python -O` strips asserts — but asserts in pytest are expected.
  *E722, BLE001, TRY002, TRY203, B904, N818, GS003*
- **§2.5 Mutable global state.** Avoid it. When unavoidable: an `_internal`
  name, a comment saying why, access through functions. Constants in
  `CAPS_WITH_UNDER` are welcome. Randomness through a
  `np.random.default_rng(seed)` passed around, never `np.random.seed`.
  *GS004, NPY002*
- **§2.6 Nested functions.** Nest only to close over a local other than
  `self`/`cls`; otherwise a module-level `_helper`. Inner classes are fine.
  *GS005*
- **§2.7 Comprehensions.** One `for` and at most one `if`; otherwise write
  the loops. *GS006*
- **§2.8 Default iterators.** `for key in table`, `for line in handle`,
  `for key, value in table.items()`; never iterate `.keys()` or
  `.readlines()`; never mutate a container while iterating it.
  *SIM118, FURB129*
- **§2.9 Generators.** Fine; document `Yields:`; release held resources
  deterministically. *GS018*
- **§2.10 Lambdas.** One short expression only; a generator expression over
  `map`/`filter` with a lambda; `operator.mul` over `lambda a, b: a * b`;
  never assign a lambda to a name. *E731, C417, PLW0108*
- **§2.11 Conditional expressions.** Only when each part fits on one line.
- **§2.12 Default arguments.** Never a mutable or a call
  (`=[]`, `=np.zeros(3)`, `=time.time()`); default to `None` and fill in.
  *B006, B008, RUF009*
- **§2.13 Properties.** Only for cheap, obvious access or trivial derived
  values, via `@property`; a pass-through property should be a public
  attribute.
- **§2.14 True/False.** `if not seq:` for emptiness; `is None` for None;
  never `== True`/`== False`; integers compared with 0 explicitly
  (`i % 10 == 0`). NumPy arrays: `.size`, `.any()`, `.all()` — never
  `if array:`. *E711, E712, PLC1802, PLW0177, GS007–GS010*
- **§2.16 Lexical scoping.** Closures are fine; beware late binding of loop
  variables. *B023*
- **§2.17 Decorators.** Only for a clear gain; documented as decorators;
  tested; no I/O at import. No `@staticmethod` (a module-level function
  instead); `@classmethod` only for named constructors or class-wide state.
  *GS011*
- **§2.18 Threading.** Do not rely on built-in atomicity; `queue.Queue`,
  `threading.Condition`, or a `concurrent.futures` executor in a `with`.
- **§2.19 Power features.** No custom metaclasses, `__del__`, `exec`,
  `eval`, `compile`, frame hacks, reparenting or import hooks; `abc`,
  `dataclasses` and `enum` are fine. *S102, S307, GS012*
- **§2.20 `from __future__`.** Welcome where needed; keep existing ones
  until old interpreters are out of the picture. *UP010*
- **§2.21 Type annotations.** Annotate every signature and type-check with
  mypy. *ANN, mypy*

### Style rules (§3)

- **§3.1 Semicolons.** None. *E702, E703*
- **§3.2 Line length.** 80 columns. No backslash continuations: implicit
  joining in parentheses, broken at the highest syntactic level; long
  strings as adjacent literals in parentheses; long URLs on their own
  comment line. *E501, format*
- **§3.3 Parentheses.** Sparingly: not around `return` values or `if`
  conditions. *format, UP034*
- **§3.4 Indentation.** Four spaces, never tabs; a trailing comma only when
  the closing bracket stands on its own line (§3.4.1). *format, W191*
- **§3.5 Blank lines.** Two between top-level definitions, one between
  methods and after a class docstring, none right after a `def` line.
  *format, GS013*
- **§3.6 Whitespace.** Standard typography; `f(x=1)` but
  `def f(x: int = 1)`; no alignment padding; no trailing whitespace.
  *format, W291*
- **§3.7 Shebang.** Only on files executed directly, then made executable:
  `#!/usr/bin/env python3`. *EXE*
- **§3.8 Docstrings and comments.** Always `"""`; a summary line within 80
  columns ending in a period, a blank line, then the rest. Every file opens
  with the project's license boilerplate (if it has a license) and a module
  docstring; in a jupytext notebook the title cell stands in for the
  docstring. Public, non-trivial or non-obvious functions document **Args:**,
  **Returns:** (or **Yields:**) and **Raises:** — with the shapes and units
  the annotation cannot express; a tuple is returned "as a tuple
  (a, b)". **Raises:** lists what a correct caller can meet (a malformed
  file, a failed fit), not the `ValueError` for an argument that breaks the
  contract its Args entry states. Classes: what an instance *is*, plus
  **Attributes:**. Properties
  read like attributes (`"""The redshift."""`); exceptions say what the error
  *means*. `@override` methods need none. Test modules need none where they
  would only repeat names. Never NumPy-style underlined sections or reST
  fields in new code. Comments say why, not what, two spaces before `#`.
  *D (Google convention), GS014–GS019*
- **§3.10 Strings.** Format with an f-string, `%` or `str.format`, not `+`;
  no `+=` accumulation in a loop (`"".join(parts)`); `"""` for multi-line;
  `textwrap.dedent` for indented blocks. Logging: a literal pattern plus
  arguments, `logger.info("Fitted %d lines", n)`, never an f-string. Error
  messages state the exact failed condition, mark interpolated values
  (`{window=}`), and are greppable. *G, GS020, GS021*
- **§3.11 Resources.** `with` for files, sockets, connections, h5py, FITS,
  netCDF/xarray datasets, `np.load` archives and pools; close every saved
  matplotlib figure with `plt.close(fig)`. *SIM115, GS022, GS023*
- **§3.12 TODO.** Exactly `# TODO: <link> - <what to do>`, the link an
  issue (`https://...` or `#12`), never a person. *TD, GS024*
- **§3.13 Import formatting.** At the top, after license and docstring, one
  per line (`typing` symbols may share one); groups `__future__`, standard
  library, third party, this repository; sorted by module path, ignoring
  case. *I, E401, E402, PLC0415*
- **§3.14 Statements.** One per line. *E701, E702*
- **§3.15 Getters and setters.** Only when access does real work; plain
  attributes otherwise; `get_x()`/`set_x()` names.
- **§3.16 Naming.** `module_name`, `ClassName`, `function_name`,
  `CONSTANT_NAME`, `variable_name`, `_internal`; descriptive, no
  letter-dropping abbreviations, no type in the name (`names_list`); no
  dashes in file names; one-letter names only for counters (`i`, `j`, `k`),
  exceptions (`e`), file handles (`f`), private type variables (`_T`) and
  cited mathematical notation (§3.16.5: `A`, `C`, `H0`, with a link to the
  source) in internal code. A public signature spells its parameters out:
  `measure(image, x_center, y_center, radius)`, not `measure(image, x, y,
  r)`. Suppress per line with the reason: `# noqa: N806` for a capitalized
  local, `N803` for a capitalized parameter, `GS030` for a one-letter public
  parameter. *N, E741, A00x, GS025, GS029, GS030*
- **§3.17 Main.** A program's logic lives in `main()`, called only under
  `if __name__ == "__main__":`; importing a module runs nothing but
  definitions. In a package, also expose it as a console script in
  `[project.scripts]` (`name = "package.module:main"`). Notebooks are
  exempt. *GS026*
- **§3.18 Function length.** Small and focused; past about 40 lines, see
  whether it splits. *GS027*
- **§3.19 Type annotations.** `X | None` (never implicit), `None` last;
  built-in generics (`list[float]`); abstract types for parameters
  (`Sequence`, `Mapping`); type parameters always given
  (`npt.NDArray[np.float64]`, not bare `np.ndarray`); `TypeAlias` in
  CapWords for long types; descriptive `TypeVar` names except private
  unconstrained ones; no `typing.Text`; no `# type:` comments;
  `# type: ignore[code]` only with a code; one parameter per line with a
  trailing comma when a signature wraps. *UP, RUF013, RUF036, ANN, GS028,
  GS029, mypy*

### Consistency (§4)

Match the conventions of the file you edit wherever the guide leaves a
choice. Do not extend an old style the guide has moved past: new code in an
old file still imports modules and writes `X | None`.

---

## Scientific Code

How the rules land in research code — each is the guide's rule applied, not
an extra one:

- **Docstrings carry shapes and units** (§3.8.3): the annotation says
  `FloatArray`; the docstring says `shape (n_pixels,), in Angstrom`.
- **NumPy truthiness** (§2.14): `if not flux.size:`, `if mask.any():`;
  `if flux:` raises on arrays of more than one element.
- **Notation** (§3.16.5): internal names may follow the paper (`A`, `C`,
  `H0`) with the source cited; public parameters stay descriptive
  (`design`, `covariance`).
- **Scientific files** (§3.11): `with fits.open(path) as hdul:`,
  `with h5py.File(path) as catalog:`, `with np.load(path) as arrays:`.
- **Figures** (§3.11): `plt.close(fig)` after saving, so batch scripts do not
  pile up open figures.
- **Randomness** (§2.5): one explicit `Generator` from
  `np.random.default_rng(seed)`, passed to what needs it.
- **Validation** (§2.4, §3.10.2): `raise ValueError(f"window must be a
  positive odd integer: {window=}")`, never `assert window % 2`. The
  precondition is stated in the Args entry, and the error is not listed
  under Raises: (§3.8.3).
- **Imports** (§2.2): `from astropy import units as u`,
  `from astropy.io import fits`, `from scipy import signal`,
  `import matplotlib.pyplot as plt` — modules, all.

### Jupytext notebooks

A percent-format script is a notebook: its cells run top to bottom and it is
never imported. Relative to a module:

- The markdown **title cell replaces the module docstring** (GS014 accepts
  it; ruff's D100 is off because it cannot tell the two apart).
- Top-level cells **are the program**: no `main()`, and notebook globals are
  fine (GS026 and GS004 skip notebooks). Constants go in one configuration
  cell, in capitals. Functions defined in a notebook take what they use as
  arguments and never read notebook globals.
- **All imports in the imports cell** (E402), which also holds the license
  lines and the PEP 723 block.
- **Show a value with a call** — `print(value)`, `table.head()` — not a
  bare name, which B018 reports as a useless expression.
- The formatter puts two blank lines around a cell that defines functions;
  jupytext accepts any number.

`examples/notebook.py` shows all of it, and `examples/continuum.py` shows a
library module with a command-line `main()`.

---

## Verification

Run these on the files you created or changed before you present them
(on the whole tree, `.`, for a project you just created):

1. **Format** — `uv run ruff format <files>` (for an existing file that was
   not formatted before: `ruff format --range=<start>-<end> <file>`).
2. **Lint** — `uv run ruff check --fix <files>`, then fix the rest by hand.
   A finding is suppressed only when the rule is wrong for that line, with
   the reason in the `noqa`.
3. **Check** — `uv run python <skill-dir>/scripts/check_code_style.py
   <files>`: no errors; read every warning; resolve every `NOTE` by running
   in the environment that has the packages.
4. **Type-check** — `uv run mypy <package> <notebooks>`, notebooks included
   (loose script:
   `uvx --with-requirements script.py mypy --config-file
   <skill-dir>/assets/mypy.ini script.py`).
5. **Run it** — the script or notebook runs top to bottom; the project's
   tests, if it has any, pass.

Outside a project, add `--config <skill-dir>/assets/ruff.toml` to the ruff
commands and use `uvx ruff`.

---

## Anti-Patterns

What a model writing "idiomatic Python" reaches for, and this skill forbids:

- **Member imports** — `from pathlib import Path`, `from dataclasses import
  dataclass`, `from scipy.optimize import curve_fit`, `from
  astropy.coordinates import SkyCoord`, `from collections import Counter`.
- **Relative imports and `sys.path` hacks** — `from .utils import x`,
  `sys.path.insert(0, "..")`.
- **NumPy- or reST-style docstrings** in new code; docstrings with no Args:
  for arguments; units and shapes left out.
- **Old typing** — `Optional[str]`, `List[int]`, `Dict[str, Any]`,
  `x: str = None`, bare `np.ndarray`, `# type: int`.
- **Assert as validation** — `assert window > 0, "window must be positive"`.
- **Catch-all handlers** — `except Exception: pass`, bare `except:`.
- **Mutable and evaluated defaults** — `def f(items=[])`,
  `def f(t=time.time())`.
- **f-strings in logging** — `logger.info(f"Loaded {n} rows")`.
- **`@staticmethod` helpers** in a class that should be module functions.
- **`len()` for emptiness**, `if array:` on NumPy arrays, `x = x or []`.
- **One-letter public parameters** — `def measure(image, x, y, r)`.
- **Raises: sections listing the `ValueError` for a broken precondition**
  the Args entry already states.
- **Strings built with `+`** or `+=` in a loop.
- **Unclosed resources** — `h5py.File(path)` without `with`, figures never
  closed.
- **Program code at module level** in a plain script (outside notebooks).
- **`TODO(claude): ...`**, or a TODO naming a person, or with no link.
- **Blanket or unexplained suppressions** — `# noqa`, `# type: ignore`.
- **Lines past 80 columns**, backslash continuations, aligned `=` columns.
- **`pip install`** into a uv project; a hand-maintained
  `requirements.txt` beside `uv.lock`.
- **Reformatting a whole existing file** for a one-line change.

---

## Self-Check Before Finishing

- [ ] `ruff format` leaves the files unchanged; `ruff check` passes, every
      `noqa` with a code and a reason.
- [ ] `check_code_style.py`: no errors, every warning read, no `NOTE` left
      unexplained.
- [ ] mypy passes on what you wrote.
- [ ] Imports are modules; only `typing` / `collections.abc` symbols are
      imported by name.
- [ ] Each module has its docstring (or notebook title cell); each public
      function and class a Google docstring with shapes and units.
- [ ] Every signature is annotated, `X | None` where None is allowed, and
      public signatures use descriptive parameter names.
- [ ] Files, datasets and figures are opened in `with` or closed explicitly.
- [ ] A plain script runs through `main()`; a notebook runs top to bottom.
- [ ] The code ran.

---

## Interaction With Other Skills

- **jupytext** decides the shape of a notebook file: header, cells,
  narrative. This skill decides the code inside the cells, with the
  notebook allowances above; jupytext's own examples follow both. Where a
  notebook's code and this skill disagree, this skill wins.
- **plot-style** decides how a figure looks; this skill decides how its code
  is written. Import its helper as a module — `import plotstyle`, then
  `plotstyle.use_style()`, `plotstyle.figsize("column")` — which plot-style's
  checker accepts, and close each figure after `plotstyle.save(fig, ...)`.
- **co-scientist**'s analysis and verification scripts follow this skill,
  and its working directory is a uv project: its `requirements.txt` goes in
  with `uv add -r`, and `uv.lock` is the record of the environment.
- **co-writer** and **cite-check** write prose, not code. co-writer's
  scripts follow this skill; cite-check's toolbox does when it is next
  edited.

---

## Files

| Path | Contents |
|---|---|
| `SKILL.md` | this digest — read whole when the skill is invoked |
| `references/rules.md` | every guide rule with reason, example and enforcing check — docstrings, annotations, anything unclear |
| `references/tooling.md` | uv, ruff, mypy and the checker: commands, configuration, existing projects, CI |
| `assets/ruff.toml` | the lint and format configuration, each rule mapped to a guide section |
| `assets/mypy.ini` | the type-checker configuration |
| `scripts/check_code_style.py` | checks GS001–GS030 (standard library only; `--list` prints them) |
| `examples/continuum.py` | a library module with a command-line `main()` |
| `examples/notebook.py` | a jupytext notebook: title cell, PEP 723 block, configuration cell |
| `tests/test_check_code_style.py` | the checker's tests, plus ruff and checker runs over the examples (`uvx --with numpy pytest <skill-dir>/tests`) |

## Source

The rules are those of the [Google Python Style Guide][guide] and the
[pylintrc][pylintrc] it links to, © Google, licensed under
[CC BY 3.0](https://creativecommons.org/licenses/by/3.0/). This skill
restates them in its own words with new examples, replaces the guide's tools
as described above, and adds the checker and the notebook allowances.

[guide]: https://google.github.io/styleguide/pyguide.html
[pylintrc]: https://google.github.io/styleguide/pylintrc
