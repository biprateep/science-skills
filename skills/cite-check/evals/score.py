"""Scores controlled citation claims from a compatible shared evaluation run.

This is evaluator library and CLI source, not a notebook. Run data stays in
ignored evaluation directories. Replay calibrates fixtures, not agent quality.
"""

from __future__ import annotations

import argparse
import collections
import dataclasses
import json
import pathlib
import sys
from typing import Any

# Direct script execution needs the repository package on the import path.
_REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO))
import evaluation.contracts  # noqa: E402
import evaluation.engine  # noqa: E402
import evaluation.reporting  # noqa: E402

_VERDICTS = {"supported", "contradicted", "unsupported", "unverifiable"}
_ERRORS = {"contradicted", "unsupported"}
_REPORT_LIMIT = 16 * 1024 * 1024


@dataclasses.dataclass(frozen=True)
class GoldClaim:
    """An independently specified expectation for one synthetic claim.

    Attributes:
        verdict: Exact expected classification.
        cohort: True control, planted error, or inaccessible evidence.
        source_text: Supplied source text, or None when unavailable.
        anchors: Relevant literal phrases required within a verbatim span.
    """

    verdict: str
    cohort: str
    source_text: str | None
    anchors: tuple[str, ...]


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise ValueError(f"Nonfinite JSON value: {value}")


def read_output(path: pathlib.Path, limit: int) -> dict[str, Any]:
    """Reads bounded, strict JSON without accepting symlinks or special files.

    Args:
        path: A path already anchored inside its owning directory.
        limit: Maximum UTF-8 file size in bytes.

    Returns:
        A decoded JSON object.

    Raises:
        OSError: The file cannot be read.
        ValueError: The file or JSON does not satisfy the output contract.
    """
    text = evaluation.contracts.read_regular(path, limit)
    value = json.loads(
        text, object_pairs_hook=_object, parse_constant=_constant
    )
    # Canonical serialization also rejects overflowed finite-number literals.
    json.dumps(value, allow_nan=False)
    if not isinstance(value, dict):
        raise ValueError("Response must be a JSON object")
    return value


def _gold_claim(entry: Any, source: Any) -> GoldClaim:
    if not isinstance(entry, dict) or not isinstance(source, dict):
        raise ValueError("Gold claim and source must be objects")
    verdict = entry.get("verdict")
    cohort = entry.get("cohort")
    valid_cohorts = {
        "supported": "true_control",
        "unverifiable": "inaccessible",
        "contradicted": "planted_error",
        "unsupported": "planted_error",
    }
    if (
        not isinstance(verdict, str)
        or not isinstance(cohort, str)
        or valid_cohorts.get(verdict) != cohort
    ):
        raise ValueError("Gold verdict and cohort are inconsistent")
    text = source.get("text")
    anchors = entry.get("anchors")
    if not isinstance(anchors, list) or any(
        not isinstance(anchor, str) or not anchor for anchor in anchors
    ):
        raise ValueError("Gold anchors must be nonempty strings")
    if cohort == "inaccessible":
        if text is not None or anchors:
            raise ValueError("Inaccessible gold must have no text or anchors")
    elif (
        not isinstance(text, str)
        or not anchors
        or any(anchor not in text for anchor in anchors)
    ):
        raise ValueError("Readable gold needs anchors present in source text")
    return GoldClaim(verdict, cohort, text, tuple(anchors))


