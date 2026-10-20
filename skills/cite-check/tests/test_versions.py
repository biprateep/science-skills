"""Finding 10: cache identity and version-specific evidence acquisition."""
import pathlib
import tempfile
import unittest
import unittest.mock

import test_evidence

SERVER = test_evidence.SERVER


class VersionTest(unittest.TestCase):
    def test_collision_resistant_cache_keys(self):
        pairs = [("doi:10.1234/a/b", "doi:10.1234/a_b"),
                 ("x" * 150 + "a", "x" * 150 + "b")]
        for first, second in pairs:
            self.assertNotEqual(SERVER._cache_key(first), SERVER._cache_key(second))
        with tempfile.TemporaryDirectory() as directory, unittest.mock.patch.object(SERVER, "CACHE_DIR", directory):
            for doi in ("10.1234/a/b", "10.1234/a_b"):
                SERVER._record_cache_put(SERVER._record(doi=doi, title=doi))
            self.assertEqual(SERVER._record_cache_get("doi:10.1234/a/b")["title"], "10.1234/a/b")

    def test_github_cff_and_readme_use_immutable_commit(self):
        sha = "a" * 40
        repo = {"full_name": "owner/project", "name": "project", "owner": {"login": "owner"},
                "default_branch": "main", "html_url": "https://github.com/owner/project"}
        urls = []
        def http(url, **kwargs):
            urls.append(url)
            return 200, 'title: Historical title\nauthors:\n  - name: Project authors\n'
        with unittest.mock.patch.object(SERVER, "_gh_json", side_effect=lambda url: (200, repo) if url.startswith("/repos") else (200, {})), unittest.mock.patch.object(SERVER, "_http", side_effect=http), unittest.mock.patch.object(SERVER, "_gh_api", return_value=(200, "old README " * 50)) as api:
            historical = SERVER._github_get("owner/project", ref=sha)
            historical["pinned_sha"] = sha
            SERVER._github_text(historical)
        self.assertTrue(all(f"/{sha}/CITATION." in url for url in urls))
        self.assertTrue(all(f"ref={sha}" in call.args[0] for call in api.call_args_list))

    def test_arxiv_versions_have_distinct_source_caches(self):
        with tempfile.TemporaryDirectory() as directory:
            source = pathlib.Path(directory) / "source.txt"
            source.write_text("Version one says the treatment is effective.")
            record = SERVER._record(registry="arxiv", arxiv="1706.03762", title="Example")
            def version_lookup(identifiers):
                version = identifiers[0]
                return {version: dict(record, arxiv_api_version=version)}
            with unittest.mock.patch.object(SERVER, "CACHE_DIR", directory), unittest.mock.patch.object(SERVER, "_full_record", return_value=record), unittest.mock.patch.object(SERVER, "_arxiv_lookup", side_effect=version_lookup):
                first = SERVER.fetch_text("arXiv:1706.03762v1", text_path=str(source))
                source.write_text("Version two says the treatment is ineffective.")
                second = SERVER.fetch_text("arXiv:1706.03762v2", text_path=str(source))
                self.assertEqual(first["id"], second["id"])
                self.assertNotEqual(first["cache_id"], second["cache_id"])
                self.assertEqual(SERVER._load_text_meta(first["cache_id"])["version"], "1706.03762v1")
                self.assertIn("Version one", pathlib.Path(first["path"]).read_text())

    def test_arxiv_version_never_falls_back_to_latest(self):
        record = SERVER._record(registry="arxiv", arxiv="1706.03762", abstract="latest abstract", pdf_urls=["https://example.org/latest.pdf"])
        record["arxiv_version"] = "1706.03762v1"
        with tempfile.TemporaryDirectory() as directory, unittest.mock.patch.object(SERVER, "CACHE_DIR", directory), unittest.mock.patch.object(SERVER, "_http", return_value=(404, "")) as http, unittest.mock.patch.object(SERVER, "_download_pdf", return_value=False) as download:
            text, basis, _ = SERVER._obtain_text(record, "versioned")
        self.assertEqual((text, basis), ("", "none"))
        self.assertIn("1706.03762v1", http.call_args.args[0])
        self.assertEqual(download.call_count, 1)
        self.assertIn("1706.03762v1", download.call_args.args[0])

    def test_exact_arxiv_version_metadata_is_required(self):
        record = SERVER._record(registry="arxiv", arxiv="1706.03762", title="Latest title")
        with unittest.mock.patch.object(SERVER, "_arxiv_lookup", return_value={}):
            with self.assertRaises(ValueError):
                SERVER._with_pin(record, "arxiv:1706.03762v999", None)
        with self.assertRaises(ValueError):
            SERVER._with_pin(record, "arxiv:1706.03762", "1706.03762")

    def test_atom_retains_version_for_exact_lookup(self):
        body = ('<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
                '<id>http://arxiv.org/abs/1706.03762v1</id><title>Historical title</title>'
                '</entry></feed>')
        with unittest.mock.patch.object(SERVER, "_http", return_value=(200, body)):
            found = SERVER._arxiv_lookup(["1706.03762v1"])
        self.assertEqual(found["1706.03762v1"]["arxiv_api_version"], "1706.03762v1")

    def test_wrong_version_response_cannot_supply_requested_evidence(self):
        record = SERVER._record(registry="arxiv", arxiv="1706.03762", title="Latest title")
        wrong = dict(record, arxiv_api_version="1706.03762v2")
        with unittest.mock.patch.object(SERVER, "_arxiv_lookup", return_value={"1706.03762v2": wrong}):
            with self.assertRaises(SERVER.RegistryLookupError):
                SERVER._with_pin(record, "arxiv:1706.03762v1", None)

    def test_verify_bib_uses_historical_metadata_and_rejects_missing_version(self):
        latest = SERVER._record(registry="arxiv", arxiv="1706.03762", title="Completely different latest title", authors=["Author, A"], year=2017)
        old = dict(latest, title="Historical title", arxiv_api_version="1706.03762v1")
        public = SERVER._public(latest, "arxiv:1706.03762", "arxiv")
        with tempfile.TemporaryDirectory() as directory:
            bib = pathlib.Path(directory) / "refs.bib"
            bib.write_text('@article{k,title={Historical title},author={Author, A},year={2017},eprint={1706.03762v1}}')
            with unittest.mock.patch.object(SERVER, "_resolve_many", return_value=[public]), unittest.mock.patch.object(SERVER, "_arxiv_lookup", return_value={"1706.03762v1": old}), unittest.mock.patch.object(SERVER, "_ads_token", return_value=""):
                report = SERVER.verify_bib(str(bib), search_unresolved=False)
            self.assertTrue(report["ok"], report)
            with unittest.mock.patch.object(SERVER, "_resolve_many", return_value=[public]), unittest.mock.patch.object(SERVER, "_arxiv_lookup", return_value={}), unittest.mock.patch.object(SERVER, "_ads_token", return_value=""):
                report = SERVER.verify_bib(str(bib), search_unresolved=False)
            self.assertFalse(report["ok"])
            self.assertEqual(report["entries"][0]["status"], "NOT_FOUND")

    def test_resolve_validates_version_and_preserves_work_identity(self):
        current = SERVER._record(registry="arxiv", arxiv="1706.03762", title="Latest title")
        old = dict(current, title="Historical title", arxiv_api_version="1706.03762v1")
        def lookup(identifiers):
            if identifiers == ["1706.03762"]:
                return {"1706.03762": current}
            return {"1706.03762v1": old} if identifiers == ["1706.03762v1"] else {}
        with tempfile.TemporaryDirectory() as directory, unittest.mock.patch.object(SERVER, "CACHE_DIR", directory), unittest.mock.patch.object(SERVER, "_ads_token", return_value=""), unittest.mock.patch.object(SERVER, "_arxiv_lookup", side_effect=lookup):
            result = SERVER.resolve_citation(["1706.03762v1", "1706.03762v999"])
            valid, absent = result["results"]
            self.assertEqual(valid["id"], "arXiv:1706.03762")
            self.assertEqual(valid["title"], "Historical title")
            self.assertEqual(valid["requested_version"], "1706.03762v1")
            self.assertFalse(absent["resolved"])
            self.assertEqual(absent["outcome"], "not-found")
            self.assertEqual(SERVER._record_cache_get(valid["id"])["title"], "Latest title")

    def test_exact_version_outage_is_not_absence(self):
        current = SERVER._record(registry="arxiv", arxiv="1706.03762", title="Latest title")
        def lookup(identifiers):
            if identifiers == ["1706.03762"]:
                return {"1706.03762": current}
            raise SERVER.RegistryLookupError("arxiv", "unavailable", 503)
        with unittest.mock.patch.object(SERVER, "_arxiv_lookup", side_effect=lookup), unittest.mock.patch.object(SERVER, "_ads_token", return_value=""), unittest.mock.patch.object(SERVER, "_record_cache_put"), unittest.mock.patch.object(SERVER, "_alias_put"):
            result = SERVER.resolve_citation("1706.03762v1")
        self.assertTrue(result["lookup_error"])
        self.assertEqual(result["outcome"], "unavailable")

    def test_official_export_cannot_silently_drop_version(self):
        record = SERVER._record(registry="arxiv", arxiv="1706.03762", title="Example")
        record["arxiv_version"] = "1706.03762v1"
        with unittest.mock.patch.object(SERVER, "_http", return_value=(200, '@misc{k,title={Example},eprint={1706.03762},url={https://arxiv.org/abs/1706.03762}}')):
            result = SERVER._official_bibtex(record)
        self.assertIsNone(result["bibtex"])
        self.assertIn("omits the requested version", " ".join(result["tried"]))
        with unittest.mock.patch.object(SERVER, "_http", return_value=(200, '@misc{k,title={Example},eprint={1706.03762v1},url={https://arxiv.org/abs/1706.03762v1}}')):
            result = SERVER._official_bibtex(record)
        self.assertIsNotNone(result["bibtex"])

    def test_missing_version_export_and_batch_return_structured_failure(self):
        record = SERVER._record(registry="arxiv", arxiv="1706.03762", title="Example")
        with tempfile.TemporaryDirectory() as directory:
            bib = pathlib.Path(directory) / "refs.bib"
            bib.write_text("% existing bibliography\n")
            before = bib.read_bytes()
            with unittest.mock.patch.object(SERVER, "_full_record", return_value=record), unittest.mock.patch.object(SERVER, "_arxiv_lookup", return_value={}):
                exported = SERVER.fetch_bibtex("arxiv:1706.03762v999")
                batch = SERVER.bib_add(str(bib), [{"identifier": "arxiv:1706.03762v999", "key": "absent"}])
            self.assertIsNone(exported["bibtex"])
            self.assertFalse(exported["resolved"])
            self.assertFalse(batch["ok"])
            self.assertEqual(bib.read_bytes(), before)
