"""Atomic claims, exact evidence validation and support judgments."""

import dataclasses
import os
import re
import typing
from typing import Any
from cite_check_engine import acquisition as _engine_acquisition
from cite_check_engine import identifiers as _engine_identifiers
from cite_check_engine import manuscripts as _engine_manuscripts
from cite_check_engine import quality as _engine_quality
from cite_check_engine import models as _engine_models
from cite_check_engine import parsing as _engine_parsing
from cite_check_engine import persistence as _engine_persistence
from cite_check_engine import resolution as _engine_resolution


_VERDICTS = ("SUPPORTS", "PARTIAL", "UNSUPPORTED", "CONTRADICTS", "UNVERIFIABLE")

def _quote_characters(text: str) -> tuple[str, list[int]]:
    """Normalize whitespace and typographic ligatures, retaining source offsets."""
    ligatures = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi",
                 "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}
    characters, offsets = [], []
    for offset, character in enumerate(text):
        replacement = " " if character.isspace() else ligatures.get(
            character, character
        )
        for item in replacement:
            if item == " " and (not characters or characters[-1] == " "):
                continue
            characters.append(item)
            offsets.append(offset)
    if characters and characters[-1] == " ":
        characters.pop()
        offsets.pop()
    return "".join(characters), offsets

def _norm_quote(text: str) -> str:
    return _quote_characters(text)[0]

def _locate_quote(text: str, quote: str) -> dict:
    """Certify an exact source span after conservative extraction normalization."""
    normalized, offsets = _quote_characters(text)
    needle = _norm_quote(quote)
    if len(needle) < 15:
        return {"found": False, "match": 0.0, "reason": "quote too short"}
    index = normalized.find(needle)
    while index >= 0:
        start, end = offsets[index], offsets[index + len(needle) - 1] + 1
        # A match cannot start or end partway through an expanded ligature.
        # Re-normalizing the entire source span checks both boundaries.
        if _norm_quote(text[start:end]) == needle:
            return {"found": True, "match": 1.0, "at": start, "end": end,
                    "source_text": text[start:end]}
        index = normalized.find(needle, index + 1)
    return {"found": False, "match": 0.0,
            "reason": "not found verbatim in the source text"}

def _validated_atoms(
    sentence: dict[str, Any],
    cites: list[_engine_models.CitationInstance],
    atoms: list[Any],
) -> list[_engine_models.Claim]:
    """Validate a complete partition and preserve all citation attachments.

    Raises:
        ValueError: Offsets, coverage or citation attachments are invalid.
    """
    if not isinstance(atoms, list) or not atoms:
        raise ValueError("atoms must be a nonempty list")
    claim = sentence["claim"]
    occurrences = {cite["occurrence_id"]: cite for cite in cites}
    eligible = {key for key, cite in occurrences.items() if not cite["nocite"]}
    result: list[_engine_models.Claim] = []
    attached, position = set(), 0
    for item in atoms:
        atom = (
            dataclasses.asdict(item) if isinstance(item, _engine_models.AtomicClaim) else item
        )
        if (
            not isinstance(atom, dict)
            or not {"start", "end", "citation_ids"} <= set(atom)
            or set(atom) - {"start", "end", "citation_ids", "kind", "reason"}
        ):
            raise ValueError("each atom needs start, end and citation_ids")
        kind, reason = atom.get("kind", "cited"), atom.get("reason")
        if kind not in ("cited", "uncited"):
            raise ValueError("atom kind must be cited or uncited")
        if reason is not None and not isinstance(reason, str):
            raise ValueError("reason must be a string")
        if kind == "uncited" and len((reason or "").strip()) < 15:
            raise ValueError(
                "uncited atoms need a scope reason of at least 15 characters"
            )
        start, end, citation_ids = (
            atom["start"],
            atom["end"],
            atom["citation_ids"],
        )
        if (
            type(start) is not int
            or type(end) is not int
            or start != position
            or not start < end <= len(claim)
        ):
            raise ValueError(
                "atoms must partition the complete sentence in order, "
                "without gaps or overlaps; use Unicode codepoint offsets"
            )
        if (
            not isinstance(citation_ids, list)
            or (kind == "cited" and not citation_ids)
            or (kind == "uncited" and citation_ids)
            or any(not isinstance(value, str) for value in citation_ids)
            or len(set(citation_ids)) != len(citation_ids)
            or not set(citation_ids) <= eligible
        ):
            raise ValueError(
                "citation_ids must name distinct cited occurrences"
            )
        for expression in _engine_parsing._TEX_MATH.finditer(claim):
            if expression.start() < start < expression.end() or (
                expression.start() < end < expression.end()
            ):
                raise ValueError(
                    "an atom boundary cannot split a math expression"
                )
        for occurrence_id, cite in occurrences.items():
            left, right = cite["marker_start"], cite["marker_end"]
            if start < right and end > left:
                if kind == "uncited":
                    raise ValueError(
                        "uncited atoms cannot contain citation markers"
                    )
                if start > left or end < right:
                    raise ValueError(
                        "an atom boundary cannot split a citation marker"
                    )
                if not cite["nocite"] and occurrence_id not in citation_ids:
                    raise ValueError(
                        "retain the citation attached inside each atom"
                    )
        atom_text = claim[start:end]
        prose = re.sub(r"⟨cite:[^⟩]*⟩", "", atom_text)
        if not any(character.isalnum() for character in prose):
            raise ValueError("each atom must contain assertion text")
        result.append(
            {
                "start": start,
                "end": end,
                "text": atom_text,
                "byte_start": len(claim[:start].encode("utf-8")),
                "byte_end": len(claim[:end].encode("utf-8")),
                "citation_ids": sorted(citation_ids),
                "kind": kind,
                "reason": reason.strip() if reason else None,
            }
        )
        attached.update(citation_ids)
        position = end
    if position != len(claim) or attached != eligible:
        raise ValueError(
            "cover the entire sentence and every citation occurrence"
        )
    return result

