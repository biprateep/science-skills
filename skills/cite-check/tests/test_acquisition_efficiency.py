"""Offline and loopback regressions for efficient, isolated acquisition."""

import concurrent.futures
import email.message
import email.utils
import http.server
import importlib
import io
import os
import pathlib
import socket
import tempfile
import threading
import time
from typing import Any
import unittest
import unittest.mock
import urllib.error

import test_evidence

SERVER = test_evidence.SERVER
TRANSPORT = importlib.import_module("cite_check_engine.transport")
CONFIG = importlib.import_module("cite_check_engine.config")
BUDGETS = importlib.import_module("cite_check_engine.budgets")
PUBLIC_URL = "https://api.crossref.org/works/10.1234/efficiency-fixture"


class Response(io.BytesIO):
    """Small complete response without a real remote connection."""

    def __init__(self, content: bytes = b"fixture response") -> None:
        super().__init__(content)
        self.status = 200
        self.headers = email.message.Message()
        self.headers["Content-Length"] = str(len(content))


class LocalHandler(http.server.BaseHTTPRequestHandler):
    """Serve deterministic responses on the test's loopback socket only."""

    protocol_version = "HTTP/1.1"

    def handle(self) -> None:
        """Allow deliberate client cancellation of the oversized fixture."""
        try:
            super().handle()
        except ConnectionResetError:
            pass

    def do_GET(self) -> None:
        """Return framed bytes, plus an intentionally incomplete fixture."""
        server: Any = self.server
        with server.state_lock:
            server.requests.append(
                (
                    self.path,
                    {key.lower(): value for key, value in self.headers.items()},
                )
            )
        payload = b"x" * 200 if self.path == "/oversize" else b"complete body"
        self.send_response(200)
        length = (
            len(payload) + 50 if self.path == "/incomplete" else len(payload)
        )
        self.send_header("Content-Length", str(length))
        if self.path == "/set-cookie":
            self.send_header("Set-Cookie", "private=fixture; Path=/")
        self.end_headers()
        try:
            self.wfile.write(payload)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        if self.path == "/incomplete":
            self.close_connection = True

    def log_message(self, *_args: Any) -> None:
        """Keep expected local HTTP fixtures out of the test output."""


class LocalServer(http.server.ThreadingHTTPServer):
    """Count accepted sockets to distinguish reuse from repeated requests."""

    daemon_threads = True

    def __init__(self) -> None:
        self.state_lock = threading.Lock()
        self.connections = 0
        self.requests: list[tuple[str, dict[str, str]]] = []
        super().__init__(("127.0.0.1", 0), LocalHandler)

    def get_request(self) -> Any:
        """Count new TCP connections independently of descriptor reuse."""
        connection = super().get_request()
        with self.state_lock:
            self.connections += 1
        return connection


class EfficiencyFixture(unittest.TestCase):
    """Keep cache and network state local to each independent test."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        for owner, name, options in (
            (CONFIG, "CACHE_DIR", {"new": str(self.root / "cache")}),
            (CONFIG, "_host_last", {"new": {}}),
            (SERVER, "_user_agent", {"return_value": "offline-efficiency"}),
        ):
            patch: Any = unittest.mock.patch.object(owner, name, **options)
            patch.start()
            self.addCleanup(patch.stop)

        guard = unittest.mock.patch.object(
            TRANSPORT.urllib.request,
            "build_opener",
            side_effect=AssertionError("unexpected external HTTP request"),
        )
        guard.start()
        self.addCleanup(guard.stop)

    def budget(self, **limits: Any) -> Any:
        """Construct a controller without installing its request context."""
        return BUDGETS._RequestBudget(
            BUDGETS._validated_budget(limits), lambda _usage: None
        )

    def call(self, controller: Any = None, **options: Any) -> Any:
        """Run one request in the given invocation's request-budget context."""
        token = BUDGETS._request_budget.set(controller)
        try:
            return TRANSPORT._http(PUBLIC_URL, cache=False, **options)
        finally:
            BUDGETS._request_budget.reset(token)


