#!/usr/bin/env python3
"""List mannered phrases and Never-list constructions in a file, by line.

Calibration, never a verdict. Mannered prose substitutes metaphor and flourish
for direct statement; the fix is the literal phrase or the field's term, never
a coinage. This script prints every occurrence of a stock phrase so a writer
can see it; a hit is a place to look, and the writer decides.

Two lexicons. MANNERED is figurative stock phrasing. NEVER is the profile's
hard bans -- sentence-initial evaluative adverbs, "Note that", "In summary",
the reveal construction, field-impact claims -- which are mechanical and are
not the author's. Dashes and sentences ending in "?" are tallied separately.

Every entry was checked against the author's five corpus papers and none
occurs there ("unlock" was in the first draft of this list and came out because
a 2026 paper of his uses it). The NEVER list does hit three sentences in his
corpus -- one "Importantly," one "Notably," one "Crucially," -- which he has
since banned. That is the admission rule: a phrase the author's own published
prose uses is not mannered for him, whatever a style guide says, and an entry
that turns out to hit his corpus is removed, not the corpus.

    python check_mannered.py FILE [FILE ...]    every hit, with context
    python check_mannered.py --count FILE ...   one line per file
    python check_mannered.py --quiet FILE ...   exit 1 if any hit, print nothing

Lines beginning ">" (quoted text) and "%" (LaTeX comments) are skipped.
Ported from the book project's scripts/check_mannered.py with a lexicon for
papers. Standard library only.
"""

from __future__ import annotations

from collections.abc import Sequence
import pathlib
import re
import sys

# (pattern, the plain phrase to reach for instead)
MANNERED = [
    (r"\bpave(s|d)? the way\b", "enables; makes possible"),
    (r"\bshed(s|ding)? (new )?light on\b", "explains; shows"),
    (r"\bopen(s|ed|ing)? the door\b", "allows; makes possible"),
    (r"\ba window (in|on)to\b", "a way to measure"),
    (r"\bat the heart of\b", "central to; the main"),
    (r"\bholy grail\b", "the goal"),
    (r"\bdouble-edged sword\b", "has a cost"),
    (r"\bgame[- ]?chang(er|ing)\b", "a large improvement"),
    (r"\bsilver bullet\b", "a complete solution"),
    (r"\blow-hanging fruit\b", "the easy cases"),
    (r"\bcornerstone\b", "the basis"),
    (r"\ba testament to\b", "shows"),
    (r"\bstands as\b", "is"),
    (r"\bpaint(s|ed|ing)? a (\w+ )?picture\b", "shows; describes"),
    (r"\btip of the iceberg\b", "a small part"),
    (r"\b(ever-)?evolving landscape\b", "the field"),
    (r"\btapestry\b", "combination; set"),
    (r"\bdelv(e|es|ed|ing)\b", "examine; study"),
    (r"\bunderscor(e|es|ed|ing)\b", "shows; emphasizes"),
    (r"\bpivotal\b", "important; decisive"),
    (r"\bparadigm(-| )shift\b", "a change of method"),
    (r"\bholistic\b", "complete; whole"),
    (r"\bnuanced\b", "detailed; qualified"),
    (r"\bintricate\b", "detailed; complicated"),
    (r"\bmultifaceted\b", "has several parts"),
    (r"\bharness(es|ed|ing)? the (power|potential)\b", "use"),
    (r"\bseamless(ly)?\b", "without a break; directly"),
    (r"\bshowcas(e|es|ed|ing)\b", "shows"),
    (r"\bpush(es|ed|ing)? the (boundaries|envelope)\b", "extends"),
    (r"\bachilles'? heel\b", "the weakness"),
    (r"\btreasure trove\b", "a large set"),
    (r"\b(embark|embarks|embarked|embarking) on\b", "begin"),
    (r"\bunveil(s|ed|ing)?\b", "present; show"),
    (r"\bmyriad\b", "many"),
    (r"\bplethora\b", "many"),
    (r"\brealm\b", "field; area"),
    (r"\bit goes without saying\b", "(delete)"),
    (r"\bneedless to say\b", "(delete)"),
    (r"\bin today's\b", "in current"),
    (r"\bcutting[- ]edge\b", "current; recent"),
    (r"\bgroundbreaking\b", "new"),
    (r"\belegant(ly)?\b", "simple; short"),
    (r"\bbeautiful(ly)?\b", "(delete, or say what is good about it)"),
]