def register_claims(
    tex_path: str, sentence_id: str, atoms: list[_engine_models.AtomicClaim]
) -> dict:
    """Register agent-proposed atomic claims without rewriting the sentence.

    The first registration enables atomic mode for this main manuscript:
    register every current cited sentence, using one span for simple claims.
    Uncited spans need kind="uncited", no citation_ids, and a scope reason.
    Changed sentence/context or partition requires registration and judging
    again. All attached atom/occurrence pairs require separate verdicts.

    Args:
        tex_path: Main manuscript path, including its input/include files.
        sentence_id: Current sentence_id returned by extract_cites.
        atoms: A complete ordered partition of the exact extracted sentence.
            Each span attaches to explicit occurrence IDs from that sentence.

    Returns:
        Registration and derived atom IDs, or an error. Offsets certify
        coverage, not semantic atomicity: a judge must review the split and
        source scope using the unchanged original sentence and context.
    """
    workdir = os.path.dirname(os.path.abspath(tex_path))
    with _engine_persistence._file_lock(_engine_persistence._project_path(workdir, "ledger.json")):
        extracted = _engine_manuscripts.extract_cites(tex_path)
        if extracted.get("error"):
            return {"ok": False, "error": extracted["error"]}
        sentence = next(
            (
                item
                for item in extracted["sentences"]
                if item["sentence_id"] == sentence_id
            ),
            None,
        )
        if sentence is None:
            return {
                "ok": False,
                "error": "sentence changed or ID is unknown; extract again",
            }
        cites = [
            cite
            for cite in extracted["cites"]
            if cite["sentence_id"] == sentence_id
        ]
        try:
            normalized = _validated_atoms(sentence, cites, atoms)
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        decomposition_id = _engine_identifiers._atomic_digest([sentence_id, normalized])
        for index, atom in enumerate(normalized):
            atom["atom_id"] = _engine_identifiers._atomic_digest([decomposition_id, index])
        registration = dict(
            sentence,
            atoms=normalized,
            decomposition_id=decomposition_id,
            tex_path=os.path.abspath(tex_path),
        )
        ledger = _engine_persistence._load_ledger(workdir)
        decompositions = ledger.setdefault("decompositions", {})
        # Discard old judgments on any revision, including changing back to an
        # earlier decomposition. An identical registration is idempotent.
        previous = decompositions.get(sentence_id)
        current_ids = {item["sentence_id"] for item in extracted["sentences"]}
        invalidated = {
            old_id
            for old_id, old in decompositions.items()
            if old.get("tex_path") == os.path.abspath(tex_path)
            and old_id not in current_ids
        }
        if previous != registration:
            invalidated.add(sentence_id)
        if invalidated:
            ledger["entries"] = {
                key: value
                for key, value in ledger["entries"].items()
                if value.get("sentence_id") not in invalidated
            }
        # Keep history keyed by exact sentence identity. Inserting a citation
        # must not overwrite a displaced sentence's atomic obligation.
        decompositions[sentence_id] = registration
        ledger["version"] = 3
        _engine_persistence._write_project(workdir, "ledger.json", ledger)
    return {"ok": True, **registration}