class ThrottleTest(EfficiencyFixture):
    """A slow registry must not serialize unrelated registry requests."""

    def test_waiting_host_does_not_block_another_host(self) -> None:
        sleeping = threading.Event()
        release = threading.Event()
        CONFIG._host_last["slow.example"] = time.monotonic()

        def wait(_seconds: float) -> None:
            sleeping.set()
            if not release.wait(3):
                raise AssertionError("test did not release throttle waiter")

        with (
            unittest.mock.patch.object(
                CONFIG,
                "_HOST_INTERVAL",
                {"slow.example": 10.0, "fast.example": 0.0},
            ),
            unittest.mock.patch.object(
                BUDGETS, "_budget_sleep", side_effect=wait
            ),
            concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor,
        ):
            slow = executor.submit(TRANSPORT._throttle, "slow.example")
            try:
                self.assertTrue(sleeping.wait(2))
                fast = executor.submit(TRANSPORT._throttle, "fast.example")
                fast.result(timeout=1)
                self.assertFalse(slow.done())
            finally:
                release.set()
            slow.result(timeout=2)

    def test_same_host_keeps_its_minimum_interval(self) -> None:
        clock = [100.0]

        def wait(seconds: float) -> None:
            clock[0] += seconds

        with (
            unittest.mock.patch.object(
                CONFIG, "_HOST_INTERVAL", {"one.example": 2.0}
            ),
            unittest.mock.patch.object(
                TRANSPORT.time, "monotonic", side_effect=lambda: clock[0]
            ),
            unittest.mock.patch.object(
                BUDGETS, "_budget_sleep", side_effect=wait
            ) as sleeping,
        ):
            TRANSPORT._throttle("one.example")
            TRANSPORT._throttle("one.example")
        sleeping.assert_called_once_with(2.0)
        self.assertEqual(CONFIG._host_last["one.example"], 102.0)


