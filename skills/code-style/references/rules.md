# The Rules, Section by Section

Every rule of the Google Python Style Guide, restated as instructions, with
the reason, an example and what enforces it. Section numbers (§) follow the
guide, so a finding can be traced back to it. The examples are this skill's
own, drawn from scientific code.

**Enforced by** names the check that catches a violation: a ruff rule code
(configured in `assets/ruff.toml`), a checker code `GS0nn`
(`scripts/check_code_style.py`), `format` for the ruff formatter, `mypy`, or
*review* when no tool can decide and the rule rests on you.

Two places depart from the guide, both on purpose:

- **Tools.** ruff replaces pylint (lint) and Black/Pyink (format); mypy
  replaces pytype, which is discontinued; uv manages Python versions,
  environments and dependencies, which the guide does not cover.
- **Annotations.** The guide requires type annotations on public APIs and
  leaves the rest to judgment. Code written under this skill annotates every
  function signature: the cost is small, and it lets the type checker see the
  whole program. Existing unannotated code is annotated when it is changed.

Where a project already has its own conventions for a choice the guide
leaves open, the project wins (§4).

---

## 2 Language rules

### §2.1 Lint

Run the linter over everything you write, and fix what it reports. When a
finding is wrong for one line, suppress that one rule on that one line and
say why, so that suppressions can be found and revisited later:

```python
def do_GET(self) -> None:  # noqa: N802 - name fixed by http.server.
```

ruff codes are not self-explanatory the way pylint's symbolic names are, so a
suppression always carries a reason. Never write a bare `# noqa`.

An argument a function must accept but does not use is deleted at the top of
the body, with a comment:

```python
def on_epoch_end(self, epoch: int, logs: dict[str, float]) -> None:
    del epoch, logs  # Unused; the callback API passes them.
    self._checkpoint()
```

Renaming it to `_logs` or `unused_logs` also silences the linter, but breaks
callers that pass it by keyword and does not prove it is unused.

*Enforced by:* the whole ruff config; PGH004 (blanket noqa), RUF100 (stale
noqa), ARG (unused arguments).

### §2.2 Imports

Import packages and modules, never the classes, functions or constants
inside them. The module name then says where every name comes from.

- `import x` for a package or module.
- `from x import y` when `x` is the package and `y` a module in it.
- `from x import y as z` when `y` would collide with another import or a
  name in this module, collides with a common parameter name in the public
  API, is inconveniently long, or is too generic to read well
  (`from matplotlib import colors as mcolors`).
- `import y as z` solely to give a module its customary short name: `np`,
  `pd`, `plt`, `mpl`, `u` for astropy.units, `xr`, `jnp`. The list is the ruff
  config's `flake8-import-conventions`; extend it only with abbreviations
  the whole field uses.

Symbols from `typing`, `collections.abc` and `typing_extensions` are exempt:
import them directly (§3.19.12).

```python
# Yes
import dataclasses
import pathlib

from astropy import coordinates
from astropy import units as u
import numpy as np
from scipy import optimize


@dataclasses.dataclass
class Target:
    position: coordinates.SkyCoord
    catalog: pathlib.Path


popt, pcov = optimize.curve_fit(model, x_data, y_data)
```

```python
# No
from dataclasses import dataclass
from pathlib import Path
from astropy.coordinates import SkyCoord
from scipy.optimize import curve_fit
```

No relative imports, not even inside a package: write the full package path,
so a module cannot be imported twice under two names.

*Enforced by:* GS001 (members), GS002 (aliases), ICN001 (standard aliases),
PLR0402 (`import a.b as b`), TID252 (relative imports).

### §2.3 Packages

Import every module by its full package path. Do not assume the directory of
the running script is on `sys.path`: `import utils` means a top-level package
called `utils`, not the `utils.py` next to the script. In a uv project that
is installed (`uv init --package`), import your own code as
`from myproject import utils`.

*Enforced by:* review; GS001 reports imports it cannot resolve as notes.

### §2.4 Exceptions

- Raise the built-in exception that fits: `ValueError` for a bad argument
  value, `TypeError` for a wrong type, `KeyError`, `FileNotFoundError`.
