"""Command-line entry point for the shared evaluation framework."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

from evaluation import contracts
from evaluation import engine
from evaluation import reporting


def main(argv: list[str] | None = None) -> int:
    """Validate, run, summarize, or compare versioned skill evaluations."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=pathlib.Path, default=pathlib.Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--require-coverage", action="store_true")
    commands.add_parser("list")
    run_parser = commands.add_parser("run")
    run_parser.add_argument("--runner", default="replay")
    run_parser.add_argument("--config", type=pathlib.Path)
    run_parser.add_argument("--allow-live", action="store_true")
    run_parser.add_argument("--skill", action="append")
    run_parser.add_argument("--repeats", type=int, default=1)
    run_parser.add_argument("--seed", type=int, default=0)
    run_parser.add_argument("--output", type=pathlib.Path)
    report_parser = commands.add_parser("report")
    report_parser.add_argument("path", type=pathlib.Path)
    compare_parser = commands.add_parser("compare")
    compare_parser.add_argument("current", type=pathlib.Path)
    compare_parser.add_argument("baseline", type=pathlib.Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "report":
            print(reporting.markdown(contracts.read_object(args.path)))
            return 0
        if args.command == "compare":
            comparison = reporting.compare(
                contracts.read_object(args.current),
                contracts.read_object(args.baseline),
            )
            print(json.dumps(comparison, indent=2, allow_nan=False))
            if (
                not comparison["comparable"]
                or comparison["incomparable"]
                or comparison["missing_cases"]
            ):
                return 2
            return 1 if comparison.get("regressions") else 0
        repo = args.repo.resolve()
        cases, inventory, covered = contracts.discover(repo)
        if args.command in {"list", "validate"}:
            print(
                json.dumps(
                    {
                        "skills": inventory,
                        "covered_skills": covered,
                        "cases": [
                            f"{case.skill}/{case.specification['id']}"
                            for case in cases
                        ],
                    },
                    indent=2,
                )
            )
            if (
                args.command == "validate"
                and args.require_coverage
                and (not inventory or inventory != covered)
            ):
                raise contracts.ContractError(
                    "Every discovered skill must have an evaluation manifest"
                )
            return 0
        if args.skill:
            if set(args.skill) - set(inventory):
                raise contracts.ContractError("Unknown --skill selection")
            cases = [case for case in cases if case.skill in args.skill]
        if not cases:
            raise contracts.ContractError("No evaluation cases selected")
        if args.runner == "replay":
            runner = {
                "id": "replay",
                "agent": "reference replay (calibration only)",
                "model": None,
                "config_sha256": contracts.digest({"replay": 1}),
            }
        else:
            if not args.allow_live:
                raise contracts.ContractError(
                    "Live runners require --allow-live"
                )
            runner = contracts.load_runner(
                args.config or repo / "evals/runners.local.json", args.runner
            )
        report, directory = engine.run(
            repo,
            cases,
            inventory,
            covered,
            runner,
            args.output or repo / ".eval-runs",
            args.repeats,
            args.seed,
        )
        report["summary"] = reporting.summarize(
            report["results"], inventory, covered
        )
        (directory / "report.json").write_text(
            json.dumps(report, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        (directory / "report.md").write_text(
            reporting.markdown(report), encoding="utf-8"
        )
        print(f"Report: {directory / 'report.json'}")
        return (
            0
            if all(result["status"] == "pass" for result in report["results"])
            else 1
        )
    except (ValueError, OSError) as error:
        print(f"Evaluation error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
