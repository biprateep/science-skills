"""Regression tests for audit finding 5: truthful, current report compilation."""

import importlib.util
import json
import pathlib
import shutil
import subprocess
import tempfile
import unittest
import unittest.mock

_SPEC = importlib.util.spec_from_file_location(
    "scientist_server", pathlib.Path(__file__).parents[1] / "mcp/server.py"
)
SERVER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(SERVER)


class ReportGateTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        self.tex = self.root / "report.tex"
        self.tex.write_text(
            r"\documentclass{article}\begin{document}Hello.\end{document}",
            encoding="utf-8",
        )

    def extract(self, tool, arguments):
        if tool == "extract_cites":
            return {"files": [str(self.tex)], "bib_files": [], "cites": []}
        self.assertIs(arguments["verify"], True)
        self.assertIs(arguments["require_support"], True)
        self.assertEqual(arguments["policy"], "submission-ready")
        return {
            "policy": "submission-ready",
            "ok": True,
            "input_complete": True,
            "complete": True,
            "submission_ready": True,
        }

    def fake_latex(self, command, **kwargs):
        (self.root / "report.pdf").write_bytes(b"test pdf")
        (self.root / "report.log").write_text("clean log", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    def test_recursive_missing_figure_and_include(self):
        (self.root / "section.tex").write_text(r"\includegraphics{absent}")
        self.tex.write_text(r"\input{section}")
        result = SERVER.validate_figures(str(self.tex))
        self.assertFalse(result["ok"])
        self.assertEqual(result["missing"][0]["target"], "absent")
        (self.root / "section.tex").unlink()
        self.assertFalse(SERVER.validate_figures(str(self.tex))["ok"])

    def test_failed_tool_exit_cannot_pass_with_pdf(self):
        def fail(command, **kwargs):
            self.fake_latex(command, **kwargs)
            return subprocess.CompletedProcess(command, 1, "undefined command", "")
        with unittest.mock.patch.object(SERVER, "_cite_check_call", self.extract):
            with unittest.mock.patch.object(SERVER.subprocess, "run", fail):
                result = SERVER.compile_report(str(self.root))
        self.assertFalse(result["success"])
        self.assertEqual(result["gate"], "toolchain")

    def test_fresh_audit_blocks_even_with_allow_unverified(self):
        (self.root / "sources.bib").write_text("", encoding="utf-8")
        def citation_call(tool, arguments):
            if tool == "extract_cites":
                return {"files": [str(self.tex)], "cites": [{"key": "a"}],
                        "bib_files": [str(self.root / "sources.bib")]}
            self.assertIs(arguments["verify"], True)
            self.assertIs(arguments["require_support"], True)
            self.assertEqual(arguments["policy"], "submission-ready")
            return {"ok": False, "failures": ["missing support"]}
        with unittest.mock.patch.object(SERVER, "_cite_check_call", citation_call):
            result = SERVER.compile_report(str(self.root), allow_unverified=True)
        self.assertFalse(result["success"])
        self.assertEqual(result["gate"], "citations")

    def test_submission_readiness_requires_exact_policy_and_boolean_flags(self):
        manifest = self.root / "checkpoints/manifest.json"
        manifest.parent.mkdir()
        manifest.write_text(
            json.dumps(
                {
                    "checkpoints": [
                        {
                            "id": "000",
                            "phase": "derivation",
                            "verified": False,
                            "file": "checkpoint_000.md",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        ready = {
            "policy": "submission-ready",
            "ok": True,
            "input_complete": True,
            "complete": True,
            "submission_ready": True,
        }
        invalid = [{"ok": True, "complete": True}]
        for policy in ("exploratory", "Submission-ready", True, None):
            invalid.append(dict(ready, policy=policy))
        missing_policy = ready.copy()
        del missing_policy["policy"]
        invalid.append(missing_policy)
        for flag in ("ok", "input_complete", "complete", "submission_ready"):
            for value in (False, "true", 1, None):
                invalid.append({**ready, flag: value})
            missing = ready.copy()
            del missing[flag]
            invalid.append(missing)
        for audit in invalid:
            with self.subTest(audit=audit):
                extracted = {
                    "files": [str(self.tex)],
                    "cites": [{"key": "a"}],
                    "bib_files": [],
                }
                with (
                    unittest.mock.patch.object(
                        SERVER,
                        "_cite_check_call",
                        side_effect=[extracted, audit],
                    ) as cite_call,
                    unittest.mock.patch.object(SERVER.subprocess, "run") as run,
                ):
                    result = SERVER.compile_report(
                        str(self.root), allow_unverified=True
                    )
                cite_call.assert_called_with(
                    "audit",
                    {
                        "tex_path": str(self.tex),
                        "policy": "submission-ready",
                        "verify": True,
                        "require_support": True,
                    },
                )
                self.assertFalse(result["success"])
                self.assertEqual(result["gate"], "citations")
                self.assertEqual(result["detail"], audit)
                run.assert_not_called()

    def test_submission_ready_audit_allows_compilation(self):
        def citation_call(tool, arguments):
            if tool == "extract_cites":
                return {
                    "files": [str(self.tex)],
                    "cites": [{"key": "a"}],
                    "bib_files": [],
                }
            return self.extract(tool, arguments)

        with (
            unittest.mock.patch.object(
                SERVER, "_cite_check_call", citation_call
            ),
            unittest.mock.patch.object(
                SERVER.subprocess, "run", self.fake_latex
            ),
        ):
            result = SERVER.compile_report(str(self.root))
        self.assertTrue(result["success"])
        self.assertEqual(
            result["gates"]["citations"],
            "passed (fresh submission-ready audit)",
        )

    def test_no_citations_or_bibliography_skips_audit(self):
        with (
            unittest.mock.patch.object(
                SERVER, "_cite_check_call", side_effect=self.extract
            ) as cite_call,
            unittest.mock.patch.object(
                SERVER.subprocess, "run", self.fake_latex
            ),
        ):
            result = SERVER.compile_report(str(self.root))
        self.assertTrue(result["success"])
        self.assertEqual(
            result["gates"]["citations"],
            "passed (no citations or bibliography)",
        )
        cite_call.assert_called_once_with(
            "extract_cites", {"tex_path": str(self.tex)}
        )

    def test_undeclared_input_coverage_blocks(self):
        with unittest.mock.patch.object(
            SERVER, "_cite_check_call", return_value={"files": [], "cites": []}
        ):
            self.assertFalse(SERVER.compile_report(str(self.root))["success"])

    def test_changed_input_invalidates_audit(self):
        def citation_call(tool, arguments):
            if tool == "extract_cites":
                return {
                    "files": [str(self.tex)],
                    "cites": [{"key": "a"}],
                    "bib_files": [],
                }
            return self.extract(tool, arguments)

        def mutate(command, **kwargs):
            self.tex.write_text("changed after audit")
            return self.fake_latex(command, **kwargs)

        with (
            unittest.mock.patch.object(
                SERVER, "_cite_check_call", citation_call
            ),
            unittest.mock.patch.object(SERVER.subprocess, "run", mutate),
        ):
            result = SERVER.compile_report(str(self.root))
        self.assertFalse(result["success"])
        self.assertEqual(result["gate"], "inputs_changed")

    def test_declared_bibliography_selects_bibtex_not_report_bib(self):
        bib = self.root / "references.bib"
        bib.write_text("", encoding="utf-8")
        self.tex.write_text(r"\bibliography{references}")
        def citation_call(tool, arguments):
            if tool == "extract_cites":
                return {"files": [str(self.tex)], "cites": [{"key": "a"}],
                        "bib_files": [str(bib)]}
            return self.extract(tool, arguments)
        with unittest.mock.patch.object(SERVER, "_cite_check_call", citation_call):
            with unittest.mock.patch.object(
                SERVER.subprocess, "run", self.fake_latex
            ):
                result = SERVER.compile_report(str(self.root))
        self.assertTrue(result["success"])
        self.assertIn("bibtex", [c["command"] for c in result["commands"]])

    def test_citation_subprocess_uses_json_and_checks_exit(self):
        with unittest.mock.patch.object(
            SERVER.subprocess, "run", return_value=subprocess.CompletedProcess(
                [], 1, json.dumps({"ok": True}), "failure"
            )
        ):
            self.assertIn("error", SERVER._cite_check_call("audit", {}))

    @unittest.skipUnless(shutil.which("pdflatex"), "pdflatex unavailable")
    def test_real_latex_errors_and_unresolved_references(self):
        for body in (r"\unknowncommand", r"See section~\ref{missing}."):
            with self.subTest(body=body):
                self.tex.write_text(
                    r"\documentclass{article}\begin{document}"
                    + body + r"\end{document}", encoding="utf-8"
                )
                result = SERVER.compile_report(str(self.root))
                self.assertFalse(result["success"])

    def test_real_unaudited_citation_is_blocked(self):
        self.tex.write_text(
            r"\documentclass{article}\begin{document}Claim\cite{absent}."
            r"\bibliography{sources}\end{document}", encoding="utf-8"
        )
        (self.root / "sources.bib").write_text("", encoding="utf-8")
        result = SERVER.compile_report(str(self.root))
        self.assertFalse(result["success"])
        self.assertEqual(result["gate"], "citations")


if __name__ == "__main__":
    unittest.main()
