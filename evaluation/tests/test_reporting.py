"""Adversarial tests for evaluation denominators and comparison provenance."""

import copy

import pytest

from evaluation import reporting


def _trial(status="pass", **updates):
    result = {
        "skill": "cite-check",
        "case_id": "grounding",
        "repeat": 1,
        "seed": 42,
        "status": status,
        "checks": [],
        "reported_success": None,
        "duration_s": 2.0,
        "usage": None,
        "case_fingerprint": "case-v1",
    }
    result.update(updates)
    return result


def _report(results, mode="replay", config="runner-v1"):
    return {
        "schema_version": 1,
        "mode": mode,
        "runner": {"config_sha256": config},
        "inventory": {
            "skills": ["cite-check", "future"],
            "covered_skills": ["cite-check"],
        },
        "results": results,
        "summary": reporting.summarize(
            results, ["cite-check", "future"], ["cite-check"]
        ),
    }


def test_empty_evaluation_preserves_inventory_and_unknowns():
    summary = reporting.summarize([], ["cite-check", "future"], ["cite-check"])
    assert set(summary["skills"]) == {"cite-check", "future"}
    assert summary["coverage"]["missing_manifests"] == ["future"]
    assert summary["coverage"]["not_executed"] == ["cite-check", "future"]
    assert summary["totals"]["success"]["rate"] is None
    assert summary["totals"]["usage"]["cost_usd"]["total"] is None
    assert summary["totals"]["unsupported_success"]["rate"] is None


def test_all_statuses_keep_denominators_and_reporting_unknowns():
    results = [
        _trial(status, repeat=i)
        for i, status in enumerate(
            ["pass", "fail", "error", "timeout", "blocked"]
        )
    ]
    results[1]["reported_success"] = True
    results[2]["reported_success"] = False
    results[3]["reported_success"] = True
    summary = reporting.summarize(results, ["cite-check"], ["cite-check"])
    totals = summary["totals"]
    assert totals["success"] == {"count": 1, "total": 5, "rate": 0.2}
    assert totals["completion"] == {"count": 2, "total": 5, "rate": 0.4}
    assert totals["attempted"] == 4
    assert totals["status_counts"] == dict.fromkeys(
        ["pass", "fail", "error", "timeout", "blocked"], 1
    )
    assert totals["unsupported_success"]["count"] == 2
    assert totals["unsupported_success"]["total"] == 2
    assert totals["unsupported_success"]["reported_success_unknown"] == 2


def test_missing_usage_does_not_become_zero():
    results = [
        _trial(usage={"input_tokens": 0, "cost_usd": None}),
        _trial(repeat=2, usage={"input_tokens": 5, "cost_usd": 0.3}),
        _trial(repeat=3),
    ]
    usage = reporting.summarize(results, [], [])["totals"]["usage"]
    assert usage["input_tokens"] == {"total": 5, "observed": 2, "scheduled": 3}
    assert usage["cost_usd"] == {"total": 0.3, "observed": 1, "scheduled": 3}
    assert usage["output_tokens"]["total"] is None


def test_no_checks_is_unknown_not_perfect_dimension_score():
    dimensions = reporting.summarize([_trial()], [], [])["totals"]["dimensions"]
    for dimension in dimensions.values():
        assert dimension["scheduled"] == 0
        assert dimension["success"]["rate"] is None
        assert dimension["completion"]["rate"] is None


def test_critical_failures_and_unrun_checks_are_visible():
    checks = [
        {
            "id": str(i),
            "dimension": "constraint_adherence",
            "critical": True,
            "status": status,
            "detail": "missing evidence | unsafe\nclaim",
        }
        for i, status in enumerate(["pass", "fail", "error", "not_run"])
    ]
    summary = reporting.summarize([_trial("fail", checks=checks)], [], [])
    dimension = summary["totals"]["dimensions"]["constraint_adherence"]
    assert dimension["completion"]["rate"] == 0.5
    assert dimension["success"]["rate"] == 0.25
    assert summary["totals"]["critical_failed_checks"] == 2
    assert [check["status"] for check in summary["critical_failures"]] == [
        "fail",
        "error",
    ]


def test_reliability_groups_by_skill_and_case():
    results = [
        _trial(),
        _trial("fail", repeat=2),
        _trial(case_id="second"),
        _trial(case_id="second", repeat=2),
        _trial(skill="other"),
        _trial("timeout", skill="other", repeat=2),
    ]
    reliability = reporting.summarize(results, [], [])["totals"]["reliability"]
    assert reliability["cases"] == 3
    assert reliability["repeated_cases"] == 3
    assert reliability["all_passed_cases"] == 1
    assert reliability["inconsistent_cases"] == 2


def test_blocked_skill_is_scheduled_but_not_executed():
    summary = reporting.summarize(
        [_trial("blocked")], ["cite-check"], ["cite-check"]
    )
    assert summary["coverage"]["scheduled_skills"] == ["cite-check"]
    assert summary["coverage"]["executed_skills"] == []
    assert summary["coverage"]["execution_coverage"]["rate"] == 0


def test_unknown_skill_is_visible_without_inflating_coverage():
    summary = reporting.summarize(
        [_trial(skill="unexpected")], ["future"], ["unexpected"]
    )
    assert summary["coverage"]["unknown_skills"] == ["unexpected"]
    assert summary["coverage"]["manifest_coverage"]["rate"] == 0
    assert summary["coverage"]["execution_coverage"]["rate"] == 0


def test_duplicate_trial_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        reporting.summarize([_trial(), _trial()], [], [])


