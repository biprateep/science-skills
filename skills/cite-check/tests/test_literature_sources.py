"""Offline regressions for opt-in discovery without identity promotion."""

import contextlib
import copy
import email.message
import io
import json
import pathlib
import tempfile
from typing import Any
import unittest
import unittest.mock
import urllib.error
import urllib.parse
import urllib.request

import test_evidence

SERVER = test_evidence.SERVER
TITLE = "Fictional measurements of a quiet star"
PAPER_ID = "a" * 40
DOI = "10.1234/fictional"
PROVIDERS = ("semanticscholar", "pubmed", "dblp")


def fixtures() -> dict[str, Any]:
    """Return independent fictional payloads in the providers' public shapes."""
    return {
        "semanticscholar": {
            "data": [
                {
                    "paperId": PAPER_ID,
                    "title": TITLE,
                    "authors": [{"name": "Jane Example"}],
                    "year": 2020,
                    "venue": "Fictional Journal",
                    "externalIds": {"DOI": DOI, "ArXiv": "2001.01234"},
                }
            ]
        },
        "esearch": {"esearchresult": {"idlist": ["123456"]}},
        "pubmed": {
            "result": {
                "uids": ["123456"],
                "123456": {
                    "uid": "123456",
                    "title": TITLE,
                    "authors": [{"name": "Example J"}],
                    "pubdate": "2020 Jan",
                    "fulljournalname": "Fictional Journal",
                    "articleids": [{"idtype": "doi", "value": DOI}],
                },
            }
        },
        "dblp": {
            "result": {
                "hits": {
                    "@total": "1",
                    "hit": [
                        {
                            "info": {
                                "key": "journals/fictional/Example20",
                                "title": TITLE,
                                "authors": {"author": {"text": "Jane Example"}},
                                "year": "2020",
                                "venue": "Fictional Journal",
                                "ee": "https://doi.org/" + DOI,
                                "type": "Journal Articles",
                            }
                        }
                    ],
                }
            }
        },
    }


class Response(io.BytesIO):
    """A real readable response shape backed only by fixture bytes."""

    def __init__(self, payload: Any) -> None:
        super().__init__(json.dumps(payload).encode("utf-8"))
        self.status = 200


