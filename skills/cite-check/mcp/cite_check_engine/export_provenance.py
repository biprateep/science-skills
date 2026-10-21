"""Bounded local export receipts; integrity records, not registry signatures."""

import hashlib
import json
import os
import re
import typing

from cite_check_engine import config
from cite_check_engine import persistence
from cite_check_engine import quality

POLICY = "official-export-v1"
TRANSFORM = "sanitize-bibtex-v1"
MAX_RECEIPT_BYTES = 4 * 1024 * 1024
MAX_EXPORT_BYTES = 1024 * 1024
_FIELDS = {
    "policy",
    "transform",
    "source",
    "origin",
    "record",
    "request",
    "raw_export",
    "raw_sha256",
    "entry",
    "entry_sha256",
    "key",
    "created",
}


def digest(text: str) -> str:
    """Hash exact UTF-8 text without normalizing whitespace or line endings."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def candidate_paths(
    receipt_id: object, bib_path: str | None = None
) -> list[str]:
    """Derive trusted storage locations solely from a content hash."""
    if not isinstance(receipt_id, str) or not re.fullmatch(
        r"[a-f0-9]{64}", receipt_id
    ):
        return []
    paths = []
    if bib_path is not None:
        paths.append(
            os.path.join(
                os.path.dirname(os.path.abspath(bib_path)),
                config.PROJECT_DIR,
                "exports",
                receipt_id + ".json",
            )
        )
    paths.append(
        os.path.join(config.CACHE_DIR, "exports", receipt_id + ".json")
    )
    return list(dict.fromkeys(paths))


def fingerprint(path: str) -> str | None:
    """Observe existence and bounded content without trusting a receipt."""
    try:
        return hashlib.sha256(
            quality.read_bytes(path, MAX_RECEIPT_BYTES)
        ).hexdigest()
    except FileNotFoundError:
        return "invalid-symlink" if os.path.lexists(path) else None
    except (OSError, quality.SourceLimitError):
        return "unreadable-or-oversized"


def _encoded(payload: dict[str, typing.Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _protect(path: str, protected: list[str]) -> None:
    for target in (path, path + ".lock"):
        if os.path.islink(target):
            raise ValueError("export artifact or lock is a symlink")
        for source in protected:
            if os.path.realpath(target) == os.path.realpath(source) or (
                os.path.exists(target)
                and os.path.exists(source)
                and os.path.samefile(target, source)
            ):
                raise ValueError("export artifact or lock aliases an input")
    if os.path.islink(os.path.dirname(path)):
        raise ValueError("export artifact directory is a symlink")


def publish(
    payload: dict[str, typing.Any],
    bib_path: str | None = None,
    protected: list[str] | None = None,
) -> dict[str, str]:
    """Publish complete immutable artifacts before a bibliography commit."""
    raw = _encoded(payload)
    if len(raw) > MAX_RECEIPT_BYTES:
        raise ValueError("export receipt exceeds the 4 MiB bound")
    receipt_id = hashlib.sha256(raw).hexdigest()
    paths = candidate_paths(receipt_id, bib_path)
    inputs = list(protected or []) + ([bib_path] if bib_path else [])
    for path in paths:
        _protect(path, inputs)
    for path in reversed(paths):
        with persistence._file_lock(path):  # noqa: SLF001 - shared engine API
            _protect(path, inputs)
            if os.path.lexists(path):
                if quality.read_bytes(path, MAX_RECEIPT_BYTES) != raw:
                    raise ValueError("existing export artifact is corrupt")
            else:
                persistence._atomic_write(path, raw)  # noqa: SLF001 - shared engine API
    return {
        "receipt": receipt_id,
        "raw_sha256": payload["raw_sha256"],
        "entry_sha256": payload["entry_sha256"],
        "policy": POLICY,
        "path": paths[0],
    }


def inspect(
    entry: dict[str, typing.Any], bib_path: str
) -> dict[str, typing.Any]:
    """Check stored hashes and return data for offline derivation replay."""
    prov = entry.get("provenance") or {}
    receipt_id = prov.get("receipt")
    if receipt_id is None:
        return {
            "status": "DECLARED",
            "detail": "legacy declaration requires re-export",
            "snapshots": {},
        }
    paths = candidate_paths(receipt_id, bib_path)
    if not paths or prov.get("export_policy") != POLICY:
        return {
            "status": "MALFORMED",
            "detail": "invalid export receipt reference",
            "snapshots": {},
        }
    snapshots = {path: fingerprint(path) for path in paths}
    found = next((path for path in paths if snapshots[path] is not None), None)
    result: dict[str, typing.Any] = {"snapshots": snapshots}
    if found is None:
        return dict(
            result,
            status="MISSING",
            detail="export artifact is missing; re-export",
        )
    try:
        if os.path.islink(found):
            raise ValueError("export artifact is a symlink")
        raw = quality.read_bytes(found, MAX_RECEIPT_BYTES)
        if hashlib.sha256(raw).hexdigest() != receipt_id:
            raise ValueError("export receipt content digest differs")
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict) or set(payload) != _FIELDS:
            raise ValueError("invalid export receipt fields")
        if (
            payload["policy"] != POLICY
            or payload["transform"] != TRANSFORM
            or payload["origin"]
            not in {"registry-export-text", "tool-generated-software-entry"}
            or not isinstance(payload["record"], dict)
            or not isinstance(payload["request"], dict)
            or not isinstance(payload["created"], str)
        ):
            raise ValueError("invalid export receipt policy or facts")
        for field, hash_field in (
            ("raw_export", "raw_sha256"),
            ("entry", "entry_sha256"),
        ):
            value = payload[field]
            if (
                not isinstance(value, str)
                or len(value.encode("utf-8")) > MAX_EXPORT_BYTES
                or digest(value) != payload[hash_field]
            ):
                raise ValueError("export content digest differs")
        if (
            prov.get("raw_sha256") != payload["raw_sha256"]
            or prov.get("entry_sha256") != payload["entry_sha256"]
        ):
            raise ValueError("provenance comment differs from receipt")
        # Canonical encoding also rejects NaN and unexpected JSON number forms.
        if _encoded(payload) != raw:
            raise ValueError("noncanonical export receipt encoding")
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        UnicodeError,
        quality.SourceLimitError,
    ) as error:
        return dict(result, status="CORRUPT", detail=str(error))
    if (
        digest(entry["raw"]) != payload["entry_sha256"]
        or entry["key"] != payload["key"]
    ):
        return dict(
            result,
            status="EDITED",
            detail="bibliography entry bytes or key changed; re-export",
        )
    return dict(
        result,
        status="VERIFIED",
        detail="local export digests match",
        payload=payload,
    )
