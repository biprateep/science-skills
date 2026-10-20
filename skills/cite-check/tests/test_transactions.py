"""Finding 8: simultaneous successful writes retain every update."""
import concurrent.futures
import json
import pathlib
import tempfile
import unittest
import unittest.mock

import test_evidence

SERVER = test_evidence.SERVER


class TransactionsTest(unittest.TestCase):
    def test_concurrent_ledger_writers_keep_all_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            source = pathlib.Path(directory) / "source.txt"
            source.write_text("The measurement supports this conclusion.")
            meta = {"id": "doi:10.1/example", "path": str(source), "basis": "fulltext"}
            with unittest.mock.patch.object(SERVER, "_full_record", return_value={"doi": "10.1/example"}), unittest.mock.patch.object(SERVER, "_load_text_meta", return_value=meta):
                def record(index):
                    return SERVER.record_support(
                        directory, f"key{index}", "A claim.", "SUPPORTS",
                        "example", quotes=[source.read_text()]
                    )
                with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
                    results = list(pool.map(record, range(24)))
            self.assertTrue(all(result["recorded"] for result in results))
            self.assertEqual(len(SERVER._load_ledger(directory)["entries"]), 24)

    def test_atomic_replace_failure_preserves_old_state(self):
        with tempfile.TemporaryDirectory() as directory:
            target = pathlib.Path(directory) / "state.json"
            target.write_text('{"old": true}')
            with unittest.mock.patch.object(SERVER.os, "replace", side_effect=OSError("interrupted")):
                with self.assertRaises(OSError):
                    SERVER._atomic_write(str(target), '{"new": true}')
            self.assertEqual(json.loads(target.read_text()), {"old": True})
            self.assertEqual(list(pathlib.Path(directory).iterdir()), [target])

    def test_concurrent_bibliography_additions(self):
        with tempfile.TemporaryDirectory() as directory:
            target = pathlib.Path(directory) / "refs.bib"
            def resolve(identifier):
                return SERVER._record(registry="crossref", doi=identifier, title=identifier)
            def export(record, *args):
                return {"bibtex": '@article{x,doi={' + record["doi"] + '}}', "source": "crossref"}
            with unittest.mock.patch.object(SERVER, "_full_record", side_effect=resolve), unittest.mock.patch.object(SERVER, "_official_bibtex", side_effect=export):
                with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                    results = list(pool.map(lambda index: SERVER.bib_add(
                        str(target), [{"identifier": f"10.1234/{index}", "key": f"k{index}"}]
                    ), range(16)))
            self.assertTrue(all(result["ok"] for result in results))
            parsed = SERVER._parse_bib(target.read_text())
            self.assertTrue(parsed["complete"])
            self.assertEqual(len(parsed["entries"]), 16)
