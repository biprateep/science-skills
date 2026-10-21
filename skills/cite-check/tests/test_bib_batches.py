"""Finding 9: bibliography batches validate before changing the file."""
import pathlib
import tempfile
import unittest
import unittest.mock

import test_evidence

SERVER = test_evidence.SERVER


class BibliographyBatchTest(unittest.TestCase):
    def test_duplicate_requested_keys_leave_file_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            target = pathlib.Path(directory) / "refs.bib"
            original = '@article{old,title={Existing}}'
            target.write_text(original)
            for replace in (False, True):
                result = SERVER.bib_add(str(target), [
                    {"identifier": "10.1234/one", "key": "same"},
                    {"identifier": "10.1234/two", "key": "same"},
                ], replace=replace)
                self.assertFalse(result["ok"])
                self.assertEqual(target.read_text(), original)

    def test_failed_item_aborts_prepared_additions(self):
        with tempfile.TemporaryDirectory() as directory:
            target = pathlib.Path(directory) / "refs.bib"
            record = SERVER._record(registry="crossref", doi="10.1234/one", title="Example")
            exported = test_evidence.official_export_fixture('@article{x,doi={10.1234/one}}', record)
            with unittest.mock.patch.object(SERVER, "CACHE_DIR", directory), unittest.mock.patch.object(SERVER, "_full_record", side_effect=[record, None]), unittest.mock.patch.object(SERVER, "_official_bibtex", return_value=exported):
                result = SERVER.bib_add(str(target), [
                    {"identifier": "10.1234/one", "key": "one"},
                    {"identifier": "10.1234/missing", "key": "two"},
                ])
            self.assertFalse(result["ok"])
            self.assertFalse(target.exists())
            self.assertEqual(result["results"][0]["status"], "aborted")

    def test_existing_duplicate_keys_reject_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            target = pathlib.Path(directory) / "refs.bib"
            original = '@article{same,title={A}}\n@article{same,title={B}}'
            target.write_text(original)
            self.assertFalse(SERVER.bib_add(str(target), ["10.1234/new"])["ok"])
            self.assertEqual(target.read_text(), original)
