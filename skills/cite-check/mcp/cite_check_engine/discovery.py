"""Multi-source candidate discovery and deterministic ranking."""

import concurrent.futures
import math
import re
import typing
from datetime import datetime
from typing import Any
from cite_check_engine import models as _engine_models
from cite_check_engine import budgets as _engine_budgets
from cite_check_engine import credentials as _engine_credentials
from cite_check_engine import identifiers as _engine_identifiers
from cite_check_engine import persistence as _engine_persistence
from cite_check_engine import registry_clients as _engine_registry_clients
from cite_check_engine import resolution as _engine_resolution
from cite_check_engine import text as _engine_text


_HINT_RE = re.compile(r"^([A-Za-z][A-Za-z'\-\s]*?)[_:\-]?((?:19|20)\d{2}|\d{2})([A-Za-z0-9_\-]*)$")

def _parse_hint(hint: str) -> dict:
    """Rough cite key → {surname, initial, year, word}. Understands Vaswani2017,
    vaswani2017attention, Vaswani17, Vaswani_2017, Smith2019a, LiW25, JSmith05,
    VanDerWaals1910, planck2016cosmological. Identifiers pass through as `id`."""
    h = (hint or "").strip().strip("{}")
    if not h:
        return {}
    if _engine_identifiers._classify(h)[0] != "unknown":
        return {"id": h}
    s = _engine_text._ascii(h).replace("{", "").replace("}", "")
    m = _HINT_RE.match(s)
    if not m:
        sur = re.sub(r"[^A-Za-z\-\s']", " ", s).strip()
        return {"surname": sur or None}
    raw_surname, ytxt, suffix = m.groups()
    if len(ytxt) == 4:
        year = int(ytxt)
    else:
        yy, cur = int(ytxt), datetime.now().year
        year = 2000 + yy if 2000 + yy <= cur + 2 else 1900 + yy
    sur, initial = raw_surname.strip(" _:-"), None
    m2 = re.match(r"^([A-Z][a-z\-']+)([A-Z])$", sur)          # LiW25
    m3 = re.match(r"^([A-Z])([A-Z][a-z\-']+)$", sur)          # JSmith05
    if m2:
        sur, initial = m2.groups()
    elif m3:
        initial, sur = m3.groups()
    sur = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", sur).strip()   # VanDerWaals → Van Der Waals
    word = None
    if suffix:
        w = re.sub(r"[^A-Za-z]", "", suffix)
        if len(w) >= 3:
            word = w.lower()
    return {"surname": sur or None, "initial": initial, "year": year, "word": word}

def _identity_keys(rec: typing.Mapping[str, typing.Any]) -> list:
    keys = []
    if rec.get("arxiv"):
        keys.append("arxiv:" + rec["arxiv"].lower())
    if rec.get("doi"):
        keys.append("doi:" + rec["doi"].lower())
    if rec.get("bibcode"):
        keys.append("bibcode:" + rec["bibcode"])
    if rec.get("github"):
        keys.append("github:" + rec["github"])
        return keys          # repositories share names freely; only the full name identifies one
    t = _engine_text._norm_title(rec.get("title", ""))
    fa = _engine_text._surname(rec["authors"][0]) if rec.get("authors") else ""
    if t and fa:
        keys.append(f"work:{t}:{fa}")
    return keys

def _merge_candidates(records: list) -> list:
    """Collapse the same work reported by several registries into one
    candidate. Records must arrive most-authoritative first."""
    merged: list[_engine_models.Work] = []
    index: dict[str, int] = {}
    for rec in records:
        keys = _identity_keys(rec)
        hit = next((index[k] for k in keys if k in index), None)
        if hit is None:
            rec = dict(rec)
            rec["registries"] = [rec["registry"]]
            hit = len(merged)
            merged.append(typing.cast(_engine_models.Work, rec))
        else:
            merged[hit] = _engine_resolution._merge_records(merged[hit], rec)
        for k in keys + _identity_keys(merged[hit]):
            index.setdefault(k, hit)
    return merged

def _given_initial(name: str) -> str:
    name = _engine_text._ascii(_engine_text._strip_latex(name or "")).strip()
    if "," in name:
        given = name.split(",", 1)[1].strip()
    else:
        toks = name.split()
        given = " ".join(toks[:-1]) if len(toks) > 1 else ""
    return given[:1].lower()