- Do not `assert` to validate arguments or anything else the code relies on;
  `python -O` removes asserts. An assert may check a condition the code does
  not depend on. In pytest tests, asserts are the point.

  ```python
  # Yes
  def rebin(flux: FloatArray, factor: int) -> FloatArray:
      if factor < 1 or flux.size % factor != 0:
          raise ValueError(
              f"factor must divide the {flux.size} pixels: {factor=}"
          )
      binned = flux.reshape(-1, factor).mean(axis=1)
      assert binned.size * factor == flux.size  # Not relied upon.
      return binned
  ```

  ```python
  # No
  def rebin(flux: FloatArray, factor: int) -> FloatArray:
      assert flux.size % factor == 0, "factor must divide the pixel count"
      return flux.reshape(-1, factor).mean(axis=1)
  ```

- A package may define its own exceptions. They inherit from an existing
  exception class, their names end in `Error`, and they do not repeat the
  module name (`spectra.ShapeMismatchError`, not `spectra.SpectraError`).
- Never catch everything (`except:`, `except Exception`,
  `except BaseException`) unless you re-raise, or the code is an isolation
  point that records the error and carries on, such as the outer loop of a
  batch job that must not die on one bad file:

  ```python
  for path in paths:
      try:
          reduce_exposure(path)
      except Exception:  # One bad exposure must not stop the night.
          logging.exception("Could not reduce %s", path)
  ```

  ruff accepts this handler because `logging.exception` records the error
  with its traceback; a handler that swallows the error silently needs a
  `# noqa: BLE001 - <reason>`.

- Keep the body of a `try` to the lines that can raise the exception you
  catch; a long body hides errors from lines you did not expect to raise.
- Use `finally` for cleanup that must run either way (better still, a `with`
  block, §3.11).
- When translating one exception into another, chain it:
  `raise CalibrationError(...) from error`.

*Enforced by:* E722, BLE001, TRY002 (raising bare `Exception`), TRY203, B904,
N818 (`Error` suffix), GS003 (assert on an argument).

### §2.5 Mutable global state

Avoid module-level values and class attributes that change while the program
runs. They break encapsulation (two callers cannot use two configurations)
and they can change behavior at import time.

When global state is unavoidable, name it internal (`_cache`), reach it only
through functions, and say in a comment why it exists. Module-level
constants are welcome, named in capitals:

```python
SPEED_OF_LIGHT_KM_S = 299_792.458
_DEFAULT_WINDOW = 101  # Internal default.

# Yes: an explicit generator, passed to whatever needs randomness.
rng = np.random.default_rng(seed)
catalog = draw_catalog(rng, n_galaxies=10_000)

# No: hidden global state that every caller shares.
np.random.seed(seed)
catalog = draw_catalog(n_galaxies=10_000)
```

A jupytext notebook is the exception by nature: its cells are the program's
top level, so notebook globals are fine. Functions defined in a notebook
still take what they use as arguments and never read notebook globals.

*Enforced by:* GS004 (public mutable module-level containers; not applied to
notebooks), NPY002 (legacy global NumPy random state).

### §2.6 Nested and local functions and classes

Nest a function only to close over a local value of the enclosing function
(other than `self` or `cls`), as a decorator's wrapper does. A helper nested
merely to hide it becomes a module-level function named with a leading
underscore, where tests can reach it. Inner classes are fine.

*Enforced by:* GS005.

### §2.7 Comprehensions and generator expressions

Use them for simple cases: one `for` clause and at most one `if`. Anything
more is written as loops. Optimize for the reader, not for line count.

```python
# Yes
bright = [star for star in stars if star.magnitude < 12]
pairs = []
for first in stars:
    for second in stars:
        if first.separation(second) < match_radius:
            pairs.append((first, second))
```

```python
# No
pairs = [(a, b) for a in stars for b in stars if a.separation(b) < radius]
```

*Enforced by:* GS006.

### §2.8 Default iterators and operators

Use the iteration and membership that containers define: `for key in
table`, `for key, value in table.items()`, `for line in handle`,
`if name in names`. Do not call `.keys()` or `.readlines()` to iterate, and
do not change a container while iterating over it.

*Enforced by:* SIM118, FURB129; review for mutation during iteration.

### §2.9 Generators

Use them freely. Document what each `next()` gives under `Yields:`, not
`Returns:`. A generator that holds an expensive resource (an open file, a
connection) must release it deterministically: wrap it in a context manager
rather than rely on the generator being exhausted or collected.

*Enforced by:* GS018.

### §2.10 Lambda functions

A lambda is for a one-line expression; beyond 60 to 80 characters, or when
it needs a name, write a nested `def`. Prefer a generator expression to
`map()` or `filter()` with a lambda, and the `operator` module to a lambda
that re-implements an operator (`operator.mul`, `operator.itemgetter(1)`).