def _find_decomposition(cite: dict, ledger: dict) -> dict | None:
    """Require exact registration once this manuscript enters atomic mode."""
    registrations = [
        value
        for value in ledger.get("decompositions", {}).values()
        if value.get("tex_path") == cite["tex_path"]
    ]
    for registration in registrations:
        if registration["sentence_id"] == cite["sentence_id"]:
            return registration
    # A moved and edited assertion cannot be matched reliably by text or
    # source ordinal. Atomic mode requires explicit registration of every
    # current sentence; a single span is valid for a simple assertion.
    return registrations[-1] if registrations else None

def _support_target(
    workdir: str,
    tex_path: str,
    occurrence_id: str,
    atom_id: str | None,
    key: str,
    claim: str,
    context: str | None,
    ledger: dict,
) -> dict:
    """Resolve an exact current occurrence and optional registered atom.

    Raises:
        ValueError: The requested target is stale, ambiguous or incomplete.
    """
    if os.path.realpath(workdir) != os.path.realpath(os.path.dirname(tex_path)):
        raise ValueError("workdir must be the main manuscript directory")
    extracted = _engine_manuscripts.extract_cites(tex_path)
    if extracted.get("error"):
        raise ValueError(extracted["error"])
    cite = next(
        (
            item
            for item in extracted["cites"]
            if item["occurrence_id"] == occurrence_id
        ),
        None,
    )
    if (
        cite is None
        or cite["nocite"]
        or cite["key"] != key
        or cite["claim"] != claim
        or cite["context"] != context
    ):
        raise ValueError(
            "use the exact current occurrence, key, claim and context"
        )
    registration = _find_decomposition(cite, ledger)
    target = {
        "occurrence_id": occurrence_id,
        "sentence_id": cite["sentence_id"],
        "location_id": cite["location_id"],
        "file": cite["file"],
        "line": cite["line"],
        "context": cite["context"],
    }
    if registration:
        if registration["sentence_id"] != cite["sentence_id"]:
            raise ValueError(
                "sentence or context changed; register claims again"
            )
        atom = next(
            (
                item
                for item in registration["atoms"]
                if item["atom_id"] == atom_id
            ),
            None,
        )
        if atom is None or occurrence_id not in atom["citation_ids"]:
            raise ValueError(
                "record each registered atom with an attached occurrence"
            )
        target.update(
            atom_id=atom_id,
            atom=atom,
            decomposition_id=registration["decomposition_id"],
        )
    elif atom_id is not None:
        raise ValueError("register claims before recording an atom verdict")
    return target

def _support_requirements(extracted: dict, ledger: dict) -> list[dict]:
    """Expand citation instances only into atoms explicitly attached to them."""
    required = []
    for cite in extracted["cites"]:
        if cite["nocite"]:
            continue
        registration = _find_decomposition(cite, ledger)
        if not registration:
            required.append(cite)
        elif registration["sentence_id"] != cite["sentence_id"]:
            required.append(dict(cite, decomposition_stale=True))
        else:
            for atom in registration["atoms"]:
                if cite["occurrence_id"] in atom["citation_ids"]:
                    required.append(
                        dict(
                            cite,
                            atom_id=atom["atom_id"],
                            atom=atom,
                            decomposition_id=registration["decomposition_id"],
                        )
                    )
    return required

def _support_id(occurrence_id: str, atom_id: str | None = None) -> str:
    """Keep sentence-occurrence and atom-occurrence judgments separate."""
    return f"occurrence:{occurrence_id}|atom:{atom_id or 'sentence'}"

