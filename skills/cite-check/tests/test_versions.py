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
            with unittest.mock.patch.object(SERVER, "CACHE_DIR", directory), unittest.mock.patch.object(SERVER, "_full_record", return_value=record):
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
