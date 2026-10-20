"""Regression tests for audit finding 3's TeX and BibTeX edge cases."""

import pathlib
import tempfile
import unittest

import test_evidence

SERVER = test_evidence.SERVER


class ParserFollowupTest(unittest.TestCase):
    def test_mixed_optional_bibliography_cannot_hide_missing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            tex = root / "main.tex"
            tex.write_text(
                r"\bibliography{refs}"
                r"\addbibresource[location=local]{missing.bib}"
            )
            (root / "refs.bib").write_text("@article{k,title={Example}}")
            report = SERVER.audit(str(tex), verify=False, policy="exploratory")
            self.assertFalse(report["ok"])
            self.assertFalse(report["complete"])
            self.assertTrue(
                any(
                    item["type"] == "missing-bib" for item in report["failures"]
                )
            )

    def test_optional_bibliography_is_actually_parsed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            tex = root / "main.tex"
            tex.write_text(r"\addbibresource[location=local]{refs.bib}")
            bib = root / "refs.bib"
            bib.write_text("@article{k,title={Example}}")
            report = SERVER.audit(str(tex), verify=False, policy="exploratory")
            self.assertTrue(report["complete"])
            self.assertTrue(report["ok"])
            self.assertEqual(report["bibs"], [str(bib)])

    def test_nested_inputs_use_main_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            sections = root / "sections"
            sections.mkdir()
            (root / "main.tex").write_text(r"\input{sections/a}")
            (sections / "a.tex").write_text(r"\input{sections/b}")
            (sections / "b.tex").write_text(
                r"The result holds \cite{k}.\bibliography{refs}"
            )
            report = SERVER.extract_cites(str(root / "main.tex"))
            self.assertTrue(report["complete"])
            self.assertEqual(report["keys"], ["k"])
            self.assertEqual(report["bib_files"], [str(root / "refs.bib")])

    def test_braceless_input_is_followed_and_missing_input_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            tex = root / "main.tex"
            tex.write_text("\\input section.tex\n")
            section = root / "section.tex"
            section.write_text(r"The result holds \cite{k}.")
            report = SERVER.extract_cites(str(tex))
            self.assertTrue(report["complete"])
            self.assertEqual(report["keys"], ["k"])
            section.unlink()
            self.assertFalse(SERVER.extract_cites(str(tex))["complete"])

    def test_unsupported_dynamic_input_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            tex = pathlib.Path(directory) / "main.tex"
            tex.write_text(r"\input\sectionfile")
            self.assertFalse(SERVER.extract_cites(str(tex))["complete"])

    def test_missing_bibliography_argument_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            tex = pathlib.Path(directory) / "main.tex"
            tex.write_text(
                r"\bibliography{refs}\addbibresource[location=local]"
            )
            self.assertFalse(SERVER.extract_cites(str(tex))["complete"])

    def test_percent_comments_do_not_create_entries(self):
        text = (
            "% contact a@example.org and @article{not-an-entry}\n"
            "@article{k,title={An email a@example.org with 10% precision}}\n"
            "% @broken\n"
        )
        parsed = SERVER._parse_bib(text)
        self.assertTrue(parsed["complete"], parsed["errors"])
        self.assertEqual(list(parsed["keys"]), ["k"])
        entry = parsed["entries"][0]
        self.assertEqual(entry["raw"], text[entry["start"] : entry["end"]])
        self.assertIn("10% precision", entry["fields"]["title"])

    def test_citations_lost_during_cleanup_cannot_pass_as_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            tex = pathlib.Path(directory) / "main.tex"
            for source in (
                r"\begin{equation}x=1\text{ from }\cite{k}\end{equation}",
                r"\[x=1\text{ from }\cite{k}\]",
                r"\affiliation{See \cite{k}}",
            ):
                with self.subTest(source=source):
                    tex.write_text(source)
                    result = SERVER.extract_cites(str(tex))
                    if result["complete"]:
                        self.assertEqual(result["keys"], ["k"])
                    else:
                        self.assertIn("citation", result["error"])


if __name__ == "__main__":
    unittest.main()
