"""Finding 11: batch and nested inputs match their advertised MCP schema."""

import asyncio
import importlib.util
import json
import os
import pathlib
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
                    for field in ("tex_path", "occurrence_id", "atom_id"):
                        self.assertIn(field, support_fields)
                    policy_schema = schemas["audit"]["properties"]["policy"]
                    self.assertEqual(policy_schema["default"], "submission-ready")
                    self.assertEqual(set(policy_schema["enum"]), {"submission-ready", "exploratory"})
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
