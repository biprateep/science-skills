"""Finding 7: registry failure is distinct from definitive absence."""
import pathlib
import tempfile
import unittest
import unittest.mock

import test_evidence

SERVER = test_evidence.SERVER


class RegistryOutcomesTest(unittest.TestCase):
    def test_http_failures_and_malformed_responses(self):
        for status, payload, outcome in [(503, None, "unavailable"),
                                          (429, None, "rate-limited"),
                                          (200, {}, "malformed-response")]:
            with unittest.mock.patch.object(SERVER, "_get_json", return_value=(status, payload)), unittest.mock.patch.object(SERVER, "_ads_token", return_value=""):
                result = SERVER.resolve_citation("10.1234/example")
                self.assertTrue(result["lookup_error"])
                self.assertEqual(result["outcome"], outcome)

    def test_definitive_absence(self):
        with unittest.mock.patch.object(SERVER, "_get_json", return_value=(404, None)), unittest.mock.patch.object(SERVER, "_ads_token", return_value=""):
            result = SERVER.resolve_citation("10.1234/example")
            self.assertEqual(result["outcome"], "not-found")
            self.assertNotIn("lookup_error", result)

    def test_fallback_succeeds_after_primary_outage(self):
        record = SERVER._record(registry="datacite", doi="10.1234/example", title="Example")
        with unittest.mock.patch.object(SERVER, "_crossref_work", side_effect=RuntimeError("down")), unittest.mock.patch.object(SERVER, "_datacite_doi", return_value=record), unittest.mock.patch.object(SERVER, "_ads_token", return_value=""), unittest.mock.patch.object(SERVER, "_record_cache_put"), unittest.mock.patch.object(SERVER, "_alias_put"):
            self.assertTrue(SERVER.resolve_citation("10.1234/example")["resolved"])

    def test_outage_does_not_accuse_bibliography_of_fabrication(self):
        with tempfile.TemporaryDirectory() as directory:
            bib = pathlib.Path(directory) / "references.bib"
            bib.write_text('@article{k,doi={10.1234/example},title={Example}}')
            with unittest.mock.patch.object(SERVER, "_get_json", return_value=(503, None)), unittest.mock.patch.object(SERVER, "_ads_token", return_value=""):
                report = SERVER.verify_bib(str(bib), search_unresolved=False)
            self.assertEqual(report["entries"][0]["status"], "UNRESOLVED")

    def test_arxiv_errors_are_not_empty_successful_feeds(self):
        for status, body in [(503, "down"), (200, "<html>wrong</html>")]:
            with unittest.mock.patch.object(SERVER, "_http", return_value=(status, body)), unittest.mock.patch.object(SERVER, "_ads_token", return_value=""):
                self.assertTrue(SERVER.resolve_citation("1706.03762")["lookup_error"])
