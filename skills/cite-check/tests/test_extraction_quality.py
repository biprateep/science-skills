"""Bounded acquisition and explicit extraction quality never certify absence."""

import email.message
import hashlib
import importlib
import io
import json
import pathlib
import tempfile
from typing import Any
import unittest
import unittest.mock
import urllib.error

import test_evidence

SERVER = test_evidence.SERVER
ACQUISITION = importlib.import_module("cite_check_engine.acquisition")
TRANSPORT = importlib.import_module("cite_check_engine.transport")
PERSISTENCE = importlib.import_module("cite_check_engine.persistence")
CONFIG = importlib.import_module("cite_check_engine.config")
DOI = "doi:10.1234/quality-fixture"
PDF_URL = "https://arxiv.org/pdf/2001.01234"
GOOD_TEXT = (
    "The measurement rises by ten percent. We compare independent observations "
    "with a calibrated reference detector and report the measured uncertainty. "
    "The control experiment uses a separate instrument with the same exposure "
    "time. Its background remains stable throughout the observation. These "
    "results describe the sampled objects and do not establish a universal "
    "relationship. A second analysis tests whether the temperature gradient "
    "changes the inferred rate. The fitted coefficient remains positive when "
    "the background correction is varied within the measured uncertainty. "
    "We exclude saturated pixels before calculating the median intensity. "
    "All quoted intervals represent the central distribution of the retained "
    "samples. A larger survey would be needed to determine population trends."
)


class StreamingResponse(io.BytesIO):
    """Track bounded reads and optional declared length without real sockets."""

    def __init__(
        self,
        payload: bytes,
        length: str | None = None,
        fail_after: int | None = None,
    ) -> None:
        super().__init__(payload)
        self.status = 200
        self.headers = email.message.Message()
        if length is not None:
            self.headers["Content-Length"] = length
        self.read_sizes: list[int | None] = []
        self.bytes_read = 0
        self.fail_after = fail_after

    def read(self, size: int | None = -1) -> bytes:
        """Reject unbounded access and optionally interrupt a partial stream."""
        self.read_sizes.append(size)
        if size is None or size < 0:
            raise AssertionError("download attempted an unbounded read")
        if self.fail_after is not None and self.bytes_read >= self.fail_after:
            raise OSError("fixture interrupted stream")
        chunk = super().read(min(size, 7))
        self.bytes_read += len(chunk)
        return chunk

    def read1(self, size: int | None = -1) -> bytes:
        """Use the same accounting for buffered budget-aware reads."""
        return self.read(size)