class LiteratureSourcesTest(unittest.TestCase):
    """Exercise public search with deterministic provider responses."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        self.payloads = fixtures()
        self.requests: list[tuple[str, dict[str, Any]]] = []
        for name, value in (("CACHE_DIR", str(self.root)), ("_host_last", {})):
            patch: Any = unittest.mock.patch.object(SERVER, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        self.get_json = unittest.mock.patch.object(
            SERVER, "_get_json", side_effect=self.provider_response
        ).start()
        self.addCleanup(unittest.mock.patch.stopall)
        self.key = unittest.mock.patch.object(
            SERVER, "key_value", return_value=(None, None)
        ).start()

    def provider_response(self, url: str, **options: Any) -> tuple[int, Any]:
        """Route only known discovery endpoints to independent fixture data."""
        self.requests.append((url, options))
        parsed = urllib.parse.urlparse(url)
        if parsed.hostname == "api.semanticscholar.org":
            name = "semanticscholar"
        elif parsed.hostname == "eutils.ncbi.nlm.nih.gov":
            name = "esearch" if "esearch" in parsed.path else "pubmed"
        elif parsed.hostname == "dblp.org":
            name = "dblp"
        else:
            raise AssertionError(f"Unexpected outbound endpoint: {url}")
        return 200, copy.deepcopy(self.payloads[name])

    def search(self, providers: list[str] | None = None, **kwargs: Any) -> Any:
        """Run public discovery with explicit provider selection by default."""
        return SERVER.search_citation(
            title=TITLE,
            registries=list(PROVIDERS) if providers is None else providers,
            **kwargs,
        )

    def row(self, provider: str) -> dict[str, Any]:
        """Fetch the one expected fictional provider candidate."""
        result = self.search([provider])
        self.assertEqual(result["errors"], {}, result)
        self.assertEqual(len(result["candidates"]), 1, result)
        return result["candidates"][0]

    def budget(self, **limits: Any) -> Any:
        """Install the existing shared controller for transport tests."""
        controller = SERVER._RequestBudget(
            SERVER._validated_budget(limits), lambda _usage: None
        )
        token = SERVER._request_budget.set(controller)
        self.addCleanup(SERVER._request_budget.reset, token)
        return controller

    def test_same_doi_across_providers_stays_separate_discovery(self) -> None:
        result = self.search()
        self.assertEqual(result["errors"], {}, result)
        self.assertEqual(len(result["candidates"]), 3, result)
        expected = {
            "semanticscholar": "semanticscholar:" + PAPER_ID,
            "pubmed": "pmid:123456",
            "dblp": "dblp:journals/fictional/Example20",
        }
        for row in result["candidates"]:
            provider = row["provenance"]["source"]
            self.assertEqual(row["id"], expected[provider])
            self.assertTrue(row["discovery_only"])
            self.assertEqual(row["verification_status"], "unverified")
            self.assertEqual(row["ids"], {})
            self.assertIn("doi:" + DOI, row["suggested_ids"])
            self.assertTrue(row["provenance"]["record_id"])
            self.assertTrue(row["provenance"]["url"].startswith("https://"))
            self.assertTrue(row["next_action"])
            self.assertNotEqual(row.get("status"), "VERIFIED")

    def test_native_ids_cannot_resolve_or_export_official_bibtex(self) -> None:
        result = self.search()
        with unittest.mock.patch.object(SERVER, "_http") as http:
            for row in result["candidates"]:
                with self.subTest(identifier=row["id"]):
                    self.assertEqual(SERVER._classify(row["id"])[0], "unknown")
                    resolved = SERVER.resolve_citation(row["id"])
                    self.assertFalse(resolved["resolved"], resolved)
                    exported = SERVER.fetch_bibtex(row["id"])
                    self.assertFalse(exported.get("bibtex"), exported)
        http.assert_not_called()

    def test_discovery_never_writes_authority_records_or_aliases(self) -> None:
        with (
            unittest.mock.patch.object(SERVER, "_record_cache_put") as records,
            unittest.mock.patch.object(SERVER, "_alias_put") as aliases,
            unittest.mock.patch.object(
                SERVER, "_merge_candidates", wraps=SERVER._merge_candidates
            ) as merge,
        ):
            result = self.search()
        self.assertEqual(len(result["candidates"]), 3)
        records.assert_not_called()
        aliases.assert_not_called()
        for call in merge.call_args_list:
            self.assertEqual(call.args[0], [])
        self.assertEqual(list(self.root.rglob("*.json")), [])

    def test_defaults_leave_new_sources_disabled(self) -> None:
        with unittest.mock.patch.object(
            SERVER, "_ads_token", return_value=None
        ):
            patches = [
                unittest.mock.patch.object(
                    SERVER, "_" + name + "_search", return_value=[]
                )
                for name in ("arxiv", "crossref", "openalex", "inspire")
            ]
            for patch in patches:
                patch.start()
                self.addCleanup(patch.stop)
            result = SERVER.search_citation(title=TITLE)
        self.assertFalse(set(PROVIDERS) & set(result["registries"]))
        self.get_json.assert_not_called()

    def test_invalid_provider_and_result_limits_fail_before_io(self) -> None:
        options: dict[str, Any]
        for options in (
            {"registries": []},
            {"registries": ["imaginary"]},
            {"registries": "pubmed"},
            {"registries": [7]},
            {"max_results": 0},
            {"max_results": 101},
            {"max_results": True},
            {"max_results": 2.5},
        ):
            with self.subTest(options=options):
                result = SERVER.search_citation(title=TITLE, **options)
                self.assertTrue(result.get("error"), result)
        self.get_json.assert_not_called()

    def test_invalid_options_are_not_bypassed_by_direct_identifier(
        self,
    ) -> None:
        with unittest.mock.patch.object(SERVER, "resolve_citation") as resolve:
            result = SERVER.search_citation(query=DOI, registries=[])
        self.assertTrue(result.get("error"), result)
        resolve.assert_not_called()

    def test_native_only_rows_remain_visible_without_export_claim(self) -> None:
        self.payloads["semanticscholar"]["data"][0]["externalIds"] = {}
        self.payloads["pubmed"]["result"]["123456"]["articleids"] = []
        del self.payloads["dblp"]["result"]["hits"]["hit"][0]["info"]["ee"]
        result = self.search()
        self.assertEqual(len(result["candidates"]), 3, result)
        for row in result["candidates"]:
            self.assertEqual(row["suggested_ids"], [])
            self.assertTrue(row["discovery_only"])
            self.assertTrue(row["next_action"])

    def test_semanticscholar_uses_bounded_get_and_optional_key(self) -> None:
        self.key.return_value = ("fixture-secret", "fixture")
        row = self.row("semanticscholar")
        self.assertIn("arxiv:2001.01234", row["suggested_ids"])
        url, options = self.requests[0]
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        self.assertEqual(query["limit"], ["10"])
        self.assertEqual(query["query"], [TITLE])
        fields = set(query["fields"][0].split(","))
        self.assertNotIn("abstract", fields)
        self.assertEqual(options["headers"]["x-api-key"], "fixture-secret")
        self.assertNotIn("fixture-secret", url)
        self.assertNotIn("fixture-secret", json.dumps(row))

    def test_semanticscholar_without_key_is_public(self) -> None:
        self.row("semanticscholar")
        self.assertNotIn("x-api-key", self.requests[0][1].get("headers") or {})

    def test_semanticscholar_key_cli_reports_status_without_secret(
        self,
    ) -> None:
        self.key.return_value = ("fixture-secret", "fixture")
        for status, exit_code, message in (
            (200, 0, "accepted"),
            (401, 1, "rejected"),
            (429, 1, "HTTP 429"),
        ):
            with self.subTest(status=status):
                output = io.StringIO()
                with (
                    unittest.mock.patch.object(
                        SERVER, "_http", return_value=(status, "fixture-secret")
                    ) as http,
                    contextlib.redirect_stdout(output),
                    self.assertRaises(SystemExit) as stopped,
                ):
                    SERVER._run_keys(["test", "semanticscholar"])
                self.assertEqual(stopped.exception.code, exit_code)
                self.assertIn(message, output.getvalue())
                self.assertNotIn("fixture-secret", output.getvalue())
                self.assertEqual(
                    http.call_args.kwargs["headers"]["x-api-key"],
                    "fixture-secret",
                )
                self.assertFalse(http.call_args.kwargs["cache"])

    def test_semanticscholar_key_cli_missing_key_makes_no_request(self) -> None:
        with (
            unittest.mock.patch.object(SERVER, "_http") as http,
            self.assertRaises(SystemExit) as stopped,
        ):
            SERVER._run_keys(["test", "semanticscholar"])
        self.assertIn(
            "no semanticscholar token configured", str(stopped.exception)
        )
        http.assert_not_called()

    def test_pubmed_batches_summary_and_checks_membership(self) -> None:
        result = self.payloads["pubmed"]["result"]
        result["uids"].append("789012")
        result["789012"] = dict(result["123456"], uid="789012")
        self.payloads["esearch"]["esearchresult"]["idlist"].append("789012")
        found = self.search(["pubmed"])
        self.assertEqual(len(found["candidates"]), 2, found)
        self.assertEqual(len(self.requests), 2)
        search = urllib.parse.parse_qs(
            urllib.parse.urlparse(self.requests[0][0]).query
        )
        summary = urllib.parse.parse_qs(
            urllib.parse.urlparse(self.requests[1][0]).query
        )
        self.assertEqual(search["db"], ["pubmed"])
        self.assertEqual(search["retmax"], ["10"])
        self.assertEqual(set(summary["id"][0].split(",")), {"123456", "789012"})
        self.assertNotIn("api_key", search)
        self.assertNotIn("api_key", summary)

    def test_pubmed_wrong_summary_membership_is_unavailable(self) -> None:
        for mutation in ("uids", "uid", "missing"):
            with self.subTest(mutation=mutation):
                self.payloads = fixtures()
                result = self.payloads["pubmed"]["result"]
                if mutation == "uids":
                    result["uids"] = ["999999"]
                elif mutation == "uid":
                    result["123456"]["uid"] = "999999"
                else:
                    del result["123456"]
                found = self.search(["pubmed"])
                self.assertTrue(found["errors"].get("pubmed"), found)
                self.assertEqual(found["candidates"], [])

    def test_dblp_uses_bounded_publication_search(self) -> None:
        self.row("dblp")
        url = urllib.parse.urlparse(self.requests[0][0])
        query = urllib.parse.parse_qs(url.query)
        self.assertEqual(url.path, "/search/publ/api")
        self.assertEqual(query["format"], ["json"])
        self.assertEqual(query["h"], ["10"])
        self.assertEqual(query["c"], ["0"])

    def test_dblp_multiple_authors_preserve_provider_names(self) -> None:
        info = self.payloads["dblp"]["result"]["hits"]["hit"][0]["info"]
        info["authors"]["author"] = [
            {"text": "Jane Example"},
            {"text": "John Fiction"},
        ]
        row = self.row("dblp")
        self.assertEqual(row["authors"], ["Jane Example", "John Fiction"])

    def test_successful_empty_results_are_distinct_from_unavailability(
        self,
    ) -> None:
        self.payloads = {
            "semanticscholar": {"data": []},
            "esearch": {"esearchresult": {"idlist": []}},
            "dblp": {"result": {"hits": {"@total": "0"}}},
        }
        result = self.search()
        self.assertEqual(result["errors"], {}, result)
        self.assertEqual(result["candidates"], [])
        self.assertEqual(len(self.requests), 3)

    def test_http_errors_do_not_become_no_match_or_sink_other_sources(
        self,
    ) -> None:
        for status in (401, 404, 429, 500):
            with self.subTest(status=status):

                def response(
                    url: str, response_status: int = status, **kwargs: Any
                ) -> tuple[int, Any]:
                    if "semanticscholar" in url:
                        return response_status, None
                    return self.provider_response(url, **kwargs)

                self.get_json.side_effect = response
                result = self.search()
                self.assertTrue(result["errors"].get("semanticscholar"), result)
                self.assertEqual(len(result["candidates"]), 2, result)

    def test_malformed_provider_payloads_fail_closed(self) -> None:
        payload: Any
        for provider in PROVIDERS:
            for payload in (None, [], {}, {"error": "temporary failure"}):
                with self.subTest(provider=provider, payload=payload):
                    self.payloads = fixtures()
                    key = "esearch" if provider == "pubmed" else provider
                    self.payloads[key] = payload
                    result = self.search([provider])
                    self.assertTrue(result["errors"].get(provider), result)
                    self.assertEqual(result["candidates"], [])

    def test_invalid_native_ids_are_never_exposed_as_candidates(self) -> None:
        for provider in PROVIDERS:
            with self.subTest(provider=provider):
                self.payloads = fixtures()
                if provider == "semanticscholar":
                    self.payloads[provider]["data"][0]["paperId"] = "bad/id"
                elif provider == "pubmed":
                    self.payloads["esearch"]["esearchresult"]["idlist"] = [
                        "../123"
                    ]
                else:
                    self.payloads[provider]["result"]["hits"]["hit"][0]["info"][
                        "key"
                    ] = "../../unsafe"
                result = self.search([provider])
                self.assertTrue(result["errors"].get(provider), result)
                self.assertEqual(result["candidates"], [])

    def test_invalid_suggested_ids_cannot_enter_official_aliases(self) -> None:
        self.payloads["semanticscholar"]["data"][0]["externalIds"] = {
            "DOI": "https://evil.example/10.1234/fake",
            "ArXiv": "wrong",
        }
        result = self.search(["semanticscholar"])
        self.assertTrue(result["errors"].get("semanticscholar"), result)
        self.assertEqual(result["candidates"], [])

    def test_duplicate_native_records_collapse_without_crossprovider_merge(
        self,
    ) -> None:
        data = self.payloads["semanticscholar"]["data"]
        data.append(copy.deepcopy(data[0]))
        self.row("semanticscholar")

    def test_conflicting_native_records_refuse_ambiguous_provider_output(
        self,
    ) -> None:
        data = self.payloads["semanticscholar"]["data"]
        data.append(dict(data[0], title="A completely different work"))
        result = self.search()
        self.assertTrue(result["errors"].get("semanticscholar"), result)
        self.assertEqual(len(result["candidates"]), 2, result)

    def test_max_results_bounds_public_return_without_unverified_promotion(
        self,
    ) -> None:
        result = self.search(max_results=1)
        self.assertEqual(len(result["candidates"]), 1, result)
        self.assertTrue(result["candidates"][0]["discovery_only"])

    def test_search_budget_is_shared_across_new_provider_workers(self) -> None:
        controller = self.budget(max_searches=1)
        result = self.search()
        self.assertEqual(controller.usage()["searches"], 1)
        self.assertEqual(len(result["errors"]), 2, result)
        self.assertLessEqual(len(result["candidates"]), 1)

    def test_zero_deadline_stops_discovery_before_network(self) -> None:
        self.budget(max_seconds=0)
        result = self.search()
        self.get_json.assert_not_called()
        self.assertEqual(set(result["errors"]), set(PROVIDERS))

    def test_http_cache_reuse_consumes_no_additional_request(self) -> None:
        controller = self.budget(max_requests=1, max_cost_usd=None)
        opener = unittest.mock.Mock()
        opener.open.return_value = Response(self.payloads["semanticscholar"])
        with (
            unittest.mock.patch.object(SERVER, "_get_json", self.real_get_json),
            unittest.mock.patch.object(
                SERVER.urllib.request, "build_opener", return_value=opener
            ),
            unittest.mock.patch.object(SERVER, "_throttle"),
        ):
            first = self.search(["semanticscholar"])
            second = self.search(["semanticscholar"])
        self.assertEqual(first["errors"], {}, first)
        self.assertEqual(second["errors"], {}, second)
        self.assertEqual(first["candidates"], second["candidates"])
        self.assertEqual(opener.open.call_count, 1)
        self.assertEqual(controller.usage()["requests"], 1)
        self.assertEqual(controller.usage()["http_cache_hits"], 1)

    def test_retry_after_throttling_cannot_exceed_request_budget(self) -> None:
        controller = self.budget(max_requests=1, max_cost_usd=None)
        opener = unittest.mock.Mock()
        opener.open.side_effect = urllib.error.HTTPError(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            429,
            "rate limit",
            email.message.Message(),
            io.BytesIO(b"retry"),
        )
        with (
            unittest.mock.patch.object(SERVER, "_get_json", self.real_get_json),
            unittest.mock.patch.object(
                SERVER.urllib.request, "build_opener", return_value=opener
            ),
            unittest.mock.patch.object(SERVER, "_throttle"),
            unittest.mock.patch.object(SERVER, "_budget_sleep"),
        ):
            result = self.search(["semanticscholar"])
        self.assertEqual(opener.open.call_count, 1)
        self.assertEqual(controller.usage()["requests"], 1)
        self.assertTrue(result["errors"].get("semanticscholar"), result)
        self.assertEqual(result["candidates"], [])

    def test_api_key_requests_never_follow_redirects_in_either_budget_mode(
        self,
    ) -> None:
        original = "https://api.semanticscholar.org/graph/v1/paper/search"
        for active_budget in (False, True):
            for destination in (
                "https://unrelated.example/collect",
                "http://api.semanticscholar.org/collect",
            ):
                with self.subTest(budget=active_budget, target=destination):
                    controller = (
                        SERVER._RequestBudget(
                            SERVER._validated_budget({"max_cost_usd": None}),
                            lambda _usage: None,
                        )
                        if active_budget
                        else None
                    )
                    token = SERVER._request_budget.set(controller)
                    headers = email.message.Message()
                    headers["Location"] = destination
                    opener = unittest.mock.Mock()
                    opener.open.side_effect = urllib.error.HTTPError(
                        original, 302, "redirect", headers, io.BytesIO(b"")
                    )
                    try:
                        with (
                            unittest.mock.patch.object(
                                SERVER.urllib.request,
                                "build_opener",
                                return_value=opener,
                            ) as build,
                            unittest.mock.patch.object(
                                SERVER.urllib.request, "urlopen"
                            ) as implicit,
                            unittest.mock.patch.object(SERVER, "_throttle"),
                        ):
                            status, _ = SERVER._http(
                                original,
                                headers={"x-api-key": "fixture-key"},
                                cache=False,
                            )
                        self.assertEqual(status, 302)
                        self.assertEqual(opener.open.call_count, 1)
                        implicit.assert_not_called()
                        request = opener.open.call_args.args[0]
                        self.assertEqual(request.full_url, original)
                        self.assertEqual(
                            dict(
                                (name.lower(), value)
                                for name, value in request.header_items()
                            )["x-api-key"],
                            "fixture-key",
                        )
                        self.assertIsNone(
                            build.call_args.args[0].redirect_request(
                                request,
                                None,
                                302,
                                "redirect",
                                headers,
                                destination,
                            )
                        )
                        if controller is not None:
                            self.assertEqual(controller.usage()["requests"], 1)
                    finally:
                        SERVER._request_budget.reset(token)

    def test_malformed_api_key_is_rejected_without_network_or_secret_echo(
        self,
    ) -> None:
        secret = "fixture\nsecret-key"
        self.key.return_value = (secret, "fixture")
        result = self.search(["semanticscholar"])
        self.assertTrue(result["errors"].get("semanticscholar"), result)
        self.assertNotIn("secret-key", json.dumps(result))
        self.get_json.assert_not_called()

    def test_pubmed_second_http_request_needs_a_fresh_budget_grant(
        self,
    ) -> None:
        controller = self.budget(max_requests=1, max_cost_usd=None)
        opener = unittest.mock.Mock()
        opener.open.return_value = Response(self.payloads["esearch"])
        with (
            unittest.mock.patch.object(SERVER, "_get_json", self.real_get_json),
            unittest.mock.patch.object(
                SERVER.urllib.request, "build_opener", return_value=opener
            ),
            unittest.mock.patch.object(SERVER, "_throttle"),
        ):
            result = self.search(["pubmed"])
        self.assertEqual(opener.open.call_count, 1)
        self.assertEqual(controller.usage()["requests"], 1)
        self.assertTrue(result["errors"].get("pubmed"), result)
        self.assertEqual(result["candidates"], [])

    def test_reordered_complete_pubmed_summary_is_valid(self) -> None:
        result = self.payloads["pubmed"]["result"]
        result["uids"] = ["789012", "123456"]
        result["789012"] = dict(result["123456"], uid="789012")
        self.payloads["esearch"]["esearchresult"]["idlist"].append("789012")
        found = self.search(["pubmed"])
        self.assertEqual(found["errors"], {}, found)
        self.assertEqual(
            {row["id"] for row in found["candidates"]},
            {"pmid:123456", "pmid:789012"},
        )

    def test_discovery_metadata_cannot_splice_into_official_candidate(
        self,
    ) -> None:
        official = SERVER._record(
            registry="crossref",
            doi=DOI,
            title="Official unrelated title",
            authors=["Official Author"],
            year=1990,
            abstract="Official text",
        )
        self.payloads["semanticscholar"]["data"][0]["abstract"] = (
            "An unrequested abstract must not become official evidence."
        )
        with unittest.mock.patch.object(
            SERVER, "_crossref_search", return_value=[official]
        ):
            result = self.search(["crossref", "semanticscholar"])
        self.assertEqual(len(result["candidates"]), 2, result)
        verified_source = next(
            row for row in result["candidates"] if row["id"] == "doi:" + DOI
        )
        self.assertEqual(verified_source["title"], "Official unrelated title")
        self.assertEqual(verified_source["authors"], ["Official Author"])
        self.assertEqual(verified_source["year"], 1990)
        cached = SERVER._record_cache_get("doi:" + DOI)
        self.assertEqual(cached["abstract"], "Official text")
        self.assertEqual(cached["title"], "Official unrelated title")

    def test_oversized_provider_batches_are_rejected(self) -> None:
        for provider in PROVIDERS:
            with self.subTest(provider=provider):
                self.payloads = fixtures()
                if provider == "semanticscholar":
                    self.payloads[provider]["data"] *= 11
                elif provider == "pubmed":
                    self.payloads["esearch"]["esearchresult"]["idlist"] *= 11
                else:
                    self.payloads[provider]["result"]["hits"]["hit"] *= 11
                result = self.search([provider])
                self.assertTrue(result["errors"].get(provider), result)
                self.assertEqual(result["candidates"], [])

    def test_wrong_nested_metadata_types_are_unavailable(self) -> None:
        for provider in PROVIDERS:
            for field, value in (("title", 12), ("authors", 12)):
                with self.subTest(provider=provider, field=field):
                    self.payloads = fixtures()
                    if provider == "semanticscholar":
                        row = self.payloads[provider]["data"][0]
                    elif provider == "pubmed":
                        row = self.payloads[provider]["result"]["123456"]
                    else:
                        row = self.payloads[provider]["result"]["hits"]["hit"][
                            0
                        ]["info"]
                    row[field] = value
                    result = self.search([provider])
                    self.assertTrue(result["errors"].get(provider), result)
                    self.assertEqual(result["candidates"], [])

    def test_reported_result_counts_cannot_contradict_returned_rows(
        self,
    ) -> None:
        for provider, payload in (
            ("semanticscholar", {"total": 3, "data": []}),
            (
                "semanticscholar",
                {
                    "total": 3,
                    "data": fixtures()["semanticscholar"]["data"],
                },
            ),
            ("pubmed", {"esearchresult": {"count": "3", "idlist": []}}),
            (
                "pubmed",
                {
                    "esearchresult": {
                        "count": "3",
                        "idlist": ["123456"],
                    }
                },
            ),
            (
                "dblp",
                {
                    "result": {
                        "hits": {
                            "@total": "1",
                            "@sent": "0",
                            "hit": fixtures()["dblp"]["result"]["hits"]["hit"],
                        }
                    }
                },
            ),
        ):
            with self.subTest(provider=provider):
                self.payloads = fixtures()
                key = "esearch" if provider == "pubmed" else provider
                self.payloads[key] = payload
                result = self.search([provider])
                self.assertTrue(result["errors"].get(provider), result)
                self.assertEqual(result["candidates"], [])

    def test_falsey_wrong_container_types_are_not_missing_metadata(
        self,
    ) -> None:
        value: Any
        for provider in ("semanticscholar", "dblp"):
            for value in ([], False, 0):
                with self.subTest(provider=provider, value=value):
                    self.payloads = fixtures()
                    if provider == "semanticscholar":
                        self.payloads[provider]["data"][0]["externalIds"] = (
                            value
                        )
                    else:
                        self.payloads[provider]["result"]["hits"]["hit"][0][
                            "info"
                        ]["authors"] = value
                    result = self.search([provider])
                    self.assertTrue(result["errors"].get(provider), result)
                    self.assertEqual(result["candidates"], [])

    def test_falsey_invalid_aliases_are_not_silently_discarded(self) -> None:
        value: Any
        for name in ("DOI", "ArXiv"):
            for value in (False, 0, []):
                with self.subTest(name=name, value=value):
                    self.payloads = fixtures()
                    self.payloads["semanticscholar"]["data"][0]["externalIds"][
                        name
                    ] = value
                    result = self.search(["semanticscholar"])
                    self.assertTrue(
                        result["errors"].get("semanticscholar"), result
                    )
                    self.assertEqual(result["candidates"], [])

    def test_declared_public_hosts_fit_zero_estimated_service_fee_budget(
        self,
    ) -> None:
        controller = self.budget(max_requests=3)
        opener = unittest.mock.Mock()
        opener.open.side_effect = lambda *_args, **_kwargs: Response({})
        with unittest.mock.patch.object(
            SERVER.urllib.request, "build_opener", return_value=opener
        ):
            for url in (
                "https://api.semanticscholar.org/graph/v1/paper/search",
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                "https://dblp.org/search/publ/api",
            ):
                with SERVER._budget_open(urllib.request.Request(url), 30):
                    pass
        self.assertEqual(controller.usage()["requests"], 3)
        self.assertEqual(controller.usage()["unknown_price_requests"], 0)
        self.assertEqual(controller.usage()["estimated_service_cost_usd"], 0.0)

    def test_unknown_host_still_refused_by_zero_cost_cap(self) -> None:
        self.budget(max_requests=3)
        with unittest.mock.patch.object(
            SERVER.urllib.request, "build_opener"
        ) as build:
            with self.assertRaises(SERVER.BudgetExhaustedError):
                SERVER._budget_open(
                    urllib.request.Request("https://unknown.example/work"), 30
                )
        build.return_value.open.assert_not_called()

    real_get_json = staticmethod(SERVER._get_json)

    def test_html_success_response_is_provider_unavailable(self) -> None:
        with (
            unittest.mock.patch.object(SERVER, "_get_json", self.real_get_json),
            unittest.mock.patch.object(
                SERVER,
                "_http",
                return_value=(200, "<html>upstream error</html>"),
            ),
        ):
            result = self.search()
        self.assertEqual(set(result["errors"]), set(PROVIDERS))
        self.assertEqual(result["candidates"], [])


if __name__ == "__main__":
    unittest.main()
