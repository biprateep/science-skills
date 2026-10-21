"""Work resolution, identity merging and immutable version pinning."""

import concurrent.futures
import re
import typing
import urllib.error
import urllib.parse
import urllib.request
from cite_check_engine import models as _engine_models
from cite_check_engine import budgets as _engine_budgets
from cite_check_engine import config as _engine_config
from cite_check_engine import credentials as _engine_credentials
from cite_check_engine import identifiers as _engine_identifiers
from cite_check_engine import persistence as _engine_persistence
from cite_check_engine import registry_clients as _engine_registry_clients


_AUTHORITY = {"ads": 5, "crossref": 4, "datacite": 4, "inspire": 3, "github": 2, "openalex": 2, "arxiv": 1}

_ID_KEYS = ("doi", "arxiv", "bibcode", "openalex", "inspire", "github")

def _merge_records(
    base: typing.Mapping[str, typing.Any],
    extra: typing.Mapping[str, typing.Any]
) -> _engine_models.Work:
    """Fill what `base` lacks from `extra`; base keeps its title and authors."""
    out = dict(base)
    for k in _ID_KEYS + ("venue", "year", "abstract", "citation_count", "type", "url"):
        if not out.get(k) and extra.get(k):
            out[k] = extra[k]
    if not out.get("title") and extra.get("title"):
        out["title"], out["authors"] = extra["title"], extra.get("authors", [])
    if len(extra.get("abstract") or "") > len(out.get("abstract") or "") + 200:
        out["abstract"] = extra["abstract"]
    out["pdf_urls"] = list(dict.fromkeys((out.get("pdf_urls") or []) + (extra.get("pdf_urls") or [])))
    regs = set(out.get("registries") or [out["registry"]]) | set(extra.get("registries") or [extra["registry"]])
    out["registries"] = sorted(regs, key=lambda r: -_AUTHORITY.get(r, 0))
    return typing.cast(_engine_models.Work, out)

def _public(rec: typing.Mapping[str, typing.Any], raw: str, kind: str) -> dict:
    out = _public_core(rec, raw, kind)
    if rec.get("repo"):
        out["repo"] = rec["repo"]
    return out

def _public_core(rec: typing.Mapping[str, typing.Any], raw: str, kind: str) -> dict:
    return {"resolved": True, "input": raw, "kind": kind, "id": _engine_identifiers._canonical(rec),
            "ids": {k: rec[k] for k in _ID_KEYS if rec.get(k)},
            "title": rec.get("title", ""), "authors": (rec.get("authors") or [])[:12],
            "n_authors": len(rec.get("authors") or []), "year": rec.get("year"),
            "venue": rec.get("venue", ""), "type": rec.get("type", ""),
            "registries": rec.get("registries") or [rec.get("registry")],
            "url": rec.get("url", ""), "has_abstract": bool(rec.get("abstract"))}

