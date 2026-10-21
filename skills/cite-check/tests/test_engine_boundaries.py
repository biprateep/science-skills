"""Regression contracts for the package extraction at baseline 128b049."""

import ast
import asyncio
import dataclasses
import hashlib
import importlib
import importlib.util
import inspect
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import typing
from typing import Any
import unittest
import unittest.mock

MCP_ROOT = pathlib.Path(__file__).parents[1] / "mcp"
ENTRY = MCP_ROOT / "server.py"
MODULES = (
    "models",
    "config",
    "budgets",
    "identifiers",
    "text",
    "persistence",
    "parsing",
    "credentials",
    "transport",
    "registry_clients",
    "resolution",
    "discovery",
    "bibliography",
    "manuscripts",
    "acquisition",
    "evidence",
    "findings",
    "reports",
    "freshness",
    "audit",
    "reporting",
    "jobs",
    "api",
    "admin",
)

# Captured before extraction using actual MCP1 and MCP2 tool registration;
# both SDKs generated exactly the same complete input schemas.
SCHEMA_DIGESTS = {
    "audit": (
        "f2a4afc982b9c53f53c5c6ccc5de8c0f307ed0b448cf8e31c71a1f84435e52a4"
    ),
    "bib_add": (
        "d8c1e3d26659e4a32e17da0f05435c4a838bee03c9edc62c8ab3f5f4c0475f04"
    ),
    "correction_report": (
        "ec62d2e9049712941fec9ed7dea3a6e28dff67963421fa4ff4fa95462d1a302c"
    ),
    "extract_cites": (
        "d2bf4fcec67706cdf9560dda72e224d09853634a9a20a6d036ee88e94696723b"
    ),
    "fetch_bibtex": (
        "56d96f6d0d71b91c26565a9f9bc2bd757b8713527307d20f089c08d45d0cbad4"
    ),
    "fetch_text": (
        "71af13b270b6a70a87003ea22b925ad560f0d648242f8cbc2ff45c39775b1e75"
    ),
    "find_passages": (
        "74867d467f5977f9c2d4ca68a8dadd40efadd6d8aeb9c31f2ff6b5d8b752090b"
    ),
    "ledger_read": (
        "bdb30ed576ff2a09f57bc8c97db9a81e00c1999816af2d656f0d1f765a1e177b"
    ),
    "lint_bib": (
        "cee2d94850028c981ca8109916872c59927b326f4bcf33246503090837837b4f"
    ),
    "ping": (
        "a08e3ed81ab89920d7ec41146f410550a78f65b43ca540b5c9e9c046e996a66a"
    ),
    "record_support": (
        "24fda7b1ba7219ec13f2fb698630bc1f1d15f308876a6bc75acd12b0527070a9"
    ),
    "register_claims": (
        "1d21707c0a2d3cdc685ef5e435a7d7b9cbdbb50199911fe6fae01e3c482e7342"
    ),
    "register_input": (
        "d0f5bd8f518e46c508270aecf90ebbb4f08472713e918237ca5aa3f051bef437"
    ),
    "resolve_citation": (
        "765189ac1665fda6859b70a18f9bd19b87a068d2869813c4296ddc2e4d7f3cad"
    ),
    "search_citation": (
        "a181966b349af67230efddd977017d73a71f2d7681210c1c35c4803cda133973"
    ),
    "verification_job": (
        "5df8c4edd3a5efbb9c2d6167894756d7ed60cd6024f48be5c8a365045bd611da"
    ),
    "verify_bib": (
        "0fcd444869ec743b5fac108064bcb8cfdf6c071dccc8ca671669263326c9e1a8"
    ),
}

