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

    def test_nested_crossref_payloads_are_typed_failures(self):
        for payload in (
            {"DOI": "10.1234/example", "title": 1},
            {"DOI": "10.1234/example", "title": "not an array"},
            {"DOI": "10.1234/example", "title": ["Example"], "author": ["bad"]},
            {"DOI": "10.1234/example", "title": ["Example"], "issued": {"date-parts": [["invalid"]]}},
            {"DOI": 123, "title": ["Example"]},
        ):
            with self.subTest(payload=payload):
                with unittest.mock.patch.object(SERVER, "_get_json", return_value=(200, {"message": payload})):
                    with self.assertRaises(SERVER.RegistryLookupError) as raised:
                        SERVER._crossref_work("10.1234/example")
                self.assertEqual(raised.exception.outcome, "malformed-response")

    def test_nested_datacite_payloads_are_typed_failures(self):
        for fields in (
            {"titles": ["wrong"]}, {"creators": ["wrong"]},
            {"descriptions": ["wrong"]}, {"titles": "wrong"},
            {"doi": 123}, {"types": []}, {"types": {"resourceTypeGeneral": []}},
            {"publicationYear": {"bad": 2026}},
        ):
            attributes = {"doi": "10.1234/example", "titles": [{"title": "Example"}]}
            attributes.update(fields)
            payload = {"data": {"attributes": attributes}}
            with self.subTest(fields=fields):
                with unittest.mock.patch.object(SERVER, "_get_json", return_value=(200, payload)):
                    with self.assertRaises(SERVER.RegistryLookupError) as raised:
                        SERVER._datacite_doi("10.1234/example")
                self.assertEqual(raised.exception.outcome, "malformed-response")

    def test_malformed_arxiv_entries_are_not_absence_or_crashes(self):
        for entry in (
            "<id>http://arxiv.org/abs/1706.03762v1</id>",
            "<id>invalid</id><title>Example</title>",
            "<id>http://arxiv.org/abs/not-an-id</id><title>Example</title>",
            "<id>http://arxiv.org/abs/1706.03762v1</id><title>Error</title>",
        ):
            body = '<feed xmlns="http://www.w3.org/2005/Atom"><entry>' + entry + '</entry></feed>'
            with self.subTest(entry=entry):
                with unittest.mock.patch.object(SERVER, "_http", return_value=(200, body)), unittest.mock.patch.object(SERVER, "_ads_token", return_value=""):
                    result = SERVER.resolve_citation("1706.03762")
                self.assertTrue(result["lookup_error"])
                self.assertEqual(result["outcome"], "malformed-response")

    def test_valid_empty_arxiv_feed_is_definitive_absence(self):
        body = '<feed xmlns="http://www.w3.org/2005/Atom" />'
        with unittest.mock.patch.object(SERVER, "_http", return_value=(200, body)), unittest.mock.patch.object(SERVER, "_ads_token", return_value=""):
            result = SERVER.resolve_citation("1706.03762")
        self.assertEqual(result["outcome"], "not-found")
        self.assertNotIn("lookup_error", result)

    def test_secondary_registry_survives_malformed_primary(self):
        def response(url):
            if "crossref" in url:
                return 200, {"message": {"DOI": "10.1234/example", "title": 1}}
            return 200, {"data": {"attributes": {"doi": "10.1234/example", "titles": [{"title": "Example"}]}}}
        with unittest.mock.patch.object(SERVER, "_get_json", side_effect=response), unittest.mock.patch.object(SERVER, "_ads_token", return_value=""), unittest.mock.patch.object(SERVER, "_record_cache_put"), unittest.mock.patch.object(SERVER, "_alias_put"):
            self.assertTrue(SERVER.resolve_citation("10.1234/example")["resolved"])
