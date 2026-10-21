"""Strict and exploratory audit policy orchestration."""

from collections import Counter
import hashlib
import os
from datetime import datetime
from typing import Any, Literal
from cite_check_engine import models as _engine_models
from cite_check_engine import acquisition as _engine_acquisition
from cite_check_engine import bibliography as _engine_bibliography
from cite_check_engine import evidence as _engine_evidence
from cite_check_engine import findings as _engine_findings
from cite_check_engine import identifiers as _engine_identifiers
from cite_check_engine import manuscripts as _engine_manuscripts
from cite_check_engine import parsing as _engine_parsing
from cite_check_engine import persistence as _engine_persistence
from cite_check_engine import reports as _engine_reports


_AUDIT_POLICIES = ("exploratory", "submission-ready")

def _coverage_axis(
    states: list[str], unresolved: set[str], verified: set[str]
) -> dict[str, Any]:
    """Count every expected unit, including unresolved outcomes."""
    counts = dict(Counter(states))
    expected = len(states)
    assessed = sum(state not in unresolved for state in states)
    accepted = sum(state in verified for state in states)
    return {
        "expected": expected,
        "assessed": assessed,
        "verified": accepted,
        "counts": counts,
        "complete": assessed == expected,
        "assessment_rate": assessed / expected if expected else None,
        "verification_rate": accepted / expected if expected else None,
    }

def _incomplete_audit(policy: str, error: str) -> dict[str, Any]:
    """Report unknown coverage when extraction cannot establish the inputs."""
    axes: dict[str, dict[str, Any]] = {}
    for name in ("existence", "provenance", "support"):
        axes[name] = {
            "expected": None,
            "assessed": 0,
            "verified": 0,
            "counts": {},
            "complete": False,
            "assessment_rate": None,
            "verification_rate": None,
        }
    axes["provenance"].pop("verified")
    axes["provenance"].pop("verification_rate")
    axes["provenance"].update(
        declared=0,
        declaration_rate=None,
        assurance="declaration-only; export digest not checked",
    )
    axes["support"].update(
        basis_counts={},
        unresolved_decompositions=None,
        atomic_total_known=False,
        unit="unknown support requirements",
    )
    return {
        "ok": False,
        "input_complete": False,
        "complete": False,
        "submission_ready": False,
        "policy": policy,
        "error": error,
        "coverage": axes,
        "failures": [{"type": "input-incomplete", "detail": error}],
        "warnings": [],
    }

def _declared_provenance(entry: dict[str, Any], result: dict[str, Any]) -> str:
    """Check declaration shape and identity, without a digest assurance."""
    if not entry:
        return "UNDEFINED"
    provenance = entry.get("provenance")
    if not provenance:
        return "UNOFFICIAL"
    sources = {
        "ads",
        "crossref",
        "datacite",
        "inspire",
        "arxiv",
        "github",
        "citation-cff",
    }
    identifier = provenance.get("id", "")
    if (
        provenance.get("source") not in sources
        or not isinstance(identifier, str)
        or not identifier.strip()
        or _engine_identifiers._classify(identifier)[0] == "unknown"
    ):
        return "MALFORMED"
    try:
        datetime.strptime(provenance.get("fetched", ""), "%Y-%m-%d")
    except (TypeError, ValueError):
        return "MALFORMED"
    ids = result.get("ids") or {}
    if not isinstance(ids, dict):
        return "MALFORMED"
    resolved = result.get("id")
    aliases = {str(resolved).lower()} if resolved else set()
    for kind, value in ids.items():
        if value:
            aliases.add(f"{kind}:{value}".lower())
    if aliases and identifier.lower() not in aliases:
        return "MISMATCH"
    return "DECLARED"

def _adequate_support_basis(entry: dict[str, Any], verified_id: str | None) -> bool:
    """Accept full text or the primary record of a verified GitHub work."""
    return entry["basis"] == "fulltext" or (
        entry["basis"] == "readme"
        and isinstance(verified_id, str)
        and verified_id.startswith("github:")
        and entry["id"] == verified_id
    )

