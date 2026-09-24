# Tooling: uv, ruff, mypy and the checker

The guide's rules are tool-independent; its tools are not what this skill
uses. **uv** manages Python versions, environments and dependencies. **ruff**
formats (in place of Black/Pyink) and lints (in place of pylint).
**mypy** type-checks (in place of pytype, which is discontinued).
**scripts/check_code_style.py** covers the rules none of them express.

Commands below write `<skill-dir>` for this skill's directory. Commands and
versions were checked against uv 0.10.9, ruff 0.16.8 and mypy 2.3.1.

## Which situation are you in?

| Situation | Environment | Lint and type config |
|---|---|---|
| New project | `uv init` (below) | copy `assets/ruff.toml` and `assets/mypy.ini` to the root |
| Existing uv project | `uv run ...` | the project's; if it has none, `--config <skill-dir>/assets/...`, and offer to add the files |
| Existing project on conda, pip, poetry, pdm or hatch | keep it; do not migrate unasked | the project's, else `--config <skill-dir>/assets/...` |
| A standalone script | inline metadata (PEP 723), `uv run` | `--config <skill-dir>/assets/...` |

A project's own tooling and configuration win over this skill's defaults
(guide §4). Offer to move a project to uv or to the skill's ruff config, and
do it only on a yes.

---

## uv

### A new project

```bash
uv init --package spectra --python 3.12   # importable code: src/ layout, build backend
uv init survey-analysis --python 3.12     # an analysis repository, not a package
cd spectra
uv add numpy scipy astropy
uv add --dev ruff mypy pytest
cp <skill-dir>/assets/ruff.toml <skill-dir>/assets/mypy.ini .
```

- Use `--package` whenever notebooks or scripts import the repository's own
  code: the project is then installed in the environment, and
  `from spectra import continuum` works from anywhere, as §2.3 requires,
  without touching `sys.path`.
- Replace the scaffold: `uv init --package` writes a hello-world `main()`
  with no docstring into `src/<package>/__init__.py` (D103, D104) and points
  `[project.scripts]` at it. Give `__init__.py` a package docstring, point
  the script at the real entry point (`spectra = "spectra.cli:main"`), and
  run the checks over the whole new tree, not just the files you wrote.
- `pyproject.toml`, `uv.lock` and `.python-version` belong under version
  control (commit when the user asks); `.venv/` never does. Never edit
  `uv.lock` by hand.
- Change dependencies only through uv, which keeps the lock in step:
  `uv add "numpy>=2"`, `uv remove seaborn`, `uv add --optional gpu cupy`,
  `uv add --group docs sphinx`, `uv lock --upgrade-package astropy`.
- `uv sync` rebuilds `.venv` from the lock; `uv run <command>` syncs first,
  so activating the environment is never necessary.
- Python versions: `uv python install 3.12`, `uv python pin 3.12` (writes
  `.python-version`); keep `requires-python` in `pyproject.toml` honest,
  since ruff takes its target version from it.

### A standalone script

A single file with its dependencies declared inline (PEP 723) runs anywhere
uv is installed. This is for files that live on their own; a script or
notebook inside a uv project takes its dependencies from `pyproject.toml`
and carries no block.

```bash
uv init --script reduce.py --python 3.12
uv add --script reduce.py numpy astropy
uv run reduce.py
uv lock --script reduce.py   # optional: writes reduce.py.lock, pinning every version
```

uv writes the `# /// script` block at the very top of the file. In a jupytext
notebook that breaks the header, which must come first: move the block once
to the top of the imports cell, followed by a blank line; later
`uv add --script` calls edit it where it is. `examples/notebook.py` shows the
layout.

### An existing project on another tool

- **conda or mamba** (common on clusters): keep the environment. ruff runs
  standalone (`uvx ruff ...`); run mypy and the checker with the
  environment's own `python` so that its packages are visible.
- **pip and requirements.txt**: inside that virtual environment, `uv pip
  install -r requirements.txt` is a faster drop-in for pip. To turn it into a
  uv project, on request: `uv init --bare`, then `uv add -r requirements.txt`.
- **poetry, pdm, hatch**: keep them.

### Never

- `pip install` into a uv-managed `.venv` or into the system Python, or
  `sudo pip` anything.
- Hand-edited `uv.lock`, or a `requirements.txt` maintained beside a uv
  project (generate one with `uv export` if a tool needs it).
- `sys.path.insert(...)` to make imports work; install the project instead.

---

## ruff

### Configuration

ruff uses, for each file, the nearest `.ruff.toml`, `ruff.toml` or
`pyproject.toml` with a `[tool.ruff]` table, walking up the directory tree;
`--config` overrides that. `assets/ruff.toml` sets no `target-version`, so in
a project it follows `requires-python` from the `pyproject.toml` beside it.
On loose files, pass the version the code must run on:
`--target-version py312`.

