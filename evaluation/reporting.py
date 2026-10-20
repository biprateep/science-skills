"""Aggregate transparent skill evaluation metrics and comparable baselines."""

import collections
import math
from typing import Any, TypeGuard

_STATUSES = ("pass", "fail", "error", "timeout", "blocked")
_DIMENSIONS = ("task_success", "constraint_adherence", "coverage")
_USAGE = ("input_tokens", "output_tokens", "tool_calls", "cost_usd")


def _fraction(count: int, total: int) -> dict[str, Any]:
    return {
        "count": count,
        "total": total,
        "rate": count / total if total else None,
    }


def _observations(values: list[int | float], total: int) -> dict[str, Any]:
    return {
        "total": sum(values) if values else None,
        "observed": len(values),
        "scheduled": total,
    }


def _number(value: Any) -> TypeGuard[int | float]:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def _usage(results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        name: _observations(
            [
                result["usage"][name]
                for result in results
                if _number((result.get("usage") or {}).get(name))
            ],
            len(results),
        )
        for name in _USAGE
    }


def _dimensions(results: list[dict[str, Any]]) -> dict[str, Any]:
    checks = []
    for result in results:
        checks.extend(result.get("checks", []))
    dimensions = {}
    for name in _DIMENSIONS:
        relevant = [check for check in checks if check["dimension"] == name]
        counts = collections.Counter(check["status"] for check in relevant)
        completed = counts["pass"] + counts["fail"]
        dimensions[name] = {
            "scheduled": len(relevant),
            "status_counts": {
                status: counts[status]
                for status in ("pass", "fail", "error", "not_run")
            },
            "completion": _fraction(completed, len(relevant)),
            "success": _fraction(counts["pass"], len(relevant)),
        }
    return dimensions


def _reliability(results: list[dict[str, Any]]) -> dict[str, Any]:
    cases: dict[tuple[str, str], list[str]] = collections.defaultdict(list)
    for result in results:
        cases[(result["skill"], result["case_id"])].append(result["status"])
    repeated = [statuses for statuses in cases.values() if len(statuses) > 1]
    return {
        "cases": len(cases),
        "all_passed_cases": sum(
            all(status == "pass" for status in statuses)
            for statuses in cases.values()
        ),
        "repeated_cases": len(repeated),
        "all_passed_repeated_cases": sum(
            all(status == "pass" for status in statuses)
            for statuses in repeated
        ),
        "inconsistent_cases": sum(
            len(set(statuses)) > 1 for statuses in repeated
        ),
        "note": "Repeated fixture trials are not independent observations.",
    }