class CoalescingTest(EfficiencyFixture):
    """Share only identical GET work within one invocation budget."""

    def pair(
        self,
        first: dict[str, Any],
        second: dict[str, Any],
        first_budget: Any,
        second_budget: Any,
        shared: bool,
    ) -> tuple[list[Any], int]:
        """Hold the leader until a waiter or another request is observed."""
        opened = threading.Event()
        second_open = threading.Event()
        release = threading.Event()
        count_lock = threading.Lock()
        count = 0

        def open_request(*_args: Any, **_kwargs: Any) -> Response:
            nonlocal count
            with count_lock:
                count += 1
                if count == 2:
                    second_open.set()
            opened.set()
            if not release.wait(3):
                raise AssertionError("test did not release HTTP leader")
            return Response()

        opener = unittest.mock.Mock()
        opener.open.side_effect = open_request
        with (
            unittest.mock.patch.object(TRANSPORT, "_throttle"),
            unittest.mock.patch.object(
                TRANSPORT.urllib.request, "build_opener", return_value=opener
            ),
            concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor,
        ):
            leader = executor.submit(self.call, first_budget, **first)
            try:
                self.assertTrue(opened.wait(2))
                follower = executor.submit(self.call, second_budget, **second)
                if shared:
                    end = time.monotonic() + 2
                    while first_budget.usage().get("coalesced_waits", 0) < 1:
                        if follower.done():
                            follower.result()
                        if time.monotonic() >= end:
                            self.fail(
                                "identical caller did not join active work"
                            )
                        time.sleep(0.005)
                    self.assertEqual(count, 1)
                else:
                    self.assertTrue(second_open.wait(2))
            finally:
                release.set()
            results = [leader.result(timeout=2), follower.result(timeout=2)]
        return results, count

    def test_same_budget_identical_get_uses_one_physical_request(self) -> None:
        budget = self.budget(max_requests=1)
        result, opened = self.pair({}, {}, budget, budget, shared=True)
        self.assertEqual(result, [(200, "fixture response")] * 2)
        self.assertEqual(opened, 1)
        self.assertEqual(budget.usage()["requests"], 1)
        self.assertEqual(budget.usage()["coalesced_waits"], 1)
        self.assertEqual(budget.usage()["http_cache_hits"], 0)

    def test_different_invocation_budgets_never_share_work(self) -> None:
        first, second = self.budget(max_requests=1), self.budget(max_requests=1)
        _, opened = self.pair({}, {}, first, second, shared=False)
        self.assertEqual(opened, 2)
        self.assertEqual(first.usage()["requests"], 1)
        self.assertEqual(second.usage()["requests"], 1)
        self.assertEqual(first.usage()["coalesced_waits"], 0)
        self.assertEqual(second.usage()["coalesced_waits"], 0)

    def test_unbudgeted_calls_do_not_share_work(self) -> None:
        _, opened = self.pair({}, {}, None, None, shared=False)
        self.assertEqual(opened, 2)

    def test_credentials_representation_and_limits_are_isolated(self) -> None:
        cases: list[tuple[dict[str, Any], dict[str, Any]]] = [
            (
                {"headers": {"Authorization": "Bearer A"}},
                {"headers": {"Authorization": "Bearer B"}},
            ),
            ({"headers": {"Cookie": "a=1"}}, {"headers": {"Cookie": "a=2"}}),
            (
                {"headers": {"Accept": "text/plain"}},
                {"headers": {"Accept": "application/json"}},
            ),
            ({"max_bytes": 100}, {"max_bytes": 200}),
            ({"binary": False}, {"binary": True}),
            ({"timeout": 10}, {"timeout": 11}),
            ({"retries": 1}, {"retries": 2}),
            ({"data": b"A"}, {"data": b"B"}),
        ]
        for first, second in cases:
            with self.subTest(first=first, second=second):
                budget = self.budget(max_requests=2)
                _, opened = self.pair(
                    first, second, budget, budget, shared=False
                )
                self.assertEqual(opened, 2)
                self.assertEqual(budget.usage()["requests"], 2)

    def test_post_requests_are_never_coalesced(self) -> None:
        budget = self.budget(max_requests=2)
        _, opened = self.pair(
            {"method": "POST", "data": b"same"},
            {"method": "POST", "data": b"same"},
            budget,
            budget,
            shared=False,
        )
        self.assertEqual(opened, 2)

    def test_failure_releases_waiters_and_allows_a_later_request(self) -> None:
        budget = self.budget(max_requests=3)
        started, release = threading.Event(), threading.Event()

        def failing(*_args: Any, **_kwargs: Any) -> Response:
            started.set()
            if not release.wait(3):
                raise AssertionError("leader not released")
            raise urllib.error.URLError("fixture outage")

        opener = unittest.mock.Mock()
        opener.open.side_effect = failing
        with (
            unittest.mock.patch.object(TRANSPORT, "_throttle"),
            unittest.mock.patch.object(
                TRANSPORT.urllib.request, "build_opener", return_value=opener
            ),
            concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor,
        ):
            leader = executor.submit(self.call, budget, retries=1)
            self.assertTrue(started.wait(2))
            follower = executor.submit(self.call, budget, retries=1)
            try:
                end = time.monotonic() + 2
                while budget.usage().get("coalesced_waits", 0) < 1:
                    if time.monotonic() >= end:
                        self.fail("waiter did not join failed leader")
                    time.sleep(0.005)
            finally:
                release.set()
            for future in (leader, follower):
                with self.assertRaises(RuntimeError):
                    future.result(timeout=2)
            opener.open.side_effect = None
            opener.open.return_value = Response(b"recovered")
            self.assertEqual(self.call(budget, retries=1), (200, "recovered"))
        self.assertEqual(opener.open.call_count, 2)
        self.assertEqual(budget.usage()["requests"], 2)
        self.assertFalse(TRANSPORT._flights)

    def test_waiter_respects_shared_deadline_without_new_request(self) -> None:
        budget = self.budget(max_requests=2, max_seconds=0.2)
        started, release = threading.Event(), threading.Event()

        def held(*_args: Any, **_kwargs: Any) -> Response:
            started.set()
            if not release.wait(3):
                raise AssertionError("leader not released")
            return Response()

        opener = unittest.mock.Mock()
        opener.open.side_effect = held
        with (
            unittest.mock.patch.object(TRANSPORT, "_throttle"),
            unittest.mock.patch.object(
                TRANSPORT.urllib.request, "build_opener", return_value=opener
            ),
            concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor,
        ):
            leader = executor.submit(self.call, budget)
            self.assertTrue(started.wait(2))
            follower = executor.submit(self.call, budget)
            try:
                with self.assertRaises(BUDGETS.BudgetExhaustedError):
                    follower.result(timeout=1)
            finally:
                release.set()
            with self.assertRaises(BUDGETS.BudgetExhaustedError):
                leader.result(timeout=2)
        self.assertEqual(opener.open.call_count, 1)
        self.assertEqual(budget.usage()["requests"], 1)
        self.assertFalse(TRANSPORT._flights)


