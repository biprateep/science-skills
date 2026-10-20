"""Finding 8 follow-up: source text and metadata commit as one snapshot."""
import pathlib
import tempfile
import unittest
import unittest.mock

import test_evidence

SERVER = test_evidence.SERVER


class SourceSnapshotsTest(unittest.TestCase):
    def test_interrupted_publish_preserves_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            source = pathlib.Path(directory) / "input.txt"
            source.write_text("The first source text is sufficiently long.")
            record = SERVER._record(registry="crossref", doi="10.1234/example")
            with unittest.mock.patch.object(SERVER, "CACHE_DIR", directory), unittest.mock.patch.object(SERVER, "_full_record", return_value=record):
                first = SERVER.fetch_text("10.1234/example", text_path=str(source))
                identity = SERVER._current_source_identity(first["id"])
                source.write_text("The replacement source text has different meaning.")
                atomic_write = SERVER._atomic_write
                def fail_metadata(path, content):
                    if path.endswith(".json"):
                        raise OSError("simulated crash at commit point")
                    atomic_write(path, content)
                with unittest.mock.patch.object(SERVER, "_atomic_write", side_effect=fail_metadata):
                    with self.assertRaises(OSError):
                        SERVER.fetch_text("10.1234/example", text_path=str(source))
                self.assertEqual(SERVER._current_source_identity(first["id"]), identity)
                second = SERVER.fetch_text("10.1234/example", text_path=str(source))
                self.assertNotEqual(first["path"], second["path"])
                self.assertIn("first source", pathlib.Path(first["path"]).read_text())
                pathlib.Path(second["path"]).write_text("corrupt")
                self.assertIsNone(SERVER._load_text_meta(second["id"]))

    def test_bibliography_symlink_updates_shared_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            shared, link = root / "shared.bib", root / "local.bib"
            shared.write_text("")
            link.symlink_to(shared)
            record = SERVER._record(registry="crossref", doi="10.1234/example")
            exported = {"bibtex": '@article{x,doi={10.1234/example}}', "source": "crossref"}
            with unittest.mock.patch.object(SERVER, "_full_record", return_value=record), unittest.mock.patch.object(SERVER, "_official_bibtex", return_value=exported):
                self.assertTrue(SERVER.bib_add(str(link), [{"identifier": "10.1234/example", "key": "x"}])["ok"])
            self.assertTrue(link.is_symlink())
            self.assertIn("10.1234/example", shared.read_text())