def load_suite(
    repo: pathlib.Path,
) -> tuple[
    dict[str, evaluation.contracts.Case], dict[str, dict[str, GoldClaim]]
]:
    """Loads current manifest cases and validates their private gold rubric.

    Args:
        repo: Repository containing the manifests and trusted rubric.

    Returns:
        Cases and gold claims, each indexed by case ID.

    Raises:
        ValueError: Gold, inputs, and manifests disagree or are malformed.
    """
    discovered, _, _ = evaluation.contracts.discover(repo)
    cases = {
        case.specification["id"]: case
        for case in discovered
        if case.skill == "cite-check"
    }
    gold = evaluation.contracts.read_object(
        repo / "skills/cite-check/evals/gold.json"
    )
    if (
        type(gold.get("schema_version")) is not int
        or gold["schema_version"] != 1
    ):
        raise ValueError("Unsupported citation gold schema")
    entries = gold.get("cases")
    if not isinstance(entries, dict) or set(entries) != set(cases):
        raise ValueError("Gold and cite-check manifest case IDs must match")
    suite = {}
    for case_id, case in cases.items():
        inputs = evaluation.contracts.contained(
            case.manifest_dir, case.specification["inputs"]
        )
        evidence = evaluation.contracts.read_object(inputs / "evidence.json")
        claims = entries[case_id].get("claims")
        if not isinstance(claims, dict) or set(claims) != set(
            evidence["claims"]
        ):
            raise ValueError(f"Gold and input claims differ: {case_id}")
        expectations = {}
        for claim_id, entry in claims.items():
            source_id = entry["source"]
            if source_id != evidence["claims"][claim_id]["source"]:
                raise ValueError(f"Gold source mismatch: {case_id}/{claim_id}")
            expectations[claim_id] = _gold_claim(
                entry, evidence["sources"].get(source_id)
            )
        suite[case_id] = expectations
    return cases, suite


def evidence_checks(
    claim: Any,
    gold: GoldClaim,
) -> tuple[bool, bool, bool]:
    """Checks quotation provenance and narrow fixture-specific anchors.

    Args:
        claim: One claim object from the evaluated response.
        gold: The independently specified expectation.

    Returns:
        Verbatim-span validity, anchor match, and inaccessible-source restraint.
        Anchor matching is a lexical fixture oracle, not semantic entailment.
    """
    quote = claim.get("evidence") if isinstance(claim, dict) else None
    if gold.source_text is None:
        return False, False, isinstance(quote, str) and not quote
    if not isinstance(quote, str) or not quote.strip():
        return False, False, False
    verbatim = quote in gold.source_text
    anchored = verbatim and all(anchor in quote for anchor in gold.anchors)
    return verbatim, anchored, False


def _fingerprint(case: evaluation.contracts.Case) -> str:
    return evaluation.contracts.digest(
        {
            "case": case.fingerprint,
            "framework": evaluation.contracts.tree_digest(
                pathlib.Path(evaluation.engine.__file__).parent
            ),
        }
    )


def _index_trials(
    report: dict[str, Any],
    cases: dict[str, evaluation.contracts.Case],
    repeats: int,
) -> dict[tuple[str, int], dict[str, Any]]:
    # Public comparison validates the shared schema, measurements, and
    # duplicate trial identities. Its comparison result is not used as a score.
    comparison = evaluation.reporting.compare(report, report)
    if comparison["warnings"] or comparison["incomparable"]:
        raise ValueError("Shared report has missing comparison provenance")
    indexed = {}
    for trial in report["results"]:
        if trial["skill"] != "cite-check":
            continue
        case_id = trial["case_id"]
        repeat = trial["repeat"]
        if case_id not in cases:
            raise ValueError(f"Unknown cite-check case: {case_id}")
        if not 1 <= repeat <= repeats:
            raise ValueError(f"Repeat {repeat} is outside 1..{repeats}")
        if trial.get("case_fingerprint") != _fingerprint(cases[case_id]):
            raise ValueError(
                f"Incompatible fixture/framework fingerprint: {case_id}"
            )
        indexed[(case_id, repeat)] = trial
    if not indexed:
        raise ValueError("No citation trial establishes fixture compatibility")
    return indexed


def _read_response(
    run: pathlib.Path,
    case_id: str,
    repeat: int,
    trial: dict[str, Any] | None,
    limit: int,
) -> tuple[dict[str, Any], str, str]:
    if trial is None:
        return {}, "missing_trial", "No scheduled trial result present"
    if trial["status"] not in {"pass", "fail"}:
        return {}, "not_completed", "Partial or ungraded output not scored"
    try:
        path = evaluation.contracts.contained(
            run, f"cite-check/{case_id}/{repeat}/response.txt"
        )
        response = read_output(path, limit)
        claims = response.get("claims")
        if not isinstance(claims, dict):
            raise ValueError("Response claims must be an object")
        return claims, "valid", ""
    except FileNotFoundError:
        return {}, "missing_output", "response.txt is missing"
    except (OSError, ValueError, RecursionError) as error:
        return {}, "invalid_output", str(error)