class RetryAndCacheTest(EfficiencyFixture):
    """Bound attempts and isolate cached representations and credentials."""

    def test_invalid_attempt_or_timeout_configuration_is_rejected(self) -> None:
        for options in [
            *({"retries": value} for value in (0, 6, True, 1.5)),
            *(
                {"timeout": value}
                for value in (0, -1, True, float("inf"), float("nan"))
            ),
        ]:
            with self.subTest(options=options):
                with self.assertRaises(ValueError):
                    self.call(**options)

    def test_retry_after_is_finite_nonnegative_and_capped(self) -> None:
        for value in (None, "-1", "nan", "inf", "not a date", "9" * 5000):
            with self.subTest(value=str(value)[:20]):
                delay = TRANSPORT._retry_delay(value, 1)
                self.assertGreaterEqual(delay, 0)
                self.assertLessEqual(delay, 30)
        self.assertEqual(TRANSPORT._retry_delay("1.5", 1), 1.5)
        self.assertEqual(TRANSPORT._retry_delay("3000", 1), 30)
        with unittest.mock.patch.object(
            TRANSPORT.time, "time", return_value=1000
        ):
            self.assertEqual(
                TRANSPORT._retry_delay(
                    email.utils.formatdate(1008, usegmt=True), 1
                ),
                8,
            )
            self.assertEqual(
                TRANSPORT._retry_delay(
                    email.utils.formatdate(900, usegmt=True), 1
                ),
                0,
            )

    def test_post_failure_is_sent_once_even_when_retries_requested(
        self,
    ) -> None:
        opener = unittest.mock.Mock()
        opener.open.side_effect = urllib.error.URLError("fixture outage")
        with (
            unittest.mock.patch.object(TRANSPORT, "_throttle"),
            unittest.mock.patch.object(BUDGETS, "_budget_sleep") as sleeping,
            unittest.mock.patch.object(
                TRANSPORT.urllib.request, "build_opener", return_value=opener
            ),
        ):
            with self.assertRaises(RuntimeError):
                self.call(method="POST", data=b"export", retries=5)
        self.assertEqual(opener.open.call_count, 1)
        sleeping.assert_not_called()

    def test_cache_does_not_cross_credentials_or_representation(self) -> None:
        opener = unittest.mock.Mock()
        opener.open.side_effect = [
            Response(b"one"),
            Response(b"two"),
            Response(b"json"),
        ]
        with (
            unittest.mock.patch.object(TRANSPORT, "_throttle"),
            unittest.mock.patch.object(
                TRANSPORT.urllib.request, "build_opener", return_value=opener
            ),
        ):
            first = {"Authorization": "Bearer first", "Accept": "text/plain"}
            second = {"Authorization": "Bearer second", "Accept": "text/plain"}
            other = {
                "Authorization": "Bearer first",
                "Accept": "application/json",
            }
            self.assertEqual(
                TRANSPORT._http(PUBLIC_URL, headers=first), (200, "one")
            )
            self.assertEqual(
                TRANSPORT._http(PUBLIC_URL, headers=second), (200, "two")
            )
            self.assertEqual(
                TRANSPORT._http(PUBLIC_URL, headers=other), (200, "json")
            )
            self.assertEqual(
                TRANSPORT._http(PUBLIC_URL, headers=first), (200, "one")
            )
        self.assertEqual(opener.open.call_count, 3)
        for artifact in (self.root / "cache" / "http").glob("*.json"):
            raw = artifact.read_text()
            self.assertNotIn("Bearer first", raw)
            self.assertNotIn("Bearer second", raw)