PUBLIC_SIGNATURES = {
    "audit": (
        "(tex_path: str, bib_path: str | None = None, require_support: "
        "bool = True, verify: bool = True, policy: "
        "Literal['exploratory', 'submission-ready'] = "
        "'submission-ready') -> dict[str, typing.Any]"
    ),
    "bib_add": (
        "(bib_path: str, items: list[BibliographyItem | str], prefer: "
        "list[str] | None = None, journal_format: int | None = None, "
        "tex_path: str | None = None, replace: bool = False, max_author: "
        "int = 10) -> dict"
    ),
    "correction_report": (
        "(tex_path: str, bib_path: str | None = None, policy: "
        "Literal['exploratory', 'submission-ready'] = "
        "'submission-ready', annotated: bool = False, verify: bool = "
        "True, require_support: bool = True) -> dict[str, typing.Any]"
    ),
    "extract_cites": ("(tex_path: str) -> dict[str, typing.Any]"),
    "fetch_bibtex": (
        "(identifier: str, key: str | None = None, prefer: list[str] | "
        "None = None, journal_format: int | None = None, tex_path: str | "
        "None = None, max_author: int = 10, version: str | None = None) "
        "-> dict"
    ),
    "fetch_text": (
        "(identifier: str, pdf_path: str | None = None, text_path: str | "
        "None = None, refresh: bool = False, max_chars: int = 0, "
        "version: str | None = None) -> dict"
    ),
    "find_passages": (
        "(identifier: str, claims: list[str] | str, k: int = 6, window: "
        "int = 2, version: str | None = None) -> dict"
    ),
    "ledger_read": ("(workdir: str) -> dict"),
    "lint_bib": (
        "(bib_path: str, keys: list[str] | None = None, verify: bool = "
        "False) -> dict[str, typing.Any]"
    ),
    "ping": ("() -> dict"),
    "record_support": (
        "(workdir: str, key: str, claim: str, verdict: str, identifier: "
        "str, quotes: list[str] | None = None, note: str | None = None, "
        "judge: str | None = None, file: str | None = None, line: int | "
        "None = None, context: str | None = None, version: str | None = "
        "None, tex_path: str | None = None, occurrence_id: str | None = "
        "None, atom_id: str | None = None, proposed_correction: "
        "ProposedCorrection | None = None) -> dict"
    ),
    "register_claims": (
        "(tex_path: str, sentence_id: str, atoms: list[AtomicClaim]) -> dict"
    ),
    "register_input": (
        "(tex_path: str, citations: list[InputCitation], reason: str) -> "
        "dict[str, typing.Any]"
    ),
    "resolve_citation": ("(identifier: str | list[str]) -> dict"),
    "search_citation": (
        "(query: str | None = None, title: str | None = None, author: "
        "str | None = None, year: int | None = None, hint: str | None = "
        "None, context: str | None = None, registries: list[str] | None "
        "= None, max_results: int = 8) -> dict[str, typing.Any]"
    ),
    "verification_job": (
        "(tex_path: str, bib_path: str | None = None, job_id: str | None "
        "= None, operation: Literal['run', 'status'] = 'run', budget: "
        "VerificationBudget | None = None, priorities: "
        "list[ClaimPriority] | None = None, search_unresolved: bool | "
        "None = None) -> dict[str, typing.Any]"
    ),
    "verify_bib": (
        "(bib_path: str, keys: list[str] | None = None, tex_path: str | "
        "None = None, search_unresolved: bool = True) -> dict"
    ),
}


