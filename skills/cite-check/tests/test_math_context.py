"""Regression tests for audit finding 2's mathematical context identity."""

import pathlib
import tempfile
import unittest
import unittest.mock

import test_evidence

SERVER = test_evidence.SERVER


class MathContextTest(unittest.TestCase):
    def test_displayed_mathematics_changes_context_identity(self):
        wrappers = [
            (r"\begin{equation}", r"\end{equation}"),
            (r"\begin{align*}", r"\end{align*}"),
            (r"\[", r"\]"),
            ("$$", "$$"),
            (r"\(", r"\)"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            tex = pathlib.Path(directory) / "main.tex"
            for opening, closing in wrappers:
                with self.subTest(wrapper=opening):
                    contexts = []
                    for math in (r"\alpha=1", r"\beta=100"):
                        tex.write_text(
                            f"{opening}{math}{closing}"
                            r" We use this result \cite{k}."
                        )
                        result = SERVER.extract_cites(str(tex))
                        self.assertTrue(result["complete"])
                        contexts.append(result["cites"][0]["context"])
                    self.assertNotEqual(
                        SERVER._claim_hash(contexts[0]),
                        SERVER._claim_hash(contexts[1]),
                    )
                    self.assertIn(r"\alpha=1", contexts[0])
                    self.assertIn(r"\beta=100", contexts[1])

    def test_citation_inside_equation_is_extracted(self):
        with tempfile.TemporaryDirectory() as directory:
            tex = pathlib.Path(directory) / "main.tex"
            tex.write_text(
                r"\begin{equation}x=1\text{ from }\cite{k}\end{equation}"
            )
            result = SERVER.extract_cites(str(tex))
            self.assertTrue(result["complete"])
            self.assertEqual(result["keys"], ["k"])
            self.assertIn("x=1", result["cites"][0]["claim"])

    def test_context_crosses_paragraph_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            tex = pathlib.Path(directory) / "main.tex"
            contexts = []
            for value in ("1", "100"):
                tex.write_text(
                    rf"\begin{{equation}}x={value}\end{{equation}}"
                    "\n\n"
                    r"We use this result \cite{k}."
                )
                contexts.append(
                    SERVER.extract_cites(str(tex))["cites"][0]["context"]
                )
            self.assertNotEqual(contexts[0], contexts[1])

    def test_changed_displayed_result_invalidates_recorded_support(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            tex, bib = root / "main.tex", root / "refs.bib"
            source = root / "source.txt"
            source.write_text("The result is supported by our experiment.")
            bib.write_text("@article{k,title={Example}}")
            tex.write_text(
                r"\begin{equation}x=1\end{equation}"
                r" We use this result \cite{k}."
            )
            meta = {
                "id": "doi:10.1/example",
                "basis": "fulltext",
                "source": "local:source.txt",
                "path": str(source),
                "intake": test_evidence.source_intake(source),
                "extraction_version": SERVER.TEXT_EXTRACTION_VERSION,
            }
            with (
                unittest.mock.patch.object(
                    SERVER,
                    "_full_record",
                    return_value={"doi": "10.1/example"},
                ),
                unittest.mock.patch.object(
                    SERVER,
                    "_load_text_meta",
                    return_value=meta,
                ),
            ):
                cite = SERVER.extract_cites(str(tex))["cites"][0]
                recorded = SERVER.record_support(
                    directory,
                    "k",
                    cite["claim"],
                    "SUPPORTS",
                    "example",
                    quotes=[source.read_text()],
                    context=cite["context"],
                )
                self.assertTrue(recorded["recorded"])
                self.assertTrue(
                    SERVER.audit(str(tex), str(bib), verify=False, policy="exploratory")["ok"]
                )
                tex.write_text(tex.read_text().replace("x=1", "x=100"))
                self.assertFalse(
                    SERVER.audit(str(tex), str(bib), verify=False, policy="exploratory")["ok"]
                )


if __name__ == "__main__":
    unittest.main()