def _resolve_many(identifiers: list) -> list:
    """Batched resolution of mixed identifiers; results in input order.
    arXiv ids go out in one id_list call, DOIs/OpenAlex/INSPIRE in a small
    thread pool, and ADS (when a token exists) enriches everything in one
    batch so records gain bibcodes and DOI↔arXiv cross-links."""
    kinds = [_engine_identifiers._classify(i) for i in identifiers]
    arxiv_ids = sorted({v for k, v in kinds if k == "arxiv"})
    dois = sorted({v for k, v in kinds if k == "doi"})
    bibcodes = sorted({v for k, v in kinds if k == "bibcode"})
    others = sorted({(k, v) for k, v in kinds if k in ("openalex", "inspire")})
    repos = sorted({v for k, v in kinds if k == "github"})

    try:
        arxiv_found = _engine_registry_clients._arxiv_lookup(arxiv_ids) if arxiv_ids else {}
    except RuntimeError as exc:
        arxiv_found = {identifier.lower(): {
            "error": str(exc), "outcome": getattr(exc, "outcome", "unavailable")
        } for identifier in arxiv_ids}

    def by_doi(identifier):
        errors = []
        for lookup in (_engine_registry_clients._crossref_work, _engine_registry_clients._datacite_doi):
            try:
                record = lookup(identifier)
                if record:
                    return identifier, record
            except RuntimeError as exc:
                errors.append(exc)
        if errors:
            return identifier, {
                "error": "; ".join(str(error) for error in errors),
                "outcome": getattr(errors[0], "outcome", "unavailable"),
            }
        return identifier, None

    def by_other(kv):
        k, v = kv
        try:
            return kv, (_engine_registry_clients._openalex_get(v) if k == "openalex" else _engine_registry_clients._inspire_get("inspire", v))
        except RuntimeError as exc:
            return kv, {"error": str(exc)}

    def by_repo(v):
        try:
            return v, _engine_registry_clients._github_get(v)
        except RuntimeError as exc:
            return v, {"error": str(exc)}

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        doi_found = dict(_engine_budgets._context_map(ex, by_doi, dois))
        other_found = dict(_engine_budgets._context_map(ex, by_other, others))
        repo_found = dict(_engine_budgets._context_map(ex, by_repo, repos))

    ads, ads_error = {}, None
    if _engine_credentials._ads_token():
        try:
            ads.update(_engine_registry_clients._ads_lookup("arxiv", arxiv_ids))
            ads.update(_engine_registry_clients._ads_lookup("doi", dois))
            ads.update(_engine_registry_clients._ads_lookup("bibcode", bibcodes))
        except RuntimeError as exc:
            ads_error = str(exc)

    results = []
    for raw, (kind, value) in zip(identifiers, kinds):
        rec, reason = None, None
        if kind == "arxiv":
            rec = arxiv_found.get(value.lower())
            reason = "arXiv API returned no entry for this id"
        elif kind == "doi":
            rec = doi_found.get(value)
            reason = "DOI is not registered at Crossref or DataCite"
        elif kind == "bibcode":
            rec = ads.get(value.lower())
            reason = ads_error or ("bibcode not found in ADS" if _engine_credentials._ads_token() else
                                   "bibcode lookup needs an ADS API token (ADS_API_TOKEN or ~/.ads/dev_key)")
        elif kind in ("openalex", "inspire"):
            rec = other_found.get((kind, value))
            reason = f"{kind} returned no record for {value}"
        elif kind == "github":
            rec = repo_found.get(value)
            reason = (f"no public GitHub repository at github.com/{value} (deleted, private, or renamed "
                      "without a redirect)")
        else:
            reason = ("unrecognized identifier — expected an arXiv id, DOI (10.*), ADS bibcode, "
                      "OpenAlex Wnnn, inspire:nnn, or a GitHub repository (github.com/owner/repo)")
        failed = False
        outcome = rec.get("outcome") if isinstance(rec, dict) else "not-found"
        if isinstance(rec, dict) and rec.get("error"):
            reason, rec, failed = rec["error"], None, not rec.get("final")
        if not rec:
            results.append(dict({"resolved": False, "input": raw, "kind": kind, "reason": reason},
                                **({"lookup_error": True, "outcome": outcome or "unavailable"}
                                   if failed else {"outcome": "not-found"})))
            continue
        rec = dict(rec)
        rec.setdefault("registries", [rec["registry"]])
        for key in ((rec.get("arxiv"), rec.get("doi"), rec.get("bibcode")) if kind != "github" else ()):
            hit = ads.get((key or "").lower())
            if hit and hit is not rec:
                rec = _merge_records(rec, hit)
                break
        _engine_persistence._record_cache_put(rec)
        _engine_persistence._alias_put(kind, value, _engine_identifiers._canonical(rec))
        public_record = rec
        if kind == "arxiv" and re.search(_engine_identifiers._ARXIV_CORE + r"v\d+", raw, re.I):
            try:
                public_record = _with_pin(rec, raw, None)
            except (RuntimeError, ValueError) as exc:
                result = {"resolved": False, "input": raw, "kind": kind,
                          "reason": str(exc), "outcome": "not-found"}
                if isinstance(exc, RuntimeError):
                    result.update(lookup_error=True, outcome=getattr(
                        exc, "outcome", "unavailable"
                    ))
                results.append(result)
                continue
        pub = _public(public_record, raw, kind)
        if public_record.get("arxiv_version"):
            pub["requested_version"] = public_record["arxiv_version"]
        m = _engine_identifiers._GITHUB_REF.search(raw) if kind == "github" else None
        if m:
            try:
                pub["ref"] = _engine_registry_clients._github_ref(rec["repo"]["full_name"], urllib.parse.unquote(m.group(1)))
            except RuntimeError as exc:
                pub["ref"] = {"found": None, "ref": m.group(1), "error": str(exc)}
        results.append(pub)
    return results