```python
# Yes
fluxes = [measure(source) for source in sources]
order = sorted(sources, key=operator.attrgetter("magnitude"))
```

```python
# No
fluxes = list(map(lambda source: measure(source), sources))
magnitude = lambda source: source.magnitude
```

*Enforced by:* E731 (lambda bound to a name), C417, PLW0108.

### §2.11 Conditional expressions

Use `a if condition else b` only when each of its three parts fits on one
line. Otherwise write an `if` statement.

```python
# Yes
label = "detection" if snr > 5 else "limit"
```

*Enforced by:* the formatter lays them out; review.

### §2.12 Default argument values

Defaults are evaluated once, when the function is defined. Never use a
mutable object or a call as a default; use `None` and fill it in:

```python
# Yes
def stack(
    images: Sequence[FloatArray], weights: FloatArray | None = None
) -> FloatArray:
    if weights is None:
        weights = np.ones(len(images))
    ...


def fit(model: Model, bounds: tuple[float, float] = (0.0, 1.0)) -> Fit: ...
```

```python
# No
def stack(images, weights=np.ones(3)): ...
def log_run(message, when=time.time()): ...
def collect(item, into=[]): ...
```

*Enforced by:* B006, B008, RUF009 (dataclass fields).

### §2.13 Properties

Use a property only for access that is cheap, obvious and unsurprising: a
trivially derived value, or control over setting an attribute. A property
that only reads and writes a private attribute is pointless; make the
attribute public. Use `@property`, never a hand-written descriptor, and do
not put computations a subclass might override behind a property.

```python
@property
def redshift(self) -> float:
    """The redshift implied by the observed and rest wavelengths."""
    return self.observed_angstrom / self.rest_angstrom - 1
```

*Enforced by:* review.

### §2.14 True and false evaluations

- Use implicit false for sequences and containers: `if not events:`,
  `if spectra:`, not `if len(events) == 0:` or `if spectra != []:`.
- Test for `None` with `is None` / `is not None`; a value can be falsy
  without being `None` (`0`, `0.0`, `""`).
- Never compare a boolean with `==`: `if not converged:`, not
  `if converged == False:`. To tell `False` from `None`, spell out both:
  `if not flag and flag is not None:`.
- Compare an integer that is not the result of `len()` explicitly with 0:
  `if frame % 10 == 0:`, not `if not frame % 10:`.
- `"0"` is true.
- **NumPy arrays raise** in a boolean context when they hold more than one
  element. Test emptiness with `.size` (`if not flux.size:`) and truth with
  `.any()` or `.all()` (`if not mask.any():`).
- `x = x or default` replaces every falsy value, not just `None`; write
  `if x is None: x = default`.

*Enforced by:* E711, E712, PLC1802, PLW0177 (comparison with NaN), GS007,
GS008, GS009, GS010.

### §2.16 Lexical scoping

Closures are fine. Remember that a nested function sees the current value of
an enclosing variable, not its value when the function was created, which
bites inside loops:

```python
# No: every callback sees the last threshold.
callbacks = [lambda flux: flux > threshold for threshold in thresholds]
```

*Enforced by:* B023.

### §2.17 Function and method decorators

Use a decorator when it clearly helps. Name and import it like any function;
its docstring says that it is a decorator; test it. A decorator runs at
import time, so it must not touch files, sockets or databases, and a call
with valid arguments must succeed.

Do not use `@staticmethod`: write a module-level function. The exception is
an existing API that requires one. Use `@classmethod` only for a named
constructor (`Spectrum.from_fits(path)`) or for a class-wide concern such as
a process-wide cache.

*Enforced by:* GS011; review for the rest.

### §2.18 Threading

Operations on built-in types such as dicts are not guaranteed atomic (a
custom `__hash__` or `__eq__` breaks it), so never depend on it. Pass data
between threads through `queue.Queue`; otherwise use the locks in
`threading`, preferring `threading.Condition` to bare locks. For parallel
numerical work, a `concurrent.futures` executor used as a context manager
(§3.11) is usually the simplest correct tool.

*Enforced by:* review.

### §2.19 Power features

Avoid custom metaclasses, bytecode access, compiling code on the fly,
dynamic inheritance, reassigning `__class__`, import hooks, reflection
through `getattr` with computed names, frame inspection and `__del__`. Such
code is compact to write and hard to read, debug and change. Standard-library
features built on them (`abc.ABCMeta`, `dataclasses`, `enum`) are fine.

*Enforced by:* S102 (`exec`), S307 (`eval`), GS012.

### §2.20 `from __future__` imports