class ExtractionFixture(unittest.TestCase):
    """Create isolated cache, original files and identity lookup fixtures."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        self.cache = self.root / "cache"
        self.original = self.root / "original.txt"
        self.original.write_text(GOOD_TEXT, encoding="utf-8")
        self.record = SERVER._record(
            registry="crossref",
            doi=DOI.removeprefix("doi:"),
            title="Fictional quality experiment",
            authors=["Jane Example"],
            year=2020,
        )
        for name, value in (("CACHE_DIR", str(self.cache)), ("_host_last", {})):
            patch: Any = unittest.mock.patch.object(SERVER, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        for name, options in (
            ("_full_record", {"return_value": self.record}),
            ("_with_pin", {"side_effect": lambda value, *_: value}),
            ("_user_agent", {"return_value": "offline-quality-fixture"}),
            ("_throttle", {}),
        ):
            patch = unittest.mock.patch.object(SERVER, name, **options)
            patch.start()
            self.addCleanup(patch.stop)

        network = unittest.mock.patch.object(
            TRANSPORT.urllib.request,
            "build_opener",
            side_effect=AssertionError("unexpected real HTTP acquisition"),
        )
        network.start()
        self.addCleanup(network.stop)

    def fetch(self, text: str | None = None, **options: Any) -> dict[str, Any]:
        """Fetch one local source through the public cache publication path."""
        if text is not None:
            self.original.write_text(text, encoding="utf-8")
        return SERVER.fetch_text(DOI, text_path=str(self.original), **options)

    def budget(self, **limits: Any) -> Any:
        """Attach the existing shared request/deadline controller."""
        controller = SERVER._RequestBudget(
            SERVER._validated_budget(limits), lambda _usage: None
        )
        token = SERVER._request_budget.set(controller)
        self.addCleanup(SERVER._request_budget.reset, token)
        return controller


class BoundedDownloadsTest(ExtractionFixture):
    """Check byte admissions before buffered response data can become a file."""

    def test_pdf_with_no_content_length_stops_at_cap_without_artifact(
        self,
    ) -> None:
        destination = self.root / "paper.pdf"
        response = StreamingResponse(b"%PDF-1.7\n" + b"x" * 100)
        with (
            unittest.mock.patch.object(CONFIG, "MAX_PDF_BYTES", 24),
            unittest.mock.patch.object(
                TRANSPORT, "_budget_open", return_value=response
            ),
        ):
            self.assertFalse(
                ACQUISITION._download_pdf(PDF_URL, str(destination))
            )
        self.assertFalse(destination.exists())
        self.assertLessEqual(response.bytes_read, 25)
        self.assertTrue(response.closed)
        self.assertEqual(list(self.root.glob("*.part")), [])

    def test_declared_oversize_is_refused_before_body_read(self) -> None:
        response = StreamingResponse(b"%PDF-1.7\nbody", length="1000000")
        destination = self.root / "paper.pdf"
        with (
            unittest.mock.patch.object(CONFIG, "MAX_PDF_BYTES", 24),
            unittest.mock.patch.object(
                TRANSPORT, "_budget_open", return_value=response
            ),
        ):
            self.assertFalse(
                ACQUISITION._download_pdf(PDF_URL, str(destination))
            )
        self.assertEqual(response.bytes_read, 0)
        self.assertFalse(destination.exists())
        self.assertTrue(response.closed)

    def test_small_declared_length_cannot_bypass_actual_body_bound(
        self,
    ) -> None:
        response = StreamingResponse(b"%PDF-1.7\n" + b"x" * 100, length="10")
        with (
            unittest.mock.patch.object(CONFIG, "MAX_PDF_BYTES", 24),
            unittest.mock.patch.object(
                TRANSPORT, "_budget_open", return_value=response
            ),
        ):
            self.assertFalse(
                ACQUISITION._download_pdf(PDF_URL, str(self.root / "a.pdf"))
            )
        self.assertLessEqual(response.bytes_read, 25)

    def test_valid_small_download_is_atomically_published(self) -> None:
        payload = b"%PDF-1.7\nfixture\n%%EOF"
        response = StreamingResponse(payload)
        destination = self.root / "paper.pdf"
        with unittest.mock.patch.object(
            TRANSPORT, "_budget_open", return_value=response
        ):
            self.assertTrue(
                ACQUISITION._download_pdf(PDF_URL, str(destination))
            )
        self.assertEqual(destination.read_bytes(), payload)
        self.assertTrue(response.closed)
        self.assertTrue(
            all(size is not None and size > 0 for size in response.read_sizes)
        )

    def test_interrupted_replacement_preserves_previous_pdf(self) -> None:
        destination = self.root / "paper.pdf"
        previous = b"%PDF-1.7\nprevious verified download\n%%EOF"
        destination.write_bytes(previous)

        def opened(*_args: Any, **_kwargs: Any) -> StreamingResponse:
            return StreamingResponse(b"%PDF-1.7\nreplacement", fail_after=7)

        with (
            unittest.mock.patch.object(
                TRANSPORT, "_budget_open", side_effect=opened
            ),
            unittest.mock.patch.object(SERVER, "_budget_sleep"),
        ):
            self.assertFalse(
                ACQUISITION._download_pdf(PDF_URL, str(destination))
            )
        self.assertEqual(destination.read_bytes(), previous)
        self.assertEqual(list(self.root.glob("*.part")), [])

    def test_html_body_cannot_be_published_as_pdf(self) -> None:
        response = StreamingResponse(b"<html>upstream failure</html>")
        destination = self.root / "paper.pdf"
        with unittest.mock.patch.object(
            TRANSPORT, "_budget_open", return_value=response
        ):
            self.assertFalse(
                ACQUISITION._download_pdf(PDF_URL, str(destination))
            )
        self.assertFalse(destination.exists())

    def test_http_cached_body_obeys_new_smaller_limit(self) -> None:
        url = "https://arxiv.org/html/2001.01234"
        response = StreamingResponse(b"x" * 100)
        with unittest.mock.patch.object(
            TRANSPORT, "_budget_open", return_value=response
        ):
            self.assertEqual(TRANSPORT._http(url, max_bytes=200)[0], 200)
        replacement = StreamingResponse(b"x" * 100)
        with unittest.mock.patch.object(
            TRANSPORT, "_budget_open", return_value=replacement
        ):
            with self.assertRaises(RuntimeError):
                TRANSPORT._http(url, max_bytes=10)
        self.assertLessEqual(replacement.bytes_read, 11)

    def test_error_response_body_obeys_same_limit(self) -> None:
        response = StreamingResponse(b"x" * 100)
        error = urllib.error.HTTPError(
            PDF_URL, 404, "missing", email.message.Message(), response
        )
        with unittest.mock.patch.object(
            TRANSPORT, "_budget_open", side_effect=error
        ):
            with self.assertRaises(RuntimeError):
                TRANSPORT._http(PDF_URL, max_bytes=24, retries=1)
        self.assertLessEqual(response.bytes_read, 25)
        self.assertTrue(response.closed)

    def test_budgeted_download_still_counts_request_and_enforces_byte_cap(
        self,
    ) -> None:
        controller = self.budget(max_requests=1)
        response = StreamingResponse(b"%PDF-1.7\n" + b"x" * 100)
        opener = unittest.mock.Mock()
        opener.open.return_value = response
        with (
            unittest.mock.patch.object(CONFIG, "MAX_PDF_BYTES", 24),
            unittest.mock.patch.object(
                TRANSPORT.urllib.request, "build_opener", return_value=opener
            ),
        ):
            self.assertFalse(
                ACQUISITION._download_pdf(PDF_URL, str(self.root / "a.pdf"))
            )
        self.assertEqual(controller.usage()["requests"], 1)
        self.assertEqual(opener.open.call_count, 1)
        self.assertLessEqual(response.bytes_read, 25)

    def test_malformed_length_headers_never_bypass_actual_byte_limit(
        self,
    ) -> None:
        for declared in ("²", "-1", "1, 2", "9" * 5000):
            with self.subTest(declared=declared[:20]):
                response = StreamingResponse(b"x" * 100, length=declared)
                with unittest.mock.patch.object(
                    TRANSPORT, "_budget_open", return_value=response
                ):
                    with self.assertRaises(RuntimeError):
                        TRANSPORT._http(
                            PDF_URL, cache=False, max_bytes=24, retries=1
                        )
                self.assertLessEqual(response.bytes_read, 25)
                self.assertTrue(response.closed)

    def test_nonobject_http_cache_is_ignored_and_replaced(self) -> None:
        response = StreamingResponse(b"first response")
        with unittest.mock.patch.object(
            TRANSPORT, "_budget_open", return_value=response
        ):
            TRANSPORT._http(PDF_URL)
        cache_files = list((self.cache / "http").glob("*.json"))
        self.assertEqual(len(cache_files), 1)
        cache_files[0].write_text("[]", encoding="utf-8")
        with unittest.mock.patch.object(
            TRANSPORT,
            "_budget_open",
            return_value=StreamingResponse(b"fresh response"),
        ) as opened:
            result = TRANSPORT._http(PDF_URL)
        self.assertEqual(result, (200, "fresh response"))
        self.assertEqual(opened.call_count, 1)
        self.assertIsInstance(json.loads(cache_files[0].read_text()), dict)

    def test_request_exhaustion_is_not_a_missing_pdf(self) -> None:
        controller = self.budget(max_requests=0)
        opener = unittest.mock.Mock()
        with unittest.mock.patch.object(
            TRANSPORT.urllib.request, "build_opener", return_value=opener
        ):
            with self.assertRaises(SERVER.BudgetExhaustedError):
                ACQUISITION._download_pdf(
                    PDF_URL, str(self.root / "blocked.pdf")
                )
        opener.open.assert_not_called()
        self.assertEqual(controller.usage()["requests"], 0)
        self.assertFalse((self.root / "blocked.pdf").exists())

    def test_unbudgeted_redirect_closes_body_and_strips_crosshost_secrets(
        self,
    ) -> None:
        redirect_body = unittest.mock.Mock()
        redirect_body.read.side_effect = AssertionError(
            "redirect body must never be drained"
        )
        headers = email.message.Message()
        headers["Location"] = "https://example.org/final.pdf"
        redirect = urllib.error.HTTPError(
            PDF_URL, 302, "redirect", headers, redirect_body
        )
        final = StreamingResponse(b"%PDF-1.7\nsmall complete fixture")
        opener = unittest.mock.Mock()
        opener.open.side_effect = [redirect, final]
        with unittest.mock.patch.object(
            TRANSPORT.urllib.request, "build_opener", return_value=opener
        ):
            status, body = TRANSPORT._http(
                PDF_URL,
                binary=True,
                cache=False,
                headers={"Authorization": "Bearer fixture", "Cookie": "x=1"},
                max_bytes=100,
            )
        self.assertEqual(status, 200)
        self.assertTrue(body.startswith(b"%PDF"))
        self.assertEqual(opener.open.call_count, 2)
        redirect_body.read.assert_not_called()
        redirect_body.close.assert_called_once()
        forwarded = opener.open.call_args_list[1].args[0]
        self.assertIsNone(forwarded.get_header("Authorization"))
        self.assertIsNone(forwarded.get_header("Cookie"))
        self.assertTrue(final.closed)
        self.assertTrue(all(size and size > 0 for size in final.read_sizes))

    def test_unbudgeted_https_downgrade_is_refused_without_body_read(
        self,
    ) -> None:
        redirect_body = unittest.mock.Mock()
        redirect_body.read.side_effect = AssertionError(
            "redirect body must never be drained"
        )
        headers = email.message.Message()
        headers["Location"] = "http://arxiv.org/final.pdf"
        redirect = urllib.error.HTTPError(
            PDF_URL, 302, "redirect", headers, redirect_body
        )
        opener = unittest.mock.Mock()
        opener.open.side_effect = redirect
        with unittest.mock.patch.object(
            TRANSPORT.urllib.request, "build_opener", return_value=opener
        ):
            with self.assertRaises(RuntimeError):
                TRANSPORT._http(PDF_URL, binary=True, cache=False, retries=1)
        self.assertEqual(opener.open.call_count, 1)
        redirect_body.read.assert_not_called()
        redirect_body.close.assert_called_once()

    def test_premature_eof_cannot_publish_declared_complete_pdf(self) -> None:
        response = StreamingResponse(b"%PDF-1.7\nshort", length="100")
        destination = self.root / "paper.pdf"
        with unittest.mock.patch.object(
            TRANSPORT, "_budget_open", return_value=response
        ):
            self.assertFalse(
                ACQUISITION._download_pdf(PDF_URL, str(destination))
            )
        self.assertFalse(destination.exists())


class SourceQualityTest(ExtractionFixture):
    """Keep readable quality, unknown completeness and source identity apart."""

    def test_clean_local_source_is_assessed_without_completeness_claim(
        self,
    ) -> None:
        result = self.fetch()
        self.assertNotIn("error", result)
        quality = result["quality"]
        self.assertEqual(quality["status"], "no-known-defect")
        self.assertTrue(quality["usable_for_judgment"])
        self.assertTrue(quality["input_complete"])
        self.assertEqual(quality["document_completeness"], "unknown")
        self.assertTrue(quality["policy"])
        self.assertTrue(quality["normalization"])
        self.assertFalse(quality["diagnostics"])
        self.assertEqual(pathlib.Path(result["path"]).read_text(), GOOD_TEXT)

    def test_empty_and_garbled_text_are_never_usable_fulltext(self) -> None:
        for text in ("", " \n\t", "\ufffd" * 2000, "\x00\x01" * 1000):
            with self.subTest(text_prefix=text[:10]):
                result = self.fetch(text)
                self.assertFalse(
                    result["quality"]["usable_for_judgment"], result
                )
                self.assertIn(
                    result["quality"]["status"], {"poor", "unreadable"}
                )
                self.assertTrue(result["quality"]["diagnostics"])

    def test_preview_truncation_keeps_full_source_and_its_identity(
        self,
    ) -> None:
        result = self.fetch(max_chars=20)
        self.assertEqual(result["text"], GOOD_TEXT[:20])
        self.assertTrue(result["preview_truncated"])
        self.assertEqual(result["quality"]["status"], "no-known-defect")
        self.assertTrue(result["quality"]["input_complete"])
        self.assertEqual(pathlib.Path(result["path"]).read_text(), GOOD_TEXT)
        self.assertEqual(
            result["text_sha256"],
            hashlib.sha256(GOOD_TEXT.encode()).hexdigest(),
        )
        original_identity = SERVER._current_source_identity(DOI)
        full = SERVER.fetch_text(DOI, max_chars=len(GOOD_TEXT) + 10)
        self.assertFalse(full["preview_truncated"])
        self.assertEqual(full["text"], GOOD_TEXT)
        self.assertEqual(
            SERVER._current_source_identity(DOI), original_identity
        )

    def test_invalid_preview_limit_is_rejected_without_publication(
        self,
    ) -> None:
        for maximum in (-1, True, 1.5, "20"):
            with self.subTest(maximum=maximum):
                result = SERVER.fetch_text(
                    DOI, text_path=str(self.original), max_chars=maximum
                )
                self.assertTrue(result.get("error"), result)
                self.assertIsNone(PERSISTENCE._load_text_meta(DOI))
        self.assertEqual(self.original.read_text(), GOOD_TEXT)

    def test_failed_pdf_fallback_preserves_abstract_basis_and_diagnostics(
        self,
    ) -> None:
        self.record["abstract"] = GOOD_TEXT
        self.record["pdf_urls"] = [PDF_URL]
        with (
            unittest.mock.patch.object(
                SERVER, "_openalex_get", return_value=None
            ),
            unittest.mock.patch.object(
                ACQUISITION, "_download_pdf", return_value=False
            ),
        ):
            result = SERVER.fetch_text(DOI)
        self.assertNotIn("error", result)
        self.assertEqual(result["basis"], "abstract")
        self.assertEqual(result["quality"]["status"], "no-known-defect")
        self.assertTrue(result["acquisition_diagnostics"])
        self.assertTrue(
            any(
                "PDF download" in note
                for note in result["acquisition_diagnostics"]
            )
        )
        self.assertIn(GOOD_TEXT, pathlib.Path(result["path"]).read_text())

    def test_passages_expose_same_source_quality(self) -> None:
        fetched = self.fetch()
        found = SERVER.find_passages(DOI, "The measurement rises", k=1)
        self.assertEqual(found["quality"], fetched["quality"])
        self.assertTrue(found["results"][0]["passages"])

    def test_legacy_cache_remains_unknown_without_silent_promotion(
        self,
    ) -> None:
        text_path, metadata_path = PERSISTENCE._text_paths(DOI)
        pathlib.Path(text_path).write_text(GOOD_TEXT, encoding="utf-8")
        pathlib.Path(metadata_path).write_text(
            json.dumps(
                {
                    "id": DOI,
                    "cache_id": DOI,
                    "basis": "fulltext",
                    "source": "local:legacy.txt",
                    "chars": len(GOOD_TEXT),
                    "extraction_version": "legacy",
                    "title": "Legacy source",
                }
            ),
            encoding="utf-8",
        )
        with unittest.mock.patch.object(ACQUISITION, "_obtain_text") as acquire:
            fetched = SERVER.fetch_text(DOI)
        acquire.assert_not_called()
        self.assertEqual(fetched["quality"]["status"], "unknown")
        self.assertFalse(fetched["quality"]["usable_for_judgment"])
        self.assertIsNone(fetched["quality"]["input_complete"])

    def test_forged_quality_flags_do_not_certify_unreadable_cached_text(
        self,
    ) -> None:
        result = self.fetch("\ufffd" * 2000)
        _, metadata_path = PERSISTENCE._text_paths(DOI)
        meta = json.loads(pathlib.Path(metadata_path).read_text())
        meta["quality"]["status"] = "no-known-defect"
        meta["quality"]["usable_for_judgment"] = True
        meta["quality"]["diagnostics"] = []
        pathlib.Path(metadata_path).write_text(
            json.dumps(meta), encoding="utf-8"
        )
        fetched = SERVER.fetch_text(DOI)
        self.assertFalse(fetched["quality"]["usable_for_judgment"], fetched)
        self.assertEqual(
            pathlib.Path(result["path"]).read_text(), "\ufffd" * 2000
        )

    def test_scientific_unicode_is_not_itself_an_extraction_defect(
        self,
    ) -> None:
        content = (
            "Η μέτρηση δείχνει μια μικρή μεταβολή. "
            "The fitted α coefficient is −0.03 and the scale is 10⁻² m²."
        )
        result = self.fetch(content)
        self.assertEqual(result["quality"]["status"], "no-known-defect")
        self.assertEqual(pathlib.Path(result["path"]).read_text(), content)

    def test_short_nonempty_source_is_explicitly_poor(self) -> None:
        result = self.fetch("Tiny source.")
        self.assertEqual(result["quality"]["status"], "poor")
        self.assertFalse(result["quality"]["usable_for_judgment"])
        self.assertTrue(result["quality"]["diagnostics"])

    def test_local_text_limit_preserves_previous_committed_snapshot(
        self,
    ) -> None:
        previous = self.fetch()
        identity = SERVER._current_source_identity(DOI)
        self.original.write_text("x" * 100, encoding="utf-8")
        with unittest.mock.patch.object(CONFIG, "MAX_SOURCE_TEXT_BYTES", 64):
            rejected = SERVER.fetch_text(DOI, text_path=str(self.original))
        self.assertTrue(rejected.get("error"), rejected)
        self.assertEqual(SERVER._current_source_identity(DOI), identity)
        self.assertEqual(pathlib.Path(previous["path"]).read_text(), GOOD_TEXT)
        self.assertEqual(self.original.read_text(), "x" * 100)

    def test_invalid_utf8_never_becomes_usable_fulltext(self) -> None:
        self.original.write_bytes(GOOD_TEXT.encode() + b"\xff\xfe")
        result = SERVER.fetch_text(DOI, text_path=str(self.original))
        self.assertTrue(
            result.get("error") or not result["quality"]["usable_for_judgment"],
            result,
        )
        self.assertTrue(self.original.read_bytes().endswith(b"\xff\xfe"))

    def test_source_quality_changes_are_part_of_evidence_identity(self) -> None:
        self.fetch()
        before = SERVER._current_source_identity(DOI)
        _, metadata_path = PERSISTENCE._text_paths(DOI)
        meta = json.loads(pathlib.Path(metadata_path).read_text())
        meta.pop("intake", None)
        pathlib.Path(metadata_path).write_text(
            json.dumps(meta), encoding="utf-8"
        )
        after = SERVER._current_source_identity(DOI)
        self.assertNotEqual(after, before)
        fetched = SERVER.fetch_text(DOI)
        self.assertEqual(fetched["quality"]["status"], "unknown")

    def test_malformed_normalization_metadata_is_not_executed_or_trusted(
        self,
    ) -> None:
        self.fetch()
        _, metadata_path = PERSISTENCE._text_paths(DOI)
        meta = json.loads(pathlib.Path(metadata_path).read_text())
        meta["normalization"] = [{"unexpected": "object"}]
        pathlib.Path(metadata_path).write_text(
            json.dumps(meta), encoding="utf-8"
        )
        result = SERVER.fetch_text(DOI)
        self.assertNotIn("error", result)
        self.assertEqual(result["quality"]["normalization"], [])

    def test_unverifiable_bad_source_is_assessed_but_not_submission_ready(
        self,
    ) -> None:
        self.fetch("Unreadable \ufffd source text requires a reviewed copy.")
        manuscript = self.root / "main.tex"
        manuscript.write_text(
            r"The measurement rises \cite{a}.", encoding="utf-8"
        )
        bibliography = self.root / "refs.bib"
        bibliography.write_text(
            test_evidence.official_bib_fixture(
                "@article{a,title={Example},doi={10.1234/quality-fixture}}",
                self.record, bibliography,
            ),
            encoding="utf-8",
        )
        cite = SERVER.extract_cites(str(manuscript))["cites"][0]
        result = SERVER.record_support(
            str(self.root),
            "a",
            cite["claim"],
            "UNVERIFIABLE",
            DOI,
            context=cite["context"],
            note="The extraction is unreadable and requires a better source.",
            judge="independent-fixture-reader",
        )
        self.assertTrue(result["recorded"], result)
        verified = {
            "entries": [
                {
                    "key": "a",
                    "status": "VERIFIED",
                    "id": DOI,
                    "ids": {"doi": DOI.removeprefix("doi:")},
                }
            ]
        }
        with unittest.mock.patch.object(
            SERVER, "verify_bib", return_value=verified
        ):
            for policy in ("submission-ready", "exploratory"):
                with self.subTest(policy=policy):
                    report = SERVER.audit(
                        str(manuscript), str(bibliography), policy=policy
                    )
                    support = report["coverage"]["support"]
                    self.assertEqual(support["assessed"], 1, report)
                    self.assertEqual(support["counts"], {"INACCESSIBLE": 1})
                    self.assertTrue(report["complete"], report)
                    self.assertFalse(report["submission_ready"], report)
                    self.assertEqual(support["verified"], 0)
                    self.assertEqual(
                        report["ok"], policy == "exploratory", report
                    )

    def test_unusable_source_only_accepts_an_unverifiable_judgment(
        self,
    ) -> None:
        text = "\ufffd" * 2000
        self.fetch(text)
        for verdict in ("SUPPORTS", "PARTIAL", "CONTRADICTS", "UNSUPPORTED"):
            with self.subTest(verdict=verdict):
                result = SERVER.record_support(
                    str(self.root),
                    "a",
                    "A measured result.",
                    verdict,
                    DOI,
                    quotes=[text],
                    note="The extraction cannot establish reliable evidence.",
                )
                self.assertFalse(result["recorded"], result)
        recorded = SERVER.record_support(
            str(self.root),
            "a",
            "A measured result.",
            "UNVERIFIABLE",
            DOI,
            note="The extraction is unreadable and requires a better source.",
        )
        self.assertTrue(recorded["recorded"], recorded)

    def test_quality_downgrade_stales_previously_supporting_judgment(
        self,
    ) -> None:
        self.fetch()
        manuscript = self.root / "main.tex"
        manuscript.write_text(
            r"The measurement rises \cite{a}.", encoding="utf-8"
        )
        bibliography = self.root / "refs.bib"
        bibliography.write_text(
            test_evidence.official_bib_fixture(
                "@article{a,title={Example},doi={10.1234/quality-fixture}}",
                self.record, bibliography,
            ),
            encoding="utf-8",
        )
        cite = SERVER.extract_cites(str(manuscript))["cites"][0]
        supported = SERVER.record_support(
            str(self.root),
            "a",
            cite["claim"],
            "SUPPORTS",
            DOI,
            quotes=["The measurement rises by ten percent."],
            context=cite["context"],
            judge="independent-fixture-reader",
        )
        self.assertTrue(supported["recorded"], supported)
        verified = {
            "entries": [
                {
                    "key": "a",
                    "status": "VERIFIED",
                    "id": DOI,
                    "ids": {"doi": DOI.removeprefix("doi:")},
                }
            ]
        }
        with unittest.mock.patch.object(
            SERVER, "verify_bib", return_value=verified
        ):
            before = SERVER.audit(str(manuscript), str(bibliography))
            self.assertTrue(before["submission_ready"], before)
            _, metadata_path = PERSISTENCE._text_paths(DOI)
            meta = json.loads(pathlib.Path(metadata_path).read_text())
            meta.pop("intake", None)
            pathlib.Path(metadata_path).write_text(
                json.dumps(meta), encoding="utf-8"
            )
            after = SERVER.audit(str(manuscript), str(bibliography))
        self.assertFalse(after["submission_ready"], after)
        self.assertEqual(after["coverage"]["support"]["verified"], 0)


class PdfQualityTest(ExtractionFixture):
    """Carry bounded worker extraction defects into the source metadata."""

    def test_empty_page_blocks_usable_quality_even_with_long_other_page(
        self,
    ) -> None:
        manuscripts = importlib.import_module("cite_check_engine.manuscripts")
        original = self.root / "source.pdf"
        binary = b"%PDF-1.7\noriginal fixture bytes"
        original.write_bytes(binary)
        extracted = {
            "pages": [{"page": 1, "text": GOOD_TEXT}, {"page": 2, "text": ""}],
            "extractor": manuscripts._input_pdf_backend(),
        }
        with unittest.mock.patch.object(
            manuscripts, "_input_pdf_extract", return_value=extracted
        ):
            result = SERVER.fetch_text(DOI, pdf_path=str(original))
        self.assertEqual(result["quality"]["status"], "poor")
        self.assertFalse(result["quality"]["usable_for_judgment"])
        self.assertTrue(result["quality"]["diagnostics"])
        self.assertEqual(original.read_bytes(), binary)

    def test_changed_pdf_bytes_with_same_extracted_text_change_identity(
        self,
    ) -> None:
        manuscripts = importlib.import_module("cite_check_engine.manuscripts")
        original = self.root / "source.pdf"
        extracted = {
            "pages": [{"page": 1, "text": GOOD_TEXT}],
            "extractor": manuscripts._input_pdf_backend(),
        }
        identities = []
        snapshots = []
        with unittest.mock.patch.object(
            manuscripts, "_input_pdf_extract", return_value=extracted
        ):
            for revision in (b"first revision", b"second revision"):
                original.write_bytes(b"%PDF-1.7\n" + revision)
                result = SERVER.fetch_text(DOI, pdf_path=str(original))
                self.assertNotIn("error", result)
                snapshots.append(pathlib.Path(result["path"]).read_text())
                identities.append(SERVER._current_source_identity(DOI))
        self.assertEqual(snapshots, [GOOD_TEXT, GOOD_TEXT])
        self.assertNotEqual(identities[0], identities[1])

    def test_invalid_cached_pdf_intake_cannot_certify_support(self) -> None:
        manuscripts = importlib.import_module("cite_check_engine.manuscripts")
        original = self.root / "source.pdf"
        original.write_bytes(b"%PDF-1.7\nfixture")
        extracted = {
            "pages": [{"page": 1, "text": GOOD_TEXT}],
            "extractor": manuscripts._input_pdf_backend(),
        }
        with unittest.mock.patch.object(
            manuscripts, "_input_pdf_extract", return_value=extracted
        ):
            fetched = SERVER.fetch_text(DOI, pdf_path=str(original))
        self.assertTrue(fetched["quality"]["usable_for_judgment"])
        _, metadata_path = PERSISTENCE._text_paths(DOI)
        pristine = pathlib.Path(metadata_path).read_text()
        invalid_facts = [
            {"input_bytes": 0},
            {"extractor": {}},
            {"extractor": dict(extracted["extractor"], name="unknown")},
            {"extractor": dict(extracted["extractor"], version="")},
            {"extractor": dict(extracted["extractor"], policy="")},
            {
                "extractor": dict(
                    extracted["extractor"], options={"strict": False}
                )
            },
        ]
        for changes in invalid_facts:
            with self.subTest(changes=changes):
                meta = json.loads(pristine)
                meta["intake"].update(changes)
                meta["quality"]["usable_for_judgment"] = True
                pathlib.Path(metadata_path).write_text(
                    json.dumps(meta), encoding="utf-8"
                )
                current = SERVER.fetch_text(DOI)
                self.assertEqual(current["quality"]["status"], "unknown")
                self.assertFalse(current["quality"]["usable_for_judgment"])
                decision = SERVER.record_support(
                    str(self.root),
                    "a",
                    "A measured result.",
                    "SUPPORTS",
                    DOI,
                    quotes=["The measurement rises by ten percent."],
                    judge="independent-fixture-reader",
                )
                self.assertFalse(decision["recorded"], decision)

    def test_pdf_worker_failure_cannot_publish_a_source_snapshot(self) -> None:
        manuscripts = importlib.import_module("cite_check_engine.manuscripts")
        original = self.root / "source.pdf"
        original.write_bytes(b"%PDF-1.7\ntruncated fixture")
        with unittest.mock.patch.object(
            manuscripts,
            "_input_pdf_extract",
            side_effect=ValueError("fixture extraction failed"),
        ):
            result = SERVER.fetch_text(DOI, pdf_path=str(original))
        self.assertTrue(result.get("error"), result)
        self.assertIsNone(PERSISTENCE._load_text_meta(DOI))

    def test_pdf_page_text_is_assessed_before_normalization(self) -> None:
        manuscripts = importlib.import_module("cite_check_engine.manuscripts")
        original = self.root / "source.pdf"
        original.write_bytes(b"%PDF-1.7\noriginal fixture")
        extracted = {
            "pages": [{"page": 1, "text": GOOD_TEXT + "\x00"}],
            "extractor": manuscripts._input_pdf_backend(),
        }
        with unittest.mock.patch.object(
            manuscripts, "_input_pdf_extract", return_value=extracted
        ):
            result = SERVER.fetch_text(DOI, pdf_path=str(original))
        self.assertFalse(result["quality"]["usable_for_judgment"], result)
        self.assertTrue(result["quality"]["diagnostics"])


if __name__ == "__main__":
    unittest.main()
