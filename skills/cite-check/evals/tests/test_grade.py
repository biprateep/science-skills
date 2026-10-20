"""Regression checks for deterministic starter-fixture graders."""

import pathlib
import subprocess
import sys
import tempfile
import unittest


class GraderTest(unittest.TestCase):
    def setUp(self):
        self.evals = pathlib.Path(__file__).resolve().parents[1]
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace = pathlib.Path(self.temporary.name)
        self.artifact = self.workspace / "response.txt"
        self.reference = (
            self.evals / "evidence-boundaries/reference/response.txt"
        ).read_text(encoding="utf-8")
        self.artifact.write_text(self.reference, encoding="utf-8")

    def grade(self, mode):
        return subprocess.run(
            [
                sys.executable,
                str(self.evals / "grade.py"),
                *[str(self.artifact)],
            ],
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
        )

    def test_reference_passes(self):
        for mode in [""]:
            with self.subTest(mode=mode):
                result = self.grade(mode)
                self.assertEqual(
                    result.returncode, 0, result.stdout + result.stderr
                )

    def test_broken_outputs_fail(self):
        for name, before, after, mode in [
            ("fabricated quotation", "12 percent", "99 percent", ""),
            (
                "invented inaccessible evidence",
                '"evidence": ""',
                '"evidence": "invented"',
                "",
            ),
        ]:
            with self.subTest(name=name):
                self.assertIn(before, self.reference)
                self.artifact.write_text(
                    self.reference.replace(before, after), encoding="utf-8"
                )
                result = self.grade(mode)
                self.assertEqual(
                    result.returncode, 1, result.stdout + result.stderr
                )

    def test_missing_output_fails(self):
        self.artifact.unlink()
        for mode in [""]:
            with self.subTest(mode=mode):
                result = self.grade(mode)
                self.assertEqual(
                    result.returncode, 1, result.stdout + result.stderr
                )


if __name__ == "__main__":
    unittest.main()
