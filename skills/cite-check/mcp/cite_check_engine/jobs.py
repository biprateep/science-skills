"""Prioritized resumable registry-verification jobs and honest accounting."""

import dataclasses
import hashlib
import json
import math
import os
import re
import uuid
from typing import Any, Literal
from cite_check_engine import acquisition as _engine_acquisition
from cite_check_engine import bibliography as _engine_bibliography
from cite_check_engine import budgets as _engine_budgets
from cite_check_engine import config as _engine_config
from cite_check_engine import evidence as _engine_evidence
from cite_check_engine import freshness as _engine_freshness
from cite_check_engine import identifiers as _engine_identifiers
from cite_check_engine import manuscripts as _engine_manuscripts
from cite_check_engine import models as _engine_models
from cite_check_engine import parsing as _engine_parsing
from cite_check_engine import persistence as _engine_persistence


def _job_priorities(
    values: list[Any] | None, requirements: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Validate scheduling advice against current occurrence/atom pairs."""
    if values is None:
        return []
    if not isinstance(values, list):
        raise ValueError("priorities must be a list")
    targets = {
        (item["occurrence_id"], item.get("atom_id")) for item in requirements
    }
    seen = set()
    result = []
    for raw in values:
        value = (
            dataclasses.asdict(raw) if isinstance(raw, _engine_models.ClaimPriority) else raw
        )
        if (
            not isinstance(value, dict)
            or not {"occurrence_id", "reason"} <= set(value)
            or set(value) - {"occurrence_id", "atom_id", "priority", "reason"}
        ):
            raise ValueError("priority needs a current occurrence and reason")
        value = dict(value)
        value.setdefault("atom_id", None)
        value.setdefault("priority", "high")
        occurrence, atom = value["occurrence_id"], value["atom_id"]
        if not isinstance(occurrence, str) or (
            atom is not None and not isinstance(atom, str)
        ):
            raise ValueError("priority target IDs must be strings")
        target = (occurrence, atom)
        if target not in targets or target in seen:
            raise ValueError(
                "priority target is missing, stale, ambiguous or duplicated"
            )
        if (
            value["priority"] not in ("high", "normal", "low")
            or not isinstance(value["reason"], str)
            or len(value["reason"].strip()) < 8
        ):
            raise ValueError(
                "priority must be high/normal/low with a meaningful reason"
            )
        seen.add(target)
        result.append(value)
    return sorted(
        result,
        key=lambda item: (item["occurrence_id"], item["atom_id"] or ""),
    )

def _job_scan(
    tex_path: str,
    bib_path: str | None,
    priorities: list[Any] | None,
    search_unresolved: bool,
) -> dict[str, Any]:
    """Build identity and support obligations from exact snapshots."""
    extracted = _engine_manuscripts.extract_cites(tex_path)
    if not extracted.get("complete"):
        raise ValueError(
            extracted.get("error", "incomplete manuscript extraction")
        )
    bibs = [os.path.abspath(bib_path)] if bib_path else extracted["bib_files"]
    if not bibs and extracted["keys"]:
        raise ValueError("no bibliography; declare it or provide bib_path")
    with _engine_persistence._file_lock(_engine_persistence._project_path(os.path.dirname(tex_path), "ledger.json")):
        ledger = _engine_evidence._audit_ledger(os.path.dirname(tex_path))
        ledger_digest = _engine_persistence._audit_file_digest(
            _engine_persistence._project_path(os.path.dirname(tex_path), "ledger.json")
        )
    files = dict(extracted["source_digests"])
    entries: dict[str, tuple[str, dict[str, Any]]] = {}
    for path in bibs:
        with open(path, "rb") as source:
            raw = source.read()
        files[path] = hashlib.sha256(raw).hexdigest()
        parsed = _engine_parsing._parse_bib(raw.decode("utf-8"))
        if not parsed["complete"]:
            raise ValueError(
                "incomplete bibliography: " + "; ".join(parsed["errors"])
            )
        for entry in parsed["entries"]:
            if entry["key"] in entries:
                raise ValueError("duplicate bibliography key: " + entry["key"])
            entries[entry["key"]] = (path, entry)
    requirements = _engine_evidence._support_requirements(extracted, ledger)
    validated_priorities = _job_priorities(priorities, requirements)
    assigned = {
        (item["occurrence_id"], item["atom_id"]): item
        for item in validated_priorities
    }
    ranks = {"high": 0, "normal": 1, "low": 2}
    support = []
    for required in requirements:
        target = (required["occurrence_id"], required.get("atom_id"))
        priority = assigned.get(
            target,
            {
                "priority": "normal",
                "reason": "Default scheduling order; no "
                "consequence assessment.",
            },
        )
        support.append(
            {
                "id": _engine_identifiers._atomic_digest(["support", *target]),
                "key": required["key"],
                "occurrence_id": target[0],
                "atom_id": target[1],
                "sentence_id": required["sentence_id"],
                "file": required["file"],
                "line": required["line"],
                "page": required.get("page"),
                "page_line": required.get("page_line"),
                "source_offset_unit": required.get("source_offset_unit"),
                "claim": required["claim"],
                "context": required["context"],
                "assertion": required.get("atom", {}).get(
                    "text", required["claim"]
                ),
                "decomposition_stale": bool(
                    required.get("decomposition_stale")
                ),
                "priority": priority["priority"],
                "priority_reason": priority["reason"],
                "priority_source": "caller"
                if target in assigned
                else "default",
                "status": "UNCHECKED",
                "assessment_scope": "not assessed by this registry-only job",
                "next_action": "Use the current strict audit to inspect "
                "existing judgments. Retrieve the "
                "correct source/version and obtain any "
                "missing independent atom/occurrence "
                "judgment; register stale decompositions "
                "first.",
            }
        )
    support.sort(
        key=lambda item: (
            ranks[item["priority"]],
            item["file"],
            item["line"],
            item["id"],
        )
    )
    keys = set(extracted["keys"]) - {"*"}
    if any(item["key"] == "*" for item in extracted["cites"]):
        keys.update(entries)
    identity = []
    printed_keys = {
        item.get("key") for item in extracted.get("inline_bibliography", [])
    }
    for key in sorted(keys):
        path, entry = entries.get(key, (None, {}))
        if key in printed_keys or None in printed_keys:
            path = None
        related = [item for item in support if item["key"] == key]
        identity_priority = min(
            (item["priority"] for item in related),
            key=lambda value: ranks[value],
            default="normal",
        )
        identity.append(
            {
                "id": _engine_identifiers._atomic_digest(["identity", path, key, entry.get("raw")]),
                "key": key,
                "bib_path": path,
                "priority": identity_priority,
                "support_ids": [item["id"] for item in related],
                "occurrence_ids": [
                    item["occurrence_id"]
                    for item in extracted["cites"]
                    if item["key"] == key
                ],
                "status": "UNCHECKED",
                "result": None,
                "attempts": 0,
                "reason": "not attempted"
                if path
                else "undefined citation key; repair bibliography",
            }
        )
    identity.sort(key=lambda item: (ranks[item["priority"]], item["key"]))
    sources = {}
    for judgment in ledger["entries"].values():
        identifier = judgment.get("source_cache_id", judgment["id"])
        sources[identifier] = _engine_acquisition._current_source_identity(identifier)
    snapshot = {
        "files": files,
        "ledger": ledger_digest,
        "sources": sources,
        "input_backend": extracted.get("extraction_metadata", {}).get(
            "extractor"
        )
        if extracted.get("input_format") == "pdf"
        else None,
    }
    if not _engine_freshness._correction_snapshot_current(snapshot, os.path.dirname(tex_path)):
        raise ValueError("inputs changed while scanning; rescan")
    return {
        "config": {
            "tex_path": tex_path,
            "bib_path": os.path.abspath(bib_path) if bib_path else None,
            "priorities": validated_priorities,
            "search_unresolved": search_unresolved,
            "tool_version": _engine_config.VERSION,
            "job_policy": _engine_budgets._JOB_POLICY,
            "pricing_policy": _engine_budgets._PRICING_POLICY,
        },
        "snapshot": snapshot,
        "identity_queue": identity,
        "support_queue": support,
        "input_scope": {
            name: extracted.get(name)
            for name in (
                "input_format",
                "scope_complete",
                "review_only",
                "diagnostics",
            )
        },
        "uncited_scope": [
            dict(atom, verified=False)
            for registration in ledger.get("decompositions", {}).values()
            if registration.get("tex_path") == tex_path
            and registration["sentence_id"]
            in {item["sentence_id"] for item in extracted["sentences"]}
            for atom in registration["atoms"]
            if atom["kind"] == "uncited"
        ],
    }

def _job_write(path: str, job: dict[str, Any]) -> None:
    """Atomically save state with a corruption-detection checksum."""
    job["updated"] = _engine_persistence._now_iso()
    payload = dict(job)
    payload["integrity"] = _engine_identifiers._atomic_digest(job)
    _engine_persistence._atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2))

def _job_valid_result(result: Any, key: str) -> bool:
    """Validate live and persisted registry outcomes before crediting work."""
    if not isinstance(result, dict) or result.get("key") != key:
        return False
    status = result.get("status")
    if status not in (
        "VERIFIED",
        "FOUND",
        "PROBABLE",
        "MISMATCH",
        "NOT_FOUND",
        "UNRESOLVED",
    ):
        return False
    if status in ("VERIFIED", "FOUND", "PROBABLE", "MISMATCH"):
        identifier = result.get("id")
        if (
            not isinstance(identifier, str)
            or _engine_identifiers._classify(identifier)[0] == "unknown"
        ):
            return False
    if "ids" in result and (
        not isinstance(result["ids"], dict)
        or any(not isinstance(value, str) for value in result["ids"].values())
    ):
        return False
    if "notes" in result and (
        not isinstance(result["notes"], list)
        or any(not isinstance(value, str) for value in result["notes"])
    ):
        return False
    return True

def _job_load(path: str, identifier: str) -> dict[str, Any]:
    """Reject corrupt job metadata, progress states and accounting."""
    with open(path, encoding="utf-8") as source:
        job = json.load(source)
    if not isinstance(job, dict):
        raise ValueError("job state must be an object")
    integrity = job.pop("integrity", None)
    if integrity != _engine_identifiers._atomic_digest(job):
        raise ValueError("job state checksum mismatch")
    if (
        set(job)
        != {
            "schema_version",
            "job_id",
            "created",
            "updated",
            "config",
            "snapshot",
            "identity_queue",
            "support_queue",
            "uncited_scope",
            "input_scope",
            "runs",
        }
        or type(job["schema_version"]) is not int
        or job["schema_version"] != 1
        or job["job_id"] != identifier
    ):
        raise ValueError("unsupported or malformed job state")
    if not isinstance(job["config"], dict) or set(job["config"]) != {
        "tex_path",
        "bib_path",
        "priorities",
        "search_unresolved",
        "tool_version",
        "job_policy",
        "pricing_policy",
    }:
        raise ValueError("invalid job configuration")
    config = job["config"]
    if (
        not isinstance(config["tex_path"], str)
        or (
            config["bib_path"] is not None
            and not isinstance(config["bib_path"], str)
        )
        or not isinstance(config["priorities"], list)
        or type(config["search_unresolved"]) is not bool
    ):
        raise ValueError("invalid job configuration values")
    if not isinstance(job["runs"], list) or not isinstance(
        job["identity_queue"], list
    ):
        raise ValueError("invalid job progress containers")
    identity_fields = {
        "id",
        "key",
        "bib_path",
        "priority",
        "support_ids",
        "occurrence_ids",
        "status",
        "result",
        "attempts",
        "reason",
    }
    for item in job["identity_queue"]:
        if (
            not isinstance(item, dict)
            or set(item) != identity_fields
            or not isinstance(item["key"], str)
            or not item["key"]
            or not isinstance(item["id"], str)
            or re.fullmatch(r"[a-f0-9]{64}", item["id"]) is None
            or (
                item["bib_path"] is not None
                and not isinstance(item["bib_path"], str)
            )
            or item["priority"] not in ("high", "normal", "low")
            or any(
                not isinstance(item[name], list)
                or any(not isinstance(value, str) for value in item[name])
                for name in ("support_ids", "occurrence_ids")
            )
        ):
            raise ValueError("malformed identity queue entry")
        if (
            not isinstance(item, dict)
            or item.get("status") not in ("UNCHECKED", "RUNNING", "ASSESSED")
            or type(item.get("attempts")) is not int
            or item["attempts"] < 0
            or not isinstance(item.get("reason"), str)
        ):
            raise ValueError("invalid identity progress")
        result = item.get("result")
        if result is not None and not _job_valid_result(result, item["key"]):
            raise ValueError("invalid identity result")
        if item["status"] == "ASSESSED" and (
            result is None or result["status"] == "UNRESOLVED"
        ):
            raise ValueError("incomplete result marked assessed")
    for run in job["runs"]:
        if (
            not isinstance(run, dict)
            or set(run) != {"run_id", "limits", "usage", "state"}
            or run["state"]
            not in ("RUNNING", "FINISHED", "PAUSED", "INTERRUPTED")
        ):
            raise ValueError("invalid job run")
        if not isinstance(run["limits"], dict) or set(run["limits"]) != set(
            dataclasses.asdict(_engine_models.VerificationBudget())
        ):
            raise ValueError("incomplete saved budget limits")
        limits = _engine_budgets._validated_budget(run["limits"])
        usage = run["usage"]
        usage_fields = {
            "requests",
            "searches",
            "http_cache_hits",
            "elapsed_seconds",
            "unknown_price_requests",
            "estimated_service_cost_usd",
            "actual_billed_cost_usd",
            "model_tokens",
            "model_calls",
            "external_model_cost_usd",
            "deadline_exceeded",
            "deadline_overshoot_seconds",
            "stop_reason",
        }
        if (not isinstance(usage, dict)
                or set(usage) not in (usage_fields, usage_fields | {"coalesced_waits"})):
            raise ValueError("invalid usage accounting")
        for name in (
            "requests",
            "searches",
            "http_cache_hits",
            "unknown_price_requests",
            "model_calls",
        ):
            if type(usage.get(name)) is not int or usage[name] < 0:
                raise ValueError("invalid usage counter")
        if type(usage.get("coalesced_waits", 0)) is not int or usage.get("coalesced_waits", 0) < 0:
            raise ValueError("invalid coalesced wait counter")
        for name in ("elapsed_seconds", "deadline_overshoot_seconds"):
            if (
                type(usage.get(name)) not in (int, float)
                or not math.isfinite(usage[name])
                or usage[name] < 0
            ):
                raise ValueError("invalid elapsed-time accounting")
        if (
            usage["requests"] > limits["max_requests"]
            or usage["searches"] > limits["max_searches"]
            or usage["unknown_price_requests"] > usage["requests"]
            or usage["model_calls"] != 0
            or usage.get("actual_billed_cost_usd") is not None
            or usage.get("model_tokens") is not None
            or usage.get("external_model_cost_usd") is not None
        ):
            raise ValueError("invalid budget accounting")
        elapsed = usage["elapsed_seconds"]
        if (
            type(usage.get("deadline_exceeded")) is not bool
            or usage["deadline_exceeded"] != (elapsed > limits["max_seconds"])
            or usage["deadline_overshoot_seconds"]
            != max(0.0, elapsed - limits["max_seconds"])
            or (
                usage.get("stop_reason") is not None
                and not isinstance(usage["stop_reason"], str)
            )
        ):
            raise ValueError("invalid deadline accounting")
        expected_cost = None if usage["unknown_price_requests"] else 0.0
        if (
            usage.get("estimated_service_cost_usd") != expected_cost
            or (
                expected_cost is not None
                and type(usage["estimated_service_cost_usd"])
                not in (int, float)
            )
            or (
                limits["max_cost_usd"] is not None
                and usage["unknown_price_requests"]
            )
        ):
            raise ValueError("invalid cost accounting")
    return job

def _job_same_scan(job: dict[str, Any], scan: dict[str, Any]) -> bool:
    """Compare immutable queue/config data separately from recorded progress."""
    mutable = {"status", "result", "attempts", "reason"}

    def identity(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {key: value for key, value in item.items() if key not in mutable}
            for item in items
        ]

    return all(
        job[name] == scan[name]
        for name in (
            "config",
            "snapshot",
            "support_queue",
            "uncited_scope",
            "input_scope",
        )
    ) and identity(job["identity_queue"]) == identity(scan["identity_queue"])

def _job_paths_safe(path: str, snapshot: dict[str, Any]) -> None:
    """Reject job/lock aliases to manuscript, bibliography or source inputs."""
    inputs = list(snapshot["files"])
    inputs.append(os.path.join(os.path.dirname(path), "ledger.json"))
    for identifier in snapshot["sources"]:
        metadata = _engine_persistence._load_text_meta(identifier)
        if metadata and metadata.get("path"):
            inputs.append(metadata["path"])
    for output in (path, path + ".lock"):
        if os.path.islink(output):
            raise ValueError("job output is a symlink")
        for source in inputs:
            if os.path.realpath(output) == os.path.realpath(source) or (
                os.path.exists(output)
                and os.path.exists(source)
                and os.path.samefile(output, source)
            ):
                raise ValueError("job output aliases an input")

def _job_result(job: dict[str, Any], path: str) -> dict[str, Any]:
    """Report identity progress without implying scientific verification."""
    queue = [
        dict(
            item,
            status="UNCHECKED",
            result=None,
            reason="interrupted saved run; identity remains unchecked",
        )
        if item["status"] == "RUNNING"
        else item
        for item in job["identity_queue"]
    ]
    total = {
        name: sum(run["usage"].get(name, 0) for run in job["runs"])
        for name in (
            "requests",
            "searches",
            "http_cache_hits",
            "coalesced_waits",
            "unknown_price_requests",
            "elapsed_seconds",
        )
    }
    total.update(
        estimated_service_cost_usd=None
        if total["unknown_price_requests"]
        else 0.0,
        actual_billed_cost_usd=None,
        model_calls=0,
        model_tokens=None,
        external_model_cost_usd=None,
    )
    result = {
        "ok": True,
        "job_id": job["job_id"],
        "job_path": path,
        "scope": "registry identity only; support is not assessed by this job",
        "submission_ready": False,
        "identity_complete": all(
            item["status"] == "ASSESSED" for item in queue
        ),
        "identity_verified": all(
            item["status"] == "ASSESSED"
            and item["result"]["status"] == "VERIFIED"
            for item in queue
        ),
        "identity_expected": len(queue),
        "input_scope": job["input_scope"],
        "identity_assessed": sum(
            item["status"] == "ASSESSED" for item in queue
        ),
        "identity_unchecked": sum(
            item["status"] != "ASSESSED" for item in queue
        ),
        "support_pending": len(job["support_queue"]),
        "identity_queue": queue,
        "support_queue": job["support_queue"],
        "uncited_scope": job["uncited_scope"],
        "config": job["config"],
        "cumulative_usage": total,
        "runs": job["runs"],
        "elapsed_accounting_complete": all(
            run["state"] not in ("INTERRUPTED", "RUNNING")
            for run in job["runs"]
        ),
        "deadline_semantics": "cooperative; OS/DNS and file operations "
        "may overshoot; elapsed and overshoot "
        "are reported",
        "accounting": "request/search counts are durable "
        "pre-operation reservations, "
        "conservatively including interrupted "
        "admissions; HTTP cache hits consume no "
        "request; actual billing and external "
        "model spend are unknown",
        "next_action": "Resume unchecked identities with "
        "another explicit per-run grant, then "
        "use existing source "
        "retrieval/independent judgment tools "
        "and a fresh submission-ready audit. Job "
        "success is not citation readiness.",
    }
    if not _engine_freshness._correction_snapshot_current(
        job["snapshot"], os.path.dirname(job["config"]["tex_path"])
    ):
        return {
            "ok": False,
            "job_id": job["job_id"],
            "submission_ready": False,
            "identity_complete": False,
            "rescan_required": True,
            "error": "job-stale: inputs changed before "
            "publication; create a new job",
        }
    if (not job["input_scope"].get("scope_complete", True)
            or job["input_scope"].get("review_only")):
        result["identity_observed_expected"] = result["identity_expected"]
        result["identity_observed_complete"] = result["identity_complete"]
        result["identity_expected"] = None
        result["identity_complete"] = False
        result["identity_verified"] = False
    return result

def verification_job(
    tex_path: str,
    bib_path: str | None = None,
    job_id: str | None = None,
    operation: Literal["run", "status"] = "run",
    budget: _engine_models.VerificationBudget | None = None,
    priorities: list[_engine_models.ClaimPriority] | None = None,
    search_unresolved: bool | None = None,
) -> dict[str, Any]:
    """Run or inspect prioritized registry checks under per-invocation limits.

    Args:
        tex_path: Main manuscript path; required on resume too.
        bib_path: Optional override; omitted resume values use saved config.
        job_id: Existing job ID to resume/inspect; omit to create a job.
        operation: Run unchecked identities, or inspect state without network.
        budget: Fresh per-run grant, not a change to previous accounting.
        priorities: Explicit scheduling advice tied to current support IDs.
        search_unresolved: Enable title searches; defaults true for new jobs.

    Returns:
        Identity progress, an unchecked support queue, and measured usage.
        ok means the job command succeeded, never scientific readiness.
    """
    try:
        limits = _engine_budgets._validated_budget(budget)
    except ValueError as invalid_budget:
        return {
            "ok": False,
            "submission_ready": False,
            "error": str(invalid_budget),
        }
    if job_id is not None and (
        not isinstance(job_id, str)
        or re.fullmatch(r"[a-f0-9]{32}", job_id) is None
    ):
        return {
            "ok": False,
            "submission_ready": False,
            "error": "invalid job ID",
        }

    def no_persist(usage: dict[str, Any]) -> None:
        del usage

    if (
        not isinstance(tex_path, str)
        or not tex_path.strip()
        or (
            bib_path is not None
            and (not isinstance(bib_path, str) or not bib_path.strip())
        )
    ):
        return {
            "ok": False,
            "submission_ready": False,
            "error": (
                "manuscript and bibliography paths must be nonempty strings"
            ),
        }
    controller = _engine_budgets._RequestBudget(limits, no_persist)
    token = _engine_budgets._request_budget.set(controller)
    identifier = job_id or uuid.uuid4().hex
    tex_path = os.path.abspath(tex_path)
    workdir = os.path.dirname(tex_path)
    path = os.path.join(workdir, _engine_config.PROJECT_DIR, "job-" + identifier + ".json")
    try:
        if operation not in ("run", "status") or (
            operation == "status" and job_id is None
        ):
            raise ValueError(
                "status requires job_id; operation must be run/status"
            )
        if (
            not isinstance(identifier, str)
            or re.fullmatch(r"[a-f0-9]{32}", identifier) is None
        ):
            raise ValueError("invalid job ID")
        preflight_error = _engine_freshness._correction_preflight(tex_path, bib_path)
        if preflight_error:
            raise ValueError(preflight_error)
        # Inspect immutable config before locking, then reload under lock.
        # This also lets omitted resume parameters adopt a saved override.
        if job_id:
            if os.path.islink(path):
                raise ValueError("job output is a symlink")
            saved = _job_load(path, identifier)["config"]
            if bib_path is None:
                bib_path = saved["bib_path"]
            preflight_error = _engine_freshness._correction_preflight(tex_path, bib_path)
            if preflight_error:
                raise ValueError(preflight_error)
        # Scan before locking so the lock-file cannot alias an input.
        provisional = _job_scan(tex_path, bib_path, None, True)
        _job_paths_safe(path, provisional["snapshot"])
        with _engine_persistence._file_lock(path):
            job = _job_load(path, identifier) if job_id else None
            if job is not None:
                previous = job["config"]
                bib_path = (
                    previous["bib_path"] if bib_path is None else bib_path
                )
                priorities = (
                    previous["priorities"] if priorities is None else priorities
                )
                search_unresolved = (
                    previous["search_unresolved"]
                    if search_unresolved is None
                    else search_unresolved
                )
            if search_unresolved is None:
                search_unresolved = True
            if type(search_unresolved) is not bool:
                raise ValueError("search_unresolved must be boolean")
            scan = _job_scan(tex_path, bib_path, priorities, search_unresolved)
            _job_paths_safe(path, scan["snapshot"])
            if job is not None and not _job_same_scan(job, scan):
                return {
                    "ok": False,
                    "job_id": identifier,
                    "submission_ready": False,
                    "identity_complete": False,
                    "rescan_required": True,
                    "error": "job-stale: inputs, source evidence, "
                    "priorities or configuration changed; "
                    "create a new job",
                }
            if job is None:
                job = dict(
                    scan,
                    schema_version=1,
                    job_id=identifier,
                    created=_engine_persistence._now_iso(),
                    updated=_engine_persistence._now_iso(),
                    runs=[],
                )
            if operation == "status":
                return _job_result(job, path)
            for previous_run in job["runs"]:
                if previous_run["state"] == "RUNNING":
                    previous_run["state"] = "INTERRUPTED"
            for item in job["identity_queue"]:
                if item["status"] == "RUNNING":
                    item.update(
                        status="UNCHECKED",
                        result=None,
                        reason="interrupted; retry with cached prior "
                        "requests where available",
                    )
            run = {
                "run_id": uuid.uuid4().hex,
                "limits": limits,
                "usage": controller.usage(),
                "state": "RUNNING",
            }
            job["runs"].append(run)

            def persist(usage: dict[str, Any]) -> None:
                run["usage"] = usage
                _job_write(path, job)

            controller.persist = persist
            persist(controller.usage())
            try:
                for item in job["identity_queue"]:
                    if item["status"] == "ASSESSED" or item["bib_path"] is None:
                        continue
                    controller.remaining()
                    item.update(
                        status="RUNNING",
                        result=None,
                        reason="in progress",
                        attempts=item["attempts"] + 1,
                    )
                    persist(controller.usage())
                    result = _engine_bibliography.verify_bib(
                        item["bib_path"],
                        keys=[item["key"]],
                        tex_path=tex_path,
                        search_unresolved=search_unresolved,
                    )
                    controller.remaining()
                    if not _engine_freshness._correction_snapshot_current(
                        job["snapshot"], workdir
                    ):
                        raise ValueError(
                            "job-stale: inputs changed during "
                            "verification; create a new job"
                        )
                    rows = (
                        result.get("entries", [])
                        if isinstance(result, dict)
                        else []
                    )
                    row = (
                        rows[0]
                        if isinstance(rows, list)
                        and len(rows) == 1
                        and isinstance(rows[0], dict)
                        and rows[0].get("key") == item["key"]
                        else None
                    )
                    if row is not None and not _job_valid_result(
                        row, item["key"]
                    ):
                        raise ValueError("malformed verifier result")
                    if row is None or row.get("status") == "UNRESOLVED":
                        item.update(
                            status="UNCHECKED",
                            result=row,
                            reason="lookup incomplete; resume to retry",
                        )
                    elif row.get("status") not in {
                        "VERIFIED",
                        "FOUND",
                        "PROBABLE",
                        "MISMATCH",
                        "NOT_FOUND",
                    }:
                        raise ValueError("malformed verifier result")
                    else:
                        item.update(
                            status="ASSESSED",
                            result=row,
                            reason="registry assessment recorded; "
                            "scientific support remains unchecked",
                        )
                    persist(controller.usage())
            except (
                _engine_budgets.BudgetExhaustedError,
                OSError,
                RuntimeError,
                ValueError,
            ) as error:
                for item in job["identity_queue"]:
                    if item["status"] == "RUNNING":
                        item.update(
                            status="UNCHECKED", result=None, reason=str(error)
                        )
                run["state"] = "PAUSED"
                if str(error).startswith("job-stale:"):
                    persist(controller.usage())
                    return {
                        "ok": False,
                        "job_id": identifier,
                        "submission_ready": False,
                        "identity_complete": False,
                        "rescan_required": True,
                        "error": str(error),
                    }
            else:
                run["state"] = "FINISHED"
            finally:
                persist(controller.usage())
            if not _engine_freshness._correction_snapshot_current(job["snapshot"], workdir):
                return {
                    "ok": False,
                    "job_id": identifier,
                    "submission_ready": False,
                    "identity_complete": False,
                    "rescan_required": True,
                    "error": "job-stale: inputs changed before "
                    "publication; create a new job",
                }
            return _job_result(job, path)
    except (OSError, ValueError, RuntimeError) as error:
        return {
            "ok": False,
            "submission_ready": False,
            "identity_complete": False,
            "error": str(error),
            "job_id": job_id,
            "run_usage": controller.usage(),
        }
    finally:
        _engine_budgets._request_budget.reset(token)
