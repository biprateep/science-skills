"""Regression tests for finding 3: fail closed on incomplete inputs."""
import pathlib
import tempfile
import unittest
import unittest.mock

import test_evidence

SERVER = test_evidence.SERVER


class CompletenessTest(unittest.TestCase):
    def test_malformed_bibliographies(self):
        for text in ['@article{k,title={unfinished}', '@article{k,title=}',
                     '@article{k title={x}}', '@article{k,title="oops}',
                     '@article{k,title={x} year=2020}']:
            with self.subTest(text=text):
                self.assertFalse(SERVER._parse_bib(text)["complete"])

    def test_nocite_star_verifies_all_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            tex = root / "main.tex"
            tex.write_text(r"\nocite{*}\bibliography{refs}")
            (root / "refs.bib").write_text('@article{fake,title={Fabrication}}')
            result = {"entries": [{"key": "fake", "status": "NOT_FOUND"}]}
            with unittest.mock.patch.object(SERVER, "verify_bib", return_value=result) as verify:
                report = SERVER.audit(str(tex))
            self.assertFalse(report["ok"])
            self.assertEqual(verify.call_args.kwargs["keys"], ["fake"])
            self.assertEqual(report["n_keys"], 1)

    def test_missing_declared_inputs_and_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            tex = root / "main.tex"
            tex.write_text(r"\input{missing}")
            self.assertFalse(SERVER.extract_cites(str(tex))["complete"])
            tex.write_text(r"\bibliography{refs,missing}")
            (root / "refs.bib").write_text('@article{k,title={x}}')
            self.assertFalse(SERVER.audit(str(tex), verify=False)["complete"])
            tex.write_text(r"\addbibresource[location=local]{refs.bib}")
            (root / "refs.bib").write_text('@article{k,title={x}}\n@book{k,title={y}}')
            self.assertFalse(SERVER.audit(str(tex), verify=False)["complete"])
            (root / "refs.bib").write_text('@article{k,title={x}')
            self.assertFalse(SERVER.verify_bib(str(root / "refs.bib"))["ok"])
