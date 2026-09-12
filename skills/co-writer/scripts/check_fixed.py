#!/usr/bin/env python3
"""Compare what two versions of a passage hold fixed. Exit 1 if anything differs.

co-writer may change how a passage is said and nothing else. This script lists,
as multisets, the things a rewrite must carry through unchanged and prints each
one that appears in one file and not the other:

  cite      every key inside \\cite, \\citep, \\citet, \\citealt, \\citealp,
            \\citeauthor, \\citeyear (keys, so a key that moves between two
            \\cite commands is not flagged; a key that appears or disappears is)
  ref       every target of \\ref, \\eqref, \\pageref, \\autoref, \\cref, \\Cref
  label     every \\label
  graphics  every \\includegraphics file
  float     every \\begin{figure} / \\begin{table} (starred or not)
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

import re
import sys
from collections import Counter

CITE_CMD = r"\\cite(?:p|t|alt|alp|author|year|yearpar|num)?\*?(?:\[[^\]]*\])*\{([^}]*)\}"
REF_CMD = r"\\(?:eq|page|auto|c|C)?ref\*?\{([^}]*)\}"
LABEL_CMD = r"\\label\{([^}]*)\}"
GRAPHICS_CMD = r"\\includegraphics\*?(?:\[[^\]]*\])?\{([^}]*)\}"
FLOAT_ENV = r"\\begin\{(figure\*?|table\*?)\}"
MATH_ENVS = r"(equation|align|eqnarray|gather|multline|displaymath|flalign|alignat|split)\*?"
NUMBER = r"(?<![\w\\{])\d+(?:,\d{3})*(?:\.\d+)?(?![\w}])"


def strip_comments(tex: str) -> str:
    return "\n".join(re.sub(r"(?<!\\)%.*$", "", line) for line in tex.splitlines())


def math_bodies(tex: str) -> list[str]:
    bodies = []
    for m in re.finditer(r"\\begin\{" + MATH_ENVS + r"\}(.*?)\\end\{\1\}", tex, flags=re.DOTALL):
        bodies.append(m.group(2))
    bodies += re.findall(r"\\\[(.*?)\\\]", tex, flags=re.DOTALL)
    bodies += re.findall(r"\$\$(.+?)\$\$", tex, flags=re.DOTALL)
    bodies += re.findall(r"\\\((.+?)\\\)", tex, flags=re.DOTALL)
    stripped = re.sub(r"\$\$.+?\$\$", " ", tex, flags=re.DOTALL)
    bodies += re.findall(r"(?<!\\)\$((?:[^$\\]|\\.)+?)(?<!\\)\$", stripped, flags=re.DOTALL)
    return [re.sub(r"\s+", "", b) for b in bodies]


def collect(path: str) -> dict[str, Counter]:
    tex = strip_comments(open(path, encoding="utf-8", errors="replace").read())
    out: dict[str, Counter] = {}
    out["cite"] = Counter(k.strip() for m in re.findall(CITE_CMD, tex) for k in m.split(",") if k.strip())
    out["ref"] = Counter(k.strip() for m in re.findall(REF_CMD, tex) for k in m.split(",") if k.strip())
    out["label"] = Counter(re.findall(LABEL_CMD, tex))
    out["graphics"] = Counter(re.findall(GRAPHICS_CMD, tex))
    out["float"] = Counter(re.findall(FLOAT_ENV, tex))
    out["math"] = Counter(math_bodies(tex))
    out["number"] = Counter(re.findall(NUMBER, tex))
    return out


def main(argv: list[str]) -> int:
    allow_drop = "--allow-drop" in argv
    files = [a for a in argv if not a.startswith("--")]
    if len(files) != 2:
        print(__doc__)
        return 2
    a, b = (collect(p) for p in files)
    failures = warnings = 0
    for kind in ("cite", "ref", "label", "graphics", "float", "math", "number"):
        for item, n in sorted((a[kind] - b[kind]).items()):
            tag = "WARN" if allow_drop else "FAIL"
            print(f"{tag}  {kind:8s} only in BEFORE (x{n}): {item[:110]}")
            if allow_drop:
                warnings += 1
            else:
                failures += 1
        for item, n in sorted((b[kind] - a[kind]).items()):
            print(f"FAIL  {kind:8s} only in AFTER  (x{n}): {item[:110]}")
            failures += 1
    if failures == 0 and warnings == 0:
        print("fixed items identical")
    elif failures == 0:
        print(f"{warnings} item(s) dropped, none added (--allow-drop)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
