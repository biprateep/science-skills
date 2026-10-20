"""Regression coverage for audit finding 4: expressions are data, never Python."""

import importlib.util
import pathlib
import tempfile
import unittest

_SPEC = importlib.util.spec_from_file_location(
    "scientist_server", pathlib.Path(__file__).parents[1] / "mcp/server.py"
)
SERVER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(SERVER)


class ExpressionSafetyTest(unittest.TestCase):
    def test_mathematics_and_calculus(self):
        table = SERVER._build_symbols({"x": "real", "k": "positive"})
        for left, right in (
            ("(x+1)**2", "x**2 + 2*x + 1"),
            ("integrate(x*exp(-k*x), (x, 0, oo))", "1/k**2"),
            ("diff(sin(x), x)", "cos(x)"),
            ("summation(x, (x, 1, 10))", "55"),
            ("sqrt(k**2)", "k"),
        ):
            with self.subTest(expression=left):
                lhs = SERVER._math_expression(left, table)
                rhs = SERVER._math_expression(right, table)
                self.assertEqual((lhs - rhs).simplify(), 0)

    def test_rejects_python_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = pathlib.Path(directory) / "executed"
            attacks = (
                f'__import__("pathlib").Path("{marker}").touch() or 0',
                'open("/tmp/unsafe", "w")',
                "x.__class__", "[x for x in (1,2)]", "(lambda: 0)()",
                "sin.__globals__", "Symbol('x')", "x[0]", "sin(x, **x)",
            )
            for expression in attacks:
                with self.subTest(expression=expression):
                    with self.assertRaises(ValueError):
                        SERVER._math_expression(expression, {})
            self.assertFalse(marker.exists())

    def test_rejects_excessive_literals_and_syntax(self):
        for expression in ("2**1000000000", "1e999", "x+" * 10000):
            with self.subTest(expression=expression[:30]):
                with self.assertRaises(ValueError):
                    SERVER._math_expression(expression, {})

    def test_symbol_names_cannot_inject_generated_numeric_code(self):
        with self.assertRaises(ValueError):
            SERVER._build_symbols({"x); print(123)": "real"})


if __name__ == "__main__":
    unittest.main()
