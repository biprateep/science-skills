"""Fresh correction report generation and safe artifact publication."""

import hashlib
import json
import os
from typing import Any, Literal
from cite_check_engine import audit as _engine_audit
from cite_check_engine import config as _engine_config
from cite_check_engine import findings as _engine_findings
from cite_check_engine import freshness as _engine_freshness
from cite_check_engine import persistence as _engine_persistence
from cite_check_engine import reports as _engine_reports


def correction_report(
    tex_path: str,
    bib_path: str | None = None,
    policy: Literal["exploratory", "submission-ready"] = "submission-ready",
    annotated: bool = False,
    verify: bool = True,
    require_support: bool = True,
) -> dict[str, Any]:
    """Create corrections from one fresh audit without editing inputs.

    Args:
        tex_path: Main manuscript path.
        bib_path: Optional bibliography override, as in audit.
        policy: The explicit audit policy; strict by default.
        annotated: Also write an escaped static HTML copy of source files.
        verify: Perform registry identity checks.
        require_support: Require recorded support in exploratory mode too.

    Returns:
        Audit results, actionable corrections and written artifact paths.
        Scientific proposals remain unapproved and are never applied.
    """
    workdir = os.path.dirname(os.path.abspath(tex_path))
    destination = os.path.join(workdir, _engine_config.PROJECT_DIR)
    preflight_error = _engine_freshness._correction_preflight(tex_path, bib_path)
    if preflight_error:
        return {
            "ok": False,
            "submission_ready": False,
            "report_written": False,
            "error": preflight_error,
            "artifacts": {},
        }
    report = _engine_audit.audit(tex_path, bib_path, require_support, verify, policy)
    if "corrections" not in report:
        report["corrections"] = _engine_findings._correction_items(report, {}, {}, {})
    snapshot = report.get("snapshot")
    if snapshot is None:
        paths = [os.path.abspath(tex_path)]
        if bib_path:
            paths.append(os.path.abspath(bib_path))
        snapshot = {
            "files": {path: _engine_persistence._audit_file_digest(path) for path in paths},
            "ledger": _engine_persistence._audit_file_digest(_engine_persistence._project_path(workdir, "ledger.json")),
            "sources": {},
        }
        report["snapshot"] = snapshot
        report["annotation_status"] = "unavailable-incomplete-input"
        annotated = False
    outputs = {
        "json": os.path.join(destination, "corrections.json"),
        "markdown": os.path.join(destination, "corrections.md"),
    }
    if annotated:
        outputs["annotated"] = os.path.join(destination, "corrections.html")
    input_paths = set(snapshot["files"])
    for path in outputs.values():
        if os.path.islink(path) or os.path.realpath(path) in {
            os.path.realpath(value) for value in input_paths
        }:
            return dict(
                report,
                ok=False,
                error="report output aliases an input",
                artifacts={},
                report_written=False,
            )
    sources = {}
    for path in report.get("source_files", []):
        try:
            with open(path, "rb") as source:
                raw = source.read()
            if hashlib.sha256(raw).hexdigest() != snapshot["files"].get(path):
                raise ValueError("source changed during report rendering")
            sources[path] = ((report.get("source_texts") or {}).get(path)
                             if path in (report.get("source_texts") or {})
                             else raw.decode("utf-8"))
        except (OSError, ValueError) as error:
            _engine_findings._invalidate_corrections(report)
            return dict(
                report,
                ok=False,
                submission_ready=False,
                complete=False,
                error=str(error),
                artifacts={},
                report_written=False,
            )
    markdown = _engine_reports._corrections_markdown(report)
    annotated_text = _engine_reports._corrections_html(report, sources) if annotated else None
    report.update(artifacts=outputs, report_written=True)
    with _engine_persistence._file_lock(_engine_persistence._project_path(workdir, "ledger.json")):
        if _engine_freshness._correction_preflight(
            tex_path, bib_path
        ) is not None or not _engine_freshness._correction_snapshot_current(snapshot, workdir):
            _engine_findings._invalidate_corrections(report)
            return dict(
                report,
                ok=False,
                submission_ready=False,
                complete=False,
                error="report-stale: inputs changed; rerun",
                artifacts={},
                report_written=False,
            )
        for key in [name for name in outputs if name != "json"] + ["json"]:
            path = outputs[key]
            if key == "json":
                _engine_persistence._atomic_write(
                    path, json.dumps(report, ensure_ascii=False, indent=2)
                )
            elif key == "markdown":
                _engine_persistence._atomic_write(path, markdown)
            elif annotated_text is not None:
                _engine_persistence._atomic_write(path, annotated_text)
    return dict(report, artifacts=outputs, report_written=True)