Future imports are welcome where they let a file use newer semantics on
older interpreters. Once they are in a file, leave them until the code can
no longer run on an interpreter that needs them.

*Enforced by:* UP010 removes only those the target Python version makes
redundant.

### §2.21 Type-annotated code

Annotate function signatures, and type-check with mypy (the guide's pytype
is discontinued). Annotations go in the source, or in `.pyi` stubs for
third-party and extension modules. When a type checker cannot handle some
code yet, say why in a comment with a link, rather than leaving it
unannotated in silence. See §3.19 for how to write annotations.

*Enforced by:* ANN001-ANN003 and ANN201-ANN206 (every signature), mypy with
`assets/mypy.ini`.

---

## 3 Style rules

### §3.1 Semicolons

Do not end lines with semicolons, and never put two statements on one line.

*Enforced by:* E702, E703, the formatter.

### §3.2 Line length

At most 80 characters. Exceptions: a long import, a URL or path in a
comment, a long string constant without whitespace (a URL), and a pragma
comment (`# noqa: ...`).

Never continue a line with a backslash. Use the implicit joining inside
parentheses, brackets and braces, adding a pair of parentheses if needed.
Break at the highest syntactic level, and if you break twice, break at the
same level both times. Split a long string literal into adjacent literals
inside parentheses:

```python
message = (
    "The spectrum has fewer good pixels than the window; widen the mask or"
    f" shrink the window ({window=}, {n_good=})."
)
```

Put a long URL in a comment on its own line rather than splitting it. A
docstring's summary line stays within 80 characters. A line the formatter
cannot shorten may exceed 80 when splitting it by hand would not help.

*Enforced by:* E501 at 80, the formatter (which also rewrites backslash
continuations into parentheses).

### §3.3 Parentheses

Use them sparingly. Not around the value of a `return`, and not around the
condition of an `if` or `while`, unless for line continuation or to mark a
tuple. A one-element tuple reads best with parentheses: `(name,)`.

*Enforced by:* the formatter, UP034.

### §3.4 Indentation

Four spaces per level, never tabs. Continuation lines either align with the
opening bracket or use a hanging indent of four spaces with nothing after the
opening bracket. A closing bracket goes at the end of the last line, or on a
line of its own indented like the line that opened it.

### §3.4.1 Trailing commas

Put a trailing comma after the last item only when the closing bracket is on
its own line, and in a one-element tuple. The formatter treats that comma as
a request to keep one item per line.

*Enforced by:* the formatter (§3.4 and §3.4.1), W191.

### §3.5 Blank lines

Top-level functions and classes are separated by two blank lines; methods by
one, and a class docstring from the first method by one; a `def` line is
never followed by a blank line. Inside functions, single blank lines where
they help.

*Enforced by:* the formatter, GS013.

### §3.6 Whitespace

Standard typography: no spaces inside brackets; none before a comma,
semicolon or colon, one after (except at a line end); none before the
bracket that opens a call, an index or a slice; no trailing whitespace. One
space either side of assignment, comparisons (`==`, `<`, `in`, `is not`, …)
and booleans (`and`, `or`, `not`); use judgment around arithmetic
operators. No spaces around `=` for keyword arguments and unannotated
defaults, but spaces around it when the parameter is annotated:
`smooth(flux, window=5)`, `def smooth(flux, window=5)`, and
`def smooth(flux: FloatArray, window: int = 5)`. Never pad lines to align
tokens vertically.

*Enforced by:* the formatter, W291, W293.

### §3.7 Shebang line

Only a file meant to be executed directly starts with
`#!/usr/bin/env python3`, and it is then marked executable. Modules that
are only imported have none.

*Enforced by:* EXE001-EXE005.

### §3.8 Comments and docstrings

#### §3.8.1 Docstrings

A docstring is always `"""`. It opens with a summary line of at most 80
characters that ends in a period, question mark or exclamation mark. When
there is more to say (usually), a blank line follows, then the rest, starting
at the indentation of the opening quotes.

#### §3.8.2 Modules

