"""Actionable findings assembled from current requirements and evidence."""

from typing import Any
from cite_check_engine import evidence as _engine_evidence
from cite_check_engine import identifiers as _engine_identifiers


def _correction_action(finding: dict[str, Any]) -> dict[str, str]:
    """Give an honest next step without inventing scientific replacements."""
    kind = finding["type"]
    if kind in {"support-stale", "audit-stale", "report-stale"}:
        action, instruction = (
            "re-judge",
            (
                "Refresh the changed inputs and obtain a new indepe"
                "ndent judgment."
            ),
        )
    elif kind == "decomposition-stale":
        action, instruction = (
            "register-claims",
            (
                "Extract current sentences, register their complete"
                " atomic spans, "
                "then judge each attached occurrence."
            ),
        )
    elif kind == "support-missing":
        action, instruction = (
            "judge-claim",
            (
                "Retrieve this cited work and record an independent support "
                "judgment for this exact assertion and occurrence."
            ),
        )
    elif kind == "support-basis" or finding.get("verdict") == "UNVERIFIABLE":
        action, instruction = (
            "obtain-text",
            (
                "Obtain adequate source text and re-judge; do not i"
                "nfer support "
                "from inaccessible evidence."
            ),
        )
    elif kind == "support":
        action, instruction = (
            "review-assertion",
            (
                "Review the disputed assertion against the evidence"
                ". A human may "
                "revise or remove it, or identify and verify an alt"
                "ernative work; "
                "then extract and judge the changed text again."
            ),
        )
    elif kind in {"existence", "verify-error", "undefined-cite"}:
        action, instruction = (
            "resolve-identity",
            (
                "Resolve the intended work through the citation tools. Retry "
                "failed lookups; obtain any replacement bibliograph"
                "y entry from "
                "an official export, never from invented metadata."
            ),
        )
    elif kind == "publication-status":
        action, instruction = (
            "review-publication-status",
            "Review the linked registry notice and its effect on the cited "
            "assertion. A correction does not invalidate every claim; a "
            "reported retraction blocks strict submission readiness.",
        )
    elif kind == "provenance":
        action, instruction = (
            "refresh-official-export",
            (
                "Check the intended identity and replace the entry through "
                "bib_add using its official export."
            ),
        )
    elif kind == "uncited-atom":
        action, instruction = (
            "review-scope",
            (
                "Review the declared uncited scope; it has not been externally "
                "verified and must not conceal a cited assertion."
            ),
        )
    elif kind == "uncited-entry":
        action, instruction = (
            "review-unused-entry",
            ("Review whether this unused bibliography entry should remain."),
        )
    elif kind == "policy-configuration":
        action, instruction = (
            "run-required-checks",
            (
                "Enable identity and support checks for submission readiness, "
                "or explicitly use exploratory mode for partial work."
            ),
        )
    else:
        action, instruction = (
            "repair-input",
            (
                "Inspect the reported input problem, repair it explicitly, and "
                "rerun the audit before relying on the result."
            ),
        )
    return {"action": action, "instruction": instruction}

def _correction_items(
    report: dict[str, Any],
    extracted: dict[str, Any],
    judgments: dict[str, dict[str, Any]],
    verification: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach findings to exact current occurrences, never truncated text."""
    items = []
    for severity, findings in (
        ("failure", report["failures"]),
        ("warning", report["warnings"]),
    ):
        for finding in findings:
            targets = []
            for cite in extracted.get("cites", []):
                if finding.get("occurrence_id") == cite["occurrence_id"]:
                    targets = [cite]
                    break
                if (
                    not finding.get("occurrence_id")
                    and finding.get("key")
                    and finding["key"] == cite["key"]
                ):
                    targets.append(cite)
            for target in targets or [None]:
                occurrence = target["occurrence_id"] if target else None
                atom_id = finding.get("atom_id")
                judgment = (
                    judgments.get(_engine_evidence._support_id(occurrence, atom_id))
                    if occurrence
                    else None
                )
                if finding["type"] in {
                    "support-stale",
                    "decomposition-stale",
                    "audit-stale",
                }:
                    judgment = None
                key = target["key"] if target else finding.get("key")
                location = {
                    "file": target["file"] if target else finding.get("file"),
                    "line": target["line"] if target else finding.get("line"),
                    "kind": "citation-command"
                    if target
                    else "reported-or-unknown",
                    "source_byte_start": target.get("source_byte_start")
                    if target
                    else None,
                    "source_byte_end": target.get("source_byte_end")
                    if target
                    else None,
                }
                if target:
                    location.update(
                        {
                            name: target.get(name)
                            for name in (
                                "page",
                                "page_line",
                                "source_start",
                                "source_end",
                                "source_offset_unit",
                            )
                        }
                    )
                source = None
                proposal = None
                if judgment:
                    source = _engine_evidence._correction_evidence(
                        judgment,
                        verification.get(key, {}).get("status") == "VERIFIED"
                        and not extracted.get("review_only", False),
                    )
                    if (
                        source is not None
                        and judgment.get("occurrence_id") == occurrence
                    ):
                        stored = judgment.get("proposed_correction")
                        if stored is not None:
                            proposal = dict(
                                stored,
                                approval="unapproved",
                                replacement_verified=False,
                            )
                sentence: dict[str, Any] = next(
                    (
                        value
                        for value in extracted.get("sentences", [])
                        if value["sentence_id"] == finding.get("sentence_id")
                    ),
                    {},
                )
                item = {
                    "finding_id": _engine_identifiers._atomic_digest(
                        [
                            severity,
                            finding,
                            occurrence,
                            atom_id,
                        ]
                    ),
                    "severity": severity,
                    "type": finding["type"],
                    "key": key,
                    "occurrence_id": occurrence,
                    "atom_id": atom_id,
                    "sentence_id": target.get("sentence_id")
                    if target
                    else finding.get("sentence_id"),
                    "location": location,
                    "bibliography_locations": report.get(
                        "bibliography_locations", {}
                    ).get(key, []),
                    "claim": target["claim"]
                    if target
                    else finding.get("claim"),
                    "context": target["context"]
                    if target
                    else sentence.get("context"),
                    "assertion": finding.get("atom")
                    or (target["claim"] if target else finding.get("claim")),
                    "detail": finding.get("detail"),
                    "verdict": finding.get("verdict"),
                    "status": finding.get("status"),
                    "next_action": _correction_action(finding),
                    "publication_status": finding.get("publication_status"),
                    "source_evidence": source,
                    "proposed_correction": proposal,
                    "applied": False,
                }
                items.append(item)
    return items

def _invalidate_corrections(report: dict[str, Any]) -> None:
    """Suppress evidence and wording when the report's inputs are stale."""
    for item in report.get("corrections", []):
        item["source_evidence"] = None
        item["proposed_correction"] = None
        item["evidence_status"] = "suppressed-stale-report"
        item["next_action"] = {
            "action": "refresh-audit",
            "instruction": "Inputs changed. Rerun extraction and audit, then re-judge affected assertions before considering corrections.",
        }