def _score_candidate(c: dict, title, author, initial, year, words) -> dict:
    s, d = 0.0, {}
    if title:
        d["title_similarity"] = _engine_text._title_sim(title, c.get("title", ""))
        s += 100 * d["title_similarity"]
    if words:
        want = set(words)
        in_title = set(_engine_text._content_words(c.get("title", "")))
        in_abs = set(_engine_text._content_words((c.get("abstract") or "")[:1500]))
        ov_t = len(want & in_title) / len(want)
        ov_a = len(want & in_abs) / len(want)
        s += 40 * ov_t + 12 * ov_a
        d["context_overlap"] = round(max(ov_t, ov_a), 2)
    if author:
        am = _engine_text._author_match([author], c.get("authors") or [])
        d["first_author_match"] = am["first"]
        s += 30 if am["first"] else (12 if am["any"] else -10)
        if initial and c.get("authors"):
            gi = _given_initial(c["authors"][0])
            if gi and gi != initial.lower():
                s -= 8
                d["initial_mismatch"] = True
    if year and c.get("year"):
        delta = abs(int(year) - int(c["year"]))
        d["year_delta"] = delta
        s += 15 if delta == 0 else (8 if delta == 1 else -15)
    s += 4 * (len(c.get("registries") or []) - 1)
    if c.get("doi") or c.get("bibcode"):
        s += 3
    if c.get("citation_count"):
        s += min(5.0, math.log10(c["citation_count"] + 1))
    d["score"] = round(s, 1)
    return d

def _confidence(d: dict, title, author, year) -> str:
    sim, fam, yd = d.get("title_similarity"), d.get("first_author_match"), d.get("year_delta")
    year_ok = yd is not None and yd <= 1
    if sim is not None:
        if sim >= 0.9 and (fam or year_ok or (not author and not year)):
            return "high"
        return "medium" if sim >= 0.75 else "low"
    if fam and year_ok:
        return "medium"
    return "low"