def _validated_correction(
    proposal: _engine_models.ProposedCorrection | dict[str, Any] | None,
    verdict: str,
    occurrence_id: str | None,
    judge: str | None,
    found_quotes: int,
) -> dict[str, Any] | None:
    """Validate a bound draft without certifying its proposed meaning."""
    if proposal is None:
        return None
    value = (
        dataclasses.asdict(proposal)
        if isinstance(proposal, _engine_models.ProposedCorrection)
        else proposal
    )
    if (
        not isinstance(value, dict)
        or not {"action", "rationale"} <= set(value)
        or set(value) - {"action", "rationale", "replacement_text"}
    ):
        raise ValueError("proposed_correction needs action and rationale")
    action = value["action"]
    if not isinstance(action, str) or action not in {
        "revise-claim",
        "replace-citation",
        "remove-claim",
        "obtain-text",
    }:
        raise ValueError("unknown proposed correction action")
    rationale = value["rationale"]
    replacement = value.get("replacement_text")
    if (
        not isinstance(rationale, str)
        or len(rationale.strip()) < 15
        or (
            replacement is not None
            and (not isinstance(replacement, str) or not replacement.strip())
        )
    ):
        raise ValueError("provide a meaningful rationale and nonempty wording")
    if (
        verdict == "SUPPORTS"
        or not occurrence_id
        or not isinstance(judge, str)
        or not judge.strip()
    ):
        raise ValueError(
            "corrections require a non-SUPPORTS verdict, explicit occurrence "
            "and judge identity"
        )
    if replacement is not None:
        if action != "revise-claim" or found_quotes == 0:
            raise ValueError(
                "replacement wording needs revise-claim and source quotations"
            )
        if _engine_parsing._CITE_CMD.search(replacement) or "⟨cite:" in replacement:
            raise ValueError(
                "replacement_text is assertion wording only; resolve citation "
                "changes separately"
            )
    return {
        "action": action,
        "rationale": rationale.strip(),
        "replacement_text": replacement,
        "author": judge,
        "approval": "unapproved",
        "replacement_verified": False,
    }

def _correction_evidence(
    judgment: dict[str, Any],
    attributed: bool,
) -> dict[str, Any] | None:
    """Recheck source spans locally instead of trusting stored found flags."""
    metadata = _engine_persistence._load_text_meta(judgment.get("source_cache_id", judgment["id"]))
    if metadata is None:
        return None
    try:
        text = _engine_quality.read_text(metadata["path"])
    except (OSError, _engine_quality.SourceLimitError):
        return None
    if (not _engine_quality.current(metadata, text)["usable_for_judgment"]
            or _engine_identifiers._source_identity(metadata, text) != judgment["source_identity"]):
        return None
    quotes = []
    for quote in judgment.get("quotes", []):
        if quote["found"]:
            checked = _locate_quote(text, quote["text"])
            if not checked["found"]:
                return None
            quotes.append(dict(checked, text=quote["text"]))
    return {
        "id": judgment["id"],
        "basis": judgment["basis"],
        "identity": judgment["source_identity"],
        "attribution": "verified" if attributed else "unverified",
        "quotes": quotes,
        "status": "current-source-spans",
    }

