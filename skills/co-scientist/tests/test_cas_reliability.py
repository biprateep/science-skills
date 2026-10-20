"""Regression tests for audit finding 6: validation, sampling and worker exits."""

import importlib.util
import pathlib
import random
import subprocess
import unittest
import unittest.mock

_SPEC = importlib.util.spec_from_file_location(
    "scientist_server", pathlib.Path(__file__).parents[1] / "mcp/server.py"
)
SERVER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(SERVER)


class VerificationReliabilityTest(unittest.TestCase):
    def test_invalid_settings_never_pass(self):
        step = {"lhs": "x", "rhs": "0", "cls": "N"}
        for settings in (
            {"steps": []}, {"steps": [1]}, {"samples": 0}, {"samples": -1},
            {"samples": True}, {"tolerance": 0}, {"tolerance": float("nan")},
            {"tolerance": float("inf")}, {"step_timeout": 0},
            {"domain": []}, {"domain": [1, 1]}, {"domain": [3, 1]},
            {"domain": [0, float("inf")]}, {"symbols": {"x": 1}},
        ):
            with self.subTest(settings=settings):
                kwargs = dict(steps=[step])
                kwargs.update(settings)
                result = SERVER.verify_derivation(**kwargs)
                self.assertIn("error", result)
                self.assertFalse(result.get("verified", False))

    def test_unchecked_only_does_not_claim_verification(self):
        result = SERVER.verify_derivation([{"cls": "U", "note": "human review"}])
        self.assertFalse(result["verified"])

    def test_sampler_respects_assumptions(self):
        specs = (
            ("integer", [-2, 3]), ("negative", [-3, 2]),
            ("positive", [-2, 3]), ("even", [0, 10]), ("odd", [0, 10]),
            ("prime", [2, 10]), ("irrational", [1, 2]),
            ("rational", [-1, 1]), ("imaginary", [-1, 1]),
        )
        for assumption, domain in specs:
            symbol = SERVER._build_symbols({"x": assumption})["x"]
            with self.subTest(assumption=assumption):
                rng = random.Random(4)
                for _ in range(10):
                    value = SERVER._sample_symbol(symbol, rng, domain)
                    self.assertIs(getattr(value, "is_" + assumption), True)

    def test_impossible_integer_domain_fails(self):
        symbol = SERVER._build_symbols({"x": "integer"})["x"]
        with self.assertRaises(ValueError):
            SERVER._sample_symbol(symbol, random.Random(1), [0.1, 0.9])

    def test_numeric_checks_do_not_pass_nonfinite_values(self):
        result = SERVER.verify_derivation(
            [{"lhs": "oo", "rhs": "oo", "cls": "N"}], step_timeout=10
        )
        self.assertFalse(result.get("verified", False))

    def test_worker_crash_and_timeout_are_bounded_failures(self):
        with unittest.mock.patch.object(
            SERVER.subprocess, "run",
            return_value=subprocess.CompletedProcess([], -9, "", ""),
        ):
            self.assertEqual(SERVER._check_with_timeout({}, 1)[1], "worker_failed")
        with unittest.mock.patch.object(
            SERVER.subprocess, "run", side_effect=subprocess.TimeoutExpired([], 1)
        ):
            self.assertEqual(SERVER._check_with_timeout({}, 1)[1], "timeout")

    def test_real_child_and_short_timeout(self):
        result = SERVER.verify_derivation(
            [{"lhs": "x", "rhs": "0", "cls": "N"}], samples=4,
            step_timeout=10,
        )
        self.assertFalse(result["verified"])
        result = SERVER.verify_derivation(
            [{"lhs": "x", "rhs": "x"}], step_timeout=0.001
        )
        self.assertFalse(result["verified"])
        self.assertEqual(result["steps"][0]["method"], "timeout")


if __name__ == "__main__":
    unittest.main()
