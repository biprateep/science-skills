"""Bounded source-artifact inspection; never a completeness certificate."""

import hashlib
import os
from typing import Any
import unicodedata

from cite_check_engine import config

POLICY = "source-quality-v1"
INTAKE_POLICY = "bounded-source-v1"


class SourceLimitError(RuntimeError):
    """An input exceeded its bound; no partial source may be published."""


def read_bytes(path: str, limit: int) -> bytes:
    """Read at most limit plus one bytes, including files growing mid-read."""
    if os.path.getsize(path) > limit:
        raise SourceLimitError(f"source exceeds {limit} byte limit")
    with open(path, "rb") as source:
        raw = source.read(limit + 1)
    if len(raw) > limit:
        raise SourceLimitError(f"source exceeds {limit} byte limit")
    return raw


def read_text(path: str) -> str:
    """Decode a bounded cached artifact without hiding replacement glyphs."""
    return read_bytes(path, config.MAX_SOURCE_TEXT_BYTES).decode(
        "utf-8", errors="replace"
    )


def make_intake(
    raw: bytes, method: str, pages: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Describe a completed bounded intake, not the whole cited document."""
    result: dict[str, Any] = {
        "policy": INTAKE_POLICY,
        "method": method,
        "input_bytes": len(raw),
        "input_sha256": hashlib.sha256(raw).hexdigest(),
        "completed": True,
    }
    if pages is not None:
        result["pages"] = len(pages)
        result["empty_pages"] = [
            page["page"] for page in pages if not page["text"].strip()
        ]
    return result


def assess(
    text: str,
    intake: dict[str, Any] | None = None,
    normalization: list[str] | None = None,
) -> dict[str, Any]:
    """Recompute observable defects; stored usability flags are not evidence.

    Twenty alphanumeric characters is a conservative readability floor.
    Replacement glyphs, non-whitespace controls and empty extracted PDF
    pages trigger review. Blank PDF pages may be intentional: the signal
    does not establish why text is missing. No language model or OCR runs.
    """
    intake = intake if isinstance(intake, dict) else {}
    completed = (
        intake.get("policy") == INTAKE_POLICY
        and intake.get("completed") is True
        and isinstance(intake.get("method"), str)
        and intake.get("method")
        in {"local-text", "pdf", "remote-text", "abstract", "none"}
        and type(intake.get("input_bytes")) is int
        and 0
        <= intake["input_bytes"]
        <= (
            config.MAX_PDF_BYTES
            if intake.get("method") == "pdf"
            else config.MAX_HTTP_BYTES
            if intake.get("method") == "remote-text"
            else config.MAX_SOURCE_TEXT_BYTES
        )
        and isinstance(intake.get("input_sha256"), str)
        and len(intake["input_sha256"]) == 64
        and all(c in "0123456789abcdef" for c in intake["input_sha256"])
    )
    empty_pages = intake.get("empty_pages", [])
    if intake.get("method") == "pdf":
        count = intake.get("pages")
        extractor = intake.get("extractor")
        extractor_valid = (
            isinstance(extractor, dict)
            and extractor.get("name") == "pypdf"
            and isinstance(extractor.get("version"), str)
            and bool(extractor["version"])
            and isinstance(extractor.get("policy"), str)
            and bool(extractor["policy"])
            and extractor.get("options") == {"strict": True, "mode": "plain"}
        )
        completed = bool(
            completed
            and intake["input_bytes"] > 0
            and extractor_valid
            and type(count) is int
            and 0 < count <= 500
            and isinstance(empty_pages, list)
            and all(type(n) is int and 1 <= n <= count for n in empty_pages)
            and len(set(empty_pages)) == len(empty_pages)
        )
    diagnostics: list[dict[str, str]] = []
    alphanumeric = sum(character.isalnum() for character in text)
    replacements = text.count("\ufffd")
    controls = sum(
        unicodedata.category(character) == "Cc" and not character.isspace()
        for character in text
    )
    status = "no-known-defect"
    if not completed:
        status = "unknown"
        diagnostics.append(
            {
                "code": "intake-unverified",
                "detail": (
                    "Refresh from the original source to establish "
                    "bounded intake."
                ),
            }
        )
    if not alphanumeric:
        status = "unreadable"
        diagnostics.append(
            {
                "code": "no-readable-text",
                "detail": "No alphanumeric text extracted.",
            }
        )
    elif alphanumeric < 20:
        status = "poor"
        diagnostics.append(
            {
                "code": "sparse-text",
                "detail": "Fewer than 20 alphanumeric characters.",
            }
        )
    if replacements or controls:
        status = "poor" if alphanumeric else "unreadable"
        diagnostics.append(
            {
                "code": "text-corruption",
                "detail": (
                    "Replacement glyphs or non-whitespace control "
                    "characters detected."
                ),
            }
        )
    if completed and intake.get("method") == "pdf" and empty_pages:
        status = "poor" if alphanumeric else "unreadable"
        diagnostics.append(
            {
                "code": "empty-pdf-pages",
                "detail": (
                    "Pages yielded no text; they may be blank or require OCR. "
                    "Review another copy."
                ),
            }
        )
    if len(text.encode("utf-8")) > config.MAX_SOURCE_TEXT_BYTES:
        status = "truncated"
        diagnostics.append(
            {
                "code": "text-limit",
                "detail": "Text exceeds the supported artifact bound.",
            }
        )
    return {
        "policy": POLICY,
        "status": status,
        "usable_for_judgment": status == "no-known-defect" and completed,
        "input_complete": True if completed else None,
        "document_completeness": "unknown",
        "intake": dict(intake) if completed else None,
        "metrics": {
            "characters": len(text),
            "alphanumeric": alphanumeric,
            "replacement_characters": replacements,
            "control_characters": controls,
            "pages": intake.get("pages") if completed else None,
            "empty_pages": empty_pages if completed else None,
        },
        "diagnostics": diagnostics,
        "normalization": list(normalization or []),
    }


def current(meta: dict[str, Any], text: str) -> dict[str, Any]:
    """Inspect current bytes using validated acquisition facts only."""
    normalization = meta.get("normalization")
    if not isinstance(normalization, list) or any(
        not isinstance(value, str)
        or value
        not in {"whitespace", "line-dehyphenation", "references-removed"}
        for value in normalization
    ):
        normalization = []
    return assess(text, meta.get("intake"), normalization)
