"""Checks notebook source structure and executes independent input probes."""

import ast
import json
import math
import pathlib
import re
import subprocess
import sys
import tempfile


def check_structure(path: pathlib.Path) -> int:
    """Checks a percent notebook header and typed cell boundaries.

    Args:
        path: Candidate percent-format notebook.

    Returns:
        Zero for pass, one for an invalid artifact.
    """
    try:
        source = path.read_text(encoding="utf-8")
        ast.parse(source)
    except (OSError, SyntaxError, UnicodeError) as error:
        print(f"invalid Python notebook: {error}")
        return 1
    lines = source.splitlines()
    if not lines or lines[0] != "# ---" or "# ---" not in lines[1:]:
        print("Missing delimited YAML header.")
        return 1
    header_end = lines.index("# ---", 1)
    header = "\n".join(lines[: header_end + 1])
    required = (
        "# jupyter:",
        "#   jupytext:",
        "#     formats: ipynb,py:percent",
        "#     text_representation:",
        "#       extension: .py",
        "#       format_name: percent",
        "#   kernelspec:",
        "#     language: python",
        "#     name: python3",
    )
    if any(line not in header.splitlines() for line in required):
        print("Incomplete pairing, format, or kernel metadata.")
        return 1
    if not re.search(
        r"^#       format_version: ['\"]?1\.3['\"]?$", header, re.M
    ):
        print("Missing percent format version.")
        return 1
    if not re.search(r"^#       jupytext_version: .+", header, re.M):
        print("Missing Jupytext version metadata.")
        return 1
    if not re.search(r"^#     display_name: .+", header, re.M):
        print("Missing kernel display name.")
        return 1
    content = "\n".join(lines[header_end + 1 :]).lstrip()
    if not content.startswith("# %%"):
        print("Content precedes the first cell marker.")
        return 1
    markers = re.findall(r"^# %%(.*)$", content, re.M)
    markdown_count = sum("[markdown]" in marker for marker in markers)
    code_count = sum("[markdown]" not in marker for marker in markers)
    if markdown_count < 2 or code_count < 3:
        print("Expected at least two markdown and three code cells.")
        return 1
    print("Percent header and cell structure passed.")
    return 0


def check_behavior(path: pathlib.Path) -> int:
    """Runs the notebook on independent normal, changed, and empty inputs.

    Args:
        path: Candidate notebook script.

    Returns:
        Zero if every input produces the expected summary, otherwise one.
    """
    for values in ([3, 5, 8, 12], [-3, 0, 9], []):
        with tempfile.TemporaryDirectory(prefix="percent-eval-") as directory:
            workspace = pathlib.Path(directory)
            (workspace / "measurements.json").write_text(
                json.dumps(values), encoding="utf-8"
            )
            try:
                result = subprocess.run(
                    [sys.executable, "-I", str(path)],
                    cwd=workspace,
                    capture_output=True,
                    text=True,
                    timeout=3,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                print("Candidate execution exceeded three seconds.")
                return 1
            if result.returncode != 0:
                print((result.stdout + result.stderr)[-4000:])
                return 1
            try:
                actual = json.loads(
                    (workspace / "results.json").read_text(encoding="utf-8")
                )
            except (OSError, ValueError) as error:
                print(f"invalid results.json: {error}")
                return 1
            total = math.fsum(values)
            expected = {
                "count": len(values),
                "total": total,
                "mean": total / len(values) if values else None,
            }
            if actual != expected:
                print(f"Input {values}: expected {expected}, got {actual}")
                return 1
    print("Execution passed for normal, changed, and empty input.")
    return 0


def main() -> int:
    """Grades one aspect of a percent-format notebook.

    Returns:
        Zero for pass, one for failure, two for invalid grader usage.
    """
    if len(sys.argv) != 3 or sys.argv[2] not in {"structure", "behavior"}:
        print("usage: grade.py WORKSPACE {structure|behavior}")
        return 2
    path = pathlib.Path(sys.argv[1]).resolve() / "analysis.py"
    if sys.argv[2] == "structure":
        return check_structure(path)
    return check_behavior(path)


if __name__ == "__main__":
    sys.exit(main())