def resolve_citation(identifier: str | list[str]) -> dict:
    """Resolve an identifier (or a list of them) to real bibliographic metadata.

    Accepts arXiv ids, DOIs, ADS bibcodes, OpenAlex W-ids, inspire:nnn, in bare,
    prefixed or URL form, and public GitHub repositories (github.com/owner/repo,
    github:owner/repo, git@github.com:owner/repo.git). resolved=false with a
    reason when the registry has no such record. A resolved result is
    existence only — verify_bib / search compare titles, authors and years to
    catch real ids attached to the wrong paper. A repository result carries
    `repo`: archived / fork / moved flags, its CITATION.cff, the paper its
    authors ask to be cited (`preferred_citation`), its software DOI, the
    identifiers its README mentions, and `ref` when the URL names a tag,
    branch or commit (checked to exist).
    """
    many = isinstance(identifier, list)
    if not isinstance(identifier, (str, list)):
        return {"resolved": False, "error": "identifier must be a string or list of strings"}
    idents = identifier if many else [identifier]
    if not idents or any(not isinstance(item, str) or not item.strip() for item in idents):
        return {"resolved": False, "error": "provide at least one nonempty identifier string"}
    try:
        res = _resolve_many(idents)
    except RuntimeError as exc:
        return {"error": f"registry lookup failed ({exc}) — retry, or mark the citation UNVERIFIED"}
    if many:
        return {"results": res, "resolved": all(r.get("resolved") for r in res), "n": len(res)}
    return res[0]

def _full_record(identifier: str) -> _engine_models.Work | None:
    """The internal record (with abstract and pdf urls) for an identifier —
    from the local record cache when it was resolved within the TTL (no
    network), else resolved now."""
    kind, value = _engine_identifiers._classify(str(identifier))
    cid = _engine_persistence._alias_get(kind, value) if kind != "unknown" else None
    rec = _engine_persistence._record_cache_get(cid, _engine_config.META_TTL) if cid else None
    if rec:
        return rec
    r = resolve_citation(identifier)
    if not r.get("resolved"):
        return None
    return _engine_persistence._record_cache_get(r["id"])

def _with_pin(
    rec: typing.Mapping[str, typing.Any], identifier: str, version: str | None
) -> _engine_models.Work:
    """Fetch software metadata at an immutable commit; retain arXiv version."""
    if rec.get("arxiv"):
        match = re.search(_engine_identifiers._ARXIV_CORE + r"v\d+", str(identifier), re.I)
        requested = version or (match.group(0) if match else None)
        if requested:
            if re.fullmatch(r"v[1-9]\d*", requested, re.I):
                requested = rec["arxiv"] + requested
            if (not re.fullmatch(_engine_identifiers._ARXIV_CORE + r"v[1-9]\d*", requested, re.I)
                    or _engine_identifiers._strip_arxiv_version(requested).lower() != rec["arxiv"].lower()):
                raise ValueError("arXiv version must name the work and a positive vN suffix")
            found = _engine_registry_clients._arxiv_lookup([requested])
            historical = found.get(requested.lower())
            if historical is None:
                if found:
                    raise _engine_registry_clients.RegistryLookupError("arxiv", "malformed-response", 200)
                raise ValueError(f"arXiv version does not exist: {requested}")
            actual = historical.get("arxiv_api_version")
            if not actual or actual.lower() != requested.lower():
                raise _engine_registry_clients.RegistryLookupError("arxiv", "malformed-response", 200)
            pinned = dict(historical, arxiv_version=actual)
            # Work aliases remain stable; title/abstract/authors are historical.
            for key in _ID_KEYS:
                if not pinned.get(key) and rec.get(key):
                    pinned[key] = rec[key]
            return typing.cast(_engine_models.Work, pinned)
    if not rec.get("github"):
        return typing.cast(_engine_models.Work, rec)
    match = _engine_identifiers._GITHUB_REF.search(str(identifier or ""))
    requested = version or (urllib.parse.unquote(match.group(1)) if match else None)
    repo = rec.get("repo") or {}
    full = repo.get("full_name") or rec["github"]
    ref = _engine_registry_clients._github_ref(full, requested or repo.get("default_branch") or "HEAD")
    if not ref.get("found"):
        raise ValueError(f"repository version does not exist: {requested}")
    pinned = _engine_registry_clients._github_get(full, ref=ref["sha"])
    if not pinned or pinned.get("error"):
        raise RuntimeError("cannot fetch pinned repository metadata")
    return typing.cast(_engine_models.Work, dict(
                pinned, pin=requested or ref["sha"], pinned_sha=ref["sha"],
                pinned_date=ref.get("date"),
                requested_version=requested or ref["sha"]))
