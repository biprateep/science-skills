"""Regression tests for finding 2: evidence and context identity."""
import json
import pathlib
import tempfile
import unittest
import unittest.mock

import test_evidence

SERVER = test_evidence.SERVER


class IdentityTest(unittest.TestCase):
    def test_scientific_claims_have_distinct_identities(self):
        for first, second in [("$α=1$", "$β=1$"), ("$x=1$", "$X=1$"),
                              ("⟨x⟩=1", "⟨y⟩=1")]:
            self.assertNotEqual(SERVER._claim_hash(first),
                                SERVER._claim_hash(second))

    def test_replacement_context_and_legacy_verdicts_are_stale(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            tex, bib, source = root / "main.tex", root / "refs.bib", root / "source.txt"
            tex.write_text(r"Result is supported \cite{k}.")
            bib.write_text("@article{k,title={Example}}")
            source.write_text("The result is supported by our experiment.")
            meta = {"id": "doi:10.1/example", "basis": "fulltext",
                    "source": "local:source.txt", "path": str(source),
                    "extraction_version": SERVER.TEXT_EXTRACTION_VERSION}
            meta["intake"] = test_evidence.source_intake(source)
            with unittest.mock.patch.object(SERVER, "_full_record", return_value={"doi": "10.1/example"}), unittest.mock.patch.object(SERVER, "_load_text_meta", return_value=meta):
                cite = SERVER.extract_cites(str(tex))["cites"][0]
                def record():
                    return SERVER.record_support(
                        directory, "k", cite["claim"], "SUPPORTS", "example",
                        quotes=[source.read_text()], context=cite["context"]
                    )
                self.assertTrue(record()["recorded"])
                self.assertTrue(SERVER.audit(str(tex), str(bib), verify=False, policy="exploratory")["ok"])
                source.write_text("The result is contradicted by our experiment.")
                report = SERVER.audit(str(tex), str(bib), verify=False, policy="exploratory")
                self.assertFalse(report["ok"])
                self.assertEqual(report["failures"][0]["type"], "support-stale")
                record()
                tex.write_text(r"Context changed. Result is supported \cite{k}.")
                self.assertFalse(SERVER.audit(str(tex), str(bib), verify=False, policy="exploratory")["ok"])
                ledger_path = root / ".cite-check" / "ledger.json"
                ledger = json.loads(ledger_path.read_text())
                for entry in ledger["entries"].values():
                    entry.pop("source_identity")
                ledger_path.write_text(json.dumps(ledger))
                self.assertFalse(SERVER.audit(str(tex), str(bib), verify=False, policy="exploratory")["ok"])
