"""Checks a repaired library using AST structure and bounded behavior probes."""

import ast
import pathlib
import subprocess
import sys

_BEHAVIOR_PROBE = """import importlib.util
import math
import sys
spec = importlib.util.spec_from_file_location("candidate", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
for values, mean, minimum in [
    ([2.0, 4.0, 9.0], 5.0, 2.0),
    ([-8.0, -2.0], -5.0, -8.0),
    ([0.0], 0.0, 0.0),
    ([1e16, 1.0, -1e16], 1 / 3, -1e16),
]:
    original = values.copy()
    actual = module.summarize(values)
    assert set(actual) == {"mean", "minimum"}, actual
    assert math.isclose(actual["mean"], mean, rel_tol=1e-12, abs_tol=1e-12)
    assert actual["minimum"] == minimum, actual
    assert values == original, "summarize mutated the input"
try:
    module.summarize([])
except ValueError:
    pass
else:
    raise AssertionError("empty input must raise ValueError")
first = module.append_label("a")
second = module.append_label("b")
assert first == ["a"] and second == ["b"] and first is not second
for labels in ([], ["existing"]):
    expected = labels + ["new"]
    returned = module.append_label("new", labels)
    assert returned is labels and labels == expected
assert module.append_label("c", None) == ["c"]
print("Numerical, empty-input, mutation, and ownership checks passed.")
"""


def check_structure(path: pathlib.Path) -> int:
    """Checks the required public signatures and a small style subset.

    Args:
        path: Candidate library module.

    Returns:
        Zero for pass, one for an invalid artifact.
    """
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError, UnicodeError) as error:
        print(f"invalid module: {error}")
        return 1
    if not ast.get_docstring(tree):
        print("Module docstring missing.")
        return 1
    if any(len(line) > 80 for line in source.splitlines()):
        print("A line exceeds 80 columns.")
        return 1
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module not in {
            "typing",
            "collections.abc",
            "__future__",
        }:
            print("Use package/module imports for this library.")
            return 1
    math_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "math":
                    math_names.add(alias.asname or alias.name)
    if not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in math_names
        and node.func.attr == "fsum"
        for node in ast.walk(tree)
    ):
        print("The requested math.fsum call is missing.")
        return 1
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }
    for name in ("summarize", "append_label"):
        function = functions.get(name)
        if function is None:
            print(f"{name}: missing function")
            return 1
        arguments = function.args.posonlyargs + function.args.args
        arguments += function.args.kwonlyargs
        if function.returns is None or any(
            argument.annotation is None for argument in arguments
        ):
            print(f"{name}: signatures must be fully annotated")
            return 1
        docstring = ast.get_docstring(function) or ""
        sections = ["Args:", "Returns:"]
        if name == "summarize":
            sections.append("Raises:")
        if any(section not in docstring for section in sections):
            print(f"{name}: Google-style documentation is incomplete")
            return 1
        if any(
            isinstance(default, (ast.List, ast.Dict, ast.Set, ast.Call))
            for default in function.args.defaults
        ):
            print(f"{name}: unsafe default argument")
            return 1
    print("Required library structure and style subset passed.")
    return 0


def main() -> int:
    """Grades one aspect of the repaired module.

    Returns:
        Zero for pass, one for failure, two for invalid grader usage.
    """
    if len(sys.argv) != 3 or sys.argv[2] not in {"structure", "behavior"}:
        print("usage: grade.py WORKSPACE {structure|behavior}")
        return 2
    path = pathlib.Path(sys.argv[1]).resolve() / "metrics.py"
    if sys.argv[2] == "structure":
        return check_structure(path)
    try:
        result = subprocess.run(
            [sys.executable, "-I", "-c", _BEHAVIOR_PROBE, str(path)],
            cwd=path.parent,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except subprocess.TimeoutExpired:
        print("Candidate behavior exceeded five seconds.")
        return 1
    print((result.stdout + result.stderr)[-4000:])
    return 0 if result.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
