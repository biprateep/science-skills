"""Explicit citation coverage and policy gates never hide unchecked work."""

import json
import pathlib
import subprocess
import sys
import tempfile
from typing import Any
import unittest
import unittest.mock

import test_evidence

SERVER = test_evidence.SERVER


class AuditPoliciesTest(unittest.TestCase):
    """Exercise policy outcomes with real ledger/source snapshots offline."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        self.tex = self.root / "main.tex"
        self.bib = self.root / "refs.bib"
        self.tex.write_text(r"The measurement rises \cite{a}.")
        self.source = self.root / "source.txt"
        self.source.write_text("The measurement rises by ten percent.")
        self.record = {"doi": "10.1234/example", "title": "Example"}
        self.metadata = {
            "id": "doi:10.1234/example",
            "basis": "fulltext",
            "path": str(self.source),
            "intake": test_evidence.source_intake(self.source),
            "source": "local:source.txt",
        }
        self.verification: list[dict[str, Any]] = [
            {
                "key": "a",
                "status": "VERIFIED",
                "id": self.metadata["id"],
                "ids": {"doi": "10.1234/example"},
            }
        ]
        for name, options in (
            ("_full_record", {"side_effect": lambda *_: self.record}),
            ("_with_pin", {"side_effect": lambda record, *_: record}),
            ("_load_text_meta", {"side_effect": lambda *_: self.metadata}),
            ("verify_bib", {"side_effect": self.verify}),
        ):
            patch = unittest.mock.patch.object(SERVER, name, **options)
            patch.start()
            self.addCleanup(patch.stop)
        self.write_bib()

    def verify(self, *args: object, **kwargs: object) -> dict[str, Any]:
        """Return independent result rows, as a registry adapter would."""
        del args, kwargs
        return {"entries": [dict(item) for item in self.verification]}

    def write_bib(self, provenance: str | None = None) -> None:
        """Issue valid fixture receipts, or retain an explicit negative marker."""
        raw = "@article{a,title={Example},doi={10.1234/example}}"
        if provenance is None:
            block = test_evidence.official_bib_fixture(raw, self.record, self.bib)
        else:
            block = provenance + "\n" + raw
        self.bib.write_text(block)

    def support(self, verdict: str = "SUPPORTS") -> None:
        """Record source-bound evidence using the public API."""
        cite = SERVER.extract_cites(str(self.tex))["cites"][0]
        result = SERVER.record_support(
            str(self.root),
            "a",
            cite["claim"],
            verdict,
            "example",
            context=cite["context"],
            quotes=[self.source.read_text()],
            note="The source provides this explicitly assessed outcome.",
        )
        self.assertTrue(result["recorded"], result)

    def audit(self, **options: object) -> dict[str, Any]:
        """Run the public audit against the fixture bibliography."""
        return SERVER.audit(str(self.tex), str(self.bib), **options)

    def test_strict_success_has_separate_complete_axes(self) -> None:
        self.support()
        report = self.audit()
        self.assertIs(report["ok"], True)
        self.assertIs(report["input_complete"], True)
        self.assertIs(report["complete"], True)
        self.assertIs(report["submission_ready"], True)
        self.assertEqual(report["policy"], "submission-ready")
        for axis in report["coverage"].values():
            self.assertEqual((axis["expected"], axis["assessed"]), (1, 1))
        provenance = report["coverage"]["provenance"]
        self.assertEqual(provenance["declared"], 1)
        self.assertEqual(provenance["verified"], 1)
        self.assertIn("local-export-digest", provenance["assurance"])

    def test_exploratory_success_never_means_submission_ready(self) -> None:
        self.support()
        report = self.audit(policy="exploratory")
        self.assertTrue(report["ok"])
        self.assertTrue(report["complete"])
        self.assertFalse(report["submission_ready"])
        rendered = pathlib.Path(report["report"]).read_text()
        self.assertIn("EXPLORATORY PROGRESS", rendered)
        self.assertNotIn("— PASS", rendered)

    def test_false_flags_cannot_weaken_strict_policy(self) -> None:
        self.support()
        for options in ({"verify": False}, {"require_support": False}):
            with self.subTest(options=options):
                report = self.audit(**options)
                self.assertFalse(report["submission_ready"])
                self.assertFalse(report["ok"])
                self.assertIn(
                    "policy-configuration",
                    {item["type"] for item in report["failures"]},
                )

    def test_unchecked_existence_and_missing_support_retain_denominators(
        self,
    ) -> None:
        report = self.audit(
            policy="exploratory", verify=False, require_support=False
        )
        self.assertTrue(report["ok"])
        self.assertFalse(report["complete"])
        self.assertFalse(report["submission_ready"])
        self.assertEqual(
            report["coverage"]["existence"]["counts"], {"UNCHECKED": 1}
        )
        self.assertEqual(
            report["coverage"]["support"]["counts"], {"MISSING": 1}
        )
        self.assertEqual(report["coverage"]["provenance"]["declared"], 1)
        for name in ("existence", "support"):
            axis = report["coverage"][name]
            self.assertEqual((axis["assessed"], axis["expected"]), (0, 1))

    def test_negative_and_inaccessible_assessments_can_be_complete(
        self,
    ) -> None:
        for verdict in (
            "PARTIAL",
            "UNVERIFIABLE",
            "UNSUPPORTED",
            "CONTRADICTS",
        ):
            with self.subTest(verdict=verdict):
                self.metadata["basis"] = (
                    "abstract" if verdict == "UNVERIFIABLE" else "fulltext"
                )
                self.support(verdict)
                strict = self.audit()
                self.assertTrue(strict["complete"])
                self.assertFalse(strict["submission_ready"])
                exploratory = self.audit(policy="exploratory")
                self.assertTrue(exploratory["complete"])
                self.assertEqual(
                    exploratory["ok"], verdict in {"PARTIAL", "UNVERIFIABLE"}
                )
                expected = (
                    "INACCESSIBLE" if verdict == "UNVERIFIABLE" else verdict
                )
                self.assertEqual(
                    exploratory["coverage"]["support"]["counts"], {expected: 1}
                )

    def test_limited_basis_requires_review_even_with_support(self) -> None:
        for basis in ("abstract", "readme"):
            with self.subTest(basis=basis):
                self.metadata["basis"] = basis
                self.support()
                report = self.audit()
                self.assertFalse(report["submission_ready"])
                self.assertEqual(report["coverage"]["support"]["verified"], 0)
                self.assertEqual(
                    report["coverage"]["support"]["basis_counts"], {basis: 1}
                )
                self.assertTrue(self.audit(policy="exploratory")["ok"])

    def test_verified_repository_primary_record_is_adequate(self) -> None:
        sha = "a" * 40
        self.record = {
            "github": "owner/repo", "title": "repo", "pin": sha,
            "pinned_sha": sha, "requested_version": sha,
        }
        self.metadata.update(
            id="github:owner/repo", basis="readme", version=sha,
            cache_id="github:owner/repo@" + sha,
        )
        self.verification = [
            {
                "key": "a",
                "status": "VERIFIED",
                "id": "github:owner/repo",
                "ids": {"github": "owner/repo"},
            }
        ]
        self.bib.write_text(
            test_evidence.official_bib_fixture(
                "@software{a,title={repo},url={https://github.com/owner/repo/tree/"
                + sha + "},note={Commit " + sha + "}}",
                self.record, self.bib, "github",
            )
        )
        self.support()
        self.assertTrue(self.audit()["submission_ready"])

    def test_malformed_or_mismatched_provenance_never_passes(self) -> None:
        self.support()
        for marker, expected in (
            ("", "UNOFFICIAL"),
            ("@comment{cite-check: x=y}", "MALFORMED"),
            (
                "@comment{cite-check: source=unknown; "
                "id=doi:10.1234/example; fetched=2026-01-01}",
                "MALFORMED",
            ),
            (
                "@comment{cite-check: source=crossref; "
                "id=doi:10.1234/other; fetched=2026-01-01}",
                "MISMATCH",
            ),
        ):
            with self.subTest(marker=marker):
                self.write_bib(marker)
                report = self.audit()
                self.assertFalse(report["submission_ready"])
                self.assertEqual(
                    report["coverage"]["provenance"]["counts"], {expected: 1}
                )
                self.assertEqual(
                    report["coverage"]["provenance"]["expected"], 1
                )
                if expected == "MISMATCH":
                    self.assertFalse(self.audit(policy="exploratory")["ok"])

    def test_valid_alias_provenance_matches_resolved_work(self) -> None:
        self.support()
        self.verification[0]["ids"]["arxiv"] = "1234.5678"
        self.bib.write_text(test_evidence.official_bib_fixture(
            "@article{a,title={Example},doi={10.1234/example},eprint={1234.5678}}",
            {"arxiv": "1234.5678", "title": "Example"}, self.bib, "arxiv",
        ))
        self.assertTrue(self.audit()["submission_ready"])

    def test_missing_or_malformed_registry_rows_are_unresolved(self) -> None:
        self.support()
        for rows in (
            [],
            [{"key": "a"}],
            [{"key": "a", "status": []}],
            [{"key": "a", "status": "VERIFIED"}],
            [
                {
                    "key": "a",
                    "status": "VERIFIED",
                    "id": "doi:10.1234/example",
                    "ids": [],
                }
            ],
        ):
            with self.subTest(rows=rows):
                self.verification = rows
                report = self.audit()
                self.assertFalse(report["complete"])
                self.assertFalse(report["submission_ready"])
                self.assertEqual(
                    report["coverage"]["existence"]["counts"], {"UNRESOLVED": 1}
                )
                self.assertEqual(report["coverage"]["existence"]["expected"], 1)

    def test_undefined_key_remains_in_every_relevant_denominator(self) -> None:
        self.tex.write_text(r"The measurement rises \cite{a,missing}.")
        report = self.audit()
        self.assertFalse(report["input_complete"])
        for axis in report["coverage"].values():
            self.assertEqual(axis["expected"], 2)
        self.assertEqual(
            report["coverage"]["existence"]["counts"]["UNDEFINED"], 1
        )

    def test_nocite_all_has_existence_but_no_support_obligation(self) -> None:
        self.tex.write_text(r"\nocite{*}")
        report = self.audit()
        self.assertTrue(report["submission_ready"])
        self.assertEqual(report["coverage"]["existence"]["expected"], 1)
        self.assertEqual(report["coverage"]["support"]["expected"], 0)
        self.assertIsNone(report["coverage"]["support"]["assessment_rate"])

    def test_empty_manuscript_has_explicit_zero_obligations(self) -> None:
        self.tex.write_text("No citations here.")
        report = SERVER.audit(str(self.tex))
        self.assertTrue(report["submission_ready"])
        for axis in report["coverage"].values():
            self.assertEqual(axis["expected"], 0)
            self.assertIsNone(axis["assessment_rate"])

    def test_bad_inputs_do_not_claim_zero_expected_work(self) -> None:
        self.tex.write_text(r"\input{missing}")
        report = self.audit()
        self.assertFalse(report["input_complete"])
        self.assertFalse(report["complete"])
        self.assertFalse(report["submission_ready"])
        for axis in report["coverage"].values():
            self.assertIsNone(axis["expected"])
        self.assertEqual(report["coverage"]["provenance"]["verified"], 0)
        self.assertFalse(report["coverage"]["support"]["atomic_total_known"])

    def test_corrupt_ledger_is_an_incomplete_audit(self) -> None:
        for value in (
            "{broken",
            "[]",
            '{"entries": []}',
            '{"entries": {"x": null}}',
        ):
            with self.subTest(value=value):
                path = pathlib.Path(
                    SERVER._project_path(str(self.root), "ledger.json")
                )
                path.write_text(value)
                report = self.audit()
                self.assertFalse(report["complete"])
                self.assertIn("ledger", report["error"])

    def test_bibliography_change_during_verification_is_stale(self) -> None:
        self.support()

        def change(*args: object, **kwargs: object) -> dict[str, Any]:
            self.write_bib("")
            return self.verify(*args, **kwargs)

        with unittest.mock.patch.object(
            SERVER, "verify_bib", side_effect=change
        ):
            report = self.audit()
        self.assertFalse(report["submission_ready"])
        self.assertFalse(report["complete"])
        self.assertIn(
            "audit-stale", {item["type"] for item in report["failures"]}
        )

    def test_source_change_after_assessment_is_stale(self) -> None:
        self.support()
        original = SERVER._current_source_identity

        def change(identifier: str) -> dict[str, Any] | None:
            identity = original(identifier)
            self.source.write_text(self.source.read_text() + " Revised.")
            return identity

        with unittest.mock.patch.object(
            SERVER, "_current_source_identity", side_effect=change
        ):
            report = self.audit()
        self.assertFalse(report["submission_ready"])
        self.assertIn(
            "audit-stale", {item["type"] for item in report["failures"]}
        )

    def test_conflicting_snapshots_of_one_source_cannot_pass(self) -> None:
        self.tex.write_text(
            r"First result rises \cite{a}. Second result falls \cite{a}."
        )
        cites = SERVER.extract_cites(str(self.tex))["cites"]
        texts = [
            "The first result rises by ten percent.",
            "The second result falls by ten percent.",
        ]
        for cite, text in zip(cites, texts, strict=True):
            self.source.write_text(text)
            result = SERVER.record_support(
                str(self.root),
                "a",
                cite["claim"],
                "SUPPORTS",
                "example",
                context=cite["context"],
                quotes=[text],
                tex_path=str(self.tex),
                occurrence_id=cite["occurrence_id"],
            )
            self.assertTrue(result["recorded"])
        original = SERVER._current_source_identity
        for restore in (False, True):
            with self.subTest(restore=restore):
                self.source.write_text(texts[0])
                calls = 0

                def mutate(
                    identifier: str, restore: bool = restore
                ) -> dict[str, Any] | None:
                    nonlocal calls
                    identity = original(identifier)
                    calls += 1
                    if calls == 1:
                        self.source.write_text(texts[1])
                    elif calls == 2 and restore:
                        self.source.write_text(texts[0])
                    return identity

                with unittest.mock.patch.object(
                    SERVER, "_current_source_identity", side_effect=mutate
                ):
                    report = self.audit()
                self.assertFalse(report["submission_ready"])
                self.assertIn(
                    "audit-stale", {item["type"] for item in report["failures"]}
                )

    def test_stale_atomic_requirements_expose_unknown_atom_total(self) -> None:
        extracted = SERVER.extract_cites(str(self.tex))
        sentence = extracted["sentences"][0]
        SERVER.register_claims(
            str(self.tex),
            sentence["sentence_id"],
            [
                {
                    "start": 0,
                    "end": len(sentence["claim"]),
                    "citation_ids": sentence["citation_ids"],
                }
            ],
        )
        self.tex.write_text(r"The measurement falls \cite{a}.")
        report = self.audit()
        axis = report["coverage"]["support"]
        self.assertEqual(axis["counts"], {"DECOMPOSITION_STALE": 1})
        self.assertEqual(axis["unresolved_decompositions"], 1)
        self.assertFalse(axis["atomic_total_known"])
        self.assertFalse(report["complete"])

    def test_existence_statuses_keep_assessment_and_readiness_separate(
        self,
    ) -> None:
        self.support()
        for status in (
            "FOUND",
            "PROBABLE",
            "MISMATCH",
            "NOT_FOUND",
            "UNRESOLVED",
        ):
            with self.subTest(status=status):
                self.verification[0]["status"] = status
                report = self.audit()
                self.assertFalse(report["submission_ready"])
                self.assertEqual(report["complete"], status != "UNRESOLVED")
                exploratory = self.audit(policy="exploratory")
                self.assertEqual(
                    exploratory["ok"], status in {"FOUND", "PROBABLE"}
                )
                self.assertEqual(
                    report["coverage"]["existence"]["counts"], {status: 1}
                )

    def test_failed_registry_keeps_expected_keys(self) -> None:
        self.support()
        with unittest.mock.patch.object(
            SERVER, "verify_bib", return_value={"error": "registry unavailable"}
        ):
            report = self.audit()
        axis = report["coverage"]["existence"]
        self.assertEqual((axis["assessed"], axis["expected"]), (0, 1))
        self.assertEqual(axis["counts"], {"UNRESOLVED": 1})
        self.assertFalse(report["complete"])

    def test_no_bibliography_for_real_citations_is_not_empty_success(
        self,
    ) -> None:
        self.bib.unlink()
        report = self.audit()
        self.assertFalse(report["input_complete"])
        self.assertEqual(report["coverage"]["existence"]["expected"], 1)
        self.assertEqual(
            report["coverage"]["existence"]["counts"], {"UNDEFINED": 1}
        )
        self.assertFalse(report["submission_ready"])

    def test_unknown_policy_and_cli_result_are_fail_closed(self) -> None:
        self.assertFalse(self.audit(policy="anything")["submission_ready"])
        process = subprocess.run(
            [
                sys.executable,
                SERVER.__file__,
                "call",
                "audit",
                json.dumps(
                    {
                        "tex_path": str(self.tex),
                        "bib_path": str(self.bib),
                        "verify": False,
                        "require_support": False,
                        "policy": "exploratory",
                    }
                ),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        report = json.loads(process.stdout)
        self.assertEqual(report["policy"], "exploratory")
        self.assertFalse(report["submission_ready"])
        self.assertEqual(report["coverage"]["existence"]["expected"], 1)