# The profile's HARD bans. Mechanical; not the author's constructions.
NEVER = [
    (
        r"(?:^|[.!?]\s+)(Notably|Interestingly|Importantly|Crucially),",
        "remarkably / unsurprisingly / as expected, once -- or nothing",
    ),
    (r"(?:^|[.!?]\s+)Note that\b", "We note that"),
    (r"\bIt is worth noting\b", "We note that"),
    (r"\bIt should be noted\b", "We note that"),
    (r"(?:^|[.!?]\s+)(Firstly|Secondly|Thirdly),", "We first ... We then ..."),
    (
        r"(?:^|[.!?]\s+)(Overall|In summary),",
        "(delete; the Summary section does this)",
    ),
    (r"\bIt is not [^.,]{2,60}, it is\b", "state the claim directly"),
    (r"\bIt is not [^.]{2,60}\. It is\b", "state the claim directly"),
    (
        r"\brevolutioni[sz]e|\brevolutionary\b",
        "(claims are about performance on named metrics)",
    ),
    (r"\bchange how science is done\b", "(delete)"),
]

TALLY = [
    ("dash", r"—|---|(?<!-)\s--\s(?!-)"),
    ("question", r"\?(?=\s|$)"),
]

# One hit: (line number, lexicon, matched phrase, plain phrase, line).
_Hit = tuple[int, str, str, str, str]


def hits(path: pathlib.Path) -> tuple[list[_Hit], dict[str, int]]:
    """Finds every lexicon hit in one file and tallies its dashes and questions.

    Lines that begin with ">" (quoted text) or "%" (LaTeX comments) are
    skipped.

    Args:
      path: The file.

    Returns:
      A tuple (found, tallies): each hit as (line number, "mannered" or
      "never", the matched phrase, the plain phrase to use instead, the
      stripped line), and the count of each TALLY pattern. Both are empty
      when the file cannot be read.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [], {}
    found: list[_Hit] = []
    tallies = {name: 0 for name, _ in TALLY}
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        if stripped.startswith(">") or stripped.startswith("%"):
            continue
        for kind, lexicon in (("mannered", MANNERED), ("never", NEVER)):
            flags = re.IGNORECASE if kind == "mannered" else 0
            for pattern, plain in lexicon:
                for match in re.finditer(pattern, line, flags=flags):
                    found.append(
                        (
                            lineno,
                            kind,
                            match.group(0).strip(),
                            plain,
                            line.strip(),
                        )
                    )
        for name, pattern in TALLY:
            tallies[name] += len(re.findall(pattern, line))
    return found, tallies


def main(argv: Sequence[str]) -> int:
    """Prints the hits of the files named in argv.

    Args:
      argv: The command-line arguments after the program name.

    Returns:
      The exit status: under --quiet, 1 if any file has a hit; 2 on bad
      usage; 0 otherwise.
    """
    count = "--count" in argv
    quiet = "--quiet" in argv
    files = [pathlib.Path(a) for a in argv if not a.startswith("--")]
    if not files:
        print(__doc__)
        return 2
    total = 0
    for path in files:
        found, tallies = hits(path)
        total += len(found)
        text = path.read_text(encoding="utf-8", errors="replace")
        words = max(1, len(re.findall(r"[A-Za-z]+", text)))
        if quiet:
            continue
        dashes_per_1k = 1000 * tallies["dash"] / words
        if count:
            print(
                f"{len(found):4d} hits  dashes/1k={dashes_per_1k:5.2f}"
                f"  questions={tallies['question']:2d}  {path}"
            )
            continue
        print(
            f"\n{path}: {len(found)} hit(s); dashes {tallies['dash']}"
            f" ({dashes_per_1k:.2f}/1k words); sentences ending '?':"
            f" {tallies['question']}"
        )
        for lineno, kind, phrase, plain, line in found:
            snippet = line if len(line) <= 140 else line[:137] + "..."
            print(f"  {lineno:5d}  [{kind}] {phrase!r:34}  ->  {plain}")
            print(f"         {snippet}")
    if quiet:
        return 1 if total else 0
    if not count:
        print(
            f"\n{total} hit(s) in {len(files)} file(s). Calibration, not a"
            " verdict."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
