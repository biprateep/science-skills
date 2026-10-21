"""Shared request schemas and typed citation-engine data contracts."""

import dataclasses
import typing
from typing import Literal


@dataclasses.dataclass
class VerificationBudget:
    """Per-run admission limits; seconds are a cooperative deadline.

    Known public registry service fees are estimated as zero under the
    documented pricing policy. Actual billed costs are not measured.
    """

    __pydantic_config__ = {"extra": "forbid"}

    max_requests: int = dataclasses.field(default=50, metadata={"strict": True})
    max_searches: int = dataclasses.field(default=10, metadata={"strict": True})
    max_seconds: float = dataclasses.field(
        default=60.0, metadata={"strict": True}
    )
    max_cost_usd: float | None = dataclasses.field(
        default=0.0, metadata={"strict": True}
    )


@dataclasses.dataclass
class ClaimPriority:
    """Caller-assigned scheduling advice for one current support requirement."""

    __pydantic_config__ = {"extra": "forbid"}

    occurrence_id: str
    reason: str
    priority: Literal["high", "normal", "low"] = "high"
    atom_id: str | None = None


@dataclasses.dataclass
class BibliographyItem:
    """An official bibliography request with an optional citation key and pin."""  # noqa: E501

    identifier: str
    key: str | None = None
    version: str | None = None


@dataclasses.dataclass
class InputCitation:
    """Explicit review mapping into an exact source-text snapshot."""

    __pydantic_config__ = {"extra": "forbid"}
    start: int = dataclasses.field(metadata={"strict": True})
    end: int = dataclasses.field(metadata={"strict": True})
    key: str
    marker: str
    page: int | None = dataclasses.field(
        default=None, metadata={"strict": True}
    )


@dataclasses.dataclass
class AtomicClaim:
    """An exact sentence span and the citation occurrences supporting it.

    Offsets are zero-based Unicode codepoints, with an exclusive end.
    """

    # MCP's Pydantic adapter honors these without adding a CLI dependency.
    __pydantic_config__ = {"extra": "forbid"}

    start: int = dataclasses.field(metadata={"strict": True})
    end: int = dataclasses.field(metadata={"strict": True})
    citation_ids: list[str]
    kind: Literal["cited", "uncited"] = "cited"
    reason: str | None = None


@dataclasses.dataclass
class ProposedCorrection:
    """An unapproved judge-authored recommendation, never an applied edit.

    Attributes:
        action: The recommended operation; replacement wording is allowed
            only for revise-claim and does not carry a new citation identity.
        rationale: Why the original assertion needs attention.
        replacement_text: Optional assertion wording requiring human review
            and a fresh support judgment after application.
    """

    __pydantic_config__ = {"extra": "forbid"}

    action: Literal[
        "revise-claim", "replace-citation", "remove-claim", "obtain-text"
    ]
    rationale: str
    replacement_text: str | None = None


class _WorkFields(typing.TypedDict):
    registry: str | None
    title: str
    authors: list[str]
    year: int | None
    venue: str
    doi: str | None
    arxiv: str | None
    bibcode: str | None
    openalex: str | None
    inspire: str | None
    github: str | None
    abstract: str
    type: str
    url: str
    citation_count: int | None
    pdf_urls: list[str]


class Work(_WorkFields, total=False):
    """Normalized registry record; provider extensions remain plain JSON.

    This static contract describes normalized data, not evidence validation.
    A real work's existence does not certify that it supports an assertion.
    """

    registries: list[str]
    publication_status: dict[str, typing.Any]
    repo: dict[str, typing.Any]
    pinned_sha: str
    pinned_ref: str
    discovery_id: str
    suggested_ids: list[str]
    provenance: dict[str, str]
    arxiv_version: str
    arxiv_api_version: str
    discovery_only: bool
    pin: str
    pinned_date: str | None
    requested_version: str


class _CitationFields(typing.TypedDict):
    key: str
    cmd: str
    file: str
    tex_path: str
    line: int
    claim: str
    context: str
    nocite: bool
    occurrence_id: str
    sentence_id: str
    location_id: str
    marker_start: int
    marker_end: int
    source_start: int
    source_end: int
    source_byte_start: int | None
    source_byte_end: int | None
    source_command: str


class CitationInstance(_CitationFields, total=False):
    """One citation occurrence, with exact source and rendered-text offsets."""

    page: int | None
    page_line: int
    source_offset_unit: str


class _ClaimFields(typing.TypedDict):
    start: int
    end: int
    text: str
    byte_start: int
    byte_end: int
    citation_ids: list[str]
    kind: str
    reason: str | None


class Claim(_ClaimFields, total=False):
    """Validated atomic span, before or after registration assigns its ID."""

    atom_id: str


class SourceSnapshot(typing.TypedDict):
    """Exact content and acquisition-policy binding, including legacy nulls."""

    quality: dict[str, typing.Any]
    sha256: str
    id: str | None
    basis: str | None
    source: str | None
    version: str | None
    extraction: str
    policy: str


class _JudgmentFields(typing.TypedDict):
    context_hash: str
    source_identity: SourceSnapshot
    source_cache_id: str
    key: str
    id: str
    claim: str
    verdict: str
    basis: str
    quotes: list[dict[str, typing.Any]]
    note: str | None
    judge: str | None
    file: str | None
    line: int | None
    recorded: str


class Judgment(_JudgmentFields, total=False):
    """Stored decision; freshness and quote checks remain runtime gates."""

    occurrence_id: str
    sentence_id: str
    atom_id: str | None
    decomposition_id: str | None
    tex_path: str
    location_id: str
    context: str
    atom: Claim
    proposed_correction: dict[str, typing.Any]
