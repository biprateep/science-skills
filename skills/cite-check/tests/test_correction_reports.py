"""Correction drafts remain bound, unapproved and separate from evidence."""

import html
import json
import pathlib
import re
import subprocess
import sys
from typing import Any
import unittest
import unittest.mock

import test_audit_policies
import test_evidence

SERVER = test_evidence.SERVER


class CorrectionReportsTest(unittest.TestCase):
    """Exercise current, stale and rendered corrections through public tools."""

    # Reuse the fixture without inheriting and re-running its test methods.
    setUp: Any = test_audit_policies.AuditPoliciesTest.setUp
    verify: Any = test_audit_policies.AuditPoliciesTest.verify
    write_bib: Any = test_audit_policies.AuditPoliciesTest.write_bib
    audit: Any = test_audit_policies.AuditPoliciesTest.audit
    tex: pathlib.Path
    bib: pathlib.Path
    source: pathlib.Path
    root: pathlib.Path

    def record_judgment(self, **options: Any) -> dict[str, Any]:
        """Record a proposed correction with a bound independent judgment."""
        cite = SERVER.extract_cites(str(self.tex))["cites"][0]
        arguments = {
            "workdir": str(self.root),
            "key": "a",
            "claim": cite["claim"],
            "verdict": "CONTRADICTS",
            "identifier": "example",
            "context": cite["context"],
            "quotes": [self.source.read_text()],
            "note": "The source gives the opposite direction for this result.",
            "tex_path": str(self.tex),
            "occurrence_id": cite["occurrence_id"],
            "judge": "independent-reader",
            "proposed_correction": {
                "action": "revise-claim",
                "rationale": "Use the direction stated in the source evidence.",
                "replacement_text": "The measurement rises by ten percent.",
            },
        }
        arguments.update(options)
        return SERVER.record_support(**arguments)

    def report(self, **options: Any) -> dict[str, Any]:
        """Create reports with a real fresh audit and mocked registries."""
        return SERVER.correction_report(str(self.tex), str(self.bib), **options)

    def test_current_proposal_has_exact_evidence_but_no_approval(self) -> None:
        self.assertTrue(self.record_judgment()["recorded"])
        report = self.audit()
        item = next(
            item for item in report["corrections"] if item["type"] == "support"
        )
        self.assertEqual(item["proposed_correction"]["approval"], "unapproved")
        self.assertFalse(item["proposed_correction"]["replacement_verified"])
        self.assertFalse(item["applied"])
        evidence = item["source_evidence"]
        self.assertEqual(evidence["attribution"], "verified")
        self.assertEqual(
            evidence["quotes"][0]["source_text"], self.source.read_text()
        )
        self.assertEqual(item["location"]["line"], 1)
        self.assertEqual(
            item["claim"],
            SERVER.extract_cites(str(self.tex))["cites"][0]["claim"],
        )

    def test_invalid_unbound_or_unsupported_proposals_are_refused(self) -> None:
        variants: list[dict[str, Any]] = [
            {"verdict": "SUPPORTS"},
            {"judge": ""},
            {"tex_path": None, "occurrence_id": None},
            {
                "proposed_correction": {
                    "action": "replace-citation",
                    "rationale": (
                        "Identify another source through official records."
                    ),
                    "replacement_text": "10.1234/invented",
                }
            },
            {
                "proposed_correction": {
                    "action": "revise-claim",
                    "rationale": (
                        "The existing source does not establish this result."
                    ),
                    "replacement_text": r"A new claim \cite{invented}.",
                }
            },
            {
                "proposed_correction": {
                    "action": "revise-claim",
                    "rationale": "An explicit correction rationale.",
                    "approved": True,
                }
            },
            {"verdict": "UNSUPPORTED", "quotes": []},
        ]
        for options in variants:
            with self.subTest(options=options):
                self.assertFalse(self.record_judgment(**options)["recorded"])

    def test_stale_source_or_context_suppresses_draft_and_quotes(self) -> None:
        self.record_judgment()
        self.source.write_text("Different source text after a correction.")
        report = self.audit()
        item = next(
            item
            for item in report["corrections"]
            if item["type"] == "support-stale"
        )
        self.assertIsNone(item["source_evidence"])
        self.assertIsNone(item["proposed_correction"])
        self.assertEqual(item["next_action"]["action"], "re-judge")

    def test_identity_unchecked_does_not_certify_attribution(self) -> None:
        self.record_judgment()
        report = self.audit(verify=False, policy="exploratory")
        item = next(
            item for item in report["corrections"] if item["type"] == "support"
        )
        self.assertEqual(item["source_evidence"]["attribution"], "unverified")
        self.assertFalse(report["submission_ready"])

    def test_repeated_occurrences_keep_separate_findings(self) -> None:
        self.tex.write_text(r"A result \cite{a}. A result \cite{a}.")
        report = self.audit()
        items = [
            item
            for item in report["corrections"]
            if item["type"] == "support-missing"
        ]
        self.assertEqual(len(items), 2)
        self.assertNotEqual(
            items[0]["occurrence_id"], items[1]["occurrence_id"]
        )
        self.assertNotEqual(items[0]["finding_id"], items[1]["finding_id"])

    def test_long_assertion_is_not_truncated(self) -> None:
        self.tex.write_text(
            "An exact assertion " + "with qualifiers " * 40 + r"\cite{a}."
        )
        expected = SERVER.extract_cites(str(self.tex))["cites"][0]["claim"]
        report = self.audit()
        item = next(
            item
            for item in report["corrections"]
            if item["type"] == "support-missing"
        )
        self.assertGreater(len(expected), 240)
        self.assertEqual(item["claim"], expected)
        self.assertEqual(item["assertion"], expected)

    def test_atomic_correction_attaches_only_to_its_assertion(self) -> None:
        self.tex.write_text(
            r"The first result holds and the measurement falls \cite{a}."
        )
        extracted = SERVER.extract_cites(str(self.tex))
        cite = extracted["cites"][0]
        split = cite["claim"].index(" and ")
        registered = SERVER.register_claims(
            str(self.tex),
            cite["sentence_id"],
            [
                {
                    "start": 0,
                    "end": split,
                    "citation_ids": [cite["occurrence_id"]],
                },
                {
                    "start": split,
                    "end": len(cite["claim"]),
                    "citation_ids": [cite["occurrence_id"]],
                },
            ],
        )
        self.assertTrue(registered["ok"])
        self.assertTrue(
            self.record_judgment(atom_id=registered["atoms"][1]["atom_id"])[
                "recorded"
            ]
        )
        report = self.audit()
        corrected = next(
            item for item in report["corrections"] if item["type"] == "support"
        )
        missing = next(
            item
            for item in report["corrections"]
            if item["type"] == "support-missing"
        )
        self.assertEqual(corrected["assertion"], registered["atoms"][1]["text"])
        self.assertIsNotNone(corrected["proposed_correction"])
        self.assertIsNone(missing["proposed_correction"])

    def test_missing_proposal_returns_mechanical_advice_only(self) -> None:
        self.record_judgment(proposed_correction=None)
        item = next(
            item
            for item in self.audit()["corrections"]
            if item["type"] == "support"
        )
        self.assertIsNone(item["proposed_correction"])
        self.assertEqual(item["next_action"]["action"], "review-assertion")
        self.assertNotIn("replacement_text", item["next_action"])

    def test_generation_success_keeps_failed_audit_and_original_bytes(
        self,
    ) -> None:
        self.record_judgment()
        originals = {
            path: path.read_bytes()
            for path in (self.tex, self.bib, self.source)
        }
        report = self.report(annotated=True)
        self.assertTrue(report["report_written"])
        self.assertFalse(report["ok"])
        self.assertFalse(report["submission_ready"])
        self.assertEqual(
            set(report["artifacts"]), {"json", "markdown", "annotated"}
        )
        for path, original in originals.items():
            self.assertEqual(path.read_bytes(), original)
        payload = json.loads(
            pathlib.Path(report["artifacts"]["json"]).read_text()
        )
        self.assertEqual(payload["corrections"], report["corrections"])

    def test_html_treats_source_and_draft_as_inert_text(self) -> None:
        self.tex.write_text(
            '<script>alert("source")</script> ' + r"Result \cite{a}."
        )
        self.record_judgment(
            proposed_correction={
                "action": "revise-claim",
                "rationale": "The source supports a different assertion.",
                "replacement_text": (
                    '<img src="https://example.invalid/x" onerror="alert(1)">'
                ),
            }
        )
        report = self.report(annotated=True)
        rendered = pathlib.Path(report["artifacts"]["annotated"]).read_text()
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("<img ", rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn("Content-Security-Policy", rendered)
        self.assertIn('id="source-0-line-1"', rendered)

    def test_changed_source_while_rendering_suppresses_artifact(self) -> None:
        self.record_judgment()
        original = SERVER._corrections_markdown

        def changed(report: dict[str, Any]) -> str:
            result = original(report)
            self.source.write_text("Changed during report rendering.")
            return result

        with unittest.mock.patch.object(
            SERVER, "_corrections_markdown", changed
        ):
            report = self.report()
        self.assertFalse(report["report_written"])
        self.assertFalse(report["submission_ready"])
        self.assertFalse(report["artifacts"])
        self.assertTrue(
            all(
                item["source_evidence"] is None
                for item in report["corrections"]
            )
        )

    def test_audit_staleness_suppresses_all_current_evidence(self) -> None:
        self.record_judgment()
        original = SERVER._correction_items

        def changed(*args: Any) -> list[dict[str, Any]]:
            result = original(*args)
            self.source.write_text("Changed after evidence was gathered.")
            return result

        with unittest.mock.patch.object(SERVER, "_correction_items", changed):
            report = self.audit()
        self.assertFalse(report["submission_ready"])
        self.assertTrue(
            all(
                item["source_evidence"] is None
                for item in report["corrections"]
            )
        )
        self.assertTrue(
            all(
                item["proposed_correction"] is None
                for item in report["corrections"]
            )
        )

    def test_pipeline_output_alias_is_rejected_before_audit(self) -> None:
        directory = self.root / ".cite-check"
        directory.mkdir(exist_ok=True)
        victim = directory / "audit.md"
        victim.write_text("Original included manuscript.")
        self.tex.write_text(r"\input{.cite-check/audit.md}")
        before = victim.read_bytes()
        with unittest.mock.patch.object(SERVER, "audit") as audit:
            result = self.report()
        self.assertFalse(result["report_written"])
        audit.assert_not_called()
        self.assertEqual(victim.read_bytes(), before)

    def test_symlinked_output_directory_is_refused(self) -> None:
        target = self.root / "other"
        target.mkdir()
        (self.root / ".cite-check").rename(self.root / "original-cite-check")
        (self.root / ".cite-check").symlink_to(target, target_is_directory=True)
        with unittest.mock.patch.object(SERVER, "audit") as audit:
            report = self.report()
        self.assertFalse(report["report_written"])
        audit.assert_not_called()
        self.assertEqual(list(target.iterdir()), [])

    def test_failed_input_has_honest_unknown_location_and_action(self) -> None:
        self.tex.write_text(r"\input{absent}")
        report = self.report()
        self.assertTrue(report["report_written"])
        self.assertNotIn("annotated", report["artifacts"])
        item = report["corrections"][0]
        self.assertIsNone(item["location"]["line"])
        self.assertIsNone(item["source_evidence"])
        self.assertEqual(item["next_action"]["action"], "repair-input")

    def test_cli_exploratory_report_is_generated_without_readiness(
        self,
    ) -> None:
        process = subprocess.run(
            [
                sys.executable,
                str(SERVER.__file__),
                "call",
                "correction_report",
                json.dumps(
                    {
                        "tex_path": str(self.tex),
                        "bib_path": str(self.bib),
                        "verify": False,
                        "require_support": False,
                        "policy": "exploratory",
                        "annotated": True,
                    }
                ),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        report = json.loads(process.stdout)
        self.assertTrue(report["report_written"])
        self.assertFalse(report["submission_ready"])

    def test_malformed_stored_quotes_and_proposals_fail_closed(self) -> None:
        self.record_judgment()
        ledger_path = self.root / ".cite-check" / "ledger.json"
        original = ledger_path.read_text()
        for field, malformed in (
            ("quotes", None),
            ("quotes", ["invented"]),
            ("proposed_correction", {"approval": True}),
        ):
            with self.subTest(field=field, value=malformed):
                ledger = json.loads(original)
                next(iter(ledger["entries"].values()))[field] = malformed
                ledger_path.write_text(json.dumps(ledger))
                report = self.report()
                self.assertFalse(report["ok"])
                self.assertFalse(report["complete"])
                self.assertTrue(report["report_written"])
                self.assertTrue(
                    all(
                        item["source_evidence"] is None
                        for item in report["corrections"]
                    )
                )
                self.assertTrue(
                    all(
                        item["proposed_correction"] is None
                        for item in report["corrections"]
                    )
                )

    def test_quote_spans_are_rechecked_instead_of_trusting_ledger(self) -> None:
        self.record_judgment()
        path = self.root / ".cite-check" / "ledger.json"
        ledger = json.loads(path.read_text())
        entry = next(iter(ledger["entries"].values()))
        entry["quotes"][0]["source_text"] = (
            "An invented quote never present in source."
        )
        entry["quotes"][0]["at"] = 999
        path.write_text(json.dumps(ledger))
        item = next(
            item
            for item in self.audit()["corrections"]
            if item["type"] == "support"
        )
        self.assertEqual(
            item["source_evidence"]["quotes"][0]["source_text"],
            self.source.read_text(),
        )
        self.assertEqual(item["source_evidence"]["quotes"][0]["at"], 0)
        entry["quotes"][0]["text"] = (
            "A different invented quote not found anywhere."
        )
        path.write_text(json.dumps(ledger))
        item = next(
            item
            for item in self.audit()["corrections"]
            if item["type"] == "support"
        )
        self.assertIsNone(item["source_evidence"])
        self.assertIsNone(item["proposed_correction"])

    def test_non_string_correction_action_is_cleanly_refused(self) -> None:
        self.assertFalse(
            self.record_judgment(
                proposed_correction={
                    "action": [],
                    "rationale": "A meaningful correction rationale.",
                }
            )["recorded"]
        )

    def test_annotated_links_preserve_separate_occurrences_and_source(
        self,
    ) -> None:
        self.tex.write_bytes(
            "α <tag> \\cite{a}.\r\nα <tag> \\cite{a}.\r\n".encode()
        )
        original = self.tex.read_bytes()
        report = self.report(annotated=True)
        rendered = (
            pathlib.Path(report["artifacts"]["annotated"]).read_bytes().decode()
        )
        items = [
            item
            for item in report["corrections"]
            if item["type"] == "support-missing"
        ]
        self.assertEqual(len(items), 2)
        for item in items:
            self.assertIn(f'id="finding-{item["finding_id"]}"', rendered)
            self.assertIn(f'href="#finding-{item["finding_id"]}"', rendered)
            self.assertIn(
                f'href="#source-0-line-{item["location"]["line"]}"', rendered
            )
        source_lines = re.findall(
            r'<code class="source-text">(.*?)</code>', rendered, re.DOTALL
        )
        reconstructed = "".join(
            html.unescape(line) for line in source_lines[:2]
        )
        self.assertEqual(reconstructed.encode(), original)
        self.assertEqual(self.tex.read_bytes(), original)

    def test_bibliography_locations_include_duplicate_and_unused_entries(
        self,
    ) -> None:
        self.bib.write_text(
            self.bib.read_text()
            + "\n@article{b,title={Unused}}\n@article{b,title={Repeated}}"
        )
        report = self.report(annotated=True)
        item = next(
            item
            for item in report["corrections"]
            if item["type"] == "uncited-entry"
        )
        self.assertIsNone(item["location"]["file"])
        self.assertEqual(len(item["bibliography_locations"]), 2)
        raw = self.bib.read_bytes()
        for location in item["bibliography_locations"]:
            self.assertEqual(location["file"], str(self.bib))
            span = raw[
                location["source_byte_start"] : location["source_byte_end"]
            ]
            self.assertTrue(span.startswith(b"@article{b,"))
            rendered = pathlib.Path(
                report["artifacts"]["annotated"]
            ).read_text()
            self.assertIn(f'href="#source-1-line-{location["line"]}"', rendered)

    def test_uncited_scope_preserves_sentence_context_without_attribution(
        self,
    ) -> None:
        self.tex.write_text(
            r"This extension is our inference and the result holds \cite{a}."
        )
        extracted = SERVER.extract_cites(str(self.tex))
        cite = extracted["cites"][0]
        split = cite["claim"].index(" and ")
        registered = SERVER.register_claims(
            str(self.tex),
            cite["sentence_id"],
            [
                {
                    "start": 0,
                    "end": split,
                    "citation_ids": [],
                    "kind": "uncited",
                    "reason": "This extension is the author's inference.",
                },
                {
                    "start": split,
                    "end": len(cite["claim"]),
                    "citation_ids": [cite["occurrence_id"]],
                },
            ],
        )
        self.assertTrue(registered["ok"])
        item = next(
            item
            for item in self.audit()["corrections"]
            if item["type"] == "uncited-atom"
        )
        self.assertEqual(item["context"], cite["context"])
        self.assertIsNone(item["occurrence_id"])
        self.assertIsNone(item["source_evidence"])
        self.assertEqual(item["next_action"]["action"], "review-scope")

    def test_markdown_filename_is_fenced_as_inert_json(self) -> None:
        report = self.audit()
        item = report["corrections"][0]
        item["location"]["file"] = "![image](https://example.invalid/x)```<img>"
        rendered = SERVER._corrections_markdown(report)
        fenced = re.search(
            r"Location:\n(`+)json\n(.*?)\n\1", rendered, re.DOTALL
        )
        assert fenced is not None
        self.assertEqual(json.loads(fenced[2]), item["location"])
        self.assertGreater(len(fenced[1]), 3)

    def test_cache_input_alias_is_refused_before_audit(self) -> None:
        self.record_judgment()
        output = self.root / ".cite-check" / "corrections.md"
        output.hardlink_to(self.source)
        before = self.source.read_bytes()
        with unittest.mock.patch.object(SERVER, "audit") as audit:
            report = self.report()
        self.assertFalse(report["report_written"])
        audit.assert_not_called()
        self.assertEqual(self.source.read_bytes(), before)

    def test_verification_output_alias_is_refused_before_audit(self) -> None:
        directory = self.root / ".cite-check"
        directory.mkdir(exist_ok=True)
        (directory / "verify.json").hardlink_to(self.bib)
        before = self.bib.read_bytes()
        with unittest.mock.patch.object(SERVER, "audit") as audit:
            report = self.report()
        self.assertFalse(report["report_written"])
        audit.assert_not_called()
        self.assertEqual(self.bib.read_bytes(), before)

    def test_structured_finding_detail_is_escaped_without_crashing(
        self,
    ) -> None:
        self.record_judgment()
        path = self.root / ".cite-check" / "ledger.json"
        ledger = json.loads(path.read_text())
        next(iter(ledger["entries"].values()))["note"] = {
            "detail": "<script>inert</script>"
        }
        path.write_text(json.dumps(ledger))
        report = self.report(annotated=True)
        self.assertTrue(report["report_written"])
        rendered = pathlib.Path(report["artifacts"]["annotated"]).read_text()
        self.assertIn("&lt;script&gt;inert&lt;/script&gt;", rendered)
        self.assertNotIn("<script>", rendered)

    def test_safe_workspace_symlink_ancestor_is_portable(self) -> None:
        alias = self.root / "workspace-alias"
        alias.symlink_to(self.root, target_is_directory=True)
        result = SERVER.correction_report(
            str(alias / self.tex.name),
            str(alias / self.bib.name),
            annotated=True,
        )
        self.assertTrue(result["report_written"], result)
        self.assertTrue(
            pathlib.Path(result["artifacts"]["annotated"]).is_file()
        )
