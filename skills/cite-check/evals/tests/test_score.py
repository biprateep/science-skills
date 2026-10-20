"""Tests citation metrics, denominator preservation, and report boundaries."""

import copy
import importlib.util
import json
import os
import pathlib
import shutil
import sys
import tempfile
import unittest
import unittest.mock

import evaluation.contracts
import evaluation.engine

_SCORE_PATH = pathlib.Path(__file__).resolve().parents[1] / "score.py"
_SPEC = importlib.util.spec_from_file_location("citation_score", _SCORE_PATH)
score = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = score
_SPEC.loader.exec_module(score)


class CitationScoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = pathlib.Path(__file__).resolve().parents[4]
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cases, inventory, covered = evaluation.contracts.discover(cls.repo)
        selected = [case for case in cases if case.skill == "cite-check"]
        cls.report, cls.reference_run = evaluation.engine.run(
            cls.repo,
            selected,
            inventory,
            covered,
            {
                "id": "replay",
                "agent": "reference calibration",
                "model": None,
                "config_sha256": "calibration-test-runner",
            },
            pathlib.Path(cls.temporary.name),
        )
        if any(trial["status"] != "pass" for trial in cls.report["results"]):
            raise AssertionError(cls.report["results"])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.run = pathlib.Path(self.directory.name) / "run"
        shutil.copytree(self.reference_run, self.run)
        self.current = copy.deepcopy(self.report)
        self.path = self.run / "report.json"

    def evaluate(self, repeats=1, repo=None):
        self.path.write_text(json.dumps(self.current), encoding="utf-8")
        return score.score_report(self.path, repo or self.repo, repeats)

    def response_path(self, case="quantitative-controls"):
        return self.run / "cite-check" / case / "1/response.txt"

    def replace_response(self, response, case="quantitative-controls"):
        self.response_path(case).write_text(
            json.dumps(response), encoding="utf-8"
        )

    def load_response(self, case="quantitative-controls"):
        return json.loads(self.response_path(case).read_text(encoding="utf-8"))

    def test_reference_calibration_has_explicit_denominators(self):
        result = self.evaluate()
        self.assertEqual(result["mode"], "replay")
        self.assertIn("no agent performance", result["interpretation"])
        metrics = result["metrics"]
        self.assertEqual(metrics["scheduled_claims"], 20)
        self.assertEqual(metrics["exact_verdict_accuracy"]["count"], 20)
        self.assertEqual(metrics["planted_errors_missed"]["total"], 9)
        self.assertEqual(metrics["false_accusations_on_controls"]["total"], 8)
        self.assertEqual(metrics["inaccessible_triage"]["total"], 3)
        self.assertEqual(metrics["verbatim_evidence_spans"]["total"], 17)
        self.assertNotIn("composite_score", result)

    def test_detection_false_accusation_and_exact_labels_are_separate(self):
        response = self.load_response()
        response["claims"]["q04"]["verdict"] = "supported"
        response["claims"]["q17"]["verdict"] = "contradicted"
        response["claims"]["q09"]["verdict"] = "unsupported"
        self.replace_response(response)
        metrics = self.evaluate()["metrics"]
        self.assertEqual(metrics["planted_errors_missed"]["count"], 1)
        self.assertEqual(metrics["false_accusations_on_controls"]["count"], 1)
        self.assertEqual(metrics["exact_verdict_accuracy"]["count"], 17)
        self.assertEqual(metrics["planted_errors_detected"]["count"], 8)

    def test_failed_completed_trial_retains_valid_observations(self):
        trial = next(
            trial
            for trial in self.current["results"]
            if trial["case_id"] == "quantitative-controls"
        )
        trial["status"] = "fail"
        response = self.load_response()
        response["claims"]["q04"]["verdict"] = "supported"
        self.replace_response(response)
        result = self.evaluate()
        self.assertEqual(
            result["metrics"]["exact_verdict_accuracy"]["count"], 19
        )
        self.assertEqual(result["metrics"]["omitted_claims"]["count"], 0)
        self.assertEqual(result["response_status_counts"]["valid"], 3)

    def test_omission_invalid_verdict_and_extra_ids_are_visible(self):
        response = self.load_response()
        del response["claims"]["q04"]
        response["claims"]["q09"]["verdict"] = ["contradicted"]
        response["claims"]["invented"] = {"verdict": "supported"}
        self.replace_response(response)
        result = self.evaluate()
        self.assertEqual(result["metrics"]["omitted_claims"]["count"], 1)
        self.assertEqual(result["metrics"]["invalid_claim_outputs"]["count"], 1)
        self.assertEqual(result["metrics"]["planted_errors_missed"]["count"], 2)
        trial = next(
            t
            for t in result["trials"]
            if t["case_id"] == "quantitative-controls"
        )
        self.assertEqual(trial["unexpected_claim_ids"], ["invented"])
        self.assertEqual(result["metrics"]["scheduled_claims"], 20)

    def test_verbatim_quote_is_not_equated_to_relevant_evidence(self):
        response = self.load_response()
        response["claims"]["q09"]["evidence"] = (
            "In the 40-cell sample, treatment increased median lifetime "
            "by 12 percent relative to the control."
        )
        self.replace_response(response)
        metrics = self.evaluate()["metrics"]
        self.assertEqual(metrics["verbatim_evidence_spans"]["count"], 17)
        self.assertEqual(metrics["evidence_anchor_matches"]["count"], 16)
        self.assertEqual(metrics["exact_verdict_accuracy"]["count"], 20)

    def test_whitespace_and_fabricated_quotes_fail_provenance(self):
        for quote in (" ", "\n", "The rate was +2.5 per second."):
            with self.subTest(quote=quote):
                response = self.load_response()
                response["claims"]["q09"]["evidence"] = quote
                self.replace_response(response)
                metrics = self.evaluate()["metrics"]
                self.assertEqual(
                    metrics["verbatim_evidence_spans"]["count"], 16
                )
                self.assertEqual(
                    metrics["evidence_anchor_matches"]["count"], 16
                )

    def test_prompts_require_evidence_for_every_readable_verdict(self):
        cases, suite = score.load_suite(self.repo)
        rule = (
            "For every claim with readable source text, include a relevant "
            "verbatim evidence span, including supported, contradicted, "
            "and unsupported verdicts."
        )
        for case_id, case in cases.items():
            with self.subTest(case=case_id):
                prompt = case.manifest_dir / case.specification["prompt"]
                text = prompt.read_text(encoding="utf-8")
                self.assertIn(rule, text)
                self.assertIn("Return only JSON, with no code fences.", text)
                readable = [
                    gold
                    for gold in suite[case_id].values()
                    if gold.source_text is not None
                ]
                self.assertTrue(all(gold.anchors for gold in readable))

    def test_matching_identity_accepts_minimal_scientific_evidence(self):
        response = self.load_response("identity-version-access")
        for claim in ("a08", "a13", "a24", "a27"):
            response["claims"][claim]["evidence"] = (
                "The updated median lifetime is 24 seconds."
            )
        self.replace_response(response, "identity-version-access")
        metrics = self.evaluate()["metrics"]
        self.assertEqual(metrics["verbatim_evidence_spans"]["count"], 17)
        self.assertEqual(metrics["evidence_anchor_matches"]["count"], 17)

    def test_live_stale_value_quote_without_version_header_is_valid(self):
        response = self.load_response("identity-version-access")
        response["claims"]["a27"]["evidence"] = (
            "The updated median lifetime is 24 seconds. "
            "The version 1 estimate of 18 seconds was superseded."
        )
        self.replace_response(response, "identity-version-access")
        self.assertEqual(
            self.evaluate()["metrics"]["evidence_anchor_matches"]["count"], 17
        )

    def test_identity_conflicts_still_require_conflicting_metadata(self):
        response = self.load_response("identity-version-access")
        for claim in ("a02", "a16"):
            response["claims"][claim]["evidence"] = (
                "The updated median lifetime is 24 seconds."
            )
        self.replace_response(response, "identity-version-access")
        metrics = self.evaluate()["metrics"]
        self.assertEqual(metrics["verbatim_evidence_spans"]["count"], 17)
        self.assertEqual(metrics["evidence_anchor_matches"]["count"], 15)

    def test_unsupported_claim_still_requires_stated_evidence(self):
        response = self.load_response("evidence-boundaries")
        response["claims"]["temperature"]["evidence"] = ""
        self.replace_response(response, "evidence-boundaries")
        metrics = self.evaluate()["metrics"]
        self.assertEqual(metrics["exact_verdict_accuracy"]["count"], 20)
        self.assertEqual(metrics["evidence_anchor_matches"]["count"], 16)

    def test_inaccessible_triage_and_invented_evidence_are_separate(self):
        response = self.load_response("identity-version-access")
        response["claims"]["a19"] = {
            "verdict": "contradicted",
            "evidence": "Invented source text.",
        }
        self.replace_response(response, "identity-version-access")
        metrics = self.evaluate()["metrics"]
        self.assertEqual(metrics["inaccessible_triage"]["count"], 2)
        self.assertEqual(metrics["inaccessible_evidence_restraint"]["count"], 2)
        self.assertEqual(
            metrics["false_accusations_on_inaccessible"]["count"], 1
        )

    def assert_missing_eight(self, result):
        metrics = result["metrics"]
        self.assertEqual(metrics["scheduled_claims"], 20)
        self.assertEqual(metrics["exact_verdict_accuracy"]["count"], 12)
        self.assertEqual(metrics["omitted_claims"]["count"], 8)
        self.assertEqual(metrics["planted_errors_missed"]["count"], 4)
        self.assertEqual(metrics["controls_unassessed"]["count"], 4)
        self.assertEqual(metrics["false_accusations_on_controls"]["total"], 8)

    def test_missing_and_invalid_responses_keep_denominators(self):
        self.response_path().unlink()
        self.assert_missing_eight(self.evaluate())
        for content in (
            "not JSON",
            "[]",
            '{"claims": []}',
            '{"claims": {}, "claims": {}}',
            '{"claims": {}, "n": NaN}',
            '{"claims": {}, "n": 1e9999}',
        ):
            with self.subTest(content=content):
                self.response_path().write_text(content, encoding="utf-8")
                result = self.evaluate()
                self.assert_missing_eight(result)
                self.assertEqual(
                    result["response_status_counts"]["invalid_output"], 1
                )

    def test_blocked_error_and_timeout_ignore_existing_reference_output(self):
        trial = next(
            t
            for t in self.current["results"]
            if t["case_id"] == "quantitative-controls"
        )
        for status in ("blocked", "error", "timeout"):
            with self.subTest(status=status):
                trial["status"] = status
                result = self.evaluate()
                self.assert_missing_eight(result)
                self.assertEqual(
                    result["response_status_counts"]["not_completed"], 1
                )

    def test_missing_trial_row_and_repeat_keep_expected_schedule(self):
        self.current["results"] = [
            t
            for t in self.current["results"]
            if t["case_id"] != "quantitative-controls"
        ]
        self.assert_missing_eight(self.evaluate())
        self.current = copy.deepcopy(self.report)
        result = self.evaluate(repeats=2)
        self.assertEqual(result["expected_trials"], 6)
        self.assertEqual(result["metrics"]["scheduled_claims"], 40)
        self.assertEqual(
            result["metrics"]["exact_verdict_accuracy"]["count"], 20
        )
        self.assertEqual(result["metrics"]["omitted_claims"]["count"], 20)
        self.assertEqual(result["trial_status_counts"]["missing_trial"], 3)

    def test_unknown_duplicate_and_out_of_range_trials_are_rejected(self):
        mutations = (
            lambda trials: trials.append(copy.deepcopy(trials[0])),
            lambda trials: trials[0].update(case_id="../escape"),
            lambda trials: trials[0].update(repeat=2),
            lambda trials: trials[0].update(repeat=0),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.current = copy.deepcopy(self.report)
                mutate(self.current["results"])
                with self.assertRaises(ValueError):
                    self.evaluate()

    def test_missing_provenance_and_stale_fingerprint_are_rejected(self):
        for field in ("case_fingerprint", "seed"):
            with self.subTest(field=field):
                self.current = copy.deepcopy(self.report)
                del self.current["results"][0][field]
                with self.assertRaises(ValueError):
                    self.evaluate()
        self.current = copy.deepcopy(self.report)
        self.current["runner"]["config_sha256"] = None
        with self.assertRaises(ValueError):
            self.evaluate()
        self.current = copy.deepcopy(self.report)
        self.current["results"][0]["case_fingerprint"] = "stale"
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            self.evaluate()

    def test_changed_gold_and_framework_are_rejected(self):
        repo = pathlib.Path(self.directory.name) / "repo"
        shutil.copytree(
            self.repo / "skills/cite-check", repo / "skills/cite-check"
        )
        shutil.copytree(self.repo / "evals", repo / "evals")
        self.assertEqual(
            self.evaluate(repo=repo)["metrics"]["scheduled_claims"], 20
        )
        gold = repo / "skills/cite-check/evals/gold.json"
        value = json.loads(gold.read_text(encoding="utf-8"))
        value["revision_note"] = "Changed trusted fixture"
        gold.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            self.evaluate(repo=repo)
        digest = evaluation.contracts.tree_digest
        framework = pathlib.Path(evaluation.engine.__file__).parent
        with unittest.mock.patch.object(
            evaluation.contracts,
            "tree_digest",
            side_effect=lambda path: (
                "changed" if path == framework else digest(path)
            ),
        ):
            with self.assertRaisesRegex(ValueError, "fingerprint"):
                self.evaluate()

    def test_oversized_symlink_and_fifo_outputs_are_not_read(self):
        limit = evaluation.contracts.load_defaults(self.repo)[
            "max_output_bytes"
        ]
        self.response_path().write_bytes(b" " * (limit + 1))
        self.assert_missing_eight(self.evaluate())
        self.response_path().unlink()
        outside = pathlib.Path(self.directory.name) / "outside.txt"
        outside.write_text('{"claims": {}}', encoding="utf-8")
        self.response_path().symlink_to(outside)
        self.assert_missing_eight(self.evaluate())
        self.response_path().unlink()
        if hasattr(os, "mkfifo"):
            os.mkfifo(self.response_path())
            self.assert_missing_eight(self.evaluate())

    def test_parent_directory_symlink_and_report_symlink_are_rejected(self):
        directory = self.response_path().parent
        moved = pathlib.Path(self.directory.name) / "moved"
        directory.rename(moved)
        directory.symlink_to(moved, target_is_directory=True)
        self.assert_missing_eight(self.evaluate())
        self.path.unlink()
        outside = pathlib.Path(self.directory.name) / "report.json"
        outside.write_text(json.dumps(self.current), encoding="utf-8")
        self.path.symlink_to(outside)
        with self.assertRaises(ValueError):
            score.score_report(self.path, self.repo, 1)

    def test_no_compatible_trial_and_invalid_schedule_are_rejected(self):
        self.current["results"] = []
        with self.assertRaises(ValueError):
            self.evaluate()
        for repeats in (0, -1, True):
            with self.subTest(repeats=repeats):
                with self.assertRaises(ValueError):
                    self.evaluate(repeats=repeats)

    def test_visible_ids_do_not_disclose_gold_cohorts(self):
        for case in ("quantitative-controls", "identity-version-access"):
            data = json.loads(
                (
                    self.repo
                    / "skills/cite-check/evals"
                    / case
                    / "input/evidence.json"
                ).read_text(encoding="utf-8")
            )
            for claim_id in data["claims"]:
                self.assertRegex(claim_id, r"^[aq][0-9]{2}$")
                self.assertNotIn("verdict", data["claims"][claim_id])
                self.assertNotIn("cohort", data["claims"][claim_id])


if __name__ == "__main__":
    unittest.main()