Every file starts with the license boilerplate the project uses, when it
declares a license (for MIT: `# SPDX-License-Identifier: MIT` and the
copyright line from the project's LICENSE). Then comes the module docstring:
a summary line, a description of what the module offers, and a short usage
example.

```python
"""Continuum normalization of one-dimensional spectra.

The continuum is a running median, robust to lines narrower than its window.

Typical usage example:

  spectrum = continuum.load_spectrum(path)
  normalized = continuum.normalize(spectrum, window=101)
"""
```

**Test modules** (§3.8.2.1) need no module docstring, and test classes and
`test_` methods need none either; a docstring that only repeats the name is
worse than none. Write one when it tells the reader something: an unusual
fixture, a slow external dependency, how to regenerate golden files.

**Jupytext notebooks** are this skill's addition: in a percent-format script
the first cell is a markdown title cell, and it stands in for the module
docstring (a real docstring would repeat it).

*Enforced by:* GS014 (docstring, or notebook title cell; ruff's D100 is off
because it cannot tell the two apart), GS015 (license boilerplate, when the
project has a LICENSE file or a `license` in pyproject.toml), D104.

#### §3.8.3 Functions and methods

A docstring is required for a function (or method, generator or property)
that is part of the public API, is not trivially short, or has logic that is
not obvious. It must let a reader call the function without reading its
code: what it does and what it needs, not how. Side effects, such as
mutating an argument, are part of what it does.

The summary may be descriptive (`"""Fits a Gaussian to the line."""`) or
imperative (`"""Fit a Gaussian to the line."""`), consistently within a
file. A property is documented like an attribute: `"""The line's centroid in
Angstrom."""`, not `"""Returns the centroid."""`.

Sections follow, each opened by a heading line ending in a colon and indented
by two or four spaces (consistently within a file). A function whose name and
signature say everything needs only the summary line.

- **Args:** each parameter by name, then a colon and its description. When
  the annotation does not say it all, say the rest: **shape and units** are
  exactly this kind of information in scientific code. List `*args` and
  `**kwargs` as such.
- **Returns:** (or **Yields:** for a generator): what the value means, with
  what its annotation does not convey. Omit when the function returns None,
  or when the summary line starts with "Returns" and already says it all.
  A tuple is described as a tuple — `A tuple (popt, pcov): ...` — never as
  if the function returned several named values, the way NumPy-style
  docstrings do.
- **Raises:** the exceptions that are part of the interface: what a
  correct caller can meet, such as a malformed file, a missing HDU or a fit
  that does not converge. Do not list what is raised when the documented
  API is violated: when the Args entry says `window: a positive odd
  integer`, the function still raises `ValueError` for `window=4`, but
  listing that error would make the misuse part of the API.

```python
def fit_line(
    wavelength: FloatArray,
    flux: FloatArray,
    center_guess: float,
) -> tuple[float, float]:
    """Fits a Gaussian absorption line and returns its center and depth.

    The continuum must already be divided out.

    Args:
      wavelength: Wavelength of each pixel in Angstrom, shape (n,).
      flux: Continuum-normalized flux, shape (n,).
      center_guess: Starting guess for the line center in Angstrom.

    Returns:
      A tuple (center, depth): the fitted center in Angstrom and the
      fractional depth, between 0 and 1.

    Raises:
      RuntimeError: If the fit does not converge.
    """
```

Write Google sections, never NumPy-style underlined sections (`Parameters`
over `----------`) or reST fields (`:param flux:`) in new code. In an
existing file that uses NumPy style throughout, match the file (§4) and say
so.

A decorated function is documented as it behaves once decorated. A method
that overrides one from a base class and is marked `@typing.override` needs
no docstring unless it changes the contract (new side effects, narrower
arguments); without the decorator it needs one, even if only
`"""See base class."""` is warranted — prefer adding `@override`.

*Enforced by:* D (pydocstyle, Google convention: D417 undocumented
arguments, D415 punctuation, D212 summary on the first line …), GS016
(NumPy and reST sections), GS017 (property phrasing), GS018 (generators).

#### §3.8.4 Classes

A class docstring's summary says what an instance represents; public
attributes (not properties) go in an **Attributes:** section, formatted like
Args:. An exception's docstring says what the error means, not when it is
raised. Never say that the class is a class.

```python
# Yes
class Exposure:
    """One CCD readout with its calibration state.

    Attributes:
      image: Counts per pixel, shape (n_rows, n_columns).
      exposure_time_s: Shutter-open time in seconds.
    """


class SaturatedError(ValueError):
    """Some pixels exceed the detector's full well."""
```

```python
# No
class Exposure:
    """Class that holds a CCD readout."""


class SaturatedError(ValueError):
    """Raised when pixels are saturated."""
```

A decorated class is documented as it behaves once decorated.

*Enforced by:* D101, D107, GS019.

#### §3.8.5 Block and inline comments

Comment the tricky parts: if you would have to explain it in review, explain
it in a comment now. A few lines before a complicated block; a short comment
at the end of a line for something non-obvious, two spaces after the code,
then `# `. Say what the code is for and why, never what it does; assume the
reader knows Python better than you do.

```python
# Pixels within half a window of either end see a padded window, so their
# continuum is biased; they are masked downstream.
continuum = running_median(flux, window)
good = np.abs(z_score) < 5  # 5 sigma: the tails are Gaussian to 6 sigma here.
```

#### §3.8.6 Punctuation, spelling and grammar

Comments are prose: capitalized, punctuated, spelled correctly, in full
sentences where that reads better. Short end-of-line comments may be
terser, consistently.

*Enforced by:* the formatter (spacing); review (content).

### §3.10 Strings

- Format with an f-string, `%` or `str.format`, even when every part is a
  string. One `+` joining two values is fine; building a string with `+` is
  not.

  ```python
  # Yes
  label = f"{target} at z = {redshift:.3f}"
  # No
  label = target + " at z = " + str(round(redshift, 3))
  ```

- Do not accumulate a string with `+=` in a loop; append the parts to a list
  and `"".join()` them, or write them to an `io.StringIO`.
- One quote character throughout a file (the formatter uses `"`); the other
  one is fine to avoid escaping.
- `"""` for multi-line strings. Multi-line strings do not follow the code's
  indentation: use adjacent literals in parentheses, or
  `textwrap.dedent("""\ ...""")`.

*Enforced by:* the formatter (quotes), GS020 (`+` chains), GS021 (`+=` in a
loop).

#### §3.10.1 Logging

Call logging functions with a literal pattern string and the values as
arguments, never with an f-string or a pre-formatted message. The pattern
stays queryable and nothing is formatted when the level is off:

```python
# Yes
_logger.info("Fitted %d lines in %s", n_lines, path)
# No
_logger.info(f"Fitted {n_lines} lines in {path}")
```

*Enforced by:* G001-G004.

#### §3.10.2 Error messages

An error message states exactly the condition that failed, marks every
interpolated value unmistakably, and can be found with grep:

```python
# Yes
if not 0 < depth <= 1:
    raise ValueError(f"depth must lie in (0, 1]: {depth=}")
# No: also true for NaN, and the value is not marked.
if depth <= 0 or depth > 1:
    raise ValueError("bad depth " + str(depth))
```

The chained comparison is false for `NaN`, so the first version rejects it;
both comparisons in the second are false for `NaN`, which slips through.

*Enforced by:* review.

### §3.11 Files, sockets and similar stateful resources

Close what you open, explicitly, and prefer a `with` block, which closes it
even on error. Relying on garbage collection holds file descriptors and
locks for an unpredictable time. This covers files, sockets, database
connections, `mmap` maps, **h5py files, FITS files, netCDF and xarray
datasets, `np.load` archives, process and thread pools, and matplotlib
figures**:

```python
with fits.open(path) as hdul:
    image = hdul["SCI"].data.astype(np.float32)

with h5py.File(catalog_path) as catalog:
    redshifts = catalog["z"][:]

with concurrent.futures.ProcessPoolExecutor() as pool:
    results = list(pool.map(reduce_exposure, paths))

fig, ax = plt.subplots()
ax.plot(wavelength, flux)
fig.savefig(figure_path)
plt.close(fig)  # Batch scripts otherwise accumulate open figures.
```

For an object that has `close()` but no context manager, use
`contextlib.closing(...)`. Where context management is impossible, document
how the resource's lifetime is managed.

*Enforced by:* SIM115 (`open`), GS022 (other openers), GS023 (figures).

### §3.12 TODO comments

Mark code that is temporary or knowingly imperfect with a TODO in this exact
layout: `TODO`, a colon, a link to the context (an issue, ideally), a
hyphen, and what is to be done.

```python
# TODO: https://github.com/org/pipeline/issues/12 - Vectorize the rebinning.
# TODO: #12 - Replace the Python loop with np.add.reduceat.
```

Not `TODO(name):`, and never a person or team as the context. A TODO about
the future names a precise date or event ("Remove once the DR2 catalog
ships").

*Enforced by:* TD001, TD003-TD007, GS024 (the link, hyphen, text layout).

### §3.13 Imports formatting

Imports go at the top of the file, after the license and module docstring
and before any code, one per line; `typing` and `collections.abc` symbols may
share a line. They are grouped from general to specific, each group sorted
by full module path, ignoring case:

1. `from __future__` imports.
2. The standard library.
3. Third-party packages.
4. Packages of this repository.

```python
from __future__ import annotations

import argparse
from collections.abc import Sequence
import logging

from astropy.io import fits
import numpy as np

from myproject import calibration
```

*Enforced by:* I (isort settings in the ruff config), E401, E402, PLC0415
(imports inside functions).

### §3.14 Statements

One statement per line. The guide allows `if condition: action` on one line
when there is no `else`; the formatter always splits it, which is also
allowed.

*Enforced by:* E701, E702, the formatter.

### §3.15 Getters and setters

Write `get_*`/`set_*` accessors only when getting or setting does real work
or costs something, such as invalidating a cache. A pair that just reads and
writes a private attribute should be a public attribute; simple logic can be
a property (§2.13). When access that used to be a property becomes an
accessor, do not keep the property as an alias: callers should break visibly.

*Enforced by:* review.

### §3.16 Naming

| Kind | Public | Internal |
|---|---|---|
| Packages | `lower_with_under` | |
| Modules | `lower_with_under` | `_lower_with_under` |
| Classes | `CapWords` | `_CapWords` |
| Exceptions | `CapWords` ending in `Error` | |
| Functions and methods | `lower_with_under()` | `_lower_with_under()` |
| Global and class constants | `CAPS_WITH_UNDER` | `_CAPS_WITH_UNDER` |
| Global, class and instance variables | `lower_with_under` | `_lower_with_under` |
| Parameters and local variables | `lower_with_under` | |

- Names describe; the wider a name's scope, the more it must say. Avoid
  abbreviations a reader outside the project would not know, and never
  abbreviate by dropping letters inside a word (`calib_img`, `nrm_flx`).
- One-letter names only for counters and iterators (`i`, `j`, `k`, `v`), an
  exception (`e`), a file handle in a `with` (`f`), and a private
  unconstrained type variable (`_T`) — and for established notation, below.
  Coordinates (`x`, `y`) read fine inside a few-line internal function; a
  public signature spells them out (`x_center`, `row`, `wavelength`).
- Do not put the type in the name (`redshift_list`, `band_to_depth_dict`).
- Acronyms in CapWords are all capitals: `FITSReader`, `HTTPError`.
- One leading underscore marks an internal name; do not use two (name
  mangling hurts readability and testing). Never invent `__dunder__` names.
- Module files end in `.py` and contain no dashes (`reduce_night.py`, not
  `reduce-night.py`), so they can be imported and tested.
- Test methods: `test_<method_under_test>_<state>`.

**Mathematical notation (§3.16.5).** In math-heavy code, short names that
match the notation of a reference paper or algorithm are preferred to
descriptive ones: `H0`, `Om0`, `A` for a design matrix, `C` for a
covariance. Cite the source of the notation in a comment or docstring (a link
is best), keep descriptive names in the public API, which readers meet out
of context, and silence the naming rule narrowly, one line at a time:

```python
def fit_linear_model(
    design: FloatArray, data: FloatArray, covariance: FloatArray
) -> FloatArray:
    """Returns the maximum-likelihood parameters of a linear model.

    Local names follow the matrix notation of Hogg, Bovy & Lang (2010),
    https://arxiv.org/abs/1008.4686.

    Args:
      design: Design matrix A, shape (n_data, n_parameters).
      data: Measurements Y, shape (n_data,).
      covariance: Their covariance C, shape (n_data, n_data).
    """
    A, C, Y = design, covariance, data  # noqa: N806 - the paper's notation.
    Cinv_A = np.linalg.solve(C, A)  # noqa: N806
    Cinv_Y = np.linalg.solve(C, Y)  # noqa: N806
    return np.linalg.solve(A.T @ Cinv_A, A.T @ Cinv_Y)
```

A binding that is tightly coupled to a non-Python codebase (a C++ library, a
FORTRAN code) may follow that codebase's naming.

*Enforced by:* N (pep8-naming), E741, A001, A002, A004, A006 (shadowed builtins),
PLC2401 (non-ASCII names), GS025 (type in the name), GS029 (type variables),
GS030 (one-letter parameters of a public function).

### §3.17 Main

Code must be importable without running anything: `pydoc` and tests import
it. A file that is also a program puts its logic in `main()` and runs it
only behind the guard; nothing but definitions runs at import.

```python
def main(argv: Sequence[str] | None = None) -> int:
    ...
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

In a package, expose the program as a console script as well, in
`pyproject.toml`, and keep the guard so that `python -m` works too:

```toml
[project.scripts]
normalize-spectrum = "spectra.continuum:main"
```

A jupytext notebook is the exception: its cells are meant to run top to
bottom, and it is never imported. Anything a notebook shares with other code
moves into a module.

*Enforced by:* GS026 (not applied to notebooks or tests).

### §3.18 Function length

Prefer small, focused functions. There is no hard limit, but past about 40
lines, see whether the function splits without harming the program's
structure. Long functions are where later changes introduce bugs.

*Enforced by:* GS027 (a warning).

### §3.19 Type annotations

- **General (§3.19.1).** Annotate every function signature. `self` and
  `cls` need no annotation (`typing.Self` where the type matters);
  `__init__` may omit `-> None`. Use `Any` for what cannot be expressed.
- **Line breaking (§3.19.2).** When a signature does not fit, put each
  parameter on its own line with a trailing comma, and the closing
  parenthesis and return type on the last line, aligned with `def`. Break
  between parameters, not inside a type; if one type is too long, give it an
  alias (§3.19.6).
- **Forward declarations (§3.19.3).** For a class not yet defined, use
  `from __future__ import annotations` or a string annotation.
- **Defaults (§3.19.4).** Spaces around `=` when the parameter has both an
  annotation and a default: `window: int = 101`.
- **None (§3.19.5).** A parameter that may be `None` says so:
  `mask: FloatArray | None = None`. Never `mask: FloatArray = None`; write
  `X | None` in new code rather than `Optional[X]`, and put `None` last.
- **Aliases (§3.19.6).** Name complex types with a `TypeAlias` in
  CapWords, `_Private` when used only in the module:
  `FloatArray: TypeAlias = npt.NDArray[np.float64]`. An alias is not a way to
  import a member (§2.2).
- **Ignoring types (§3.19.7).** `# type: ignore[code]` on the one line, with
  the error code, when the checker is wrong.
- **Variables (§3.19.8).** Annotate a variable whose type the checker cannot
  infer with an annotated assignment (`medians: FloatArray = np.median(...)`),
  never a `# type:` comment.
- **Tuples and lists (§3.19.9).** `list[float]` holds one type;
  `tuple[float, ...]` is homogeneous, `tuple[float, float]` has fixed
  positions (a common return type).
- **Type variables (§3.19.10).** `TypeVar` and `ParamSpec` get descriptive
  names (`Scalar = TypeVar("Scalar", int, float)`), except a private,
  unconstrained one (`_T`). Use `AnyStr` for "str or bytes, the same
  throughout".
- **Strings (§3.19.11).** `str` for text, `bytes` for binary; never
  `typing.Text`.
- **Imports for typing (§3.19.12).** Import `typing` and `collections.abc`
  symbols directly, several per line if you like; treat their names as
  reserved words. Annotate parameters with abstract types (`Sequence`,
  `Mapping`, `Iterable`) and returns with the concrete type when it matters;
  use built-in generics (`list`, `dict`, `tuple`), not `typing.List`.
- **Conditional imports (§3.19.13).** `if TYPE_CHECKING:` imports only when a
  runtime import must be avoided, placed right after the other imports, and
  referenced as strings. Prefer restructuring.
- **Circular dependencies (§3.19.14).** A cycle caused by typing is a design
  smell; refactor. As a last resort, alias the other module to `Any` and
  annotate with strings.
- **Generics (§3.19.15).** Give generic types their parameters:
  `Sequence[float]`, `Mapping[str, FloatArray]`, `npt.NDArray[np.float64]`,
  never a bare `Sequence` or `np.ndarray` (which means `Any` inside). If the
  parameter would be `Any`, consider a `TypeVar`.

The guide prefers `TypeAlias` and `TypeVar` to the newer `type X = ...` and
`def f[T](...)` syntax, so the ruff config does not rewrite to them (UP040,
UP046, UP047 are off).

*Enforced by:* UP006, UP007, UP035, UP045 (modern syntax), UP019
(`typing.Text`), RUF013 (implicit Optional), RUF036 (None last), ANN, PLC0105
and PLC0132 (TypeVar declarations), GS028 (type comments), GS029 (type
variable names), mypy (`disallow_any_generics` for §3.19.15).

---

## 4 Consistency

Be consistent with the code around you. When you edit a file, look at its
conventions first; where the guide leaves a choice open (docstring mood,
section indentation, index-variable suffixes), follow the file. The guide's
rules set the shared vocabulary; local style keeps a file readable as one
piece.

Consistency is not a reason to extend an old style the guide has moved away
from. New code uses module imports, `X | None` and Google docstrings even in
a file that mostly does not, unless the user wants the file kept uniform.