def _claim_row(
    case_id: str,
    repeat: int,
    claim_id: str,
    claims: dict[str, Any],
    gold: GoldClaim,
) -> dict[str, Any]:
    claim = claims.get(claim_id)
    present = claim_id in claims
    verdict = claim.get("verdict") if isinstance(claim, dict) else None
    valid = isinstance(verdict, str) and verdict in _VERDICTS
    verbatim, anchored, restraint = evidence_checks(claim, gold)
    return {
        "case_id": case_id,
        "repeat": repeat,
        "claim_id": claim_id,
        "cohort": gold.cohort,
        "expected": gold.verdict,
        "predicted": verdict if valid else None,
        "omitted": not present,
        "invalid_claim": present and not valid,
        "exact_verdict": valid and verdict == gold.verdict,
        "verbatim_span": verbatim,
        "evidence_anchor_match": anchored,
        "inaccessible_evidence_restraint": restraint,
    }


def _fraction(count: int, total: int) -> dict[str, int | float | None]:
    return {
        "count": count,
        "total": total,
        "rate": count / total if total else None,
    }


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Computes separate rates over every scheduled gold claim slot.

    Args:
        rows: Per-claim observations, including unobserved and invalid outputs.

    Returns:
        Numerators, denominators, and rates; zero denominators have null rates.
    """
    errors = [row for row in rows if row["cohort"] == "planted_error"]
    controls = [row for row in rows if row["cohort"] == "true_control"]
    inaccessible = [row for row in rows if row["cohort"] == "inaccessible"]
    readable = [row for row in rows if row["cohort"] != "inaccessible"]
    detected = sum(row["predicted"] in _ERRORS for row in errors)
    return {
        "scheduled_claims": len(rows),
        "exact_verdict_accuracy": _fraction(
            sum(row["exact_verdict"] for row in rows), len(rows)
        ),
        "planted_errors_detected": _fraction(detected, len(errors)),
        "planted_errors_missed": _fraction(len(errors) - detected, len(errors)),
        "false_accusations_on_controls": _fraction(
            sum(row["predicted"] in _ERRORS for row in controls), len(controls)
        ),
        "controls_unassessed": _fraction(
            sum(row["predicted"] in {None, "unverifiable"} for row in controls),
            len(controls),
        ),
        "omitted_claims": _fraction(
            sum(row["omitted"] for row in rows), len(rows)
        ),
        "invalid_claim_outputs": _fraction(
            sum(row["invalid_claim"] for row in rows), len(rows)
        ),
        "verbatim_evidence_spans": _fraction(
            sum(row["verbatim_span"] for row in readable), len(readable)
        ),
        "evidence_anchor_matches": _fraction(
            sum(row["evidence_anchor_match"] for row in readable), len(readable)
        ),
        "inaccessible_triage": _fraction(
            sum(row["predicted"] == "unverifiable" for row in inaccessible),
            len(inaccessible),
        ),
        "inaccessible_evidence_restraint": _fraction(
            sum(row["inaccessible_evidence_restraint"] for row in inaccessible),
            len(inaccessible),
        ),
        "false_accusations_on_inaccessible": _fraction(
            sum(row["predicted"] in _ERRORS for row in inaccessible),
            len(inaccessible),
        ),
    }


def score_report(
    report_path: pathlib.Path,
    repo: pathlib.Path,
    repeats: int,
) -> dict[str, Any]:
    """Scores an entire citation suite, preserving expected missing trials.

    Args:
        report_path: Shared run report, beside its trial output directories.
        repo: Repository holding the current fixtures and grading contract.
        repeats: Explicit expected repetitions for every cite-check case.

    Returns:
        Per-claim records, separate metrics, and compatibility provenance.

    Raises:
        ValueError: The report, expected schedule, or fingerprints are invalid.
        OSError: The report cannot be read.
    """
    if type(repeats) is not int or repeats < 1:
        raise ValueError("repeats must be a positive integer")
    run = report_path.parent.resolve()
    report_file = evaluation.contracts.contained(run, report_path.name)
    report = read_output(report_file, _REPORT_LIMIT)
    cases, suite = load_suite(repo)
    indexed = _index_trials(report, cases, repeats)
    limit = evaluation.contracts.load_defaults(repo)["max_output_bytes"]
    rows = []
    trials = []
    for case_id, gold_claims in suite.items():
        for repeat in range(1, repeats + 1):
            trial = indexed.get((case_id, repeat))
            claims, state, detail = _read_response(
                run, case_id, repeat, trial, limit
            )
            trials.append(
                {
                    "case_id": case_id,
                    "repeat": repeat,
                    "status": trial["status"] if trial else "missing_trial",
                    "response_status": state,
                    "detail": detail,
                    "unexpected_claim_ids": sorted(
                        set(claims) - set(gold_claims)
                    ),
                }
            )
            for claim_id, gold in gold_claims.items():
                rows.append(_claim_row(case_id, repeat, claim_id, claims, gold))
    return {
        "schema_version": 1,
        "mode": report["mode"],
        "interpretation": (
            "Reference replay: fixture calibration only; no agent performance."
            if report["mode"] == "replay"
            else "Observed live run on controlled synthetic fixtures only."
        ),
        "runner": report["runner"],
        "source_report": str(report_file),
        "expected_repeats": repeats,
        "expected_trials": len(trials),
        "trial_status_counts": dict(
            collections.Counter(trial["status"] for trial in trials)
        ),
        "response_status_counts": dict(
            collections.Counter(trial["response_status"] for trial in trials)
        ),
        "case_fingerprints": {
            case_id: _fingerprint(case) for case_id, case in cases.items()
        },
        "metrics": metrics(rows),
        "by_case": {
            case_id: metrics([row for row in rows if row["case_id"] == case_id])
            for case_id in cases
        },
        "trials": trials,
        "claims": rows,
        "limitations": [
            "Verbatim spans measure quotation provenance, not entailment.",
            "Anchor matching checks fixture-specific literal phrases only.",
            "Missing/invalid/blocked/error outputs remain in denominators.",
            "Low false-accusation rates require reading controls_unassessed.",
            "Live registries, full-text retrieval, and MCP are not measured.",
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    """Renders the separate metric denominators and interpretation limits.

    Args:
        report: Citation-specific score report.

    Returns:
        A readable Markdown report without raw source or response text.
    """
    runner = report["runner"]
    label = str(runner.get("agent") or runner.get("id") or "unknown")
    model = str(runner.get("model") or "unknown")
    label = label.replace("\n", " ").replace("\r", " ")
    model = model.replace("\n", " ").replace("\r", " ")
    lines = [
        "# Cite-check evaluation",
        "",
        report["interpretation"],
        "",
        f"Runner: {label}. Model: {model}.",
        "",
    ]
    lines += ["| Metric | Count / expected | Rate |", "| --- | --- | --- |"]
    for name, metric in report["metrics"].items():
        if name == "scheduled_claims":
            continue
        rate = "unknown" if metric["rate"] is None else f"{metric['rate']:.1%}"
        lines.append(
            f"| {name} | {metric['count']} / {metric['total']} | {rate} |"
        )
    lines += ["", f"Expected trials: {report['expected_trials']}.", ""]
    lines += [f"- {note}" for note in report["limitations"]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Runs citation-specific reporting without launching any model.

    Args:
        argv: CLI arguments, or None to use process arguments.

    Returns:
        Zero for a scored report; two for incompatible or invalid input.
        Metric failures are observations, not scorer execution failures.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=pathlib.Path)
    parser.add_argument("--repeats", type=int, required=True)
    parser.add_argument(
        "--format", choices=("json", "markdown"), default="json"
    )
    arguments = parser.parse_args(argv)
    try:
        report = score_report(arguments.report, _REPO, arguments.repeats)
        output = (
            render_markdown(report)
            if arguments.format == "markdown"
            else json.dumps(report, indent=2, allow_nan=False) + "\n"
        )
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as error:
        print(f"Citation scoring error: {error}", file=sys.stderr)
        return 2
    print(output, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
