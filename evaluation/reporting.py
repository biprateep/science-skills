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
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


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
        current: Current validated run report with provenance and results.
        baseline: Earlier validated run report with provenance and results.

    Returns:
        Comparable outcome changes, exclusions, new/missing trials, and
        paired usage and duration deltas. Duration uses seconds, cost USD.
    """
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
        report: Validated run report containing a summary from summarize().

    Returns:
        Markdown with visible denominators, unknowns, and critical failures.
    """
    summary = report["summary"]
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