def test_missing_baseline_trials_never_count_as_passed():
    baseline = _report([_trial(), _trial(case_id="missing")])
    current = _report([_trial("fail"), _trial(case_id="new")])
    comparison = reporting.compare(current, baseline)
    assert comparison["comparable"] == 1
    assert len(comparison["regressions"]) == 1
    assert comparison["new_cases"][0]["case_id"] == "new"
    assert comparison["missing_cases"][0]["case_id"] == "missing"


@pytest.mark.parametrize(
    "change",
    ["rubric", "mode", "runner", "missing_case_hash", "missing_runner_hash"],
)
def test_incomparable_changes_exclude_outcomes_and_costs(change):
    baseline = _report([_trial(usage={"cost_usd": 1.0})])
    current = _report([_trial("fail", usage={"cost_usd": 2.0})])
    if change == "rubric":
        current["results"][0]["case_fingerprint"] = "changed"
    elif change == "mode":
        current["mode"] = "live"
    elif change == "runner":
        current["runner"]["config_sha256"] = "changed"
    elif change == "missing_case_hash":
        del current["results"][0]["case_fingerprint"]
    else:
        del current["runner"]["config_sha256"]
    comparison = reporting.compare(current, baseline)
    assert comparison["comparable"] == 0
    assert len(comparison["incomparable"]) == 1
    assert comparison["regressions"] == []
    assert comparison["usage"]["cost_usd"]["delta"] is None
    assert comparison["duration_s"]["delta"] is None


def test_paired_usage_and_duration_ignore_unmatched_observations():
    baseline = _report(
        [
            _trial(usage={"cost_usd": 0.2}),
            _trial(repeat=2, usage={"cost_usd": 100}),
            _trial(repeat=3, duration_s=1000),
        ]
    )
    current = _report(
        [
            _trial(usage={"cost_usd": 0.5}, duration_s=5),
            _trial(repeat=2, duration_s=None),
            _trial(repeat=4, usage={"cost_usd": 1000}, duration_s=500),
        ]
    )
    comparison = reporting.compare(current, baseline)
    assert comparison["usage"]["cost_usd"]["observed_pairs"] == 1
    assert comparison["usage"]["cost_usd"]["delta"] == pytest.approx(0.3)
    assert comparison["duration_s"]["delta"] == 3


def test_improvements_and_failure_mode_changes_are_separate():
    baseline = _report([_trial("fail"), _trial("timeout", repeat=2)])
    current = _report([_trial("pass"), _trial("error", repeat=2)])
    comparison = reporting.compare(current, baseline)
    assert len(comparison["improvements"]) == 1
    assert len(comparison["outcome_changes"]) == 2
    assert comparison["regressions"] == []


def test_markdown_labels_replay_and_unknown_usage():
    report = _report([_trial()])
    rendered = reporting.markdown(report)
    assert "Replay calibration (not agent performance)" in rendered
    assert "cost_usd: unknown; observed 0/1" in rendered
    assert "future" in rendered
    assert "unknown (0/0)" in rendered
    report["mode"] = "live"
    assert "Live agent evaluation" in reporting.markdown(report)


def test_report_functions_do_not_mutate_input():
    current = _report([_trial()])
    original = copy.deepcopy(current)
    reporting.compare(current, current)
    reporting.markdown(current)
    assert current == original


@pytest.mark.parametrize("seed", [None, 43])
def test_seed_mismatch_or_missing_excludes_measurements(seed):
    baseline = _report([_trial()])
    current = _report([_trial("fail", seed=seed)])
    comparison = reporting.compare(current, baseline)
    assert comparison["comparable"] == 0
    assert not comparison["regressions"]
    assert comparison["duration_s"]["delta"] is None
    assert "seed" in comparison["incomparable"][0]["reasons"][0]


@pytest.mark.parametrize("version", [None, True, 1.0, "1", 2])
def test_unsupported_schema_rejected_by_public_report_apis(version):
    baseline = _report([_trial()])
    current = _report([_trial()])
    current["schema_version"] = version
    with pytest.raises(ValueError, match="schema_version"):
        reporting.compare(current, baseline)
    with pytest.raises(ValueError, match="schema_version"):
        reporting.compare(baseline, current)
    with pytest.raises(ValueError, match="schema_version"):
        reporting.markdown(current)


@pytest.mark.parametrize(
    "field,value",
    [
        ("results", None),
        ("results", [None]),
        ("results", [{}]),
        ("runner", []),
        ("inventory", {}),
        ("mode", "unknown"),
    ],
)
def test_malformed_envelopes_raise_value_error(field, value):
    report = _report([_trial()])
    report[field] = value
    with pytest.raises(ValueError):
        reporting.compare(report, _report([]))
    with pytest.raises(ValueError):
        reporting.markdown(report)


@pytest.mark.parametrize(
    "field,value",
    [
        ("skill", []),
        ("repeat", True),
        ("status", {}),
        ("checks", None),
        ("checks", [{}]),
        ("seed", True),
        ("duration_s", float("nan")),
        ("usage", []),
        ("usage", {"cost_usd": -1}),
        ("usage", {"tool_calls": 1.5}),
        ("case_fingerprint", []),
        ("reported_success", 1),
    ],
)
def test_malformed_trials_raise_value_error(field, value):
    report = _report([_trial()])
    report["results"][0][field] = value
    with pytest.raises(ValueError):
        reporting.compare(report, _report([]))
    with pytest.raises(ValueError):
        reporting.markdown(report)


def test_markdown_recomputes_summary_from_observations():
    report = _report([_trial("fail")])
    report["summary"] = {"skills": "untrustworthy"}
    assert "0/1 (0.0%)" in reporting.markdown(report)


def test_seed_zero_remains_comparable():
    report = _report([_trial(seed=0)])
    assert reporting.compare(report, report)["comparable"] == 1
