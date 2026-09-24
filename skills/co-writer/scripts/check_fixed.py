#!/usr/bin/env python3
r"""Compare what two versions of a passage hold fixed; exit 1 on a difference.

co-writer may change how a passage is said and nothing else. This script lists,
as multisets, the things a rewrite must carry through unchanged and prints each
one that appears in one file and not the other:

  cite      every key inside \cite, \citep, \citet, \citealt, \citealp,
            \citeauthor, \citeyear (keys, so a key that moves between two
            \cite commands is not flagged; a key that appears or disappears is)
  ref       every target of \ref, \eqref, \pageref, \autoref, \cref, \Cref
  label     every \label
  graphics  every \includegraphics file
  float     every \begin{figure} / \begin{table} (starred or not)
  math      every math body, inline and display, with whitespace removed
  number    every number in the text

It reads nothing else. It cannot tell whether a claim changed strength or
whether a cited paper still supports a rewritten sentence; the cold read and
cite-check do that.

    python check_fixed.py BEFORE AFTER [--allow-drop]

--allow-drop reports items present only in BEFORE as warnings rather than
failures, for a hard-limit cut the author has ruled on. Items present only in
AFTER always fail: nothing may be added.

Ported from the book project's scripts/check_fixed.py, with the kinds a paper
needs. Standard library only.
"""

from __future__ import annotations

import collections
from collections.abc import Iterable, Sequence
import pathlib
import re
import sys

CITE_CMD = (
    r"\\cite(?:p|t|alt|alp|author|year|yearpar|num)?\*?"
    r"(?:\[[^\]]*\])*\{([^}]*)\}"
)
REF_CMD = r"\\(?:eq|page|auto|c|C)?ref\*?\{([^}]*)\}"
LABEL_CMD = r"\\label\{([^}]*)\}"
GRAPHICS_CMD = r"\\includegraphics\*?(?:\[[^\]]*\])?\{([^}]*)\}"
FLOAT_ENV = r"\\begin\{(figure\*?|table\*?)\}"
MATH_ENVS = (
    r"(equation|align|eqnarray|gather|multline|displaymath|flalign|alignat"
    r"|split)\*?"
)
NUMBER = r"(?<![\w\\{])\d+(?:,\d{3})*(?:\.\d+)?(?![\w}])"
KINDS = ("cite", "ref", "label", "graphics", "float", "math", "number")


def strip_comments(tex: str) -> str:
    r"""Removes % comments, leaving escaped \% signs in place."""
    return "\n".join(
        re.sub(r"(?<!\\)%.*$", "", line) for line in tex.splitlines()
    )


def math_bodies(tex: str) -> list[str]:
    r"""Returns every math body in tex, inline and display, without whitespace.

    Args:
      tex: LaTeX source, comments already removed.

    Returns:
      The bodies of the math environments, then of \[...\], $$...$$,
      \(...\) and $...$, each with all whitespace removed.
    """
    bodies: list[str] = []
    environment = r"\\begin\{%s\}(.*?)\\end\{\1\}" % MATH_ENVS
    for match in re.finditer(environment, tex, flags=re.DOTALL):
        bodies.append(match.group(2))
    bodies += re.findall(r"\\\[(.*?)\\\]", tex, flags=re.DOTALL)
    bodies += re.findall(r"\$\$(.+?)\$\$", tex, flags=re.DOTALL)
    bodies += re.findall(r"\\\((.+?)\\\)", tex, flags=re.DOTALL)
    stripped = re.sub(r"\$\$.+?\$\$", " ", tex, flags=re.DOTALL)
    bodies += re.findall(
        r"(?<!\\)\$((?:[^$\\]|\\.)+?)(?<!\\)\$", stripped, flags=re.DOTALL
    )
    return [re.sub(r"\s+", "", body) for body in bodies]


def _keys(arguments: Iterable[str]) -> collections.Counter[str]:
    """Counts the comma-separated keys of each command argument."""
    keys: collections.Counter[str] = collections.Counter()
    for argument in arguments:
        for key in argument.split(","):
            if key.strip():
                keys[key.strip()] += 1
    return keys


def collect(path: str) -> dict[str, collections.Counter[str]]:
    """Returns the fixed items of one LaTeX file, as a multiset per kind.

    Args:
      path: The file.

    Returns:
      For each of KINDS, how often each item occurs in the file.
    """
    text = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
    tex = strip_comments(text)
    out: dict[str, collections.Counter[str]] = {}
    out["cite"] = _keys(re.findall(CITE_CMD, tex))
    out["ref"] = _keys(re.findall(REF_CMD, tex))
    out["label"] = collections.Counter(re.findall(LABEL_CMD, tex))
    out["graphics"] = collections.Counter(re.findall(GRAPHICS_CMD, tex))
    out["float"] = collections.Counter(re.findall(FLOAT_ENV, tex))
    out["math"] = collections.Counter(math_bodies(tex))
    out["number"] = collections.Counter(re.findall(NUMBER, tex))
    return out


def main(argv: Sequence[str]) -> int:
    """Compares the two files named in argv and prints what differs.

    Args:
      argv: The command-line arguments after the program name.

    Returns:
      The exit status: 1 if an item differs (dropped items only count
      without --allow-drop), 2 on bad usage, 0 otherwise.
    """
    allow_drop = "--allow-drop" in argv
    files = [argument for argument in argv if not argument.startswith("--")]
    if len(files) != 2:
        print(__doc__)
        return 2
    before, after = (collect(path) for path in files)
    failures = warnings = 0
    for kind in KINDS:
        for item, count in sorted((before[kind] - after[kind]).items()):
            tag = "WARN" if allow_drop else "FAIL"
            print(f"{tag}  {kind:8s} only in BEFORE (x{count}): {item[:110]}")
            if allow_drop:
                warnings += 1
            else:
                failures += 1
        for item, count in sorted((after[kind] - before[kind]).items()):
            print(f"FAIL  {kind:8s} only in AFTER  (x{count}): {item[:110]}")
            failures += 1
    if failures == 0 and warnings == 0:
        print("fixed items identical")
    elif failures == 0:
        print(f"{warnings} item(s) dropped, none added (--allow-drop)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
