"""Regression tests for audit finding 1: exact evidence certification."""
import importlib.util
import pathlib
import unittest

SPEC = importlib.util.spec_from_file_location(
    "cite_server", pathlib.Path(__file__).parents[1] / "mcp" / "server.py"
)
SERVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SERVER)


class EvidenceTest(unittest.TestCase):
    """Quotes cannot alter scientific meaning through normalization."""

    def test_semantic_changes_are_rejected(self):
        pairs = [
            ("The treatment did not improve survival in the study.",
             "The treatment did improve survival in the study."),
            ("The measured velocity is -100 km/s.",
             "The measured velocity is +100 km/s."),
            ("The measured probability is 0.01.",
             "The measured probability is 0.91."),
            ("The measured parameter is α = X².",
             "The measured parameter is β = x2."),
        ]
        for source, quote in pairs:
            with self.subTest(quote=quote):
                self.assertFalse(SERVER._locate_quote(source, quote)["found"])

    def test_offsets_refer_to_original_source(self):
        source = "prefix\nThe ﬁtted\n  value is -100 km/s. suffix"
        result = SERVER._locate_quote(
            source, "The fitted value is -100 km/s."
        )
        self.assertTrue(result["found"])
        self.assertEqual(result["source_text"],
                         source[result["at"]:result["end"]])
        self.assertEqual(result["at"], source.index("The"))

    def test_superscripts_are_not_plain_digits(self):
        self.assertFalse(SERVER._locate_quote(
            "The total area is 100 m².", "The total area is 100 m2."
        )["found"])


if __name__ == "__main__":
    unittest.main()
