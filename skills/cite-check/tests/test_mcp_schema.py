"""Finding 11: batch and nested inputs match their advertised MCP schema."""

import asyncio
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

import test_evidence

SERVER = test_evidence.SERVER


class InputValidationTest(unittest.TestCase):
    def test_invalid_batches_are_rejected_before_lookup(self):
        for value in [[], [None], [""], {}, 42]:
            self.assertIn("error", SERVER.resolve_citation(value))
        self.assertEqual(SERVER.resolve_citation(["not-an-id", "also-invalid"])["n"], 2)

    def test_lint_cli_advice_is_not_readiness(self):
        with tempfile.TemporaryDirectory() as directory:
            bibliography = pathlib.Path(directory) / "refs.bib"
            bibliography.write_text("@article{a,title={Example}}")
            result = subprocess.run(
                [sys.executable, SERVER.__file__, "call", "lint_bib",
                 json.dumps({"bib_path": str(bibliography)})],
                check=True, capture_output=True, text=True,
            )
            report = json.loads(result.stdout)
            self.assertTrue(report["ok"])
            self.assertTrue(report["advisory_only"])
            self.assertFalse(report["advisory_clean"])
            self.assertFalse(report["submission_ready"])
            self.assertIsNone(report["comparison_complete"])

    def test_nested_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            bib = str(pathlib.Path(directory) / "refs.bib")
            for items in [
                [],
                [{}],
                [{"identifier": 7}],
                [{"identifier": "x", "version": 8}],
            ]:
                self.assertFalse(SERVER.bib_add(bib, items)["ok"])
        self.assertIn("error", SERVER.find_passages("x", ["claim"], k=0))
        self.assertFalse(
            SERVER.record_support(".", "x", "claim", "SUPPORTS", "x", quotes="a quote")[
                "recorded"
            ]
        )