class ConnectionReuseTest(unittest.TestCase):
    """Exercise actual HTTP/1.1 sockets only against a local test server."""

    def setUp(self) -> None:
        if importlib.util.find_spec("httpx") is None:
            self.skipTest("httpx is required to test connection reuse")
        self.pool = importlib.import_module("cite_check_engine.network_pool")
        self.pool.close_pool()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.local = LocalServer()
        self.thread = threading.Thread(
            target=self.local.serve_forever, daemon=True
        )
        self.thread.start()
        self.addCleanup(self.local.server_close)
        self.addCleanup(self.thread.join, 2)
        self.addCleanup(self.local.shutdown)
        self.addCleanup(self.pool.close_pool)
        port = self.local.server_address[1]
        self.url = f"http://127.0.0.1:{port}"
        for patch in (
            unittest.mock.patch.object(
                CONFIG, "CACHE_DIR", self.temporary.name
            ),
            unittest.mock.patch.object(TRANSPORT, "_throttle"),
            unittest.mock.patch.dict(
                os.environ,
                {
                    "NO_PROXY": "127.0.0.1,localhost",
                    "no_proxy": "127.0.0.1,localhost",
                },
            ),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def request(self, path: str, **options: Any) -> Any:
        """Send one bounded request to the local HTTP/1.1 fixture."""
        return TRANSPORT._http(
            self.url + path, cache=False, timeout=2, retries=1, **options
        )

    def test_sequential_requests_reuse_one_tcp_connection(self) -> None:
        for path in ("/one", "/two", "/three"):
            self.assertEqual(self.request(path), (200, "complete body"))
        self.assertEqual(len(self.local.requests), 3)
        self.assertEqual(self.local.connections, 1)
        for _, headers in self.local.requests:
            self.assertEqual(headers.get("accept-encoding"), "identity")

    def test_oversize_response_is_discarded_before_next_request(self) -> None:
        with self.assertRaises(RuntimeError):
            self.request("/oversize", max_bytes=20)
        self.assertEqual(self.request("/after"), (200, "complete body"))
        self.assertEqual(self.local.connections, 2)

    def test_incomplete_response_cannot_poison_next_reused_request(
        self,
    ) -> None:
        with self.assertRaises(RuntimeError):
            self.request("/incomplete")
        self.assertEqual(self.request("/after"), (200, "complete body"))
        self.assertEqual(self.local.connections, 2)

    def test_response_cookies_are_not_forwarded_between_calls(self) -> None:
        self.request("/set-cookie", headers={"Authorization": "Bearer first"})
        self.request("/second", headers={"Authorization": "Bearer second"})
        self.request("/third")
        self.assertEqual(
            self.local.requests[0][1].get("authorization"), "Bearer first"
        )
        self.assertEqual(
            self.local.requests[1][1].get("authorization"), "Bearer second"
        )
        self.assertNotIn("authorization", self.local.requests[2][1])
        self.assertTrue(
            all("cookie" not in headers for _, headers in self.local.requests)
        )

    def test_environment_proxy_is_used_once_without_external_resolution(
        self,
    ) -> None:
        real_lookup = socket.getaddrinfo

        def loopback_only(host: Any, *args: Any, **kwargs: Any) -> Any:
            if host not in ("127.0.0.1", b"127.0.0.1"):
                raise AssertionError("proxy test tried external DNS")
            return real_lookup(host, *args, **kwargs)

        self.pool.close_pool()
        with (
            unittest.mock.patch.dict(
                os.environ,
                {
                    "HTTP_PROXY": self.url,
                    "http_proxy": self.url,
                    "ALL_PROXY": self.url,
                    "all_proxy": self.url,
                    "NO_PROXY": "",
                    "no_proxy": "",
                },
            ),
            unittest.mock.patch.object(
                socket, "getaddrinfo", side_effect=loopback_only
            ),
        ):
            result = TRANSPORT._http(
                "http://citation-fixture.invalid/resource",
                cache=False,
                timeout=2,
                retries=1,
            )
        self.assertEqual(result, (200, "complete body"))
        self.assertEqual(self.local.connections, 1)
        self.assertEqual(
            self.local.requests[0][0],
            "http://citation-fixture.invalid/resource",
        )
        self.assertEqual(
            self.local.requests[0][1]["host"], "citation-fixture.invalid"
        )

    def test_explicit_pool_close_requires_a_new_connection(self) -> None:
        self.request("/before")
        self.pool.close_pool()
        self.request("/after")
        self.assertEqual(self.local.connections, 2)


if __name__ == "__main__":
    unittest.main()
