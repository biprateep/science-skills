"""Regression tests for audit finding 1's normalized source-span boundaries."""

import unittest

import test_evidence

SERVER = test_evidence.SERVER


class QuoteBoundaryTest(unittest.TestCase):
    def test_partial_ligature_is_not_a_verbatim_span(self):
        for source, quote in (
            ("ﬁtted value is scientific", "itted value is scientific"),
            ("This is a handcuﬀ", "This is a handcuf"),
        ):
            with self.subTest(source=source):
                self.assertFalse(SERVER._locate_quote(source, quote)["found"])

    def test_search_continues_after_an_invalid_partial_ligature(self):
        source = "ﬁtted value is scientific. Then itted value is scientific."
        quote = "itted value is scientific"
        match = SERVER._locate_quote(source, quote)
        self.assertTrue(match["found"])
        self.assertEqual(match["at"], source.index("itted"))
        self.assertEqual(match["source_text"], quote)

    def test_complete_ligatures_preserve_exact_source_offsets(self):
        source = "Prefix: ﬁtted value is scientific."
        match = SERVER._locate_quote(source, "fitted value is scientific.")
        self.assertTrue(match["found"])
        self.assertEqual(
            match["source_text"], source[match["at"] : match["end"]]
        )
        self.assertEqual(
            SERVER._norm_quote(match["source_text"]),
            "fitted value is scientific.",
        )


if __name__ == "__main__":
    unittest.main()
