"""Snapshot consistency and output/input alias preflight checks."""

import os
from typing import Any
from cite_check_engine import acquisition as _engine_acquisition
from cite_check_engine import config as _engine_config
from cite_check_engine import evidence as _engine_evidence
from cite_check_engine import export_provenance as _engine_export_provenance
from cite_check_engine import manuscripts as _engine_manuscripts
from cite_check_engine import parsing as _engine_parsing
from cite_check_engine import persistence as _engine_persistence


def _correction_snapshot_current(
    snapshot: dict[str, Any], workdir: str
) -> bool:
    """Check only local bound inputs; rendering never repeats registry calls."""
    return (
        (snapshot.get("input_backend") is None
         or snapshot["input_backend"] == _engine_manuscripts._input_pdf_backend())
        and _engine_persistence._audit_file_digest(_engine_persistence._project_path(workdir, "ledger.json"))
        == snapshot["ledger"]
        and all(
            _engine_persistence._audit_file_digest(path) == digest
            for path, digest in snapshot["files"].items()
        )
        and all(
            _engine_export_provenance.fingerprint(path) == digest
            for path, digest in snapshot.get("exports", {}).items()
        )
        and all(
            _engine_acquisition._current_source_identity(identifier) == identity
            for identifier, identity in snapshot["sources"].items()
        )
    )

def _correction_preflight(tex_path: str, bib_path: str | None) -> str | None:
    """Reject report-pipeline output aliases before any audit mutation."""
    workdir = os.path.dirname(os.path.abspath(tex_path))
    extracted = _engine_manuscripts.extract_cites(tex_path)
    inputs = set(extracted.get("files", [os.path.abspath(tex_path)]))
    bibs = (
        [os.path.abspath(bib_path)]
        if bib_path
        else extracted.get("bib_files", [])
    )
    inputs.update(bibs)
    for bib in bibs:
        try:
            with open(bib, encoding="utf-8", newline="") as source:
                parsed = _engine_parsing._parse_bib(source.read())
            for entry in parsed["entries"]:
                inputs.update(_engine_export_provenance.candidate_paths(
                    (entry.get("provenance") or {}).get("receipt"), bib
                ))
        except (OSError, UnicodeError, ValueError):
            pass
    inputs.update(extracted.get("source_digests", {}))
    directories = {os.path.join(workdir, _engine_config.PROJECT_DIR)}
    directories.update(
        os.path.join(os.path.dirname(bib), _engine_config.PROJECT_DIR) for bib in bibs
    )
    outputs: list[str] = []
    for directory in directories:
        if os.path.islink(directory):
            return "report directory is a symlink"
        outputs.extend(
            os.path.join(directory, name)
            for name in (
                "audit.md",
                "audit.json",
                "verify.json",
                "corrections.json",
                "corrections.md",
                "corrections.html",
                "ledger.json.lock",
            )
        )
    try:
        ledger = _engine_evidence._audit_ledger(workdir)
    except (OSError, ValueError):
        ledger = {"entries": {}}
    for judgment in ledger["entries"].values():
        metadata = _engine_persistence._load_text_meta(
            judgment.get("source_cache_id", judgment["id"])
        )
        if metadata and metadata.get("path"):
            inputs.add(metadata["path"])
    resolved_inputs = {os.path.realpath(path) for path in inputs}
    for output in outputs:
        if (
            os.path.islink(output)
            or os.path.realpath(output) in resolved_inputs
        ):
            return (
                "report pipeline output aliases a manuscript or bib"
                "liography input"
            )
        for source in inputs:
            if (
                os.path.exists(output)
                and os.path.exists(source)
                and os.path.samefile(output, source)
            ):
                return "report pipeline output is hard-linked to an input"
    return None
