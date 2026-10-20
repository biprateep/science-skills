"""Behavioral regression tests for the shared evaluator."""

import json
import os
import pathlib
import subprocess
import sys
import tempfile
from typing import Any
import unittest

from evaluation import __main__ as cli
from evaluation import contracts
from evaluation import engine
from evaluation import grading
from evaluation import process


class FrameworkTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = pathlib.Path(self.temporary.name)
        (self.repo / "evals").mkdir()
        self.write(
            "evals/defaults.json",
            json.dumps(
                {"schema_version": 1, "timeout_s": 2, "max_output_bytes": 4096}
            ),
        )
        self.write("skills/example/SKILL.md", "Follow the task.")
        self.write(
            "skills/example/evals/task/prompt.md",
            "Return a JSON object with answer 42.",
        )
        self.write(
            "skills/example/evals/task/reference/response.txt", '{"answer": 42}'
        )
        self.spec: dict[str, Any] = {
            "id": "answer",
            "description": "Independent numeric answer",
            "prompt": "task/prompt.md",
            "reference": "task/reference",
            "checks": [
                {
                    "id": "value",
                    "kind": "json_equals",
                    "dimension": "task_success",
                    "critical": True,
                    "pointer": "/answer",
                    "expected": 42,
                }
            ],
        }
        self.manifest = {
            "schema_version": 1,
            "skill": "example",
            "cases": [self.spec],
        }
        self.save_manifest()

    def write(self, name, content):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def save_manifest(self):
        self.write(
            "skills/example/evals/manifest.json", json.dumps(self.manifest)
        )

    def runner(self, code, output="stdout"):
        path = self.write("runner.py", code)
        return {
            "id": "fake",
            "agent": "test",
            "model": None,
            "argv": [sys.executable, str(path), "{response_file}"],
            "output": output,
            "capabilities": [],
            "config_sha256": "fake",
        }

    def run_case(self, runner=None, repeats=1):
        cases, inventory, covered = contracts.discover(self.repo)
        return engine.run(
            self.repo,
            cases,
            inventory,
            covered,
            runner or {"id": "replay"},
            self.repo / ".eval-runs",
            repeats,
        )

    def test_discovery_inherits_defaults_and_exposes_uncovered_skills(self):
        self.write("skills/future/SKILL.md", "Future skill")
        cases, inventory, covered = contracts.discover(self.repo)
        self.assertEqual(inventory, ["example", "future"])
        self.assertEqual(covered, ["example"])
        self.assertEqual(cases[0].timeout_s, 2)

    def test_replay_repairs_existing_input_and_repeats(self):
        self.spec["inputs"] = "task/input"
        self.write("skills/example/evals/task/input/answer.txt", "wrong")
        self.write(
            "skills/example/evals/task/reference/artifacts/answer.txt", "right"
        )
        self.spec["checks"].append(
            {
                "id": "repair",
                "kind": "file_contains",
                "dimension": "constraint_adherence",
                "critical": False,
                "path": "answer.txt",
                "text": "right",
            }
        )
        self.save_manifest()
        report, directory = self.run_case(repeats=2)
        self.assertEqual(
            [item["status"] for item in report["results"]], ["pass", "pass"]
        )
        self.assertEqual([item["seed"] for item in report["results"]], [0, 1])
        self.assertFalse(
            (
                directory / "example/answer/1/workspace/skills/example/evals"
            ).exists()
        )
        self.assertIsNone(report["results"][0]["reported_success"])

    def test_live_stdout_failure_is_not_success(self):
        report, _ = self.run_case(self.runner("print('{\"answer\": 0}')"))
        self.assertEqual(report["results"][0]["status"], "fail")

    def test_live_file_runner_and_prompt_stdin(self):
        code = (
            "import pathlib, sys\n"
            "assert 'Return a JSON' in sys.stdin.read()\n"
            "pathlib.Path(sys.argv[1]).write_text('{\"answer\": 42}')\n"
        )
        report, _ = self.run_case(self.runner(code, "file"))
        self.assertEqual(report["results"][0]["status"], "pass")

    def test_envelope_keeps_explicit_claim_and_observed_usage(self):
        envelope = {
            "response": '{"answer": 0}',
            "reported_success": True,
            "usage": {"output_tokens": 12},
        }
        report, _ = self.run_case(
            self.runner(f"print({json.dumps(envelope)!r})", "envelope")
        )
        result = report["results"][0]
        self.assertEqual(result["status"], "fail")
        self.assertTrue(result["reported_success"])
        self.assertEqual(result["usage"]["output_tokens"], 12)
        self.assertIsNone(result["usage"]["cost_usd"])

    def test_invalid_envelope_is_error(self):
        envelope = {
            "response": '{"answer": 42}',
            "usage": {"output_tokens": True},
        }
        report, _ = self.run_case(
            self.runner(f"print({json.dumps(envelope)!r})", "envelope")
        )
        self.assertEqual(report["results"][0]["status"], "error")

    def test_missing_capability_blocks_without_running(self):
        self.spec["capabilities"] = ["network"]
        self.save_manifest()
        report, _ = self.run_case(
            self.runner("raise RuntimeError('must not run')")
        )
        result = report["results"][0]
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["checks"][0]["status"], "not_run")

    def test_empty_missing_and_malformed_outputs_do_not_pass(self):
        for code, mode in [
            ("pass", "stdout"),
            ("pass", "file"),
            ("print('garbage')", "stdout"),
            ('print(\'{"answer": 0, "answer": 42}\')', "stdout"),
        ]:
            with self.subTest(code=code, mode=mode):
                report, _ = self.run_case(self.runner(code, mode))
                self.assertIn(report["results"][0]["status"], {"fail", "error"})

    def test_grader_failure_and_fault_are_distinct(self):
        for exit_code, expected in [(0, "pass"), (1, "fail"), (2, "error")]:
            path = self.write("grader.py", f"raise SystemExit({exit_code})")
            self.spec["checks"] = [
                {
                    "id": "command",
                    "kind": "command",
                    "dimension": "task_success",
                    "critical": True,
                    "argv": ["{python}", str(path)],
                }
            ]
            self.save_manifest()
            report, _ = self.run_case()
            self.assertEqual(report["results"][0]["status"], expected)

    def test_grader_changes_invalidate_case_fingerprint(self):
        first = contracts.discover(self.repo)[0][0].fingerprint
        self.write("skills/example/evals/grader.py", "# New grading contract")
        second = contracts.discover(self.repo)[0][0].fingerprint
        self.assertNotEqual(first, second)

    def test_source_provenance_precedes_agent_modifications(self):
        runner = self.runner(
            "import pathlib\n"
            "pathlib.Path('skills/example/SKILL.md').write_text('changed')\n"
            "print('{\"answer\": 42}')"
        )
        report, _ = self.run_case(runner)
        clean, _ = self.run_case()
        self.assertEqual(
            report["results"][0]["skill_content_sha256"],
            clean["results"][0]["skill_content_sha256"],
        )

    def test_timeout_output_limit_and_missing_command(self):
        for code, timeout, expected in [
            ("import time; time.sleep(2)", 0.05, "timeout"),
            ("print('x' * 10000)", 2, "output_limit"),
        ]:
            outcome = process.execute(
                [sys.executable, "-c", code], self.repo, timeout, 1024
            )
            self.assertEqual(outcome.status, expected)
            self.assertLessEqual(len(outcome.output), 1024)
        self.assertEqual(
            process.execute(
                ["missing-command-science-eval"], self.repo, 1, 1024
            ).status,
            "blocked",
        )

    def test_paths_and_symlinks_cannot_escape_fixture(self):
        for path in ("../secret", "/tmp/secret", "a/../../secret", "a\\secret"):
            with (
                self.subTest(path=path),
                self.assertRaises(contracts.ContractError),
            ):
                contracts.contained(self.repo, path)
        (self.repo / "link").symlink_to(
            self.repo / "evals", target_is_directory=True
        )
        with self.assertRaises(contracts.ContractError):
            contracts.contained(self.repo, "link/defaults.json")

    def test_malformed_contract_types_raise_contract_error(self):
        for key, value in [
            ("kind", []),
            ("dimension", {}),
            ("critical", 1),
            ("pointer", "/bad~2"),
        ]:
            with self.subTest(key=key):
                check = dict(self.spec["checks"][0], **{key: value})
                with self.assertRaises(contracts.ContractError):
                    contracts._validate_check(check)

    def test_json_bool_does_not_equal_number(self):
        self.spec["checks"][0]["expected"] = 1
        self.save_manifest()
        report, _ = self.run_case(self.runner("print('{\"answer\": true}')"))
        self.assertEqual(report["results"][0]["status"], "fail")

    def test_substitution_is_not_shell_interpolation(self):
        self.assertEqual(
            grading.expand(
                ["tool", "{workspace}"], {"workspace": "x; echo secret"}
            ),
            ["tool", "x; echo secret"],
        )

    @unittest.skipUnless(os.name == "posix", "POSIX FIFO behavior")
    def test_fifo_response_fails_without_blocking(self):
        report, _ = self.run_case(
            self.runner("import os, sys\nos.mkfifo(sys.argv[1])", "file")
        )
        self.assertEqual(report["results"][0]["status"], "error")

    def test_special_output_is_not_read(self):
        with self.assertRaises((OSError, contracts.ContractError)):
            contracts.read_regular(self.repo, 1024)

    def test_nonfinite_json_is_rejected(self):
        for source in ('{"x":1e999}', '{"x":NaN}', '{"x":Infinity}'):
            path = self.write("invalid.json", source)
            with self.assertRaises(contracts.ContractError):
                contracts.read_object(path)

    def test_top_level_json_array_can_be_graded(self):
        self.spec["checks"][0].update(pointer="", expected=[42])
        self.save_manifest()
        report, _ = self.run_case(self.runner("print('[42]')"))
        self.assertEqual(report["results"][0]["status"], "pass")

    def test_inherited_budget_changes_fingerprint(self):
        first = contracts.discover(self.repo)[0][0].fingerprint
        defaults = contracts.load_defaults(self.repo)
        defaults["timeout_s"] = 5
        self.write("evals/defaults.json", json.dumps(defaults))
        self.assertNotEqual(
            first, contracts.discover(self.repo)[0][0].fingerprint
        )

    def test_git_ignored_private_material_is_not_copied(self):
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.write(".gitignore", "private-data/\n")
        self.write("skills/example/private-data/secret.txt", "PRIVATE")
        self.write("skills/example/scratch/private.txt", "PRIVATE")
        self.write("skills/example/public.txt", "PUBLIC")
        _, directory = self.run_case()
        copied = directory / "example/answer/1/workspace/skills/example"
        self.assertTrue((copied / "public.txt").is_file())
        self.assertFalse((copied / "private-data").exists())
        self.assertFalse((copied / "scratch").exists())

    def test_cli_live_requires_explicit_opt_in(self):
        self.assertEqual(
            cli.main(["--repo", str(self.repo), "run", "--runner", "fake"]), 2
        )

    def test_cli_missing_and_incomparable_baselines_do_not_pass(self):
        report, _ = self.run_case()
        baseline = self.write("baseline.json", json.dumps(report))
        report["results"][0]["seed"] += 1
        current = self.write("current.json", json.dumps(report))
        self.assertEqual(cli.main(["compare", str(current), str(baseline)]), 2)
        report["results"] = []
        current.write_text(json.dumps(report), encoding="utf-8")
        self.assertEqual(cli.main(["compare", str(current), str(baseline)]), 2)


if __name__ == "__main__":
    unittest.main()