def record_support(
    workdir: str,
    key: str,
    claim: str,
    verdict: str,
    identifier: str,
    quotes: list[str] | None = None,
    note: str | None = None,
    judge: str | None = None,
    file: str | None = None,
    line: int | None = None,
    context: str | None = None,
    version: str | None = None,
    tex_path: str | None = None,
    occurrence_id: str | None = None,
    atom_id: str | None = None,
    proposed_correction: _engine_models.ProposedCorrection | None = None,
) -> dict:
    """Record a support verdict for one (cite key, claim sentence) pair.

    verdict ∈ SUPPORTS | PARTIAL | UNSUPPORTED | CONTRADICTS | UNVERIFIABLE.
    SUPPORTS / PARTIAL / CONTRADICTS are refused unless at least one `quote`
    is found verbatim in the cited paper's fetched text (fetch_text first).
    PARTIAL / CONTRADICTS / UNSUPPORTED / UNVERIFIABLE need a `note` saying
    what the paper does and does not say; UNVERIFIABLE is refused when full
    text is available. `claim` must be the exact sentence extract_cites gave.
    Pass tex_path and occurrence_id together; atom_id selects a registered
    span while claim/context retain the full original. Atomic mode requires
    an atom_id even for a registered single-span sentence. Legacy calls only
    satisfy unambiguous sentences in manuscripts outside atomic mode.
    proposed_correction optionally records an unapproved independent-judge
    draft for a non-support verdict; it never applies or verifies new wording.
    """
    if bool(tex_path) != bool(occurrence_id) or (atom_id and not occurrence_id):
        return {
            "recorded": False,
            "error": (
                "tex_path and occurrence_id are required together; "
                "atoms need both"
            ),
        }
    target = {}
    if tex_path and occurrence_id:
        tex_path = os.path.abspath(tex_path)
        try:
            target = _support_target(
                workdir,
                tex_path,
                occurrence_id,
                atom_id,
                key,
                claim,
                context,
                _engine_persistence._load_ledger(workdir),
            )
        except ValueError as error:
            return {"recorded": False, "error": str(error)}
    if quotes is not None and (
        not isinstance(quotes, list)
        or any(not isinstance(quote, str) for quote in quotes)
    ):
        return {"recorded": False, "error": "quotes must be a list of strings"}
    verdict = (verdict or "").strip().upper()
    if verdict not in _VERDICTS:
        return {
            "recorded": False,
            "error": f"verdict must be one of {list(_VERDICTS)}",
        }
    rec = _engine_resolution._full_record(identifier)
    if rec is None:
        return {"recorded": False, "error": f"cannot resolve {identifier}"}
    try:
        rec = _engine_resolution._with_pin(rec, identifier, version)
    except (RuntimeError, ValueError) as exc:
        return {"recorded": False, "error": str(exc)}
    cid = _engine_identifiers._canonical(rec)
    cache_id = _engine_identifiers._text_identity(rec)
    meta = _engine_persistence._load_text_meta(cache_id) or _engine_acquisition.fetch_text(identifier, version=version)
    if meta.get("error"):
        return {"recorded": False, "error": meta["error"]}
    basis = meta["basis"]
    text = ""
    if basis != "none":
        try:
            text = _engine_quality.read_text(meta["path"])
        except (OSError, RuntimeError) as error:
            return {"recorded": False, "error": str(error)}
    quality = _engine_quality.current(meta, text)
    if not quality["usable_for_judgment"] and verdict != "UNVERIFIABLE":
        return {
            "recorded": False, "quality": quality,
            "error": "Source extraction is inadequate or unknown; obtain a readable copy or record UNVERIFIABLE with a reason.",
        }
    quotes = [q.strip() for q in (quotes or []) if q and q.strip()]
    checks = [dict({"text": q}, **_locate_quote(text, q)) for q in quotes]
    n_found = sum(1 for c in checks if c["found"])
    note = (note or "").strip()
    if verdict in ("SUPPORTS", "PARTIAL", "CONTRADICTS") and n_found == 0:
        return {
            "recorded": False,
            "basis": basis,
            "quotes": checks,
            "error": f"{verdict} needs at least one quote found verbatim in the paper's "
            f"{'text' if basis == 'fulltext' else basis} — quote the paper, not your paraphrase",
        }
    if (
        verdict in ("PARTIAL", "CONTRADICTS", "UNSUPPORTED", "UNVERIFIABLE")
        and len(note) < 15
    ):
        return {
            "recorded": False,
            "error": f"{verdict} needs a note (≥ 15 characters) saying what the paper does and does not say",
        }
    if verdict == "UNVERIFIABLE" and basis == "fulltext" and quality["usable_for_judgment"]:
        return {
            "recorded": False,
            "error": "full text is available — read it and decide (SUPPORTS / PARTIAL / "
            "UNSUPPORTED / CONTRADICTS); UNVERIFIABLE is only for papers whose text could not be obtained",
        }
    try:
        correction = _validated_correction(
            proposed_correction, verdict, occurrence_id, judge, n_found
        )
    except ValueError as error:
        return {"recorded": False, "error": str(error)}
    with _engine_persistence._file_lock(_engine_persistence._project_path(workdir, "ledger.json")):
        ledger = _engine_persistence._load_ledger(workdir)
        # Revalidate inside the transaction: registration may have changed
        # while fetching source text. Never commit against an obsolete split.
        if tex_path and occurrence_id:
            try:
                target = _support_target(
                    workdir, tex_path, occurrence_id, atom_id,
                    key, claim, context, ledger,
                )
            except ValueError as error:
                return {"recorded": False, "error": str(error)}
        lid = (_support_id(occurrence_id, atom_id) if occurrence_id
               else f"{key}|{_engine_identifiers._claim_hash(claim)}")
        ledger["version"] = 3
        judgment: _engine_models.Judgment = {"context_hash": _engine_identifiers._claim_hash(context if context is not None else claim),
                                  "source_identity": _engine_identifiers._source_identity(meta, text),
                                  "source_cache_id": meta.get("cache_id", cid), "key": key, "id": cid, "claim": claim, "verdict": verdict, "basis": basis,
                                  "quotes": checks, "note": note or None, "judge": judge or None,
                                  "file": file, "line": line, "recorded": _engine_persistence._now_iso()}
        # _support_target already validated this occurrence/atom binding.
        typing.cast(dict[str, Any], judgment).update(target)
        ledger["entries"][lid] = judgment
        if correction is not None:
            ledger["entries"][lid]["proposed_correction"] = correction
        _engine_persistence._write_project(workdir, "ledger.json", ledger)
    return {"recorded": True, "ledger_id": lid, "verdict": verdict, "basis": basis,
            "quotes_found": n_found, "quotes": checks}

