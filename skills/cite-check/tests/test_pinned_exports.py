"""Finding 10 follow-up: exports keep the already-resolved source commit."""
import unittest
import unittest.mock

import test_evidence

SERVER = test_evidence.SERVER


class PinnedExportTest(unittest.TestCase):
    def test_export_does_not_resolve_mutable_tag_again(self):
        record = SERVER._record(registry="github", github="owner/project", title="Project")
        record.update(pin="v1.0", pinned_sha="a" * 40, pinned_date="2024-01-02",
                      requested_version="v1.0", repo={"full_name": "owner/project", "owner": "owner"})
        with unittest.mock.patch.object(SERVER, "_github_pin", side_effect=AssertionError("must use resolved commit")):
            bibtex, source = SERVER._github_bibtex(record)
        self.assertEqual(source, "github")
        self.assertIn("version = {v1.0}", bibtex)
        self.assertIn("Commit " + "a" * 40, bibtex)
        self.assertIn("/tree/" + "a" * 40, bibtex)
        provenance = SERVER._prov_comment(record, source)
        self.assertIn("version=v1.0", provenance)
        self.assertIn("commit=" + "a" * 40, provenance)
