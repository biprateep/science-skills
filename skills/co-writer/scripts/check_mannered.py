#!/usr/bin/env python3
"""List mannered phrases and Never-list constructions in a file, by line.

Calibration, never a verdict. Mannered prose substitutes metaphor and flourish
for direct statement; the fix is the literal phrase or the field's term, never
a coinage. This script prints every occurrence of a stock phrase so a writer
can see it; a hit is a place to look, and the writer decides.

Two lexicons. MANNERED is figurative stock phrasing. NEVER combines universal
boilerplate bans with optional author-specific bans loaded from
``lexicon.json`` in the active co-writer profile directory
(``$CO_WRITER_PROFILE_DIR``, or ``$CO_WRITER_HOME/profile``, default
``~/.co-writer/profile``). An author's ``lexicon.json`` may also list
``"allow"`` patterns for phrases their own prose legitimately uses; any hit
matching an allowed pattern is skipped. Dashes and sentences ending in "?" are
tallied separately.

    python check_mannered.py FILE [FILE ...]    every hit, with context
    python check_mannered.py --count FILE ...   one line per file
    python check_mannered.py --quiet FILE ...   exit 1 if any hit, print nothing
    python check_mannered.py --profile-dir DIR FILE ...

Lines beginning ">" (quoted text) and "%" (LaTeX comments) are skipped.
Standard library only.
"""

from __future__ import annotations

from collections.abc import Sequence
import json
import os
import pathlib
import re
import sys

# (pattern, the plain phrase to reach for instead)
MANNERED: list[tuple[str, str]] = [
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

# Universal starter bans; author-specific bans come from <profile>/lexicon.json.
DEFAULT_NEVER: list[tuple[str, str]] = [
    (r"\bIt is worth noting\b", "state the point directly"),
    (r"\bIt should be noted\b", "state the point directly"),
    (
        r"(?:^|[.!?]\s+)(Overall|In summary),",
        "(delete; let the concluding section do this)",
    ),
    (r"\bIt is not [^.,]{2,60}, it is\b", "state the claim directly"),
    (r"\bIt is not [^.]{2,60}\. It is\b", "state the claim directly"),
    (
        r"\brevolutioni[sz]e|\brevolutionary\b",
        "(claims are about performance on named metrics)",
    ),
    (r"\bchange how science is done\b", "(delete)"),
]

# Retained as an alias for callers importing NEVER directly.
NEVER = DEFAULT_NEVER

TALLY = [
    ("dash", r"—|---|(?<!-)\s--\s(?!-)"),
    ("question", r"\?(?=\s|$)"),
]

# One hit: (line number, lexicon, matched phrase, plain phrase, line).
_Hit = tuple[int, str, str, str, str]


def resolve_profile_dir(
    profile_dir: pathlib.Path | None = None,
) -> pathlib.Path:
    """Returns the active co-writer profile directory.

    Args:
      profile_dir: Explicit override directory, if provided.

    Returns:
      The resolved profile directory path (which may not yet exist).
    """
    if profile_dir is not None:
        return profile_dir.expanduser()
    override = os.environ.get("CO_WRITER_PROFILE_DIR", "").strip()
    if override:
        return pathlib.Path(override).expanduser()
    store = os.environ.get("CO_WRITER_HOME", "").strip()
    base = (
        pathlib.Path(store).expanduser()
        if store
        else pathlib.Path.home() / ".co-writer"
    )
    return base / "profile"


def load_lexicon(
    profile_dir: pathlib.Path | None = None,
) -> tuple[list[tuple[str, str]], list[str]]:
    """Loads Never entries and allow patterns from the active profile.

    Args:
      profile_dir: Optional profile directory containing ``lexicon.json``.

    Returns:
      A tuple ``(never, allow)`` where ``never`` merges ``DEFAULT_NEVER`` with
      any profile overrides (profile entries win on identical patterns) and
      ``allow`` is a list of regex strings exempted from hits.
    """
    merged: dict[str, str] = dict(DEFAULT_NEVER)
    allow: list[str] = []
    lexicon_path = resolve_profile_dir(profile_dir) / "lexicon.json"
    if lexicon_path.is_file():
        try:
            with lexicon_path.open(encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            data = {}
        if isinstance(data, dict):
            for entry in data.get("never") or []:
                if (
                    isinstance(entry, list)
                    and len(entry) == 2
                    and all(isinstance(part, str) for part in entry)
                ):
                    merged[entry[0]] = entry[1]
            for pattern in data.get("allow") or []:
                if isinstance(pattern, str) and pattern:
                    allow.append(pattern)
    return list(merged.items()), allow


def _is_allowed(phrase: str, allow: Sequence[str]) -> bool:
    """Returns whether ``phrase`` matches any profile allow-list regex."""
    return any(re.search(pattern, phrase, re.IGNORECASE) for pattern in allow)


def hits(
    path: pathlib.Path,
    profile_dir: pathlib.Path | None = None,
) -> tuple[list[_Hit], dict[str, int]]:
    """Finds every lexicon hit in one file and tallies its dashes and questions.

    Lines that begin with ">" (quoted text) or "%" (LaTeX comments) are
    skipped.

    Args:
      path: The file to scan.
      profile_dir: Optional profile directory for ``lexicon.json`` overrides.

    Returns:
      A tuple ``(found, tallies)``: each hit as ``(line number, "mannered" or
      "never", matched phrase, plain phrase to use instead, stripped line)``,
      and the count of each ``TALLY`` pattern. Both are empty when the file
      cannot be read.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [], {}
    never, allow = load_lexicon(profile_dir)
    found: list[_Hit] = []
    tallies = {name: 0 for name, _ in TALLY}
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        if stripped.startswith(">") or stripped.startswith("%"):
            continue
        for kind, lexicon in (("mannered", MANNERED), ("never", never)):
            flags = re.IGNORECASE if kind == "mannered" else 0
            for pattern, plain in lexicon:
                for match in re.finditer(pattern, line, flags=flags):
                    phrase = match.group(0).strip()
                    if _is_allowed(phrase, allow):
                        continue
                    found.append((lineno, kind, phrase, plain, line.strip()))
        for name, pattern in TALLY:
            tallies[name] += len(re.findall(pattern, line))
    return found, tallies


def _parse_args(
    argv: Sequence[str],
) -> tuple[bool, bool, pathlib.Path | None, list[pathlib.Path]]:
    """Parses CLI flags and file paths without mutating argv."""
    count = False
    quiet = False
    profile_dir: pathlib.Path | None = None
    files: list[pathlib.Path] = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--count":
            count = True
        elif arg == "--quiet":
            quiet = True
        elif arg == "--profile-dir" and index + 1 < len(argv):
            profile_dir = pathlib.Path(argv[index + 1])
            index += 1
        elif arg.startswith("--profile-dir="):
            profile_dir = pathlib.Path(arg.split("=", 1)[1])
        elif arg.startswith("--"):
            raise ValueError(f"unknown option: {arg}")
        else:
            files.append(pathlib.Path(arg))
        index += 1
    return count, quiet, profile_dir, files


def main(argv: Sequence[str]) -> int:
    """Prints the hits of the files named in argv.

    Args:
      argv: The command-line arguments after the program name.

    Returns:
      The exit status: under ``--quiet``, 1 if any file has a hit; 2 on bad
      usage; 0 otherwise.
    """
    try:
        count, quiet, profile_dir, files = _parse_args(argv)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2
    if not files:
        print(__doc__)
        return 2
    total = 0
    for path in files:
        found, tallies = hits(path, profile_dir=profile_dir)
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