def ledger_read(workdir: str) -> dict:
    """Read the support ledger of a manuscript directory."""
    return {"path": _engine_persistence._project_path(workdir, "ledger.json"), "ledger": _engine_persistence._load_ledger(workdir)}

def _audit_ledger(workdir: str) -> dict[str, Any]:
    """Load ledger structure, rejecting malformed state instead of skipping it.

    Raises:
        ValueError: Ledger entries or registrations are malformed.
        OSError: The ledger cannot be read.
    """
    ledger = _engine_persistence._load_ledger(workdir)
    if not isinstance(ledger, dict) or not isinstance(
        ledger.get("entries"), dict
    ):
        raise ValueError("ledger must contain an entries object")
    for entry in ledger["entries"].values():
        if not isinstance(entry, dict) or not {
            "id",
            "key",
            "claim",
            "verdict",
            "basis",
        } <= set(entry):
            raise ValueError("malformed support ledger entry")
        if any(
            not isinstance(entry[name], str)
            for name in ("id", "key", "claim", "verdict", "basis")
        ) or (
            "source_cache_id" in entry
            and not isinstance(entry["source_cache_id"], str)
        ):
            raise ValueError("support ledger identity fields must be strings")
    for entry in ledger["entries"].values():
        quotes = entry.get("quotes", [])
        if not isinstance(quotes, list) or any(
            not isinstance(quote, dict)
            or type(quote.get("found")) is not bool
            or not isinstance(quote.get("text"), str)
            for quote in quotes
        ):
            raise ValueError("malformed stored quotation checks")
        proposal = entry.get("proposed_correction")
        if proposal is not None:
            if (
                not isinstance(proposal, dict)
                or set(proposal)
                != {
                    "action",
                    "rationale",
                    "replacement_text",
                    "author",
                    "approval",
                    "replacement_verified",
                }
                or proposal["approval"] != "unapproved"
                or proposal["replacement_verified"] is not False
                or proposal["author"] != entry.get("judge")
            ):
                raise ValueError("malformed stored correction proposal")
            _validated_correction(
                {
                    name: proposal[name]
                    for name in ("action", "rationale", "replacement_text")
                },
                entry["verdict"],
                entry.get("occurrence_id"),
                entry.get("judge"),
                sum(quote["found"] for quote in quotes),
            )
    decompositions = ledger.get("decompositions", {})
    if not isinstance(decompositions, dict):
        raise ValueError("decompositions must be an object")
    for registration in decompositions.values():
        if (
            not isinstance(registration, dict)
            or not {
                "sentence_id",
                "tex_path",
                "atoms",
                "decomposition_id",
                "file",
                "claim",
            }
            <= set(registration)
            or not isinstance(registration["atoms"], list)
        ):
            raise ValueError("malformed atomic registration")
        if any(
            not isinstance(registration[name], str)
            for name in (
                "sentence_id",
                "tex_path",
                "decomposition_id",
                "file",
                "claim",
            )
        ):
            raise ValueError(
                "atomic registration identity fields must be strings"
            )
        for atom in registration["atoms"]:
            if (
                not isinstance(atom, dict)
                or not {
                    "atom_id",
                    "text",
                    "kind",
                    "citation_ids",
                }
                <= set(atom)
                or not isinstance(atom["citation_ids"], list)
            ):
                raise ValueError("malformed registered atom")
            if (
                any(
                    not isinstance(atom[name], str)
                    for name in ("atom_id", "text", "kind")
                )
                or any(
                    not isinstance(value, str) for value in atom["citation_ids"]
                )
                or (
                    atom["kind"] == "uncited"
                    and not isinstance(atom.get("reason"), str)
                )
            ):
                raise ValueError("malformed registered atom fields")
    return ledger
