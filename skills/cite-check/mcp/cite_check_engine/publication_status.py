"""Directional Crossref updates, separate from identity and claim support."""

import datetime
import typing
import urllib.parse

from cite_check_engine import config
from cite_check_engine import identifiers
from cite_check_engine import persistence

MAX_RELATIONS = 100
_STATES = {
    "UNKNOWN",
    "NO_UPDATES_REPORTED",
    "RETRACTED",
    "CORRECTED",
    "EXPRESSION_OF_CONCERN",
    "NOTICE",
    "UPDATED",
}


def unknown(reason: str) -> dict[str, typing.Any]:
    """Represent absent status coverage without certifying a work as clear."""
    return {
        "state": "UNKNOWN",
        "doi": None,
        "complete": False,
        "source": None,
        "source_url": None,
        "observed_at": persistence._now_iso(),  # noqa: SLF001
        "metadata_cache_ttl_seconds": config.META_TTL,
        "updates": [],
        "notices_for": [],
        "reasons": [reason],
        "detail": reason,
    }


def _date(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("invalid update date")
    parts = value.get("date-parts")
    if parts is not None:
        if (
            not isinstance(parts, list)
            or len(parts) != 1
            or not isinstance(parts[0], list)
            or not 1 <= len(parts[0]) <= 3
            or any(type(part) is not int for part in parts[0])
        ):
            raise ValueError("invalid update date parts")
        numbers = parts[0]
        datetime.date(*(numbers + [1] * (3 - len(numbers))))
        return "-".join(
            f"{part:04d}" if index == 0 else f"{part:02d}"
            for index, part in enumerate(numbers)
        )
    stamp = value.get("date-time")
    if stamp is not None:
        if not isinstance(stamp, str) or len(stamp) > 40:
            raise ValueError("invalid update timestamp")
        return (
            datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            .date()
            .isoformat()
        )
    return None


def _event(
    value: object, direction: str, own_doi: str
) -> dict[str, typing.Any]:
    if not isinstance(value, dict):
        raise ValueError("update relation is not an object")
    doi, kind = value.get("DOI"), value.get("type")
    if (
        not isinstance(doi, str)
        or len(doi) > 2048
        or not identifiers._DOI_RE.fullmatch(doi)  # noqa: SLF001
        or not isinstance(kind, str)
        or not kind.strip()
        or len(kind) > 80
    ):
        raise ValueError("update relation lacks a valid DOI or type")
    result: dict[str, typing.Any] = {
        "direction": direction,
        "doi": doi.lower(),
        "url": "https://doi.org/" + urllib.parse.quote(doi.lower(), safe="/"),
        "type": kind.strip().lower().replace("_", "-").replace(" ", "-"),
        "source": value.get("source", "unspecified"),
        "label": value.get("label", kind),
        "date": None,
        "metadata_errors": [],
        "self_relation": doi.lower() == own_doi,
    }
    try:
        result["date"] = _date(value.get("updated"))
    except (ValueError, TypeError, OverflowError) as error:
        result["metadata_errors"].append(str(error))
    if any(
        not isinstance(result[name], str) or len(result[name]) > 256
        for name in ("source", "label")
    ):
        result["metadata_errors"].append("invalid update source or label")
        result["source"], result["label"] = "unspecified", kind
    return result


def normalize(message: object) -> dict[str, typing.Any]:
    """Read both relation directions from a complete Crossref work response.

    An observation can come from the HTTP metadata cache. Its local inspection
    time is not represented as a new network fetch or a registry attestation.
    """
    result = unknown("publication status unavailable")
    if not isinstance(message, dict):
        return result
    doi = message.get("DOI")
    if (
        not isinstance(doi, str)
        or len(doi) > 2048
        or not identifiers._DOI_RE.fullmatch(doi)  # noqa: SLF001
    ):
        return result
    doi = doi.lower()
    result.update(
        doi=doi,
        source="crossref",
        source_url="https://api.crossref.org/works/"
        + urllib.parse.quote(doi, safe=""),
        complete=True,
        reasons=[],
    )
    for field, destination in (
        ("updated-by", "updates"),
        ("update-to", "notices_for"),
    ):
        values = message.get(field, [])
        if not isinstance(values, list):
            result["reasons"].append(f"{field} is malformed")
            result["complete"] = False
            continue
        if len(values) > MAX_RELATIONS:
            result["reasons"].append(
                f"{field} exceeds {MAX_RELATIONS} relations"
            )
            result["complete"] = False
        for value in values[:MAX_RELATIONS]:
            try:
                event = _event(value, field, doi)
            except (ValueError, TypeError, OverflowError) as error:
                result["reasons"].append(str(error))
                result["complete"] = False
                continue
            if event["metadata_errors"]:
                result["reasons"].extend(event["metadata_errors"])
                result["complete"] = False
            if event not in result[destination]:
                result[destination].append(event)
    affected = result["updates"] + [
        event for event in result["notices_for"] if event["self_relation"]
    ]
    kinds = {event["type"] for event in affected}
    if "retraction" in kinds:
        state = "RETRACTED"
    elif "expression-of-concern" in kinds:
        state = "EXPRESSION_OF_CONCERN"
    elif kinds & {
        "correction",
        "erratum",
        "corrigendum",
        "addendum",
        "clarification",
    }:
        state = "CORRECTED"
    elif affected:
        state = "UPDATED"
    elif not result["complete"]:
        state = "UNKNOWN"
    elif result["notices_for"]:
        state = "NOTICE"
    else:
        state = "NO_UPDATES_REPORTED"
    result["state"] = state
    descriptions = {
        "RETRACTED": (
            "Crossref reports a retraction affecting this work; review the "
            "notice before relying on it."
        ),
        "CORRECTED": (
            "Crossref reports a correction affecting this work; review its "
            "effect on the cited assertion."
        ),
        "EXPRESSION_OF_CONCERN": (
            "Crossref reports an expression of concern affecting this "
            "work; explicit review is required."
        ),
        "UPDATED": (
            "Crossref reports an update affecting this work; review the "
            "linked notice."
        ),
        "NOTICE": (
            "This work is an update notice for other works; it is not "
            "thereby itself retracted."
        ),
        "UNKNOWN": (
            "Publication-status metadata is incomplete or malformed; "
            "current status is unknown."
        ),
        "NO_UPDATES_REPORTED": (
            "No update relation was supplied in the observed Crossref "
            "record; this does not certify current publication status as "
            "clear."
        ),
    }
    result["detail"] = descriptions[state]
    if any(event["self_relation"] for event in affected):
        result["reasons"].append("self/in-situ update requires explicit review")
    result["reasons"] = list(dict.fromkeys(result["reasons"]))
    return result


def _strings(value: object, maximum: int, length: int) -> bool:
    return (
        isinstance(value, list)
        and len(value) <= maximum
        and all(isinstance(item, str) and len(item) <= length for item in value)
    )


def _valid_cached(value: dict[str, typing.Any], doi: str | None) -> bool:
    required = {
        "doi",
        "state",
        "complete",
        "source",
        "source_url",
        "observed_at",
        "metadata_cache_ttl_seconds",
        "updates",
        "notices_for",
        "reasons",
        "detail",
    }
    if (
        set(value) != required
        or not isinstance(value["state"], str)
        or value["state"] not in _STATES
        or type(value["complete"]) is not bool
        or not isinstance(value["detail"], str)
        or len(value["detail"]) > 1024
        or not _strings(value["reasons"], 2 * MAX_RELATIONS + 3, 512)
        or not isinstance(value["observed_at"], str)
        or len(value["observed_at"]) != 20
        or type(value["metadata_cache_ttl_seconds"]) is not int
        or value["metadata_cache_ttl_seconds"] < 0
    ):
        return False
    datetime.datetime.strptime(value["observed_at"], "%Y-%m-%dT%H:%M:%SZ")
    for field in ("updates", "notices_for"):
        if (
            not isinstance(value[field], list)
            or len(value[field]) > MAX_RELATIONS
        ):
            return False
    if value["source"] is None:
        return (
            value["state"] == "UNKNOWN"
            and value["complete"] is False
            and value["doi"] is None
            and value["source_url"] is None
            and not value["updates"]
            and not value["notices_for"]
        )
    own = value["doi"]
    if (
        value["source"] != "crossref"
        or not isinstance(own, str)
        or len(own) > 2048
        or not identifiers._DOI_RE.fullmatch(own)  # noqa: SLF001
        or (doi is not None and own.lower() != doi.lower())
        or value["source_url"]
        != "https://api.crossref.org/works/" + urllib.parse.quote(own, safe="")
    ):
        return False
    message: dict[str, typing.Any] = {"DOI": own}
    for field, direction in (
        ("updates", "updated-by"),
        ("notices_for", "update-to"),
    ):
        message[direction] = []
        for event in value[field]:
            if (
                not isinstance(event, dict)
                or set(event)
                != {
                    "direction",
                    "doi",
                    "url",
                    "type",
                    "source",
                    "label",
                    "date",
                    "metadata_errors",
                    "self_relation",
                }
                or not _strings(event["metadata_errors"], 2, 512)
            ):
                return False
            date = event["date"]
            if date is not None and (
                not isinstance(date, str) or len(date) > 10
            ):
                return False
            raw = {
                "DOI": event["doi"],
                "type": event["type"],
                "source": event["source"],
                "label": event["label"],
                "updated": {
                    "date-parts": [[int(part) for part in date.split("-")]]
                }
                if date
                else None,
            }
            rebuilt = _event(raw, direction, own)
            rebuilt["metadata_errors"] = event["metadata_errors"]
            if rebuilt != event:
                return False
            message[direction].append(raw)
    replay = normalize(message)
    if value["state"] != replay["state"] and not (
        not value["complete"]
        and value["state"] == "UNKNOWN"
        and replay["state"] in {"NO_UPDATES_REPORTED", "NOTICE"}
    ):
        return False
    return True


def available(value: object, doi: str | None = None) -> dict[str, typing.Any]:
    """Validate bounded persisted status metadata and its DOI binding."""
    try:
        if isinstance(value, dict) and _valid_cached(value, doi):
            return value
    except (ValueError, TypeError, KeyError, OverflowError):
        pass
    return unknown(
        "No valid authoritative publication-status metadata was assessed "
        "for this work."
    )
