# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.16.0
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---
"""CI gates reject missing coverage and isolate optional live providers."""

# %%
import contextlib
import email.message
import importlib.metadata
import importlib.util
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import types
from typing import Any
import unittest
import unittest.mock
import urllib.error

HERE = pathlib.Path(__file__).resolve().parent


def load_helper(name: str) -> types.ModuleType:
    """Load one standalone helper without modifying the interpreter path."""
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load CI helper {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNNER = load_helper("run_regression")
LIVE = load_helper("public_live_probes")


# %%
class RegressionGateTest(unittest.TestCase):
    """Missing dependencies, skipped cases and empty suites fail the gate."""

    def test_expected_installed_sdk_major_passes(self) -> None:
        major = int(importlib.metadata.version("mcp").split(".")[0])
        RUNNER.preflight(major)

    def test_wrong_installed_sdk_major_fails(self) -> None:
        major = int(importlib.metadata.version("mcp").split(".")[0])
        with self.assertRaises(RuntimeError):
            RUNNER.preflight(2 if major == 1 else 1)

    def test_missing_required_imports_are_not_skipped(self) -> None:
        original = importlib.import_module
        major = int(importlib.metadata.version("mcp").split(".")[0])
        for missing in ("mcp", "pypdf", "httpx"):
            with self.subTest(missing=missing):

                def import_module(
                    name: str,
                    package: str | None = None,
                    missing_name: str = missing,
                ) -> Any:
                    if name == missing_name:
                        raise ModuleNotFoundError(missing_name)
                    return original(name, package)

                with (
                    unittest.mock.patch.object(
                        RUNNER.importlib,
                        "import_module",
                        side_effect=import_module,
                    ),
                    self.assertRaises(RuntimeError),
                ):
                    RUNNER.preflight(major)

    def test_missing_sdk_distribution_metadata_fails(self) -> None:
        with (
            unittest.mock.patch.object(
                RUNNER.importlib.metadata,
                "version",
                side_effect=importlib.metadata.PackageNotFoundError("mcp"),
            ),
            self.assertRaises(RuntimeError),
        ):
            RUNNER.preflight(1)

    def test_runner_rejects_empty_suite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(RUNNER.run_suite(pathlib.Path(directory)), 1)

    def test_runner_executes_and_rejects_skip_failure_or_error(self) -> None:
        variants = {
            "pass": ("self.assertTrue(True)", 0),
            "skip": ("self.skipTest('missing required dependency')", 1),
            "failure": ("self.assertTrue(False)", 1),
            "error": ("raise RuntimeError('broken contract')", 1),
        }
        for name, (body, expected) in variants.items():
            with (
                self.subTest(name=name),
                tempfile.TemporaryDirectory() as directory,
            ):
                path = pathlib.Path(directory)
                module_name = "test_ci_fixture_" + name
                (path / f"{module_name}.py").write_text(
                    "import unittest\n"
                    "class Fixture(unittest.TestCase):\n"
                    "    def test_case(self):\n"
                    f"        {body}\n"
                )
                try:
                    with contextlib.redirect_stderr(io.StringIO()):
                        self.assertEqual(RUNNER.run_suite(path), expected)
                finally:
                    sys.modules.pop(module_name, None)
                    if str(path) in sys.path:
                        sys.path.remove(str(path))

    def test_runner_cli_requires_supported_sdk_selection(self) -> None:
        for arguments in ([], ["--sdk-major", "3"]):
            with self.subTest(arguments=arguments):
                result = subprocess.run(
                    [
                        sys.executable,
                        str(HERE / "run_regression.py"),
                        *arguments,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                self.assertEqual(result.returncode, 2)

    def test_preflight_failure_prevents_test_execution(self) -> None:
        with (
            unittest.mock.patch.object(
                RUNNER, "preflight", side_effect=RuntimeError("missing SDK")
            ),
            unittest.mock.patch.object(RUNNER, "run_suite") as suite,
        ):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(RUNNER.main(["--sdk-major", "1"]), 2)
        suite.assert_not_called()

    def test_cli_smoke_refuses_invalid_interpreter_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            invalid = str(pathlib.Path(directory) / "missing-python")
            result = subprocess.run(
                ["bash", str(HERE / "verify_mcp.sh")],
                env=dict(os.environ, CITE_CHECK_TEST_PYTHON=invalid),
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        self.assertEqual(result.returncode, 2)
        self.assertIn("CITE_CHECK_TEST_PYTHON", result.stderr)
        self.assertNotIn("PASS", result.stdout)


# %%
class PublicProbeSafetyTest(unittest.TestCase):
    """Live probes require explicit opt-in and classify provider uncertainty."""

    def test_live_main_requires_opt_in_before_network(self) -> None:
        with unittest.mock.patch.object(LIVE, "run_probes") as probes:
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    LIVE.main([])
        self.assertEqual(raised.exception.code, 2)
        probes.assert_not_called()

    def test_live_probe_rejects_unknown_target_before_network(self) -> None:
        with unittest.mock.patch.object(
            LIVE.urllib.request, "build_opener"
        ) as opener:
            with self.assertRaises(ValueError):
                LIVE.probe("crossref", "https://attacker.invalid/private")
        opener.assert_not_called()

    def test_live_main_nonzero_for_unavailable_or_contract_failure(
        self,
    ) -> None:
        for outcome in ("unavailable", "contract-failure"):
            with self.subTest(outcome=outcome):
                result = {"ok": False, "probes": [{"outcome": outcome}]}
                output = io.StringIO()
                with unittest.mock.patch.object(
                    LIVE, "run_probes", return_value=result
                ):
                    with contextlib.redirect_stdout(output):
                        self.assertEqual(LIVE.main(["--live"]), 1)
                self.assertEqual(json.loads(output.getvalue()), result)

    def test_live_main_success_preserves_machine_readable_result(self) -> None:
        result = {"ok": True, "probes": [{"outcome": "available"}]}
        output = io.StringIO()
        with unittest.mock.patch.object(
            LIVE, "run_probes", return_value=result
        ):
            with contextlib.redirect_stdout(output):
                self.assertEqual(LIVE.main(["--live"]), 0)
        self.assertEqual(json.loads(output.getvalue()), result)


# %%
class ProbeResponse(io.BytesIO):
    """Track every read while mimicking a bounded HTTP response."""

    def __init__(self, data: bytes, status: int = 200) -> None:
        super().__init__(data)
        self.status = status
        self.read_sizes: list[int] = []

    def read(self, size: int | None = -1) -> bytes:
        """Reject unbounded drains, including error and redirect bodies."""
        if size is None or size < 0:
            raise AssertionError("unbounded probe read")
        self.read_sizes.append(size)
        return super().read(size)


class PublicProbeResponseTest(unittest.TestCase):
    """Use synthetic HTTP responses exclusively, without external traffic."""

    def call_probe(
        self, response: ProbeResponse, provider: str = "crossref"
    ) -> tuple[dict[str, Any], unittest.mock.MagicMock]:
        """Execute the probe through its real request and body parser."""
        opener = unittest.mock.MagicMock()
        opener.open.return_value = response
        with unittest.mock.patch.object(
            LIVE.urllib.request, "build_opener", return_value=opener
        ):
            result = LIVE.probe(provider, LIVE.PROBES[provider])
        return result, opener

    def test_real_provider_body_shapes_succeed_anonymously(self) -> None:
        bodies = {
            "crossref": b'{"message":{"DOI":"10.1103/PhysRev.47.777"}}',
            "datacite": (
                b'{"data":{"attributes":{"doi":"10.5281/zenodo.3509134"}}}'
            ),
            "arxiv": (
                b'<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
                b"<id>http://arxiv.org/abs/1706.03762v7</id></entry></feed>"
            ),
        }
        for provider, body in bodies.items():
            with self.subTest(provider=provider):
                response = ProbeResponse(body)
                result, opener = self.call_probe(response, provider)
                self.assertEqual(result["outcome"], "available")
                request = opener.open.call_args.args[0]
                self.assertEqual(request.full_url, LIVE.PROBES[provider])
                self.assertIsNone(request.get_header("Authorization"))
                self.assertIsNone(request.get_header("Cookie"))
                self.assertEqual(opener.open.call_args.kwargs["timeout"], 15)
                self.assertEqual(opener.open.call_count, 1)
                self.assertTrue(response.closed)

    def test_malformed_and_wrong_identity_are_contract_failures(self) -> None:
        for body in (
            b"not JSON",
            b"[]",
            b'{"message":null}',
            b'{"message":{"DOI":"10.1234/wrong"}}',
            b"\xff",
        ):
            with self.subTest(body=body):
                response = ProbeResponse(body)
                result, _ = self.call_probe(response)
                self.assertEqual(result["outcome"], "contract-failure")
                self.assertTrue(response.closed)

    def test_large_response_is_read_only_to_bound_and_closed(self) -> None:
        response = ProbeResponse(b"x" * (LIVE.MAX_BYTES + 100))
        result, _ = self.call_probe(response)
        self.assertEqual(result["outcome"], "contract-failure")
        self.assertEqual(response.read_sizes, [LIVE.MAX_BYTES + 1])
        self.assertTrue(response.closed)

    def test_http_outages_are_separate_from_contract_failures(self) -> None:
        for code, expected in (
            (429, "unavailable"),
            (503, "unavailable"),
            (403, "unavailable"),
            (404, "contract-failure"),
            (302, "contract-failure"),
        ):
            with self.subTest(code=code):
                body = ProbeResponse(b"secret provider diagnostic")
                error = urllib.error.HTTPError(
                    LIVE.PROBES["crossref"],
                    code,
                    "error",
                    email.message.Message(),
                    body,
                )
                opener = unittest.mock.MagicMock()
                opener.open.side_effect = error
                with unittest.mock.patch.object(
                    LIVE.urllib.request, "build_opener", return_value=opener
                ):
                    result = LIVE.probe("crossref", LIVE.PROBES["crossref"])
                self.assertEqual(result["outcome"], expected)
                self.assertEqual(result["status"], code)
                self.assertNotIn("secret provider", json.dumps(result))
                self.assertEqual(body.read_sizes, [])
                self.assertTrue(body.closed)
                self.assertEqual(opener.open.call_count, 1)

    def test_timeout_and_connection_failure_are_unavailable(self) -> None:
        for error in (TimeoutError("secret"), urllib.error.URLError("secret")):
            with self.subTest(error=error):
                opener = unittest.mock.MagicMock()
                opener.open.side_effect = error
                with unittest.mock.patch.object(
                    LIVE.urllib.request, "build_opener", return_value=opener
                ):
                    result = LIVE.probe("crossref", LIVE.PROBES["crossref"])
                self.assertEqual(result["outcome"], "unavailable")
                self.assertNotIn("secret", json.dumps(result))
                self.assertEqual(opener.open.call_count, 1)

    def test_redirect_handler_never_follows_or_reads_response(self) -> None:
        response = ProbeResponse(b"redirect body")
        request = LIVE.urllib.request.Request(LIVE.PROBES["crossref"])
        handler = LIVE.NoRedirect()
        redirected = handler.redirect_request(
            request, response, 302, "Found", {}, "https://attacker.invalid/"
        )
        self.assertIsNone(redirected)
        self.assertEqual(response.read_sizes, [])
        response.close()

    def test_run_probes_reports_each_provider_and_failure_independently(
        self,
    ) -> None:
        results = [
            {"outcome": "available"},
            {"outcome": "unavailable"},
            {"outcome": "contract-failure"},
        ]
        with unittest.mock.patch.object(
            LIVE, "probe", side_effect=results
        ) as probe:
            report = LIVE.run_probes()
        self.assertFalse(report["ok"])
        self.assertEqual(report["kind"], "provider-availability")
        self.assertEqual(report["results"], results)
        self.assertEqual(
            probe.call_args_list,
            [
                unittest.mock.call(name, url)
                for name, url in LIVE.PROBES.items()
            ],
        )


# %%
if __name__ == "__main__":
    unittest.main()