To keep everything in `pyproject.toml` instead, move each table of
`assets/ruff.toml` under `tool.ruff` (`[lint]` becomes `[tool.ruff.lint]`,
the top-level keys go under `[tool.ruff]`).

### Commands

```bash
uv run ruff format .                          # §3 layout, whole tree
uv run ruff format --range=120-164 module.py  # only lines 120-164 of one file
uv run ruff check --fix .                     # lint; applies the safe fixes
uv run ruff check --statistics .              # findings per rule: a first look at old code
uvx ruff format --config <skill-dir>/assets/ruff.toml script.py   # no project
uvx ruff check --config <skill-dir>/assets/ruff.toml --fix script.py
```

`uv run ruff` uses the version pinned in the project's lock; `uvx ruff` the
latest release. The config requires ruff 0.16 or later.

**Formatting existing code.** Formatting a whole file that was not formatted
before rewrites lines you did not touch and buries your change in the diff.
Check first with `ruff format --check file.py`: if it passes, format the
whole file after your edit; if not, format only your lines with `--range`,
and leave the rest unless the user asks.

**Fixes.** `--fix` applies only fixes ruff marks safe. Read the diff; never
pass `--unsafe-fixes` without looking at each change.

### Suppressions

- One rule, one line, a reason (§2.1):
  `x = legacy_call()  # noqa: N806 - name fixed by the paper's notation.`
- A whole file, only for a file-wide reason, at the top:
  `# ruff: noqa: N816`.
- The checker's codes work the same way (`# noqa: GS001 - reason`): the
  config declares them `external`.
- A bare `# noqa` is an error (PGH004), and a suppression that no longer
  suppresses anything is reported (RUF100).

### Adopting the config in an existing codebase

Only with the user's agreement. Run `ruff check --statistics` to see the
size of the job, fix rules one family at a time (imports and docstrings
first, since ruff fixes many of them), and give not-yet-converted
directories a temporary `per-file-ignores` entry, not a bulk `--add-noqa`.

### Editors

The VS Code extension `charliermarsh.ruff` and ruff's language server (`ruff
server`) read the same configuration, so what the editor shows is what the
checks report.

---

## mypy

```bash
uv run mypy src/ notebooks/             # mypy is a dev dependency; notebooks too
uv run --with mypy mypy analysis.py     # ad hoc, with the project's packages visible
uvx --with-requirements reduce.py mypy --config-file <skill-dir>/assets/mypy.ini reduce.py
```

The last form reads the script's inline dependencies, so mypy sees numpy and
the rest; a bare `uvx mypy reduce.py` cannot find them.

`assets/mypy.ini` turns on what the guide's typing rules need
(`disallow_any_generics` for §3.19.15, `no_implicit_optional` for §3.19.5,
`warn_unused_ignores` for §2.1) and does not treat a package without type
information as an error (`import-untyped`), which is common among scientific
libraries. When stubs exist on PyPI, add them: `uv add --dev pandas-stubs
types-requests`.

**ty**, Astral's type checker, is still in beta (0.0.x, September 2026).
Once it reaches 1.0 it can replace mypy in this toolchain (`uvx ty check`);
until then, do not switch unless the user asks.

---

## The checker

```bash
uv run python <skill-dir>/scripts/check_code_style.py src/ notebooks/
uv run python <skill-dir>/scripts/check_code_style.py --list
```

- It uses only the standard library (Python 3.10+) but must run in the
  environment that runs the code: it resolves each `from x import y` to
  decide whether `y` is a module, first on disk and, when that cannot
  decide, by importing `x`. A `NOTE` line means an import could not be
  resolved, usually because the package is not installed where the checker
  ran; run it in the right environment rather than ignoring the note.
- `--no-import` never imports anything and decides from the file system
  alone, at the cost of reporting modules that a package exposes only as an
  attribute (`os.path`) as members.
- `--strict` fails on warnings as well as errors; `--config` names the ruff
  config whose `flake8-import-conventions` aliases count as standard (by
  default the nearest one, else the skill's).
- Exit status: 1 on an error (or a warning under `--strict`), 2 on bad usage,
  0 otherwise.

Errors are unambiguous violations of a "do not" in the guide. Warnings are
heuristics: read each one and either fix the code or, when the heuristic is
wrong, suppress it on that line with a reason.

The checker's own tests: `uvx --with numpy pytest <skill-dir>/tests`.

---

## Pre-commit and continuous integration

Only when the user wants them. A pre-commit configuration, pinned to the
ruff release:

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.16.8
    hooks:
      - id: ruff-check
        args: [--fix]
      - id: ruff-format
```

A GitHub Actions job:

```yaml
jobs:
  style:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v10
      - run: uv sync --locked
      - run: uv run ruff format --check .
      - run: uv run ruff check .
      - run: uv run mypy src/ notebooks/
```