def audit(
    tex_path: str,
    bib_path: str | None = None,
    require_support: bool = True,
    verify: bool = True,
    policy: Literal["exploratory", "submission-ready"] = "submission-ready",
) -> dict[str, Any]:
    """Audit citation integrity under an explicit completion policy.

    Args:
        tex_path: Main manuscript, including input/include files.
        bib_path: Optional bibliography override.
        require_support: Fail on missing judgments, also in exploratory mode.
            False never weakens submission-ready requirements.
        verify: Run registry verification. False leaves existence unchecked
            and cannot pass the submission-ready policy.
        policy: Exploratory progress or the default submission-ready gate.

    Returns:
        Separate coverage axes and input/assessment completeness. Complete
        means assessed, including negative or inaccessible outcomes; only
        submission_ready certifies the strict policy. Writes audit reports.
    """
    if policy not in _AUDIT_POLICIES:
        return _incomplete_audit(str(policy), "unknown audit policy")
    strict = policy == "submission-ready"
    ex = _engine_manuscripts.extract_cites(tex_path)
    if ex.get("error"):
        return _incomplete_audit(policy, ex["error"])
    workdir = os.path.dirname(os.path.abspath(tex_path))
    expected_bibs = list(
        dict.fromkeys(
            [
                os.path.abspath(b)
                for b in ([bib_path] if bib_path else ex["bib_files"])
                if b
            ]
        )
    )
    bibs = [path for path in expected_bibs if os.path.isfile(path)]
    failures: list[dict[str, Any]] = [
        {"type": "missing-bib", "detail": path}
        for path in expected_bibs
        if path not in bibs
    ]
    failures.extend(
        {
            "type": item["code"],
            "detail": item["message"],
            **{
                key: value
                for key, value in item.items()
                if key not in {"code", "message"}
            },
        }
        for item in ex.get("diagnostics", [])
    )
    inline_keys = {
        item["key"]
        for item in ex.get("inline_bibliography", [])
        if item.get("key")
    }
    if any(item.get("key") is None
           for item in ex.get("inline_bibliography", [])):
        inline_keys.update(ex["keys"])
    warnings: list[dict[str, Any]] = []
    if not bibs and (expected_bibs or ex["cites"]):
        failures.append(
            {
                "type": "no-bib",
                "detail": (
                    "no readable .bib — pass bib_path or "
                    "declare \\bibliography{…}"
                ),
            }
        )
    entries: dict[str, tuple[str, dict[str, Any]]] = {}
    bibliography_locations: dict[str, list[dict[str, Any]]] = {}
    bib_snapshots = dict.fromkeys(expected_bibs)
    for b in bibs:
        try:
            with open(b, "rb") as fh:
                raw = fh.read()
            bib_snapshots[b] = hashlib.sha256(raw).hexdigest()
            bib_text = raw.decode("utf-8")
            parsed = _engine_parsing._parse_bib(bib_text)
        except (OSError, UnicodeError) as exc:
            failures.append({"type": "unreadable-bib", "detail": str(exc)})
            continue
        for error in parsed["errors"]:
            failures.append({"type": "bib-parse", "detail": f"{b}: {error}"})
        for entry in parsed["entries"]:
            bibliography_locations.setdefault(entry["key"], []).append(
                {
                    "file": b,
                    "line": bib_text.count("\n", 0, entry["start"]) + 1,
                    "kind": "bibliography-entry",
                    "start": entry["start"],
                    "end": entry["end"],
                    "offset_unit": "unicode-codepoint",
                    "source_byte_start": len(
                        bib_text[: entry["start"]].encode("utf-8")
                    ),
                    "source_byte_end": len(
                        bib_text[: entry["end"]].encode("utf-8")
                    ),
                }
            )
            if entry["key"] in entries:
                failures.append(
                    {
                        "type": "duplicate-key",
                        "key": entry["key"],
                        "detail": "key appears in multiple entries",
                    }
                )
            entries.setdefault(entry["key"], (b, entry))
    cite_keys = set(ex["keys"])
    nocite_all = any(c["key"] == "*" for c in ex["cites"])
    if nocite_all:
        cite_keys.update(entries)
    for k in sorted(cite_keys - set(entries) - inline_keys):
        failures.append(
            {
                "type": "undefined-cite",
                "key": k,
                "detail": "cited in the .tex but in no .bib",
            }
        )
    if not nocite_all:
        for k in sorted(set(entries) - cite_keys):
            warnings.append(
                {
                    "type": "uncited-entry",
                    "key": k,
                    "detail": "in the .bib but never cited",
                }
            )
    ver = {}
    bibliography_observation_conflict = False
    if verify:
        for bib in bibs:
            keys_here = [
                key
                for key, (path, _) in entries.items()
                if path == bib and key in cite_keys
            ]
            if not keys_here:
                continue
            if _engine_persistence._audit_file_digest(bib) != bib_snapshots[bib]:
                bibliography_observation_conflict = True
            result = _engine_bibliography.verify_bib(bib, keys=keys_here, tex_path=tex_path)
            if _engine_persistence._audit_file_digest(bib) != bib_snapshots[bib]:
                bibliography_observation_conflict = True
            if not isinstance(result, dict) or result.get("error"):
                failures.append(
                    {
                        "type": "verify-error",
                        "detail": (
                            result.get("error")
                            if isinstance(result, dict)
                            else "malformed verifier response"
                        ),
                    }
                )
                continue
            rows = result.get("entries", [])
            if not isinstance(rows, list):
                rows = []
            for entry in rows:
                if (
                    isinstance(entry, dict)
                    and isinstance(entry.get("key"), str)
                    and entry["key"] in keys_here
                ):
                    if not isinstance(entry.get("ids", {}), dict):
                        entry = dict(entry, status="UNRESOLVED", ids={})
                    ver[entry["key"]] = entry
    for key in inline_keys:
        ver[key] = {
            "key": key,
            "status": "UNCHECKED",
            "notes": [
                "Printed inline reference has no verified official provenance"
            ],
        }
        bibliography_locations.setdefault(key, []).extend(
            item for item in ex["inline_bibliography"] if item["key"] == key
        )
    unofficial, provenance_states = [], []
    for key in sorted(cite_keys):
        parsed_entry = entries.get(key, (None, {}))[1]
        provenance_state = (
            "UNOFFICIAL"
            if key in inline_keys
            else _declared_provenance(parsed_entry, ver.get(key, {}))
        )
        if provenance_state != "DECLARED":
            unofficial.append(key)
        provenance_states.append(provenance_state)
        if provenance_state != "DECLARED":
            (
                failures
                if strict or provenance_state == "MISMATCH"
                else warnings
            ).append(
                {
                    "type": "provenance",
                    "key": key,
                    "status": provenance_state,
                    "detail": "no declared official-export provenance",
                }
            )
        result = ver.setdefault(
            key,
            {
                "key": key,
                "status": (
                    "UNDEFINED"
                    if not parsed_entry
                    else "UNRESOLVED"
                    if verify
                    else "UNCHECKED"
                ),
            },
        )
        status = result.get("status", "UNRESOLVED")
        if not isinstance(status, str) or status not in {
            "VERIFIED",
            "FOUND",
            "PROBABLE",
            "MISMATCH",
            "NOT_FOUND",
            "UNRESOLVED",
            "UNCHECKED",
            "UNDEFINED",
        }:
            status = "UNRESOLVED"
        if status == "VERIFIED" and (
            not isinstance(result.get("id"), str) or not result["id"].strip()
        ):
            status = "UNRESOLVED"
        result["status"] = status
        if status != "VERIFIED":
            blocking = strict or status in {
                "MISMATCH",
                "NOT_FOUND",
                "UNRESOLVED",
                "UNDEFINED",
            }
            (failures if blocking else warnings).append(
                {
                    "type": "existence",
                    "key": key,
                    "status": status,
                    "detail": "; ".join(result.get("notes") or []),
                }
            )
    if strict and (not verify or not require_support):
        failures.append(
            {
                "type": "policy-configuration",
                "detail": (
                    "submission-ready requires verify=true and "
                    "require_support=true; use exploratory for partial work"
                ),
            }
        )
    try:
        with _engine_persistence._file_lock(_engine_persistence._project_path(workdir, "ledger.json")):
            ledger_state = _engine_evidence._audit_ledger(workdir)
            ledger_digest = _engine_persistence._audit_file_digest(
                _engine_persistence._project_path(workdir, "ledger.json")
            )
    except (OSError, ValueError) as error:
        return _incomplete_audit(policy, f"cannot audit ledger: {error}")
    ledger = ledger_state["entries"]
    verdicts: Counter[str] = Counter()
    coverage: dict[str, str] = {}
    missing: list[dict[str, Any]] = []
    support_states, support_bases = [], []
    supported_adequately = 0
    current_judgments = {}
    source_snapshots: dict[str, _engine_models.SourceSnapshot | None] = {}
    source_observation_conflict = False
    legacy_counts = Counter(
        (cite["key"], _engine_identifiers._claim_hash(cite["claim"]))
        for cite in ex["cites"]
        if not cite["nocite"]
    )
    requirements = _engine_evidence._support_requirements(ex, ledger_state)
    uncited_atoms = []
    for sentence in ex["sentences"]:
        registration = _engine_evidence._find_decomposition(sentence, ledger_state)
        if (
            not registration
            or registration["sentence_id"] != sentence["sentence_id"]
        ):
            continue
        for atom in registration["atoms"]:
            if atom["kind"] == "uncited":
                scope = {
                    "sentence_id": sentence["sentence_id"],
                    "file": sentence["file"],
                    "claim": sentence["claim"],
                    "atom_id": atom["atom_id"],
                    "atom": atom["text"],
                    "reason": atom["reason"],
                    "verified": False,
                }
                uncited_atoms.append(scope)
                warnings.append(
                    dict(
                        scope,
                        type="uncited-atom",
                        detail=(
                            "declared uncited scope; not verified: "
                            + atom["reason"]
                        ),
                    )
                )
    for c in requirements:
        loc = {
            "key": c["key"],
            "file": c["file"],
            "line": c["line"],
            "claim": c["claim"][:240],
            "occurrence_id": c["occurrence_id"],
        }
        if c.get("atom_id"):
            loc.update(atom_id=c["atom_id"], atom=c["atom"]["text"])
        if c.get("decomposition_stale"):
            support_states.append("DECOMPOSITION_STALE")
            failures.append(
                dict(
                    loc,
                    type="decomposition-stale",
                    detail=(
                        "atomic mode requires a current sentence registration; "
                        "register claims and re-judge"
                    ),
                )
            )
            coverage[c["key"]] = coverage.get(c["key"], "") + " STALE"
            continue
        judgment = ledger.get(_engine_evidence._support_id(c["occurrence_id"], c.get("atom_id")))
        if (
            judgment is None
            and not c.get("atom_id")
            and legacy_counts[(c["key"], _engine_identifiers._claim_hash(c["claim"]))] == 1
        ):
            legacy = ledger.get(f"{c['key']}|{_engine_identifiers._claim_hash(c['claim'])}")
            # A legacy judgment is safe only when it maps to one occurrence
            # and any supplied historical source location still matches.
            if (
                legacy
                and (legacy.get("file") in (None, c["file"]))
                and (legacy.get("line") in (None, c["line"]))
            ):
                judgment = legacy
        if not judgment:
            support_states.append("MISSING")
            missing.append(c)
            coverage[c["key"]] = coverage.get(c["key"], "") + " MISSING"
            continue
        vid = (ver.get(c["key"]) or {}).get("id")
        if vid and judgment["id"] != vid:
            support_states.append("STALE")
            failures.append(
                dict(
                    loc,
                    type="support-stale",
                    verdict=judgment["verdict"],
                    detail=(
                        f"verdict was judged against {judgment['id']} "
                        f"but entry resolves to {vid} — re-judge"
                    ),
                )
            )
            coverage[c["key"]] = coverage.get(c["key"], "") + " STALE"
            continue
        source_cache_id = judgment.get("source_cache_id", judgment["id"])
        current_source = _engine_acquisition._current_source_identity(source_cache_id)
        if (
            source_cache_id in source_snapshots
            and source_snapshots[source_cache_id] != current_source
        ):
            source_observation_conflict = True
        source_snapshots.setdefault(source_cache_id, current_source)
        entry = entries.get(c["key"], (None, {}))[1]
        expected_ref = _engine_parsing._entry_ref(entry) if entry else None
        expected_version = ((ver.get(c["key"]) or {}).get("ref") or {}).get(
            "sha"
        )
        source_version = (judgment.get("source_identity") or {}).get("version")
        if expected_ref and not expected_version:
            expected_version = expected_ref
        arxiv_version = _engine_parsing._entry_arxiv_version(entry) if entry else None
        if arxiv_version:
            expected_version = arxiv_version
        if (
            judgment.get("decomposition_id") != c.get("decomposition_id")
            or (c.get("atom_id") and judgment.get("atom") != c["atom"])
            or not judgment.get("source_identity")
            or (expected_version and source_version != expected_version)
            or judgment["source_identity"] != current_source
            or judgment.get("context_hash") != _engine_identifiers._claim_hash(c["context"])
        ):
            support_states.append("STALE")
            failures.append(
                dict(
                    loc,
                    type="support-stale",
                    verdict=judgment["verdict"],
                    detail=(
                        "source, context or evidence policy changed; re-judge"
                    ),
                )
            )
            coverage[c["key"]] = coverage.get(c["key"], "") + " STALE"
            continue
        if (not (current_source or {}).get("quality", {}).get("usable_for_judgment")
                and judgment.get("verdict") != "UNVERIFIABLE"):
            support_states.append("INVALID")
            failures.append(dict(
                loc, type="support-quality", verdict=judgment["verdict"],
                detail="Source extraction is poor, unreadable or unverified; obtain a readable copy and re-judge.",
                quality=(current_source or {}).get("quality"),
            ))
            coverage[c["key"]] = coverage.get(c["key"], "") + " UNVERIFIABLE"
            continue
        if judgment.get("verdict") not in _engine_evidence._VERDICTS:
            support_states.append("INVALID")
            failures.append(dict(loc, type="support-invalid"))
            continue
        current_judgments[_engine_evidence._support_id(c["occurrence_id"], c.get("atom_id"))] = (
            judgment
        )
        verdict = judgment["verdict"]
        support_states.append(
            "INACCESSIBLE" if verdict == "UNVERIFIABLE" else verdict
        )
        support_bases.append(judgment["basis"])
        verdicts[verdict] += 1
        adequate = _adequate_support_basis(
            judgment,
            vid if ver.get(c["key"], {}).get("status") == "VERIFIED" else None,
        )
        supported_adequately += verdict == "SUPPORTS" and adequate
        coverage[c["key"]] = (
            coverage.get(c["key"], "") + f" {verdict}({judgment['basis']})"
        )
        if verdict in ("UNSUPPORTED", "CONTRADICTS"):
            failures.append(
                dict(
                    loc,
                    type="support",
                    verdict=verdict,
                    detail=judgment.get("note"),
                )
            )
        elif verdict in ("PARTIAL", "UNVERIFIABLE"):
            (failures if strict else warnings).append(
                dict(
                    loc,
                    type="support",
                    verdict=verdict,
                    detail=judgment.get("note"),
                )
            )
        elif not adequate:
            (failures if strict else warnings).append(
                dict(
                    loc,
                    type="support-basis",
                    verdict=verdict,
                    detail=(
                        f"limited evidence basis: {judgment['basis']}; "
                        "obtain full text or a verified repository's record"
                    ),
                )
            )
    for c in missing:
        (failures if strict or require_support else warnings).append(
            {
                "type": "support-missing",
                "key": c["key"],
                "file": c["file"],
                "line": c["line"],
                "claim": c["claim"][:240],
                "occurrence_id": c["occurrence_id"],
                "atom_id": c.get("atom_id"),
                "atom": (c.get("atom") or {}).get("text"),
                "detail": (
                    "no support verdict recorded for this atom/occurrence"
                ),
            }
        )
    for k in cite_keys:
        coverage.setdefault(k, "")
    input_complete = (
        ex.get("scope_complete", True)
        and not ex.get("review_only", False)
        and not any(
            item["type"]
            in {
                "missing-bib",
                "unreadable-bib",
                "no-bib",
                "bib-parse",
                "duplicate-key",
                "undefined-cite",
            }
            for item in failures
        )
    )
    existence_axis = _coverage_axis(
        [result["status"] for result in ver.values()],
        {"UNCHECKED", "UNRESOLVED", "UNDEFINED"},
        {"VERIFIED"},
    )
    provenance_axis = _coverage_axis(
        provenance_states,
        {"UNDEFINED"},
        {"DECLARED"},
    )
    provenance_axis["declared"] = provenance_axis.pop("verified")
    provenance_axis["declaration_rate"] = provenance_axis.pop(
        "verification_rate"
    )
    provenance_axis["assurance"] = "declaration-only; export digest not checked"
    support_axis = _coverage_axis(
        support_states,
        {"MISSING", "STALE", "DECOMPOSITION_STALE", "INVALID"},
        set(),
    )
    support_axis["verified"] = supported_adequately
    support_axis["verification_rate"] = (
        supported_adequately / len(requirements) if requirements else None
    )
    support_axis["basis_counts"] = dict(Counter(support_bases))
    support_axis["unresolved_decompositions"] = sum(
        bool(item.get("decomposition_stale")) for item in requirements
    )
    support_axis["atomic_total_known"] = not support_axis[
        "unresolved_decompositions"
    ]
    support_axis["unit"] = (
        "current atom/occurrence judgments, or unresolved occurrence "
        "placeholders where decomposition is stale"
    )
    axes = {
        "existence": existence_axis,
        "provenance": provenance_axis,
        "support": support_axis,
    }
    if not ex.get("scope_complete", True):
        for axis in axes.values():
            axis["observed_expected"] = axis["expected"]
            axis["expected"] = None
            axis["complete"] = False
            for name in (
                "assessment_rate", "verification_rate", "declaration_rate"
            ):
                if name in axis:
                    axis[name] = None
        support_axis["atomic_total_known"] = False
    complete = input_complete and all(
        axis["complete"] for axis in axes.values()
    )
    report = {
        "ok": not failures,
        "complete": complete,
        "input_complete": input_complete,
        "policy": policy,
        "submission_ready": strict and not failures and complete,
        "coverage": axes,
        "tex": os.path.abspath(tex_path),
        "bibs": bibs,
        "n_instances": ex["n_instances"],
        "n_keys": len(cite_keys),
        "existence_counts": dict(Counter(r["status"] for r in ver.values())),
        "support_counts": dict(verdicts),
        "support_missing": len(missing),
        "n_support_requirements": len(requirements),
        "n_atomic_requirements": sum("atom_id" in c for c in requirements),
        "n_uncited_atoms": len(uncited_atoms),
        "uncited_atoms": uncited_atoms,
        "unofficial_entries": sorted(unofficial),
        "failures": failures,
        "warnings": warnings,
        "checked": _engine_persistence._now_iso(),
    }
    report.update(
        {
            name: ex.get(name)
            for name in (
                "input_format",
                "scope_complete",
                "review_only",
                "diagnostics",
                "inline_bibliography",
                "extraction_metadata",
                "source_texts",
            )
        }
    )
    report["bibliography_locations"] = bibliography_locations
    report["corrections"] = _engine_findings._correction_items(
        report, ex, current_judgments, ver
    )
    report["source_files"] = list(dict.fromkeys(ex["files"] + bibs))
    report["snapshot"] = {
        "files": {**ex["source_digests"], **bib_snapshots},
        "ledger": ledger_digest,
        "sources": source_snapshots,
        "input_backend": ex.get("extraction_metadata", {}).get("extractor")
        if ex.get("input_format") == "pdf"
        else None,
    }
    coverage = {k: v.strip() or "—" for k, v in coverage.items()}
    with _engine_persistence._file_lock(_engine_persistence._project_path(workdir, "ledger.json")):
        ledger_changed = (
            _engine_persistence._audit_file_digest(_engine_persistence._project_path(workdir, "ledger.json"))
            != ledger_digest
        )
        manuscript_changed = _engine_identifiers._atomic_digest(
            _engine_manuscripts.extract_cites(tex_path)
        ) != _engine_identifiers._atomic_digest(ex)
        bibliography_changed = bibliography_observation_conflict or any(
            _engine_persistence._audit_file_digest(path) != digest
            for path, digest in bib_snapshots.items()
        )
        sources_changed = source_observation_conflict or any(
            _engine_acquisition._current_source_identity(identifier) != snapshot
            for identifier, snapshot in source_snapshots.items()
        )
        if (
            ledger_changed
            or manuscript_changed
            or bibliography_changed
            or sources_changed
        ):
            failures.append(
                {
                    "type": "audit-stale",
                    "detail": (
                        "manuscript, bibliography, ledger or source "
                        "changed during audit; "
                        "rerun audit"
                    ),
                }
            )
            report["ok"] = False
            report["complete"] = False
            report["submission_ready"] = False
            _engine_findings._invalidate_corrections(report)
        md_path = _engine_persistence._project_path(workdir, "audit.md")
        _engine_persistence._atomic_write(md_path, _engine_reports._audit_markdown(report, ver, coverage))
        report["report"] = md_path
        _engine_persistence._write_project(workdir, "audit.json", report)
    report["summary"] = (
        f"{policy}: ready={report['submission_ready']}; "
        f"{len(failures)} failure(s), {len(warnings)} warning(s); "
        f"{ex['n_instances']} citation instances, "
        f"{len(missing)} without a support verdict; "
        f"existence {report['existence_counts']}"
    )
    return report