def search_citation(
    query: str | None = None,
    title: str | None = None,
    author: str | None = None,
    year: int | None = None,
    hint: str | None = None,
    context: str | None = None,
    registries: list[str] | None = None,
    max_results: int = 8,
) -> dict[str, Any]:
    """Find real papers matching a description; returns ranked candidates.

    Give as much as you know: `title` (best), `author` (first-author surname),
    `year`, a rough cite key as `hint` ("Vaswani2017", "planck2016cosmological"),
    and/or the sentence being written as `context`. `query` is free text, or a
    bare identifier or GitHub URL (then this is just a resolve). Software:
    registries=["github"] searches repository names and descriptions (opt-in;
    the default registries are the bibliographic ones). Candidates are ranked by
    cite-check's own title/author/year/context scoring — registry ranking is
    not trusted. Opt in to semanticscholar, pubmed, or dblp for additional
    discovery. Their native IDs are locators only: independently resolve a
    suggested_id, compare metadata, then obtain an official export and assess
    support. Discovery metadata never enters authoritative record caches.
    No search candidate establishes citation identity or claim support.
    """
    supported = {
        "ads",
        "arxiv",
        "crossref",
        "openalex",
        "inspire",
        "github",
    } | _engine_registry_clients._DISCOVERY_SOURCES
    if (
        type(max_results) is not int
        or not 1 <= max_results <= 100
        or year is not None
        and (type(year) is not int or not 1000 <= year <= 9999)
        or any(
            value is not None
            and (not isinstance(value, str) or len(value) > 10000)
            for value in (query, title, author, hint, context)
        )
        or registries is not None
        and (
            not isinstance(registries, list)
            or not registries
            or any(
                not isinstance(name, str) or name not in supported
                for name in registries
            )
        )
    ):
        return {
            "error": "Invalid search arguments or unknown registry selector.",
            "candidates": [],
            "n_candidates": 0,
            "errors": {},
        }
    h = _parse_hint(hint) if hint else {}
    direct = h.get("id") or (
        query if query and _engine_identifiers._classify(query)[0] != "unknown" else None
    )
    if direct:
        r = _engine_resolution.resolve_citation(direct)
        r["confidence"] = "high" if r.get("resolved") else "none"
        return {
            "direct": True,
            "query": direct,
            "candidates": [r] if r.get("resolved") else [],
            "n_candidates": 1 if r.get("resolved") else 0,
            "errors": {} if r.get("resolved") else {"resolve": r.get("reason")},
        }
    if query and not title:
        title = query
    author = author or h.get("surname")
    year = int(year) if year else h.get("year")
    initial = h.get("initial")
    words = [h["word"]] if h.get("word") else []
    if context:
        words += [w for w in _engine_text._content_words(context) if len(w) >= 4][:8]
    words = list(dict.fromkeys(words))
    if not (title or author or words):
        return {
            "error": "give a title/query, author+year hint, or sentence context"
        }

    enabled = list(
        dict.fromkeys(
            registries
            if registries is not None
            else ["ads", "arxiv", "crossref", "openalex", "inspire"]
        )
    )
    if not _engine_credentials._ads_token():
        enabled = [r for r in enabled if r != "ads"]
    fns = {
        "ads": _engine_registry_clients._ads_search,
        "arxiv": _engine_registry_clients._arxiv_search,
        "crossref": _engine_registry_clients._crossref_search,
        "openalex": _engine_registry_clients._openalex_search,
        "inspire": _engine_registry_clients._inspire_search,
        "github": _engine_registry_clients._github_search,
        "semanticscholar": _engine_registry_clients._semanticscholar_search,
        "pubmed": _engine_registry_clients._pubmed_search,
        "dblp": _engine_registry_clients._dblp_search,
    }
    kwargs = dict(title=title, author=author, words=words or None, year=year)

    def run(name):
        try:
            budget = _engine_budgets._request_budget.get()
            if budget is not None:
                budget.reserve("search")
            return name, fns[name](**kwargs), None
        except Exception as exc:  # one registry down must not sink the search
            return name, [], f"{type(exc).__name__}: {exc}"

    records, errors = [], {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        for name, recs, err in _engine_budgets._context_map(
            ex, run, [r for r in enabled if r in fns]
        ):
            records += recs
            if err:
                errors[name] = err
    records.sort(key=lambda r: -_engine_resolution._AUTHORITY.get(r["registry"], 0))
    scored = []
    discoveries = [record for record in records if record.get("discovery_only")]
    established = [
        record for record in records if not record.get("discovery_only")
    ]
    for c in _merge_candidates(established):
        d = _score_candidate(c, title, author, initial, year, words)
        d["confidence"] = _confidence(d, title, author, year)
        pub = _engine_resolution._public(c, "", "search")
        for k in ("resolved", "input", "kind"):
            pub.pop(k, None)
        scored.append(dict(pub, **d))
        _engine_persistence._record_cache_put(c)  # fetch_bibtex / fetch_text reuse it by id
    for candidate in discoveries:
        details = _score_candidate(
            candidate, title, author, initial, year, words
        )
        details["confidence"] = _confidence(details, title, author, year)
        aliases = candidate["suggested_ids"]
        scored.append(
            dict(
                id=candidate["discovery_id"],
                ids={},
                title=candidate["title"],
                authors=candidate["authors"][:12],
                n_authors=len(candidate["authors"]),
                year=candidate["year"],
                venue=candidate["venue"],
                type=candidate["type"],
                registries=[candidate["registry"]],
                url=candidate["url"],
                has_abstract=False,
                discovery_only=True,
                verification_status="unverified",
                suggested_ids=aliases,
                provenance=candidate["provenance"],
                next_action=(
                    "Resolve a suggested_id independently, compare its "
                    "metadata with this candidate, then obtain an official "
                    "export and assess claim support."
                    if aliases
                    else "No official identifier is supplied. Search official "
                    "registries; establish identity before export or support."
                ),
                **details,
            )
        )
    scored.sort(key=lambda x: -x["score"])
    return {
        "query": {
            "title": title,
            "author": author,
            "initial": initial,
            "year": year,
            "words": words,
            "hint": hint,
        },
        "registries": enabled,
        "errors": errors,
        "n_candidates": len(scored),
        "candidates": scored[:max_results],
        "note": (
            "Ranked by cite-check scoring; confirm the candidate through "
            "independent identity checks and official export. Discovery-only "
            "rows require resolving suggested_ids and comparing metadata; "
            "their native id is not an export identifier. "
            "Search never verifies support."
        ),
    }
