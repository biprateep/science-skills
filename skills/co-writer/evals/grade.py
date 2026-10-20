"""Checks the narrowly specified edit and hedge/citation grouping."""

import pathlib
import re
import sys


def main() -> int:
    """Checks removal of empty emphasis while retaining the two hedges.

    Returns:
        Zero for a passing edit, one for failed output, two for bad usage.
    """
    if len(sys.argv) != 2:
        print("usage: grade.py WORKSPACE")
        return 2
    try:
        text = (pathlib.Path(sys.argv[1]) / "rewrite.tex").read_text(
            encoding="utf-8"
        )
    except OSError as error:
        print(f"missing rewrite: {error}")
        return 1
    lowered = text.lower()
    if "it is important to note" in lowered or "it should be noted" in lowered:
        print("Empty introductory emphasis remains.")
        return 1
    # Each citation closes a claim group in this deliberately small fixture.
    citations = re.findall(r"\\citep\{(demo[ab])\}", lowered)
    if citations != ["demoa", "demob"]:
        print("Expected citation order or multiplicity changed.")
        return 1
    groups = re.split(r"\\citep\{Demo[AB]\}", lowered, flags=re.IGNORECASE)
    if len(groups) != 3:
        print("The expected two citation groups are missing.")
        return 1
    for group, words in zip(
        groups[:2],
        [("pilot", "may"), ("comparison", "may", "zero")],
        strict=True,
    ):
        if any(re.search(rf"\b{word}\b", group) is None for word in words):
            print("A required hedge or its original claim group changed.")
            return 1
    print("Empty emphasis removed; required hedge/citation groups retained.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
