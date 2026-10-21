# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
# ---
# %%
"""Run the complete citation regression suite with mandatory capabilities."""

import argparse
import importlib
import importlib.metadata
import pathlib
import sys
import unittest


def preflight(expected_major: int) -> None:
    """Require the selected native SDK and all critical optional test paths."""
    if expected_major not in (1, 2):
        raise RuntimeError("expected MCP SDK major must be 1 or 2")
    for name in ("mcp", "httpx", "pypdf"):
        try:
            importlib.import_module(name)
        except ImportError as error:
            raise RuntimeError(
                f"required regression dependency missing: {name}"
            ) from error
    try:
        major = int(importlib.metadata.version("mcp").split(".", 1)[0])
    except (importlib.metadata.PackageNotFoundError, ValueError) as error:
        raise RuntimeError(
            "cannot determine installed MCP SDK major"
        ) from error
    if major != expected_major:
        raise RuntimeError(f"expected MCP SDK {expected_major}, found {major}")


def run_suite(start_dir: pathlib.Path) -> int:
    """Discover all regression tests and reject failures, skips or no tests."""
    suite = unittest.TestLoader().discover(str(start_dir), pattern="test_*.py")
    if suite.countTestCases() == 0:
        print("Regression collection is empty.", file=sys.stderr)
        return 1
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.skipped:
        print(
            "Regression coverage incomplete: skipped tests are forbidden.",
            file=sys.stderr,
        )
    return int(not result.wasSuccessful() or bool(result.skipped))


def main(argv: list[str] | None = None) -> int:
    """Run the selected SDK lane; the caller must enforce a wall timeout."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk-major", required=True, type=int, choices=(1, 2))
    args = parser.parse_args(argv)
    try:
        preflight(args.sdk_major)
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 2
    return run_suite(pathlib.Path(__file__).resolve().parent)


# %%
if __name__ == "__main__":
    raise SystemExit(main())