@unittest.skipUnless(importlib.util.find_spec("mcp"), "MCP SDK not installed")
class ProtocolSchemaTest(unittest.TestCase):
    def test_stdio_schema_and_batch_call(self):
        asyncio.run(self.check_protocol())

    async def check_protocol(self):
        import mcp
        import mcp.client.stdio

        with tempfile.TemporaryDirectory() as directory:
            environment = dict(
                os.environ,
                CITE_CHECK_CACHE=directory,
                XDG_CONFIG_HOME=directory,
                CITE_CHECK_KEYRING="off",
            )
            for name in ("ADS_API_TOKEN", "ADS_DEV_KEY", "ADS_TOKEN"):
                environment.pop(name, None)
            parameters = mcp.StdioServerParameters(
                command=sys.executable,
                args=[str(pathlib.Path(SERVER.__file__).resolve())],
                env=environment,
            )
            async with mcp.client.stdio.stdio_client(parameters) as streams:
                async with mcp.ClientSession(*streams) as session:
                    await asyncio.wait_for(session.initialize(), 15)
                    listed = (await session.list_tools()).model_dump(by_alias=True)
                    schemas = {
                        tool["name"]: tool["inputSchema"] for tool in listed["tools"]
                    }
                    identifier = schemas["resolve_citation"]["properties"]["identifier"]
                    alternatives = identifier["anyOf"]
                    self.assertEqual(
                        {item["type"] for item in alternatives}, {"string", "array"}
                    )
                    array = next(
                        item for item in alternatives if item["type"] == "array"
                    )
                    self.assertEqual(array["items"]["type"], "string")
                    self.assertIn("identifier", json.dumps(schemas["bib_add"]))
                    self.assertIn("version", json.dumps(schemas["bib_add"]))
                    self.assertEqual(set(schemas), set(SERVER.TOOLS))
                    atomic_schema = json.dumps(schemas["register_claims"])
                    for field in ("start", "end", "citation_ids", "kind", "reason"):
                        self.assertIn(field, atomic_schema)
                    support_fields = schemas["record_support"]["properties"]
                    for field in ("tex_path", "occurrence_id", "atom_id", "proposed_correction"):
                        self.assertIn(field, support_fields)
                    proposal_schema = json.dumps(schemas["record_support"])
                    for field in ("replacement_text", "rationale", "revise-claim", "replace-citation"):
                        self.assertIn(field, proposal_schema)
                    correction_fields = schemas["correction_report"]["properties"]
                    self.assertEqual(correction_fields["policy"]["default"], "submission-ready")
                    self.assertFalse(correction_fields["annotated"]["default"])
                    job_schema = schemas["verification_job"]
                    for field in ("max_requests", "max_searches", "max_seconds", "max_cost_usd", "occurrence_id", "atom_id", "reason", "priority"):
                        self.assertIn(field, json.dumps(job_schema))
                    self.assertEqual(job_schema["properties"]["operation"]["default"], "run")
                    lint_schema = schemas["lint_bib"]
                    self.assertEqual(lint_schema["required"], ["bib_path"])
                    self.assertFalse(lint_schema["properties"]["verify"]["default"])
                    key_schema = lint_schema["properties"]["keys"]["anyOf"]
                    self.assertEqual(
                        next(item for item in key_schema
                             if item["type"] == "array")["items"]["type"],
                        "string",
                    )
                    policy_schema = schemas["audit"]["properties"]["policy"]
                    self.assertEqual(policy_schema["default"], "submission-ready")
                    self.assertEqual(set(policy_schema["enum"]), {"submission-ready", "exploratory"})
                    input_schema = json.dumps(schemas["register_input"])
                    for field in (
                        "tex_path",
                        "citations",
                        "start",
                        "end",
                        "key",
                        "marker",
                        "page",
                        "reason",
                    ):
                        self.assertIn(field, input_schema)
                    plain = pathlib.Path(directory) / "input.txt"
                    plain.write_text("A measured result [1].")
                    mappings = {
                        "tex_path": str(plain),
                        "citations": [
                            {
                                "start": 18,
                                "end": 21,
                                "key": "a",
                                "marker": "[1]",
                            }
                        ],
                        "reason": "The author supplied this exact "
                                  "citation binding.",
                    }
                    native_input = (
                        await session.call_tool("register_input", mappings)
                    ).model_dump(by_alias=True)
                    self.assertFalse(native_input.get("isError", False))
                    input_text = " ".join(
                        item.get("text", "") for item in native_input["content"]
                    )
                    self.assertIn('"registered": true', input_text)
                    direct_input = SERVER.register_input(**mappings)
                    self.assertTrue(direct_input["ok"], direct_input)
                    self.assertEqual(
                        SERVER.extract_cites(str(plain))["keys"], ["a"]
                    )
                    for malformed in (
                        {"start": True},
                        {"start": 18.0},
                        {"page": False},
                        {"extra": 1},
                    ):
                        invalid_mapping = dict(
                            mappings,
                            citations=[
                                dict(mappings["citations"][0], **malformed)
                            ],
                        )
                        rejected = (
                            await session.call_tool(
                                "register_input", invalid_mapping
                            )
                        ).model_dump(by_alias=True)
                        self.assertTrue(
                            rejected.get("isError", False), rejected
                        )
                        self.assertFalse(
                            SERVER.register_input(**invalid_mapping)["ok"]
                        )
                    manuscript = pathlib.Path(directory) / "main.tex"
                    manuscript.write_text(r"A result holds \cite{a}.")
                    extraction = SERVER.extract_cites(str(manuscript))
                    sentence = extraction["sentences"][0]
                    arguments = {
                        "tex_path": str(manuscript),
                        "sentence_id": sentence["sentence_id"],
                        "atoms": [{
                            "start": 0, "end": len(sentence["claim"]),
                            "citation_ids": sentence["citation_ids"],
                        }],
                    }
                    atomic_result = (await session.call_tool(
                        "register_claims", arguments
                    )).model_dump(by_alias=True)
                    self.assertFalse(atomic_result.get("isError", False))
                    atomic_text = " ".join(
                        item.get("text", "") for item in atomic_result["content"]
                    )
                    self.assertIn('"atom_id"', atomic_text)
                    self.assertEqual(
                        SERVER.register_claims(**arguments)["atoms"],
                        SERVER.ledger_read(directory)["ledger"]["decompositions"][
                            sentence["sentence_id"]
                        ]["atoms"],
                    )
                    for malformed in (
                        {"start": False}, {"start": 0.0}, {"unexpected": True}
                    ):
                        invalid = dict(arguments)
                        invalid["atoms"] = [dict(arguments["atoms"][0], **malformed)]
                        refused = (await session.call_tool(
                            "register_claims", invalid
                        )).model_dump(by_alias=True)
                        self.assertTrue(refused.get("isError", False), refused)
                        self.assertFalse(SERVER.register_claims(**invalid)["ok"])
                    audit_result = (await session.call_tool("audit", {
                        "tex_path": str(manuscript), "verify": False,
                        "require_support": False, "policy": "exploratory",
                    })).model_dump(by_alias=True)
                    audit_text = " ".join(item.get("text", "") for item in audit_result["content"])
                    self.assertIn('"submission_ready": false', audit_text)
                    self.assertIn('"coverage"', audit_text)
                    correction_result = (await session.call_tool("correction_report", {
                        "tex_path": str(manuscript), "verify": False,
                        "require_support": False, "policy": "exploratory", "annotated": True,
                    })).model_dump(by_alias=True)
                    correction_text = " ".join(item.get("text", "") for item in correction_result["content"])
                    self.assertIn('"report_written": true', correction_text)
                    self.assertIn('"submission_ready": false', correction_text)
                    self.assertTrue((pathlib.Path(directory) / ".cite-check" / "corrections.html").is_file())
                    for proposal in (
                        {"action": "unknown", "rationale": "A meaningful correction reason."},
                        {"action": "revise-claim", "rationale": "A meaningful correction reason.", "approved": True},
                    ):
                        refused_proposal = (await session.call_tool("record_support", {
                            "workdir": directory, "key": "a", "claim": sentence["claim"],
                            "verdict": "UNSUPPORTED", "identifier": "not-an-id",
                            "proposed_correction": proposal,
                        })).model_dump(by_alias=True)
                        self.assertTrue(refused_proposal.get("isError", False))
                    bibliography = pathlib.Path(directory) / "refs.bib"
                    bibliography.write_text("@article{a,title={Example},doi={10.1234/example}}")
                    lint_result = (await session.call_tool("lint_bib", {
                        "bib_path": str(bibliography), "keys": ["a"],
                    })).model_dump(by_alias=True)
                    self.assertFalse(lint_result.get("isError", False))
                    lint_text = " ".join(item.get("text", "")
                                         for item in lint_result["content"])
                    lint_report = json.loads(lint_text)
                    self.assertTrue(lint_report["advisory_only"])
                    self.assertFalse(lint_report["submission_ready"])
                    self.assertEqual(lint_report,
                                     SERVER.lint_bib(str(bibliography), ["a"]))
                    job_result = (await session.call_tool("verification_job", {
                        "tex_path": str(manuscript), "bib_path": str(bibliography),
                        "budget": {"max_requests": 0, "max_searches": 0},
                    })).model_dump(by_alias=True)
                    job_text = " ".join(item.get("text", "") for item in job_result["content"])
                    self.assertIn('"identity_unchecked": 1', job_text)
                    self.assertIn('"support_pending": 1', job_text)
                    self.assertIn('"submission_ready": false', job_text)
                    saved_job = next((pathlib.Path(directory) / ".cite-check").glob("job-*.json"))
                    job_id = json.loads(saved_job.read_text())["job_id"]
                    status_result = (await session.call_tool("verification_job", {
                        "tex_path": str(manuscript), "job_id": job_id, "operation": "status",
                    })).model_dump(by_alias=True)
                    self.assertFalse(status_result.get("isError", False))
                    status_text = " ".join(item.get("text", "") for item in status_result["content"])
                    self.assertIn('"identity_unchecked": 1', status_text)
                    for invalid_budget in ({"max_requests": True}, {"max_requests": 1.5}, {"max_seconds": True}, {"max_seconds": "1"}, {"max_cost_usd": False}, {"max_cost_usd": "1"}, {"undocumented": 1}):
                        invalid_job = (await session.call_tool("verification_job", {
                            "tex_path": str(manuscript), "budget": invalid_budget,
                        })).model_dump(by_alias=True)
                        self.assertTrue(invalid_job.get("isError", False))
                    refused = (await session.call_tool("audit", {
                        "tex_path": str(manuscript), "policy": "unknown",
                    })).model_dump(by_alias=True)
                    self.assertTrue(refused.get("isError", False))
                    result = (
                        await session.call_tool(
                            "resolve_citation",
                            {"identifier": ["not-an-id", "also-invalid"]},
                        )
                    ).model_dump(by_alias=True)
                    self.assertFalse(result.get("isError", False))
                    content = " ".join(
                        item.get("text", "") for item in result["content"]
                    )
                    self.assertIn('"n"', content)
