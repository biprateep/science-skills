"""Pass a shared evaluation prompt to Antigravity's string-valued print flag."""

import os
import pathlib
import sys


def main() -> None:
    """Replace this process with the native CLI, retaining run limits."""
    if len(sys.argv) != 2:
        sys.exit("usage: antigravity_runner.py PROMPT_FILE")
    prompt = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
    if not prompt.strip():
        sys.exit("The evaluation prompt must not be empty")
    os.execvp(
        "agy",
        ["agy", "--sandbox", "--output-format", "text", f"--print={prompt}"],
    )


if __name__ == "__main__":
    main()