def _critical_failures(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures = []
    for result in results:
        for check in result.get("checks", []):
            if check.get("critical") and check["status"] in ("fail", "error"):
                failures.append(
                    {
                        "skill": result["skill"],
                        "case_id": result["case_id"],
                        "repeat": result["repeat"],
                        "check_id": check["id"],
                        "status": check["status"],
                        "detail": check.get("detail", ""),
                    }
                )
    return failures


def _metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    counts = collections.Counter(result["status"] for result in results)
    scheduled = len(results)
    known = [r for r in results if isinstance(r.get("reported_success"), bool)]
    claimed = [r for r in known if r["reported_success"]]
    unsupported = sum(
        r["status"] in ("fail", "error", "timeout") for r in claimed
    )
    return {
        "scheduled": scheduled,
        "status_counts": {status: counts[status] for status in _STATUSES},
        "success": _fraction(counts["pass"], scheduled),
        "completion": _fraction(counts["pass"] + counts["fail"], scheduled),
        "attempted": scheduled - counts["blocked"],
        "dimensions": _dimensions(results),
        "critical_failed_checks": len(_critical_failures(results)),
        "unsupported_success": {
            **_fraction(unsupported, len(claimed)),
            "reported_success_observed": len(known),
            "reported_success_unknown": scheduled - len(known),
            "observation_coverage": _fraction(len(known), scheduled),
        },
        "usage": _usage(results),
        "duration_s": _observations(
            [r["duration_s"] for r in results if _number(r.get("duration_s"))],
            scheduled,
        ),
        "reliability": _reliability(results),
    }


def summarize(
    results: list[dict[str, Any]],
    inventory: list[str],
    manifested: list[str],
) -> dict[str, Any]:
    """Summarize validated trials without imputing unobserved measurements.

    Args:
        results: Validated scheduled trials, including blocked trials.
        inventory: Names of every discovered skill directory.
        manifested: Skill names with evaluation manifests.

    Returns:
        Per-skill metrics, repository coverage, totals, and critical failures.
        Rates with zero denominators and unobserved usage totals are null.
    """
    _index(results)  # Validate uniqueness before counting repeated trials.
    available = set(inventory)
    configured = set(manifested)
    scheduled = {result["skill"] for result in results}
    executed = {r["skill"] for r in results if r["status"] != "blocked"}
    skills = sorted(available | configured | scheduled)
    return {
        "coverage": {
            "inventory_skills": sorted(available),
            "manifested_skills": sorted(configured),
            "scheduled_skills": sorted(scheduled),
            "executed_skills": sorted(executed),
            "missing_manifests": sorted(available - configured),
            "not_scheduled": sorted(available - scheduled),
            "not_executed": sorted(available - executed),
            "unknown_skills": sorted((configured | scheduled) - available),
            "manifest_coverage": _fraction(
                len(available & configured), len(available)
            ),
            "execution_coverage": _fraction(
                len(available & executed), len(available)
            ),
        },
        "skills": {
            skill: _metrics([r for r in results if r["skill"] == skill])
            for skill in skills
        },
        "totals": _metrics(results),
        "critical_failures": _critical_failures(results),
    }


def _index(
    results: list[dict[str, Any]],
) -> dict[tuple[str, str, int], dict[str, Any]]:
    indexed = {}
    for result in results:
        key = (result["skill"], result["case_id"], result["repeat"])
        if key in indexed:
            raise ValueError(f"Duplicate evaluation trial: {key}")
        if result["status"] not in _STATUSES:
            raise ValueError(f"Unknown trial status: {result['status']}")
        indexed[key] = result
    return indexed


def _validate_checks(checks: Any) -> None:
    if not isinstance(checks, list):
        raise ValueError("Trial checks must be an array")
    for check in checks:
        if not isinstance(check, dict):
            raise ValueError("Each check must be an object")
        if not isinstance(check.get("id"), str) or not check["id"]:
            raise ValueError("Check id must be a nonempty string")
        if check.get("dimension") not in _DIMENSIONS:
            raise ValueError("Unknown check dimension")
        if check.get("status") not in ("pass", "fail", "error", "not_run"):
            raise ValueError("Unknown check status")
        if type(check.get("critical")) is not bool:
            raise ValueError("Check critical must be boolean")
        if not isinstance(check.get("detail", ""), str):
            raise ValueError("Check detail must be a string")


def _validate_measurements(result: dict[str, Any]) -> None:
    success = result.get("reported_success")
    if success is not None and type(success) is not bool:
        raise ValueError("reported_success must be boolean or null")
    duration = result.get("duration_s")
    if duration is not None and not _number(duration):
        raise ValueError("duration_s must be finite, nonnegative, or null")
    usage = result.get("usage")
    if usage is None:
        return
    if not isinstance(usage, dict):
        raise ValueError("Trial usage must be an object or null")
    for name in _USAGE:
        value = usage.get(name)
        if value is None:
            continue
        if not _number(value):
            raise ValueError(f"Usage {name} must be finite and nonnegative")
        if name != "cost_usd" and type(value) is not int:
            raise ValueError(f"Usage {name} must be an integer")


def _validate_trial(result: Any) -> None:
    if not isinstance(result, dict):
        raise ValueError("Each trial must be an object")
    for name in ("skill", "case_id"):
        if not isinstance(result.get(name), str) or not result[name]:
            raise ValueError(f"Trial {name} must be a nonempty string")
    repeat = result.get("repeat")
    if type(repeat) is not int or repeat < 0:
        raise ValueError("Trial repeat must be a nonnegative integer")
    if result.get("status") not in _STATUSES:
        raise ValueError("Unknown trial status")
    seed = result.get("seed")
    if seed is not None and (type(seed) is not int or seed < 0):
        raise ValueError("Trial seed must be a nonnegative integer or null")
    fingerprint = result.get("case_fingerprint")
    if fingerprint is not None and not isinstance(fingerprint, str):
        raise ValueError("Case fingerprint must be a string")
    _validate_checks(result.get("checks"))
    _validate_measurements(result)


def _validate_report(report: Any) -> None:
    if not isinstance(report, dict):
        raise ValueError("Report must be an object")
    version = report.get("schema_version")
    if type(version) is not int or version != 1:
        raise ValueError("Report schema_version must be integer 1")
    if report.get("mode") not in ("replay", "live"):
        raise ValueError("Report mode must be replay or live")
    runner = report.get("runner")
    if not isinstance(runner, dict):
        raise ValueError("Report runner must be an object")
    fingerprint = runner.get("config_sha256")
    if fingerprint is not None and not isinstance(fingerprint, str):
        raise ValueError("Runner configuration fingerprint must be a string")
    inventory = report.get("inventory")
    if not isinstance(inventory, dict):
        raise ValueError("Report inventory must be an object")
    for name in ("skills", "covered_skills"):
        skills = inventory.get(name)
        if not isinstance(skills, list) or not all(
            isinstance(skill, str) and skill for skill in skills
        ):
            raise ValueError(f"Inventory {name} must be an array of names")
    results = report.get("results")
    if not isinstance(results, list):
        raise ValueError("Report results must be an array")
    for result in results:
        _validate_trial(result)


def _identity(key: tuple[str, str, int]) -> dict[str, Any]:
    return {"skill": key[0], "case_id": key[1], "repeat": key[2]}


def _compatibility(
    current: dict[str, Any], baseline: dict[str, Any]
) -> list[str]:
    reasons = []
    if current.get("mode") not in ("replay", "live"):
        reasons.append("current mode missing or invalid")
    if current.get("mode") != baseline.get("mode"):
        reasons.append("mode changed")
    current_hash = current.get("runner", {}).get("config_sha256")
    baseline_hash = baseline.get("runner", {}).get("config_sha256")
    if not current_hash or not baseline_hash:
        reasons.append("runner configuration fingerprint missing")
    elif current_hash != baseline_hash:
        reasons.append("runner configuration changed")
    return reasons


def _paired_delta(
    pairs: list[tuple[dict[str, Any], dict[str, Any]]], name: str
) -> dict[str, Any]:
    observations = []
    for current, baseline in pairs:
        if name == "duration_s":
            after, before = current.get(name), baseline.get(name)
        else:
            after = (current.get("usage") or {}).get(name)
            before = (baseline.get("usage") or {}).get(name)
        if _number(after) and _number(before):
            observations.append((after, before))
    after_total = sum(after for after, _ in observations)
    before_total = sum(before for _, before in observations)
    return {
        "observed_pairs": len(observations),
        "comparable_pairs": len(pairs),
        "current_total": after_total if observations else None,
        "baseline_total": before_total if observations else None,
        "delta": after_total - before_total if observations else None,
    }


def _compare_trials(
    current: dict[tuple[str, str, int], dict[str, Any]],
    baseline: dict[tuple[str, str, int], dict[str, Any]],
    reasons: list[str],
) -> tuple[dict[str, Any], list[tuple[dict[str, Any], dict[str, Any]]]]:
    output: dict[str, Any] = {
        "regressions": [],
        "improvements": [],
        "outcome_changes": [],
        "incomparable": [],
    }
    pairs = []
    for key in sorted(current.keys() & baseline.keys()):
        after, before = current[key], baseline[key]
        trial_reasons = list(reasons)
        if not after.get("case_fingerprint") or not before.get(
            "case_fingerprint"
        ):
            trial_reasons.append("case fingerprint missing")
        elif after["case_fingerprint"] != before["case_fingerprint"]:
            trial_reasons.append("case definition changed")
        if after.get("seed") is None or before.get("seed") is None:
            trial_reasons.append("trial seed missing")
        elif after["seed"] != before["seed"]:
            trial_reasons.append("trial seed changed")
        if trial_reasons:
            output["incomparable"].append(
                {**_identity(key), "reasons": trial_reasons}
            )
            continue
        pairs.append((after, before))
        if after["status"] == before["status"]:
            continue
        change = {
            **_identity(key),
            "baseline": before["status"],
            "current": after["status"],
        }
        output["outcome_changes"].append(change)
        if before["status"] == "pass":
            output["regressions"].append(change)
        elif after["status"] == "pass":
            output["improvements"].append(change)
    return output, pairs


def compare(
    current: dict[str, Any], baseline: dict[str, Any]
) -> dict[str, Any]:
    """Compare matching trials only when their measurement settings agree.

    Args:
        current: Current schema version 1 report with provenance and results.
        baseline: Earlier schema version 1 report with provenance and results.

    Returns:
        Comparable outcome changes, exclusions, new/missing trials, and
        paired usage and duration deltas. Duration uses seconds, cost USD.
    """
    _validate_report(current)
    _validate_report(baseline)
    current_trials = _index(current["results"])
    baseline_trials = _index(baseline["results"])
    reasons = _compatibility(current, baseline)
    output, pairs = _compare_trials(current_trials, baseline_trials, reasons)
    return {
        **output,
        "warnings": reasons,
        "comparable": len(pairs),
        "new_cases": [
            _identity(k)
            for k in sorted(current_trials.keys() - baseline_trials.keys())
        ],
        "missing_cases": [
            _identity(k)
            for k in sorted(baseline_trials.keys() - current_trials.keys())
        ],
        "duration_s": _paired_delta(pairs, "duration_s"),
        "usage": {name: _paired_delta(pairs, name) for name in _USAGE},
    }


def _escape(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def _rate(fraction: dict[str, Any]) -> str:
    if fraction["rate"] is None:
        return f"unknown ({fraction['count']}/{fraction['total']})"
    return f"{fraction['count']}/{fraction['total']} ({fraction['rate']:.1%})"


def _skill_table(summary: dict[str, Any]) -> list[str]:
    lines = [
        "| Skill | Success / scheduled | Completion | Attempted "
        "| Fail | Error | Timeout | Blocked |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for skill, metrics in summary["skills"].items():
        counts = metrics["status_counts"]
        cells = [
            _escape(skill),
            _rate(metrics["success"]),
            _rate(metrics["completion"]),
            str(metrics["attempted"]),
        ]
        cells.extend(str(counts[status]) for status in _STATUSES[1:])
        lines.append(f"| {' | '.join(cells)} |")
    return lines


def _coverage_text(summary: dict[str, Any]) -> list[str]:
    coverage = summary["coverage"]
    missing = ", ".join(map(_escape, coverage["missing_manifests"])) or "none"
    unexecuted = ", ".join(map(_escape, coverage["not_executed"])) or "none"
    return [
        f"Manifest coverage: {_rate(coverage['manifest_coverage'])}.",
        f"Execution coverage: {_rate(coverage['execution_coverage'])}.",
        f"Missing manifests: {missing}.",
        f"Skills not executed: {unexecuted}.",
    ]


def _usage_text(summary: dict[str, Any]) -> list[str]:
    lines = ["## Observed resource usage", ""]
    for name, values in summary["totals"]["usage"].items():
        total = "unknown" if values["total"] is None else str(values["total"])
        lines.append(
            f"- {name}: {total}; observed "
            f"{values['observed']}/{values['scheduled']} trials."
        )
    success = summary["totals"]["unsupported_success"]
    lines.extend(
        [
            "",
            f"Unsupported success claims: {_rate(success)}; success reporting "
            f"observed on {success['reported_success_observed']} trials, "
            f"unknown on {success['reported_success_unknown']}.",
        ]
    )
    return lines


def _critical_text(summary: dict[str, Any]) -> list[str]:
    lines = [
        "",
        "## Critical failed checks",
        "",
    ]
    for failure in summary["critical_failures"]:
        lines.append(
            f"- {_escape(failure['skill'])}/{_escape(failure['case_id'])}, "
            f"repeat {failure['repeat']}, {_escape(failure['check_id'])} "
            f"({failure['status']}): {_escape(failure['detail'])}"
        )
    if not summary["critical_failures"]:
        lines.append("None observed.")
    return lines


def markdown(report: dict[str, Any]) -> str:
    """Render a concise report distinguishing calibration from live evaluation.

    Args:
        report: Schema version 1 run report with results and skill inventory.

    Returns:
        Markdown with visible denominators, unknowns, and critical failures.
    """
    _validate_report(report)
    summary = summarize(
        report["results"],
        report["inventory"]["skills"],
        report["inventory"]["covered_skills"],
    )
    label = (
        "Replay calibration (not agent performance)"
        if report["mode"] == "replay"
        else "Live agent evaluation"
    )
    lines = [f"# {label}", "", *_skill_table(summary), ""]
    lines.extend(_coverage_text(summary))
    lines.extend(["", *_usage_text(summary), *_critical_text(summary)])
    reliability = summary["totals"]["reliability"]
    lines.extend(
        [
            "",
            f"All-pass cases: {reliability['all_passed_cases']}/"
            f"{reliability['cases']}; inconsistent repeated cases: "
            f"{reliability['inconsistent_cases']}/{reliability['repeated_cases']}.",
            reliability["note"],
            "",
        ]
    )
    return "\n".join(lines)
