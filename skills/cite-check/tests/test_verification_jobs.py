"""Offline regressions for bounded, resumable identity verification."""

import concurrent.futures
import email.message
import io
import json
import os
import pathlib
import tempfile
import threading
import time
import types
from typing import Any
import unittest
import unittest.mock
import urllib.error
import urllib.request

import test_evidence

SERVER = test_evidence.SERVER
PUBLIC_URL = "https://api.crossref.org/works/10.1234/example"


def redirect_headers(url: str) -> email.message.Message:
    """Construct actual header objects for offline redirect errors."""
    headers = email.message.Message()
    headers["location"] = url
    return headers


class Response(io.BytesIO):
    """Small context-managed HTTP response without a network connection."""

    def __init__(self, content: bytes = b"{}", status: int = 200) -> None:
        super().__init__(content)
        self.status = status


class BudgetTransportTest(unittest.TestCase):
    """Exercise physical admissions independently of registry results."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        for name, value in (
            ("CACHE_DIR", self.temporary.name),
            ("_host_last", {}),
        ):
            patch: Any = unittest.mock.patch.object(SERVER, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        patch = unittest.mock.patch.object(
            SERVER, "_user_agent", return_value="offline-regression"
        )
        patch.start()
        self.addCleanup(patch.stop)
        self.persisted: list[dict[str, Any]] = []

    def budget(self, **limits: object) -> Any:
        """Install one invocation-local controller for this test."""
        controller = SERVER._RequestBudget(
            SERVER._validated_budget(limits), self.persisted.append
        )
        token = SERVER._request_budget.set(controller)
        self.addCleanup(SERVER._request_budget.reset, token)
        return controller

    def test_request_limit_is_shared_across_worker_contexts(self) -> None:
        controller = self.budget(max_requests=3)

        def reserve(_: int) -> bool:
            try:
                SERVER._request_budget.get().reserve("request", PUBLIC_URL)
                return True
            except SERVER.BudgetExhaustedError:
                return False

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            admitted = SERVER._context_map(executor, reserve, range(12))
        self.assertEqual(sum(admitted), 3)
        self.assertEqual(controller.usage()["requests"], 3)
        self.assertEqual(self.persisted[-1]["requests"], 3)

    def test_request_reservation_is_saved_before_network(self) -> None:
        controller = self.budget(max_requests=1)

        def opened(*_: object, **__: object) -> Response:
            self.assertEqual(self.persisted[-1]["requests"], 1)
            return Response()

        opener = unittest.mock.Mock()
        opener.open.side_effect = opened
        with unittest.mock.patch.object(
            SERVER.urllib.request, "build_opener", return_value=opener
        ):
            with SERVER._budget_open(urllib.request.Request(PUBLIC_URL), 30):
                pass
        self.assertEqual(controller.usage()["requests"], 1)

    def test_retries_cannot_exceed_request_grant(self) -> None:
        controller = self.budget(max_requests=1)
        opener = unittest.mock.Mock()
        opener.open.side_effect = urllib.error.URLError("temporary outage")
        with (
            unittest.mock.patch.object(
                SERVER.urllib.request, "build_opener", return_value=opener
            ),
            unittest.mock.patch.object(SERVER, "_budget_sleep"),
        ):
            with self.assertRaises(SERVER.BudgetExhaustedError):
                SERVER._http(PUBLIC_URL, cache=False)
        self.assertEqual(opener.open.call_count, 1)
        self.assertEqual(controller.usage()["requests"], 1)

    def test_redirect_hop_requires_another_request_reservation(self) -> None:
        controller = self.budget(max_requests=1)
        body = Response(b"unused redirect body")
        redirect = urllib.error.HTTPError(
            PUBLIC_URL,
            302,
            "moved",
            redirect_headers("https://api.crossref.org/elsewhere"),
            body,
        )
        opener = unittest.mock.Mock()
        opener.open.side_effect = [redirect, Response()]
        with (
            unittest.mock.patch.object(
                SERVER.urllib.request, "build_opener", return_value=opener
            ),
            unittest.mock.patch.object(SERVER, "_throttle"),
        ):
            with self.assertRaises(SERVER.BudgetExhaustedError):
                SERVER._budget_open(urllib.request.Request(PUBLIC_URL), 30)
        self.assertTrue(body.closed)
        self.assertEqual(opener.open.call_count, 1)
        self.assertEqual(controller.usage()["requests"], 1)

    def test_redirect_does_not_drain_body_and_clips_hop_timeout(self) -> None:
        clock = [100.0]
        with unittest.mock.patch.object(
            SERVER.time, "monotonic", side_effect=lambda: clock[0]
        ):
            controller = self.budget(max_requests=2, max_seconds=1)
            body = unittest.mock.Mock()
            body.read.side_effect = AssertionError("redirect body was read")
            redirect = urllib.error.HTTPError(
                PUBLIC_URL,
                302,
                "moved",
                redirect_headers("https://api.crossref.org/elsewhere"),
                body,
            )
            opener = unittest.mock.Mock()

            def opened(*_: object, **kwargs: Any) -> Response:
                if opener.open.call_count == 1:
                    clock[0] += 0.6
                    raise redirect
                self.assertLessEqual(kwargs["timeout"], 0.401)
                return Response()

            opener.open.side_effect = opened
            with (
                unittest.mock.patch.object(
                    SERVER.urllib.request, "build_opener", return_value=opener
                ),
                unittest.mock.patch.object(SERVER, "_throttle"),
            ):
                with SERVER._budget_open(
                    urllib.request.Request(PUBLIC_URL), 30
                ):
                    pass
            body.read.assert_not_called()
            body.close.assert_called_once()
            self.assertEqual(controller.usage()["requests"], 2)

    def test_unknown_price_redirect_is_not_sent_under_cost_cap(self) -> None:
        controller = self.budget(max_requests=5, max_cost_usd=0)
        redirect = urllib.error.HTTPError(
            PUBLIC_URL,
            302,
            "moved",
            redirect_headers("https://example.org/x"),
            Response(),
        )
        opener = unittest.mock.Mock()
        opener.open.side_effect = [redirect, Response()]
        with (
            unittest.mock.patch.object(
                SERVER.urllib.request, "build_opener", return_value=opener
            ),
            unittest.mock.patch.object(SERVER, "_throttle"),
        ):
            with self.assertRaises(SERVER.BudgetExhaustedError):
                SERVER._budget_open(urllib.request.Request(PUBLIC_URL), 30)
        self.assertEqual(opener.open.call_count, 1)
        self.assertEqual(
            controller.usage()["stop_reason"], "unknown-request-price"
        )

    def test_https_downgrade_is_refused(self) -> None:
        self.budget(max_requests=5)
        redirect = urllib.error.HTTPError(
            PUBLIC_URL,
            302,
            "moved",
            redirect_headers("http://api.crossref.org/elsewhere"),
            Response(),
        )
        opener = unittest.mock.Mock()
        opener.open.side_effect = [redirect, Response()]
        with unittest.mock.patch.object(
            SERVER.urllib.request, "build_opener", return_value=opener
        ):
            with self.assertRaises(SERVER.BudgetExhaustedError):
                SERVER._budget_open(urllib.request.Request(PUBLIC_URL), 30)
        self.assertEqual(opener.open.call_count, 1)

    def test_unknown_price_is_unknown_when_cap_disabled(self) -> None:
        controller = self.budget(max_cost_usd=None)
        controller.reserve("request", "https://example.org/unknown")
        usage = controller.usage()
        self.assertEqual(usage["unknown_price_requests"], 1)
        self.assertIsNone(usage["estimated_service_cost_usd"])
        self.assertIsNone(usage["actual_billed_cost_usd"])
        self.assertIsNone(usage["model_tokens"])
        self.assertEqual(usage["model_calls"], 0)

    def test_cached_response_uses_no_network_grant(self) -> None:
        opener = unittest.mock.Mock()
        opener.open.return_value = Response(b"cached")
        with unittest.mock.patch.object(
            SERVER.urllib.request, "build_opener", return_value=opener
        ):
            SERVER._http(PUBLIC_URL)
        controller = self.budget(max_requests=0)
        with unittest.mock.patch.object(
            SERVER.urllib.request, "build_opener"
        ) as network:
            self.assertEqual(SERVER._http(PUBLIC_URL), (200, "cached"))
        network.assert_not_called()
        self.assertEqual(controller.usage()["requests"], 0)
        self.assertEqual(controller.usage()["http_cache_hits"], 1)

    def test_backend_search_limit_survives_worker_pool(self) -> None:
        controller = self.budget(max_searches=1)
        with (
            unittest.mock.patch.object(SERVER, "_ads_token", return_value=None),
            unittest.mock.patch.object(
                SERVER, "_crossref_search", return_value=[]
            ) as crossref,
            unittest.mock.patch.object(
                SERVER, "_openalex_search", return_value=[]
            ) as openalex,
        ):
            result = SERVER.search_citation(
                title="An example work", registries=["crossref", "openalex"]
            )
        self.assertEqual(crossref.call_count + openalex.call_count, 1)
        self.assertEqual(controller.usage()["searches"], 1)
        self.assertTrue(result["errors"])

    def test_deadline_refuses_long_wait_before_sleep(self) -> None:
        controller = self.budget(max_seconds=0.1)
        with unittest.mock.patch.object(SERVER.time, "sleep") as sleeping:
            with self.assertRaises(SERVER.BudgetExhaustedError):
                controller.sleep(1)
        sleeping.assert_not_called()

    def test_deadline_rechecked_after_response_chunk(self) -> None:
        clock = [100.0]
        with unittest.mock.patch.object(
            SERVER.time, "monotonic", side_effect=lambda: clock[0]
        ):
            controller = self.budget(max_seconds=1)
            response = unittest.mock.Mock()

            def read(_: int) -> bytes:
                clock[0] += 2
                return b"late data"

            response.read1.side_effect = read
            response.fp = None
            with self.assertRaises(SERVER.BudgetExhaustedError):
                SERVER._budget_read(response)
            self.assertTrue(controller.usage()["deadline_exceeded"])
            self.assertEqual(
                controller.usage()["deadline_overshoot_seconds"], 1
            )
            self.assertEqual(response.read1.call_count, 1)

    def test_throttle_lock_wait_uses_remaining_deadline(self) -> None:
        self.budget(max_seconds=0.1)
        lock = unittest.mock.Mock()
        lock.acquire.return_value = False
        with unittest.mock.patch.object(SERVER, "_host_lock", lock):
            with self.assertRaises(SERVER.BudgetExhaustedError):
                SERVER._throttle("api.crossref.org")
        self.assertGreater(lock.acquire.call_args.kwargs["timeout"], 0)
        self.assertLessEqual(lock.acquire.call_args.kwargs["timeout"], 0.1)
        lock.release.assert_not_called()


class VerificationJobsTest(unittest.TestCase):
    """Check saved progress and complete obligation counts offline."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        self.tex = self.root / "main.tex"
        self.bib = self.root / "refs.bib"
        self.tex.write_text(
            "First result \\cite{a}.\n\n"
            "Central result \\cite{b}.\n\n"
            "Another result \\cite{c}.\n\n"
            "Repeated source \\cite{a}.\n\\bibliography{refs}\n",
            encoding="utf-8",
        )
        self.bib.write_text(
            "\n".join(
                f"@article{{{key}, title={{Work {key}}}, "
                f"doi={{10.1234/{key}}}, year={{2020}}}}"
                for key in ("a", "b", "c")
            ),
            encoding="utf-8",
        )
        self.called: list[str] = []
        patch = unittest.mock.patch.object(
            SERVER, "verify_bib", side_effect=self.verify
        )
        patch.start()
        self.addCleanup(patch.stop)
        patch = unittest.mock.patch.object(
            SERVER.urllib.request,
            "build_opener",
            side_effect=AssertionError("test attempted live network"),
        )
        patch.start()
        self.addCleanup(patch.stop)

    def verify(
        self, bib_path: str, keys: list[str], **_: Any
    ) -> dict[str, Any]:
        """Spend one admitted request and return a bound verifier row."""
        del bib_path
        SERVER._request_budget.get().reserve("request", PUBLIC_URL)
        key = keys[0]
        self.called.append(key)
        return {
            "entries": [
                {
                    "key": key,
                    "status": "VERIFIED",
                    "id": f"doi:10.1234/{key}",
                    "ids": {"doi": f"10.1234/{key}"},
                    "via": f"doi:10.1234/{key}",
                    "registry_title": f"Work {key}",
                    "notes": [],
                }
            ]
        }

    def start(self, **kwargs: Any) -> dict[str, Any]:
        """Run against the fixture's main source."""
        return SERVER.verification_job(str(self.tex), **kwargs)

    def test_priority_changes_order_without_hiding_pending_work(self) -> None:
        cited = SERVER.extract_cites(str(self.tex))["cites"]
        occurrence = next(item for item in cited if item["key"] == "b")
        result = self.start(
            budget={"max_requests": 1},
            priorities=[
                {
                    "occurrence_id": occurrence["occurrence_id"],
                    "priority": "high",
                    "reason": "Central result of the paper",
                }
            ],
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.called, ["b"])
        self.assertEqual(result["identity_expected"], 3)
        self.assertEqual(result["identity_assessed"], 1)
        self.assertEqual(result["identity_unchecked"], 2)
        self.assertEqual(result["support_pending"], 4)
        self.assertEqual(result["support_queue"][0]["key"], "b")
        self.assertEqual(
            {item["status"] for item in result["support_queue"]}, {"UNCHECKED"}
        )
        self.assertFalse(result["identity_complete"])
        self.assertFalse(result["submission_ready"])
        self.assertIsNone(result["cumulative_usage"]["actual_billed_cost_usd"])

    def test_resume_retains_completed_units_and_accumulates_grants(
        self,
    ) -> None:
        first = self.start(budget={"max_requests": 1})
        second = self.start(job_id=first["job_id"], budget={"max_requests": 2})
        self.assertTrue(second["identity_complete"], second)
        self.assertTrue(second["identity_verified"])
        self.assertFalse(second["submission_ready"])
        self.assertEqual(self.called, ["a", "b", "c"])
        self.assertEqual(second["cumulative_usage"]["requests"], 3)
        self.assertEqual(
            [run["limits"]["max_requests"] for run in second["runs"]], [1, 2]
        )
        third = self.start(job_id=first["job_id"], operation="status")
        self.assertEqual(self.called, ["a", "b", "c"])
        self.assertEqual(third["cumulative_usage"]["requests"], 3)
        self.assertEqual(len(third["runs"]), 2)

    def test_atomic_priorities_preserve_separate_support_obligations(
        self,
    ) -> None:
        self.tex.write_text(
            "The value rises and the rate falls \\cite{a}.\n"
            "\\bibliography{refs}",
            encoding="utf-8",
        )
        sentence = SERVER.extract_cites(str(self.tex))["sentences"][0]
        split = sentence["claim"].index("and")
        registered = SERVER.register_claims(
            str(self.tex),
            sentence["sentence_id"],
            [
                {
                    "start": 0,
                    "end": split,
                    "citation_ids": sentence["citation_ids"],
                },
                {
                    "start": split,
                    "end": len(sentence["claim"]),
                    "citation_ids": sentence["citation_ids"],
                },
            ],
        )
        self.assertTrue(registered["ok"], registered)
        atom = registered["atoms"][1]
        result = self.start(
            budget={"max_requests": 0},
            priorities=[
                {
                    "occurrence_id": sentence["citation_ids"][0],
                    "atom_id": atom["atom_id"],
                    "priority": "high",
                    "reason": "The rate is the central measurement.",
                }
            ],
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["identity_expected"], 1)
        self.assertEqual(result["support_pending"], 2)
        self.assertEqual(result["support_queue"][0]["atom_id"], atom["atom_id"])
        self.assertEqual(result["support_queue"][0]["assertion"], atom["text"])
        self.assertEqual(
            len({item["id"] for item in result["support_queue"]}), 2
        )

    def test_nocite_star_checks_all_entries_without_support_claims(
        self,
    ) -> None:
        self.tex.write_text(
            "\\nocite{*}\n\\bibliography{refs}", encoding="utf-8"
        )
        result = self.start(budget={"max_requests": 0})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["identity_expected"], 3)
        self.assertEqual(result["identity_unchecked"], 3)
        self.assertEqual(result["support_pending"], 0)

    def test_zero_request_grant_keeps_everything_unchecked(self) -> None:
        result = self.start(budget={"max_requests": 0})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["identity_unchecked"], 3)
        self.assertEqual(result["identity_assessed"], 0)
        self.assertEqual(result["cumulative_usage"]["requests"], 0)
        self.assertEqual(self.called, [])

    def test_resume_uses_saved_explicit_bibliography_override(self) -> None:
        self.tex.write_text("A result \\cite{a}.\n", encoding="utf-8")
        first = self.start(bib_path=str(self.bib), budget={"max_requests": 0})
        inspected = self.start(job_id=first["job_id"], operation="status")
        self.assertTrue(inspected["ok"], inspected)
        resumed = self.start(job_id=first["job_id"], budget={"max_requests": 1})
        self.assertTrue(resumed["identity_complete"], resumed)
        self.assertEqual(self.called, ["a"])

    def test_changed_manuscript_or_bibliography_requires_new_job(self) -> None:
        for path in (self.tex, self.bib):
            with self.subTest(path=path.name):
                original = path.read_bytes()
                first = self.start(budget={"max_requests": 0})
                path.write_bytes(original + b"\n% revision\n")
                result = self.start(job_id=first["job_id"])
                self.assertFalse(result["ok"], result)
                self.assertTrue(result["rescan_required"])
                path.write_bytes(original)
        self.assertEqual(self.called, [])

    def test_changed_ledger_invalidates_saved_progress(self) -> None:
        first = self.start(budget={"max_requests": 1})
        ledger = self.root / ".cite-check" / "ledger.json"
        ledger.write_text(
            json.dumps({"version": 3, "entries": {}, "decompositions": {}}),
            encoding="utf-8",
        )
        result = self.start(job_id=first["job_id"])
        self.assertFalse(result["ok"], result)
        self.assertTrue(result["rescan_required"])
        self.assertEqual(self.called, ["a"])

    def test_changed_source_snapshot_invalidates_saved_progress(self) -> None:
        identity = {"text_sha256": "first"}
        ledger = {
            "entries": {"j": {"id": "doi:10.1234/a"}},
            "decompositions": {},
        }
        with (
            unittest.mock.patch.object(
                SERVER, "_audit_ledger", return_value=ledger
            ),
            unittest.mock.patch.object(
                SERVER, "_load_text_meta", return_value=None
            ),
            unittest.mock.patch.object(
                SERVER,
                "_current_source_identity",
                side_effect=lambda _: dict(identity),
            ),
        ):
            first = self.start(budget={"max_requests": 1})
            identity["text_sha256"] = "second"
            result = self.start(job_id=first["job_id"])
        self.assertFalse(result["ok"], result)
        self.assertTrue(result["rescan_required"])
        self.assertEqual(self.called, ["a"])

    def test_changed_search_configuration_is_refused(self) -> None:
        first = self.start(budget={"max_requests": 0}, search_unresolved=False)
        result = self.start(job_id=first["job_id"], search_unresolved=True)
        self.assertFalse(result["ok"], result)
        self.assertTrue(result["rescan_required"])
        self.assertEqual(self.called, [])

    def test_invalid_and_duplicate_priorities_are_refused(self) -> None:
        occurrence = SERVER.extract_cites(str(self.tex))["cites"][0]
        valid = {
            "occurrence_id": occurrence["occurrence_id"],
            "reason": "The main scientific conclusion depends on this.",
        }
        for priorities in (
            [dict(valid, occurrence_id="stale")],
            [valid, valid],
            [dict(valid, atom_id="not-an-attached-atom")],
            [dict(valid, priority="critical")],
            [dict(valid, reason="")],
        ):
            with self.subTest(priorities=priorities):
                result = self.start(priorities=priorities)
                self.assertFalse(result["ok"], result)
        self.assertEqual(self.called, [])

    def test_undefined_key_is_retained_without_false_completion(self) -> None:
        self.tex.write_text(
            "Missing work \\cite{missing}.\n\\bibliography{refs}",
            encoding="utf-8",
        )
        result = self.start()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["identity_expected"], 1)
        self.assertEqual(result["identity_unchecked"], 1)
        self.assertEqual(result["identity_queue"][0]["key"], "missing")
        self.assertFalse(result["identity_complete"])
        self.assertEqual(self.called, [])

    def test_lookup_failure_remains_retryable_not_not_found(self) -> None:
        with unittest.mock.patch.object(
            SERVER,
            "verify_bib",
            return_value={
                "entries": [
                    {"key": "a", "status": "UNRESOLVED", "notes": ["outage"]}
                ]
            },
        ):
            result = self.start()
        self.assertEqual(result["identity_assessed"], 0)
        self.assertFalse(result["identity_complete"])
        self.assertEqual(result["identity_unchecked"], 3)

    def test_malformed_verifier_rows_cannot_certify_identity(self) -> None:
        for row in (
            None,
            {"key": "a", "status": "VERIFIED"},
            {"key": "a", "status": "VERIFIED", "id": 17},
            {"key": "a", "status": "VERIFIED", "id": "invented"},
        ):
            with (
                self.subTest(row=row),
                unittest.mock.patch.object(
                    SERVER, "verify_bib", return_value={"entries": [row]}
                ),
            ):
                result = self.start()
                self.assertFalse(result.get("identity_verified", False), result)
                self.assertEqual(result.get("identity_assessed", 0), 0)

    def test_corrupt_state_checksum_is_refused(self) -> None:
        first = self.start(budget={"max_requests": 0})
        path = pathlib.Path(first["job_path"])
        saved = json.loads(path.read_text(encoding="utf-8"))
        saved["identity_queue"][0]["status"] = "ASSESSED"
        path.write_text(json.dumps(saved), encoding="utf-8")
        result = self.start(job_id=first["job_id"])
        self.assertFalse(result["ok"], result)
        self.assertEqual(self.called, [])

    def test_structurally_invalid_rechecksummed_state_is_refused(self) -> None:
        first = self.start(budget={"max_requests": 0})
        path = pathlib.Path(first["job_path"])
        saved = json.loads(path.read_text(encoding="utf-8"))
        saved.pop("integrity")
        saved["identity_queue"][0].update(
            status="ASSESSED", result={"key": "a", "status": "VERIFIED"}
        )
        SERVER._job_write(str(path), saved)
        result = self.start(job_id=first["job_id"], operation="status")
        self.assertFalse(result["ok"], result)

    def test_failure_after_reservation_preserves_conservative_usage(
        self,
    ) -> None:
        def failed(*_: object, **__: object) -> None:
            SERVER._request_budget.get().reserve("request", PUBLIC_URL)
            path = next((self.root / ".cite-check").glob("job-*.json"))
            state = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(state["runs"][-1]["usage"]["requests"], 1)
            raise RuntimeError("connection failed after admission")

        with unittest.mock.patch.object(
            SERVER, "verify_bib", side_effect=failed
        ):
            first = self.start()
        self.assertEqual(first["cumulative_usage"]["requests"], 1)
        self.assertEqual(first["identity_assessed"], 0)
        second = self.start(job_id=first["job_id"], budget={"max_requests": 3})
        self.assertTrue(second["identity_complete"], second)
        self.assertEqual(second["cumulative_usage"]["requests"], 4)

    def test_concurrent_resumes_do_not_repeat_completed_identity(self) -> None:
        first = self.start(budget={"max_requests": 0})
        entered = threading.Event()
        release = threading.Event()
        lock = threading.Lock()
        count = [0]

        def verify(*args: Any, **kwargs: Any) -> dict[str, Any]:
            with lock:
                count[0] += 1
                is_first = count[0] == 1
            if is_first:
                entered.set()
                self.assertTrue(release.wait(3))
            return self.verify(*args, **kwargs)

        with (
            unittest.mock.patch.object(
                SERVER, "verify_bib", side_effect=verify
            ),
            concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor,
        ):
            one = executor.submit(
                self.start, job_id=first["job_id"], budget={"max_requests": 1}
            )
            self.assertTrue(entered.wait(3))
            two = executor.submit(
                self.start, job_id=first["job_id"], budget={"max_requests": 1}
            )
            release.set()
            results = [one.result(timeout=5), two.result(timeout=5)]
        self.assertTrue(all(result["ok"] for result in results), results)
        self.assertEqual(self.called, ["a", "b"])
        final = self.start(job_id=first["job_id"], operation="status")
        self.assertEqual(final["identity_assessed"], 2)
        self.assertEqual(final["cumulative_usage"]["requests"], 2)

    def test_job_lock_wait_respects_cooperative_grant(self) -> None:
        first = self.start(budget={"max_requests": 0})
        with SERVER._file_lock(first["job_path"]):
            before = time.monotonic()
            result = self.start(
                job_id=first["job_id"], budget={"max_seconds": 0.05}
            )
            elapsed = time.monotonic() - before
        self.assertFalse(result["ok"], result)
        self.assertLess(elapsed, 1.0)
        self.assertEqual(self.called, [])

    def test_interrupted_run_resumes_without_losing_reserved_usage(
        self,
    ) -> None:
        first = self.start(budget={"max_requests": 1})
        path = pathlib.Path(first["job_path"])
        state = json.loads(path.read_text(encoding="utf-8"))
        state.pop("integrity")
        state["runs"][-1]["state"] = "RUNNING"
        state["identity_queue"][1]["status"] = "RUNNING"
        SERVER._job_write(str(path), state)
        resumed = self.start(job_id=first["job_id"], budget={"max_requests": 2})
        self.assertTrue(resumed["identity_complete"], resumed)
        self.assertEqual(resumed["runs"][0]["state"], "INTERRUPTED")
        self.assertEqual(resumed["cumulative_usage"]["requests"], 3)
        self.assertFalse(resumed["elapsed_accounting_complete"])
        self.assertEqual(self.called, ["a", "b", "c"])

    def test_invalid_budget_and_job_ids_return_structured_failure(self) -> None:
        for budget in (
            {"max_requests": True},
            {"max_searches": -1},
            {"max_seconds": float("nan")},
            {"max_cost_usd": float("inf")},
            {"unknown": 1},
        ):
            with self.subTest(budget=budget):
                self.assertFalse(self.start(budget=budget)["ok"])
        for identifier in (17, "../escape", "", "a" * 31):
            with self.subTest(identifier=identifier):
                self.assertFalse(self.start(job_id=identifier)["ok"])
        self.assertEqual(self.called, [])

    def test_empty_manuscript_has_zero_obligations_without_bibliography(
        self,
    ) -> None:
        self.tex.write_text("There are no citations here.\n", encoding="utf-8")
        result = self.start()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["identity_expected"], 0)
        self.assertEqual(result["support_pending"], 0)
        self.assertTrue(result["identity_complete"])
        self.assertFalse(result["submission_ready"])

    def test_job_output_hardlink_cannot_overwrite_bibliography(self) -> None:
        identifier = "a" * 32
        project = self.root / ".cite-check"
        project.mkdir()
        target = project / f"job-{identifier}.json"
        os.link(self.bib, target)
        original = self.bib.read_bytes()
        with unittest.mock.patch.object(
            SERVER.uuid,
            "uuid4",
            return_value=types.SimpleNamespace(hex=identifier),
        ):
            result = self.start()
        self.assertFalse(result["ok"], result)
        self.assertEqual(self.bib.read_bytes(), original)
        self.assertEqual(self.called, [])

    def test_symlinked_artifact_directory_is_refused(self) -> None:
        other = self.root / "other"
        other.mkdir()
        (self.root / ".cite-check").symlink_to(other, target_is_directory=True)
        original = self.bib.read_bytes()
        result = self.start()
        self.assertFalse(result["ok"], result)
        self.assertEqual(self.bib.read_bytes(), original)
        self.assertEqual(self.called, [])

    def test_safe_symlinked_workspace_ancestor_is_supported(self) -> None:
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        result = SERVER.verification_job(
            str(alias / "main.tex"), budget={"max_requests": 0}
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["identity_unchecked"], 3)


if __name__ == "__main__":
    unittest.main()