class EngineBoundariesTest(unittest.TestCase):
    """Check ownership and wire contracts independently of the test proxy."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        self.environment = dict(
            os.environ,
            PYTHONDONTWRITEBYTECODE="1",
            CITE_CHECK_CACHE=str(self.root / "cache"),
            XDG_CONFIG_HOME=str(self.root / "config"),
            CITE_CHECK_KEYRING="off",
        )
        self.environment.pop("PYTHONPATH", None)
        if str(MCP_ROOT) not in sys.path:
            sys.path.insert(0, str(MCP_ROOT))
            self.addCleanup(sys.path.remove, str(MCP_ROOT))
        self.api = importlib.import_module("cite_check_engine.api")

    def execute(
        self, arguments: list[str], data: bytes | None = None
    ) -> subprocess.CompletedProcess[bytes]:
        """Execute a bounded offline child from an unrelated directory."""
        return subprocess.run(
            [sys.executable, *arguments],
            input=data,
            cwd=self.root,
            env=self.environment,
            capture_output=True,
            timeout=20,
            check=False,
        )

    def python(self, source: str) -> dict[str, Any]:
        """Run a fresh import scenario and return its one JSON response."""
        setup = f"import sys\nsys.path.insert(0, {str(MCP_ROOT)!r})\n"
        result = self.execute(["-c", setup + source])
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        return json.loads(result.stdout)

    def test_all_public_signatures_preserve_arguments_defaults_and_types(
        self,
    ) -> None:
        self.assertEqual(set(self.api.TOOLS), set(PUBLIC_SIGNATURES))
        for name, expected in PUBLIC_SIGNATURES.items():
            with self.subTest(tool=name):
                actual = str(inspect.signature(self.api.TOOLS[name]))
                actual = actual.replace("cite_check_engine.models.", "")
                self.assertEqual(actual, expected)

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "MCP SDK unavailable")
    def test_complete_native_input_schemas_match_the_pre_refactor_contract(
        self,
    ) -> None:
        async def schemas() -> dict[str, Any]:
            try:
                server_class = importlib.import_module("mcp.server").MCPServer
            except AttributeError:
                server_class = importlib.import_module(
                    "mcp.server.fastmcp"
                ).FastMCP
            app = server_class("engine-boundary-fixture")
            for function in self.api.TOOLS.values():
                app.tool()(function)
            return {
                tool.name: tool.model_dump(by_alias=True)["inputSchema"]
                for tool in await app.list_tools()
            }

        actual = asyncio.run(schemas())
        self.assertEqual(set(actual), set(SCHEMA_DIGESTS))
        for name, schema in actual.items():
            encoded = json.dumps(schema, sort_keys=True, separators=(",", ":"))
            self.assertEqual(
                hashlib.sha256(encoded.encode()).hexdigest(),
                SCHEMA_DIGESTS[name],
                f"Wire schema changed for {name}: {encoded}",
            )

    def test_independent_module_imports_need_no_server_or_optional_sdk(
        self,
    ) -> None:
        for first in MODULES:
            with self.subTest(first=first):
                result = self.python(
                    "import builtins, importlib, json, socket, sys\n"
                    "original = builtins.__import__\n"
                    "def guarded(name, *args, **kwargs):\n"
                    "    if name.split('.')[0] in {'mcp', 'pypdf'}:\n"
                    "        raise ImportError('optional dependency blocked')\n"
                    "    return original(name, *args, **kwargs)\n"
                    "builtins.__import__ = guarded\n"
                    "def no_network(*args, **kwargs):\n"
                    "    raise AssertionError('network during import')\n"
                    "socket.socket.connect = no_network\n"
                    "socket.create_connection = no_network\n"
                    f"importlib.import_module('cite_check_engine.{first}')\n"
                    f"names = {MODULES!r}\n"
                    "for name in names:\n"
                    "    importlib.import_module('cite_check_engine.' + name)\n"
                    "print(json.dumps({'server': 'server' in sys.modules, "
                    "'sdk': 'mcp' in sys.modules}))\n"
                )
                self.assertEqual(result, {"server": False, "sdk": False})
        self.assertFalse((self.root / "cache").exists())
        self.assertFalse((self.root / "config").exists())

    def test_public_tools_are_actual_owner_functions(self) -> None:
        for name, function in self.api.TOOLS.items():
            with self.subTest(tool=name):
                owner = importlib.import_module(function.__module__)
                self.assertTrue(
                    function.__module__.startswith("cite_check_engine.")
                )
                self.assertIs(getattr(owner, name), function)
                self.assertNotEqual(
                    function.__module__, "cite_check_engine.api"
                )

    def test_engine_owner_import_aliases_are_never_shadowed(self) -> None:
        for path in sorted((MCP_ROOT / "cite_check_engine").glob("*.py")):
            with self.subTest(module=path.name):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                owner_imports = [
                    alias
                    for node in tree.body
                    if isinstance(node, (ast.Import, ast.ImportFrom))
                    for alias in node.names
                    if alias.asname and alias.asname.startswith("_engine_")
                ]
                aliases = {alias.asname for alias in owner_imports}
                shadows = []
                for node in ast.walk(tree):
                    name = None
                    if isinstance(node, ast.arg):
                        name = node.arg
                    elif isinstance(node, ast.Name) and isinstance(
                        node.ctx, (ast.Store, ast.Del)
                    ):
                        name = node.id
                    elif isinstance(
                        node,
                        (
                            ast.ExceptHandler,
                            ast.FunctionDef,
                            ast.AsyncFunctionDef,
                            ast.ClassDef,
                            ast.MatchAs,
                            ast.MatchStar,
                        ),
                    ):
                        name = node.name
                    elif isinstance(node, ast.MatchMapping):
                        name = node.rest
                    elif (
                        isinstance(node, ast.alias)
                        and node not in owner_imports
                    ):
                        name = node.asname or node.name.split(".")[0]
                    if name in aliases:
                        line = getattr(node, "lineno", "unknown")
                        shadows.append(f"{name} at line {line}")
                self.assertEqual(shadows, [], f"{path.name}: {shadows}")

    def test_repeated_entrypoint_alias_imports_do_not_duplicate_engine_state(
        self,
    ) -> None:
        result = self.python(
            "import importlib, importlib.util, json, sys\n"
            "models = importlib.import_module('cite_check_engine.models')\n"
            "budgets = importlib.import_module('cite_check_engine.budgets')\n"
            "config = importlib.import_module('cite_check_engine.config')\n"
            "before = (models.InputCitation, budgets._request_budget, "
            "config._host_lock)\n"
            f"path = {str(ENTRY)!r}\n"
            "for name in ('first_entry', 'second_entry'):\n"
            "    spec = importlib.util.spec_from_file_location(name, path)\n"
            "    module = importlib.util.module_from_spec(spec)\n"
            "    spec.loader.exec_module(module)\n"
            "after = (models.InputCitation, budgets._request_budget, "
            "config._host_lock)\n"
            "print(json.dumps({'same': "
            "all(a is b for a,b in zip(before, after)), "
            "'alternate_models': [name for name in sys.modules "
            "if name.endswith('.models') and 'cite' in name]}))\n"
        )
        self.assertTrue(result["same"])
        self.assertEqual(
            result["alternate_models"], ["cite_check_engine.models"]
        )

    def test_cli_resolve_and_invalid_search_work_from_arbitrary_directory(
        self,
    ) -> None:
        for tool, arguments, field in (
            (
                "resolve_citation",
                {"identifier": "not-an-identifier"},
                "resolved",
            ),
            (
                "search_citation",
                {"query": "Example", "registries": []},
                "error",
            ),
        ):
            with self.subTest(tool=tool):
                process = self.execute(
                    [str(ENTRY), "call", tool, json.dumps(arguments)]
                )
                self.assertEqual(process.returncode, 1, process.stderr.decode())
                result = json.loads(process.stdout)
                self.assertEqual(result, self.api.TOOLS[tool](**arguments))
                self.assertIn(field, result)

    def test_symlink_entrypoint_preserves_cli_and_key_dispatch(self) -> None:
        entry = self.root / "linked-cite-check.py"
        entry.symlink_to(ENTRY)
        result = self.execute([str(entry), "keys", "names"])
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertIn("semanticscholar", result.stdout.decode().splitlines())
        process = self.execute(
            [
                str(entry),
                "call",
                "search_citation",
                json.dumps({"query": "Example", "registries": []}),
            ]
        )
        self.assertEqual(process.returncode, 1, process.stderr.decode())
        self.assertEqual(json.loads(process.stdout)["candidates"], [])

    def test_cli_rejects_malformed_json_without_creating_artifacts(
        self,
    ) -> None:
        result = self.execute(
            [str(ENTRY), "call", "extract_cites", "{bad-json"]
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid JSON args", result.stderr.decode())
        self.assertEqual(result.stdout, b"")
        self.assertEqual(list(self.root.iterdir()), [])

    @unittest.skipUnless(importlib.util.find_spec("pypdf"), "pypdf unavailable")
    def test_pdf_worker_runs_through_real_and_symlink_entrypoints(self) -> None:
        pypdf = importlib.import_module("pypdf")
        writer = pypdf.PdfWriter()
        writer.add_blank_page(width=100, height=100)
        buffer = io.BytesIO()
        writer.write(buffer)
        raw = buffer.getvalue()
        linked = self.root / "linked-pdf-worker.py"
        linked.symlink_to(ENTRY)
        for entry in (ENTRY, linked):
            with self.subTest(entry=entry):
                process = self.execute([str(entry), "_extract-pdf"], raw)
                self.assertEqual(process.returncode, 0, process.stderr.decode())
                result = json.loads(process.stdout)
                self.assertEqual(result["pages"], [{"page": 1, "text": ""}])
                self.assertEqual(result["extractor"]["name"], "pypdf")
        manuscripts = importlib.import_module("cite_check_engine.manuscripts")
        direct = manuscripts._input_pdf_extract(raw)
        self.assertEqual(direct["pages"], [{"page": 1, "text": ""}])

    def test_shared_request_dataclasses_keep_nested_public_identity(
        self,
    ) -> None:
        models = importlib.import_module("cite_check_engine.models")
        for name in (
            "BibliographyItem",
            "InputCitation",
            "AtomicClaim",
            "ProposedCorrection",
            "VerificationBudget",
            "ClaimPriority",
        ):
            with self.subTest(model=name):
                model = getattr(models, name)
                self.assertTrue(dataclasses.is_dataclass(model))
                self.assertEqual(model.__module__, "cite_check_engine.models")
        for tool, parameter, model_name in (
            ("register_input", "citations", "InputCitation"),
            ("register_claims", "atoms", "AtomicClaim"),
            ("verification_job", "budget", "VerificationBudget"),
            ("record_support", "proposed_correction", "ProposedCorrection"),
        ):
            annotation = typing.get_type_hints(self.api.TOOLS[tool])[parameter]
            self.assertIn(
                getattr(models, model_name), typing.get_args(annotation)
            )
        request = models.InputCitation(start=0, end=3, key="a", marker="[1]")
        path = self.root / "paper.txt"
        path.write_text("[1] confirms this finding.", encoding="utf-8")
        registered = self.api.TOOLS["register_input"](
            str(path), [request], "The author mapped this observed reference."
        )
        self.assertTrue(registered["registered"], registered)
        extracted = self.api.TOOLS["extract_cites"](str(path))
        self.assertEqual(extracted["keys"], ["a"])
        self.assertTrue(extracted["review_only"])

    def test_invalid_dataclass_values_still_fail_at_wire_boundary(self) -> None:
        models = importlib.import_module("cite_check_engine.models")
        path = self.root / "paper.txt"
        path.write_text("[1] confirms this finding.", encoding="utf-8")
        for request in (
            models.InputCitation(start=True, end=3, key="a", marker="[1]"),
            models.InputCitation(start=0, end=99, key="a", marker="[1]"),
        ):
            result = self.api.TOOLS["register_input"](
                str(path),
                [request],
                "The author mapped this observed reference.",
            )
            self.assertFalse(result["registered"], result)
        self.assertFalse((self.root / ".cite-check").exists())

    def test_adapter_discovery_and_transport_share_budget_and_cache_state(
        self,
    ) -> None:
        budgets = importlib.import_module("cite_check_engine.budgets")
        config = importlib.import_module("cite_check_engine.config")
        credentials = importlib.import_module("cite_check_engine.credentials")
        transport = importlib.import_module("cite_check_engine.transport")
        controller = budgets._RequestBudget(
            budgets._validated_budget({"max_requests": 1}), lambda _usage: None
        )
        token = budgets._request_budget.set(controller)
        self.addCleanup(budgets._request_budget.reset, token)
        response = io.BytesIO(b'{"data": []}')
        response.status = 200  # type: ignore[attr-defined]
        opener = unittest.mock.Mock()
        opener.open.return_value = response
        cache = self.root / "shared-cache"
        with (
            unittest.mock.patch.object(config, "CACHE_DIR", str(cache)),
            unittest.mock.patch.object(
                credentials, "key_value", return_value=(None, None)
            ),
            unittest.mock.patch.object(
                transport.urllib.request, "build_opener", return_value=opener
            ),
            unittest.mock.patch.object(transport, "_throttle"),
        ):
            for _ in range(2):
                result = self.api.TOOLS["search_citation"](
                    title="Fictional shared-state example",
                    registries=["semanticscholar"],
                )
                self.assertEqual(result["errors"], {}, result)
        self.assertEqual(opener.open.call_count, 1)
        self.assertEqual(controller.usage()["requests"], 1)
        self.assertEqual(controller.usage()["searches"], 2)
        self.assertEqual(controller.usage()["http_cache_hits"], 1)
        self.assertEqual(len(list(cache.rglob("*.json"))), 1)

    def test_invalid_nested_claim_dataclass_cannot_register_coverage(
        self,
    ) -> None:
        models = importlib.import_module("cite_check_engine.models")
        path = self.root / "paper.md"
        path.write_text("A measured result [@a].", encoding="utf-8")
        extracted = self.api.TOOLS["extract_cites"](str(path))
        sentence = extracted["sentences"][0]
        invalid = models.AtomicClaim(
            start=True,
            end=len(sentence["claim"]),
            citation_ids=sentence["citation_ids"],
        )
        rejected = self.api.TOOLS["register_claims"](
            str(path), sentence["sentence_id"], [invalid]
        )
        self.assertFalse(rejected["ok"], rejected)

    def test_legacy_test_patch_routes_to_and_restores_real_owner(self) -> None:
        legacy = importlib.import_module("test_evidence").SERVER
        transport = importlib.import_module("cite_check_engine.transport")
        credentials = importlib.import_module("cite_check_engine.credentials")
        budgets = importlib.import_module("cite_check_engine.budgets")
        models = importlib.import_module("cite_check_engine.models")
        original = transport._get_json
        self.assertIs(legacy._request_budget, budgets._request_budget)
        self.assertIs(legacy.InputCitation, models.InputCitation)
        with (
            unittest.mock.patch.object(
                legacy, "_get_json", return_value=(200, {"data": []})
            ) as request,
            unittest.mock.patch.object(
                credentials, "key_value", return_value=(None, None)
            ),
        ):
            self.assertIs(transport._get_json, request)
            result = self.api.TOOLS["search_citation"](
                title="A fictional owner-routing example",
                registries=["semanticscholar"],
            )
            self.assertEqual(result["errors"], {}, result)
            request.assert_called_once()
        self.assertIs(transport._get_json, original)

    def test_typed_workflow_values_keep_plain_json_and_required_fields(
        self,
    ) -> None:
        models = importlib.import_module("cite_check_engine.models")
        registries = importlib.import_module(
            "cite_check_engine.registry_clients"
        )
        identifiers = importlib.import_module("cite_check_engine.identifiers")
        evidence = importlib.import_module("cite_check_engine.evidence")
        resolution = importlib.import_module("cite_check_engine.resolution")
        persistence = importlib.import_module("cite_check_engine.persistence")
        work = registries._record(
            doi="10.1234/EXAMPLE", title="Fictional source", registry="crossref"
        )
        self.assertEqual(work["doi"], "10.1234/example")
        path = self.root / "paper.md"
        path.write_text("The rate rises [@a].", encoding="utf-8")
        extracted = self.api.TOOLS["extract_cites"](str(path))
        sentence = extracted["sentences"][0]
        citations = extracted["cites"]
        atoms = evidence._validated_atoms(
            sentence,
            citations,
            [
                {
                    "start": 0,
                    "end": len(sentence["claim"]),
                    "citation_ids": sentence["citation_ids"],
                }
            ],
        )
        source = self.root / "source.txt"
        quote = "The rate rises in this experiment."
        source.write_text(quote, encoding="utf-8")
        metadata = {
            "id": "doi:10.1234/example",
            "basis": "fulltext",
            "source": "local:source.txt",
            "path": str(source),
            "intake": importlib.import_module("test_evidence").source_intake(
                source
            ),
        }
        snapshot = identifiers._source_identity(metadata, quote)
        with (
            unittest.mock.patch.object(
                resolution, "_full_record", return_value=work
            ),
            unittest.mock.patch.object(
                persistence, "_load_text_meta", return_value=metadata
            ),
        ):
            saved = self.api.TOOLS["record_support"](
                str(self.root),
                "a",
                sentence["claim"],
                "SUPPORTS",
                "doi:10.1234/example",
                quotes=[quote],
                judge="independent-fixture-reader",
            )
        self.assertTrue(saved["recorded"], saved)
        judgment = self.api.TOOLS["ledger_read"](str(self.root))["ledger"][
            "entries"
        ][saved["ledger_id"]]
        self.assertEqual(judgment["source_identity"], snapshot)
        for model_name, value in (
            ("Work", work),
            ("CitationInstance", citations[0]),
            ("Claim", atoms[0]),
            ("SourceSnapshot", snapshot),
            ("Judgment", judgment),
        ):
            with self.subTest(model=model_name):
                model = getattr(models, model_name)
                self.assertTrue(typing.is_typeddict(model))
                self.assertTrue(model.__required_keys__ <= set(value))
                self.assertIs(type(value), dict)
                self.assertEqual(json.loads(json.dumps(value)), value)
        self.assertIs(
            typing.get_type_hints(registries._record)["return"], models.Work
        )
        self.assertIs(
            typing.get_type_hints(identifiers._source_identity)["return"],
            models.SourceSnapshot,
        )
        self.assertEqual(
            typing.get_args(
                typing.get_type_hints(evidence._validated_atoms)["return"]
            ),
            (models.Claim,),
        )
        self.assertEqual(
            typing.get_args(
                typing.get_type_hints(evidence._validated_atoms)["cites"]
            ),
            (models.CitationInstance,),
        )


if __name__ == "__main__":
    unittest.main()
