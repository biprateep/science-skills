"""The native CLI receives prompt text as a flag value, never another flag."""

import importlib.util
import pathlib
import sys
import unittest.mock


def test_print_receives_prompt_with_no_shell_interpolation(tmp_path):
    path = pathlib.Path(__file__).parents[1] / "antigravity_runner.py"
    spec = importlib.util.spec_from_file_location("antigravity_runner", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    prompt = tmp_path / "prompt.txt"
    content = "Evaluate this claim.\nLiteral $(text) and `ticks`."
    prompt.write_text(content, encoding="utf-8")
    with (
        unittest.mock.patch.object(sys, "argv", [str(path), str(prompt)]),
        unittest.mock.patch.object(module.os, "execvp") as execute,
    ):
        module.main()
    execute.assert_called_once_with(
        "agy",
        ["agy", "--sandbox", "--output-format", "text", f"--print={content}"],
    )
