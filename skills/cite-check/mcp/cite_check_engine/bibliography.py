"""Official exports, bibliography transactions, verification and lint."""

import concurrent.futures
import dataclasses
from collections import Counter
import hashlib
import html
import os
import re
import typing
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
from cite_check_engine import models as _engine_models
from cite_check_engine import budgets as _engine_budgets
from cite_check_engine import credentials as _engine_credentials
from cite_check_engine import discovery as _engine_discovery
from cite_check_engine import identifiers as _engine_identifiers
from cite_check_engine import models as _engine_models
from cite_check_engine import parsing as _engine_parsing
from cite_check_engine import persistence as _engine_persistence
from cite_check_engine import registry_clients as _engine_registry_clients
from cite_check_engine import resolution as _engine_resolution
from cite_check_engine import text as _engine_text
from cite_check_engine import transport as _engine_transport


_DEFAULT_PREFER = ["ads", "crossref", "datacite", "inspire", "arxiv", "github"]

_MACRO_CLASSES = re.compile(r"\\documentclass(?:\[[^\]]*\])?\{(?:aastex\w*|aasjournal\w*|mnras|emulateapj|apj\w*|aa)\}")

def _journal_format_for(tex_path: str | None) -> int:
    """ADS journal macros (\\apj, \\mnras) compile only where the class defines
    them; everywhere else ask ADS for journal abbreviations instead."""
    if not tex_path or not os.path.exists(tex_path):
        return 2
    with open(tex_path, errors="replace") as fh:
        return 1 if _MACRO_CLASSES.search(fh.read(6000)) else 2

def _official_bibtex(rec: _engine_models.Work, prefer=None, journal_format: int = 2, max_author: int = 10) -> dict:
    """BibTeX from a registry's own export, in `prefer` order. Never
    synthesised — the one exception is a GitHub repository with no DOI
    export, laid out field for field by _github_bibtex from its authors'
    CITATION.cff or its GitHub record."""
    tried = []
    order = prefer or _DEFAULT_PREFER
    if rec.get("arxiv_version"):
        order = ["arxiv"]
    if rec.get("github") and rec.get("pin"):
        order = ["github"]          # a DOI export would cite the latest version, not the one asked for
    for src in order:
        bib, label = None, src
        try:
            if src == "ads":
                if not _engine_credentials._ads_token():
                    tried.append("ads: no API token")
                    continue
                bibcode = rec.get("bibcode")
                if not bibcode:
                    for kind, val in (("doi", rec.get("doi")), ("arxiv", rec.get("arxiv"))):
                        hit = _engine_registry_clients._ads_lookup(kind, [val]).get(val.lower()) if val else None
                        if hit:
                            bibcode = rec["bibcode"] = hit["bibcode"]
                            break
                if not bibcode:
                    tried.append("ads: record not indexed")
                    continue
                bib = _engine_registry_clients._ads_export([bibcode], journal_format, max_author).get(bibcode)
            elif src == "crossref" and rec.get("doi"):
                status, body = _engine_transport._http(f"{_engine_registry_clients._CROSSREF}/{urllib.parse.quote(typing.cast(str, rec['doi']), safe='')}"
                                     "/transform/application/x-bibtex")
                bib = body if status == 200 and body.lstrip().startswith("@") else None
            elif src == "datacite" and rec.get("doi"):
                status, body = _engine_transport._http(f"https://api.datacite.org/dois/{urllib.parse.quote(typing.cast(str, rec['doi']), safe='')}",
                                     headers={"Accept": "application/x-bibtex"})
                bib = body if status == 200 and body.lstrip().startswith("@") else None
            elif src == "inspire":
                for kind, val in (("arxiv", rec.get("arxiv")), ("doi", rec.get("doi")), ("inspire", rec.get("inspire"))):
                    if not val:
                        continue
                    path = {"arxiv": "arxiv", "doi": "doi", "inspire": "literature"}[kind]
                    status, body = _engine_transport._http(f"{_engine_registry_clients._INSPIRE}/{path}/{urllib.parse.quote(val, safe='')}?format=bibtex")
                    if status == 200 and body.lstrip().startswith("@"):
                        bib = body
                        break
            elif src == "arxiv" and rec.get("arxiv"):
                status, body = _engine_transport._http(f"https://arxiv.org/bibtex/{rec.get('arxiv_version') or rec['arxiv']}")
                bib = body if status == 200 and body.lstrip().startswith("@") else None
            elif src == "github" and rec.get("github"):
                bib, label = _engine_registry_clients._github_bibtex(rec)
            else:
                continue
        except RuntimeError as exc:
            tried.append(f"{src}: {exc}")
            continue
        if not bib:
            tried.append(f"{src}: version '{rec['pin']}' is not a tag, branch or commit of {rec['github']}"
                         if src == "github" and rec.get("pin") else f"{src}: no export")
            continue
        parsed = _engine_parsing._parse_bib(bib)["entries"]
        if not parsed:
            tried.append(f"{src}: unparsable export")
            continue
        entry = parsed[0]
        if rec.get("arxiv_version") and _engine_parsing._entry_arxiv_version(entry) != rec["arxiv_version"]:
            tried.append(
                f"{src}: official export omits the requested version "
                f"{rec['arxiv_version']} — refusing to drop the pin"
            )
            continue
        sim = _engine_text._title_sim(rec.get("title", ""), entry["fields"].get("title", ""))
        if rec.get("title") and entry["fields"].get("title") and sim < 0.6 and not (
                rec.get("github") and _names_repo(entry["fields"]["title"], typing.cast(str, rec["github"]))):
            tried.append(f"{src}: export title mismatch ({sim})")
            continue
        return {"bibtex": _sanitize_bibtex(entry, rec), "source": label, "title_similarity": sim, "tried": tried}
    return {"bibtex": None, "source": None, "tried": tried}

_MONTHS = {"jan": "jan", "january": "jan", "feb": "feb", "february": "feb", "mar": "mar", "march": "mar",
           "apr": "apr", "april": "apr", "may": "may", "jun": "jun", "june": "jun", "jul": "jul", "july": "jul",
           "aug": "aug", "august": "aug", "sep": "sep", "sept": "sep", "september": "sep", "oct": "oct",
           "october": "oct", "nov": "nov", "november": "nov", "dec": "dec", "december": "dec"}

def _sanitize_bibtex(entry: dict, rec: typing.Mapping[str, typing.Any]) -> str:
    """Encoding repairs on a registry export, then a canonical layout. Crossref
    ships HTML entities and tags, line-wrapped values, month=Sept, and drops
    collaboration authors ('author = { and Ade, …}'); the missing name is put
    back from the same registry's JSON record. No content is invented."""
    fields = {}
    for k, v in entry["fields"].items():
        v = html.unescape(re.sub(r"<[^>]+>", "", v))
        v = re.sub(r"(?<!\\)&", r"\\&", v)
        fields[k] = re.sub(r"\s+", " ", v).strip()
    author = fields.get("author", "")
    if rec.get("authors") and (not author or re.match(r"^\s*and\b", author, re.I)):
        first = re.sub(r"[{}]", "", rec["authors"][0])
        fields["author"] = ("{%s}" % first) + (" " + author.strip() if author.strip() else "")
    if fields.get("month"):
        m = _MONTHS.get(re.sub(r"[^a-z]", "", fields["month"].lower()))
        if m:
            fields["month"] = m
        else:
            fields.pop("month")
    width = max(len(k) for k in fields) if fields else 0
    lines = [f"@{entry['type'].upper()}{{{entry['key']},"]
    for k, v in fields.items():
        val = v if k == "month" else "{" + v + "}"
        lines.append(f"{k:>{width + 6}} = {val},")
    lines[-1] = lines[-1].rstrip(",")
    return "\n".join(lines) + "\n}"

def _rewrite_key(bibtex: str, key: str) -> str:
    return re.sub(r"^(\s*@\w+\s*[{(]\s*)[^,\s]*(\s*,)", lambda m: m.group(1) + key + m.group(2), bibtex, count=1)

def _prov_comment(rec: typing.Mapping[str, typing.Any], source: str) -> str:
    title = re.sub(r"[{}@\n\"]", " ", rec.get("title", ""))[:100].strip()
    pin = f"; version={rec['pin']}" if rec.get("github") and rec.get("pin") else ""
    if rec.get("pinned_sha"):
        pin += f"; commit={rec['pinned_sha']}"
    body = f'cite-check: source={source}; id={_engine_identifiers._canonical(rec)}{pin}; fetched={_engine_persistence._today()}; title="{title}"'
    return "@comment{" + body.replace("@", "(at)") + "}"

def _default_key(rec: typing.Mapping[str, typing.Any], existing: set) -> str:
    fam = re.sub(r"[^a-z]", "", _engine_text._surname(rec["authors"][0]) if rec.get("authors") else "") or "anon"
    base = f"{fam.capitalize()}{rec.get('year') or ''}"
    key, n = base, 0
    while key in existing:
        n += 1
        key = base + ("abcdefghijklmnopqrstuvwxyz"[n - 1] if n <= 26 else str(n))
    return key

def fetch_bibtex(identifier: str, key: str | None = None, prefer: list[str] | None = None,
                 journal_format: int | None = None, tex_path: str | None = None,
                 max_author: int = 10, version: str | None = None) -> dict:
    """Official BibTeX for one identifier, from ADS / Crossref / DataCite /
    INSPIRE / arXiv (first that has it, in `prefer` order); a GitHub repository
    with no DOI export gets an @software entry laid out from its CITATION.cff
    (source citation-cff) or its GitHub record with the release or commit
    pinned (source github). `version` (or a /tree/<ref> URL) pins the tag,
    branch or commit that was used; it must exist. `key` renames the entry. journal_format (ADS): 1 macros, 2 abbreviations, 3 full names —
    auto-detected from tex_path's documentclass when omitted. bibtex=null means
    no registry exports one: do not hand-write it.
    """
    rec = _engine_resolution._full_record(identifier)
    if rec is None:
        r = _engine_resolution.resolve_citation(identifier)
        return {"bibtex": None, "resolved": False, "reason": r.get("reason") or r.get("error")}
    try:
        rec = _engine_resolution._with_pin(rec, identifier, version)
    except (RuntimeError, ValueError) as exc:
        return {"bibtex": None, "resolved": False, "reason": str(exc),
                "lookup_error": isinstance(exc, RuntimeError)}
    jf = int(journal_format) if journal_format else _journal_format_for(tex_path)
    got = _official_bibtex(rec, prefer, jf, max_author)
    if not got["bibtex"]:
        return {"bibtex": None, "resolved": True, "id": _engine_identifiers._canonical(rec), "tried": got["tried"],
                "reason": ("no registry offers a BibTeX export for this record — do not hand-write "
                           "one; cite a version that has a DOI or arXiv id, or record the gap")}
    bib = _rewrite_key(got["bibtex"], key) if key else got["bibtex"]
    return dict({"bibtex": bib, "key": _engine_parsing._parse_bib(bib)["entries"][0]["key"], "source": got["source"],
                 "id": _engine_identifiers._canonical(rec), "ids": {k: typing.cast(typing.Mapping[str, typing.Any], rec)[k] for k in _engine_resolution._ID_KEYS if rec.get(k)},
                 "title": rec["title"], "provenance": _prov_comment(rec, got["source"]), "tried": got["tried"]},
                **_repo_advice(rec))

def _repo_advice(rec: typing.Mapping[str, typing.Any]) -> dict:
    """For a repository: what its record says the writer should know."""
    repo = rec.get("repo") or {}
    out = {}
    if repo.get("notes"):
        out["repo_notes"] = repo["notes"]
    pc = repo.get("preferred_citation")
    if pc and pc.get("ids"):
        out["preferred_citation"] = next(iter(pc["ids"].values()))
    elif repo.get("readme_ids"):
        out["readme_ids"] = repo["readme_ids"]
        out.setdefault("repo_notes", []).append(
            "no CITATION file; the README links these identifiers — if one is the paper the authors ask "
            "to be cited, resolve and add it too")
    return out

@_engine_persistence._serialized_bibliography
def bib_add(bib_path: str, items: list[_engine_models.BibliographyItem | str], prefer: list[str] | None = None, journal_format: int | None = None,
            tex_path: str | None = None, replace: bool = False, max_author: int = 10) -> dict:
    """Add official entries to a .bib. items: [{"identifier": …, "key": …}] (key
    optional → Surname2017; "version" pins a GitHub repository's tag, branch
    or commit). Each entry is written with a provenance comment.
    Duplicates (same DOI/arXiv/bibcode already present) are reported, not
    added; an existing key is left alone unless replace=true, which swaps a
    hand-written entry for the official one under the same key.
    """
    bib_path = os.path.realpath(bib_path)
    text = ""
    if os.path.exists(bib_path):
        with open(bib_path, errors="replace") as fh:
            text = fh.read()
    if isinstance(items, (str, dict)):
        items = [items]
    if not isinstance(items, list) or not items:
        return {"ok": False, "error": "items must be a nonempty list", "results": []}
    items = [dataclasses.asdict(item) if isinstance(item, _engine_models.BibliographyItem) else item
             for item in items]
    parsed = _engine_parsing._parse_bib(text)
    if not parsed["complete"]:
        return {"ok": False, "error": "; ".join(parsed["errors"]), "results": []}
    requested = set()
    for item in items:
        if not isinstance(item, (str, dict)):
            return {"ok": False, "error": "items must be identifiers or objects", "results": []}
        if isinstance(item, dict):
            identifier = item.get("identifier") or item.get("id")
            if not isinstance(identifier, str) or not identifier.strip():
                return {"ok": False, "error": "each item needs an identifier string", "results": []}
            if item.get("version") is not None and not isinstance(item["version"], str):
                return {"ok": False, "error": "version must be a string", "results": []}
        elif not item.strip():
            return {"ok": False, "error": "empty identifier", "results": []}
        key = item.get("key") if isinstance(item, dict) else None
        if key is not None:
            if not isinstance(key, str) or not key or re.search(r"[\s,{}()=]", key):
                return {"ok": False, "error": "invalid bibliography key", "results": []}
            if key in requested:
                return {"ok": False, "error": f"duplicate key in batch: {key}", "results": []}
            requested.add(key)
    by_id = {}
    for e in parsed["entries"]:
        ids = _engine_parsing._entry_ids(e)
        if any(ids.get(k) for k in ("doi", "arxiv", "bibcode")):
            ids.pop("github", None)       # a paper that links its code is not the code
        for k, v in ids.items():
            by_id.setdefault(f"{k}:{v.lower()}", e["key"])
    jf = int(journal_format) if journal_format else _journal_format_for(tex_path)
    results, additions, replacements = [], [], {}
    taken = set(parsed["keys"])
    for item in items:
        if isinstance(item, str):
            item = {"identifier": item}
        ident, want = item.get("identifier") or item.get("id"), item.get("key")
        rec = _engine_resolution._full_record(ident) if ident else None
        if rec is None:
            results.append({"identifier": ident, "key": want, "status": "unresolved"})
            continue
        try:
            rec = _engine_resolution._with_pin(rec, ident, item.get("version"))
        except (RuntimeError, ValueError) as exc:
            results.append({"identifier": ident, "key": want,
                            "status": "unresolved", "note": str(exc)})
            continue
        dup = next((by_id[f"{k}:{typing.cast(typing.Mapping[str, typing.Any], rec)[k].lower()}"] for k in ("doi", "arxiv", "bibcode", "github")
                    if rec.get(k) and f"{k}:{typing.cast(typing.Mapping[str, typing.Any], rec)[k].lower()}" in by_id), None)
        if dup and dup != want and not replace:
            results.append({"identifier": ident, "key": want, "status": "duplicate", "existing_key": dup,
                            "note": f"already in the .bib as {dup} — cite that key"})
            continue
        key = want or dup or _default_key(rec, taken)
        if key in taken and key not in parsed["keys"]:
            results.append({"identifier": ident, "key": key, "status": "key-conflict",
                            "note": "key already reserved by this batch"})
            continue
        if key in parsed["keys"] and not replace:
            have = _engine_parsing._entry_ids(parsed["keys"][key])
            same = any(have.get(k) and rec.get(k) and have[k].lower() == typing.cast(typing.Mapping[str, typing.Any], rec)[k].lower() for k in ("doi", "arxiv", "bibcode", "github"))
            results.append({"identifier": ident, "key": key, "status": "exists" if same else "key-conflict",
                            "note": None if same else f"key {key} already holds a different work; pick another key or replace=true"})
            continue
        got = _official_bibtex(rec, prefer, jf, max_author)
        if not got["bibtex"]:
            results.append({"identifier": ident, "key": key, "status": "no-official-bibtex", "tried": got["tried"]})
            continue
        block = _prov_comment(rec, got["source"]) + "\n" + _rewrite_key(got["bibtex"], key).strip() + "\n"
        status = "replaced" if key in parsed["keys"] else "added"
        (replacements.__setitem__(key, block) if status == "replaced" else additions.append((key, block)))
        taken.add(key)
        for k in ("doi", "arxiv", "bibcode", "github"):
            if rec.get(k):
                by_id[f"{k}:{typing.cast(typing.Mapping[str, typing.Any], rec)[k].lower()}"] = key
        results.append(dict({"identifier": ident, "key": key, "status": status, "source": got["source"],
                             "id": _engine_identifiers._canonical(rec), "title": rec["title"]}, **_repo_advice(rec)))
    accepted = {"added", "replaced", "exists", "duplicate"}
    if any(result["status"] not in accepted for result in results):
        for result in results:
            if result["status"] in {"added", "replaced"}:
                result["status"] = "aborted"
        return {"bib": bib_path, "ok": False, "results": results,
                "error": "batch validation failed; bibliography unchanged"}
    if replacements or additions:
        new = text
        for e in sorted(parsed["entries"], key=lambda e: -e["start"]):
            if e["key"] not in replacements:
                continue
            start = e["start"]
            prev = [c for c in parsed["comments"] if c["cite_check"] and c["end"] <= start
                    and not text[c["end"]:start].strip()]
            if prev:
                start = prev[-1]["start"]
            new = new[:start] + replacements[e["key"]] + new[e["end"]:]
        if additions:
            new = new.rstrip("\n") + ("\n\n" if new.strip() else "") + "\n".join(b for _, b in additions)
        _engine_persistence._atomic_write(bib_path, new)
    return {"bib": bib_path, "results": results,
            "ok": all(r["status"] in ("added", "replaced", "exists", "duplicate") for r in results)}

_OK_STATUS = {"VERIFIED", "FOUND"}

def _compare_arxiv_version(entry: dict, pub: dict, version: str) -> dict:
    """Compare against the exact arXiv edition, never the latest metadata."""
    record = dict(pub["ids"])
    record.setdefault("arxiv", _engine_parsing._entry_ids(entry).get("arxiv"))
    try:
        historical = _engine_resolution._with_pin(record, "arxiv:" + version, version)
    except (RuntimeError, ValueError) as exc:
        return {
            "key": entry["key"],
            "status": "UNRESOLVED" if isinstance(exc, RuntimeError) else "NOT_FOUND",
            "via": "arxiv:" + version, "id": pub["id"], "ids": pub["ids"],
            "notes": [str(exc)], "provenance": entry["provenance"],
        }
    result = _compare(
        entry, _engine_resolution._public(historical, "arxiv:" + version, "arxiv"),
        "arxiv:" + version,
    )
    result["arxiv_version"] = historical["arxiv_version"]
    return result

def _compare(entry: dict, pub: dict, via: str) -> dict:
    """Entry fields vs the registry record: the actual existence test."""
    f = entry["fields"]
    title, authors, year = f.get("title", ""), _engine_text._split_bib_authors(f.get("author", "")), _engine_registry_clients._year(f.get("year"))
    sim = _engine_text._title_sim(title, pub["title"]) if title else None
    am = _engine_text._author_match(authors, pub["authors"])
    yd = abs(year - pub["year"]) if year and pub.get("year") else None
    notes = []
    if sim is None:
        status = "PROBABLE"
        notes.append("entry has no title — the identifier resolves but nothing can be compared")
    elif sim >= 0.9:
        status = "VERIFIED"
        if am["first"] is False:
            status = "PROBABLE"
            notes.append(f"first author differs: bib '{authors[0]}' vs registry '{pub['authors'][0]}'")
        if yd is not None and yd > 2:
            status = "PROBABLE"
            notes.append(f"year differs by {yd} (bib {year}, registry {pub['year']})")
    elif sim >= 0.75:
        status = "PROBABLE" if am["first"] else "MISMATCH"
        notes.append(f"title similarity only {sim}: registry has '{pub['title'][:90]}'")
    else:
        status = "MISMATCH"
        notes.append(f"identifier resolves to a different paper: '{pub['title'][:90]}' (similarity {sim})")
    return {"key": entry["key"], "status": status, "via": via, "id": pub["id"], "ids": pub["ids"],
            "title_similarity": sim, "first_author_match": am["first"], "year_bib": year,
            "year_registry": pub.get("year"), "registry_title": pub["title"], "notes": notes,
            "provenance": entry["provenance"]}

def _names_repo(title: str, full: str) -> bool:
    """Does the title name the repository as a whole word run ('corner.py:
    Scatterplot matrices…' names dfm/corner.py)?"""
    name = _engine_text._norm_title(full.split("/")[-1])
    return len(name) >= 3 and f" {name} " in f" {_engine_text._norm_title(title)} "

def _compare_repo(entry: dict, pub: dict) -> dict:
    """Entry fields vs the GitHub repository its URL points at. The title must
    be the repository's own (CITATION.cff title, name, name and description,
    or a title that names it); an entry titled as the paper the repository
    asks to be cited is FOUND — that paper is what the entry should be. A
    cited version must exist as a tag, branch or commit."""
    requested = _engine_parsing._entry_ref(entry)
    if requested:
        try:
            raw = _engine_registry_clients._github_get(pub["ids"]["github"])
            if not raw or raw.get("error"):
                raise RuntimeError("repository unavailable")
            pinned = _engine_resolution._with_pin(raw, pub["id"], requested)
            pub = _engine_resolution._public(pinned, pub["id"], "github")
        except (RuntimeError, ValueError) as exc:
            return {"key": entry["key"], "status": "UNRESOLVED",
                    "via": pub["id"], "id": pub["id"], "ids": pub["ids"],
                    "notes": [f"cited version could not be checked: {exc}"],
                    "provenance": entry["provenance"]}
    f, repo = entry["fields"], pub.get("repo") or {}
    full = repo.get("full_name") or pub["ids"]["github"]
    title, authors, year = f.get("title", ""), _engine_text._split_bib_authors(f.get("author", "")), _engine_registry_clients._year(f.get("year"))
    name, desc = full.split("/")[1], repo.get("description") or ""
    own = [t for t in (pub["title"], name, full, desc, f"{name}: {desc}", f"{pub['title']}: {desc}") if t]
    sim = max(_engine_text._title_sim(title, t) for t in own) if title else None
    people = list(pub.get("authors") or []) + [x for x in (repo.get("owner_name"), repo.get("owner")) if x]
    am = _engine_text._author_match(authors, people)
    out = {"key": entry["key"], "via": f"github:{pub['ids']['github']}", "id": pub["id"], "ids": pub["ids"],
           "title_similarity": sim, "first_author_match": am["first"], "year_bib": year,
           "year_registry": pub.get("year"), "registry_title": pub["title"],
           "notes": list(repo.get("notes") or []), "provenance": entry["provenance"]}
    if sim is None:
        out["status"] = "PROBABLE"
        out["notes"].append("entry has no title — the repository exists but nothing can be compared")
    elif sim >= 0.9:
        out["status"] = "VERIFIED"
    else:
        paper = _repo_paper_match(title, repo)
        if paper:
            return dict(out, status=paper["status"], id=paper.get("id", out["id"]), ids=paper.get("ids", out["ids"]),
                        title_similarity=paper["similarity"], registry_title=paper["title"],
                        notes=[paper["note"]] + out["notes"])
        if _names_repo(title, full):
            out["status"] = "VERIFIED"
            out["notes"].append(f"title names the repository; its own title is '{pub['title'][:80]}'")
        elif sim >= 0.75:
            out["status"] = "PROBABLE"
            out["notes"].append(f"title similarity only {sim}: the repository is '{full}' — '{desc[:80]}'")
        else:
            out["status"] = "MISMATCH"
            out["notes"] = [f"the URL points at a different work: github.com/{full} — '{desc[:80]}' "
                                f"(similarity {sim})"]
            return out
    if am["first"] is False and am["any"] is False:
        out["status"] = "PROBABLE"
        out["notes"].append(f"authors differ: bib '{authors[0]}' vs repository '{people[0]}'")
    ref = _engine_parsing._entry_ref(entry)
    if ref:
        try:
            out["ref"] = _engine_registry_clients._github_ref(full, ref)
        except RuntimeError as exc:
            out["ref"] = {"found": None, "ref": ref}
            out["notes"].append(f"cited version '{ref}' not checked: {exc}")
        if out["ref"]["found"] is False:
            out["status"] = "PROBABLE"
            out["notes"].append(f"cited version '{ref}' is not a tag, branch or commit of {full}")
    return out

def _repo_paper_match(title: str, repo: dict) -> dict | None:
    """Is an entry pointing at a repository really the paper that repository
    asks to be cited (CITATION.cff / CITATION.bib) or links from its README?"""
    pc = repo.get("preferred_citation") or {}
    declared = [("doi:" if k == "doi" else "arXiv:") + v for k, v in (pc.get("ids") or {}).items()]
    candidates = list(dict.fromkeys(declared + list(repo.get("readme_ids") or [])[:6]))
    try:
        resolved = _engine_resolution._resolve_many(candidates) if candidates else []
    except RuntimeError:
        resolved = []
    for r in resolved:
        if r.get("resolved"):
            s = _engine_text._title_sim(title, r["title"])
            if s >= 0.9:
                where = pc.get("source") if r["input"] in declared else "linked from the README"
                return {"status": "FOUND", "id": r["id"], "ids": r["ids"], "similarity": s, "title": r["title"],
                        "note": f"entry is the paper '{r['title'][:80]}' ({where}), not the repository — replace "
                                f"it with the official entry: bib_add(items=[{{'identifier': '{r['id']}', "
                                "'key': …}], replace=true)"}
    if pc.get("title") and _engine_text._title_sim(title, pc["title"]) >= 0.9:
        return {"status": "PROBABLE", "similarity": _engine_text._title_sim(title, pc["title"]), "title": pc["title"],
                "note": f"entry is the paper the repository asks to be cited ({pc.get('source')}), which declares "
                        f"no DOI or arXiv id — find it with search_citation(title='{pc['title'][:80]}')"}
    return None

def _search_entry(entry: dict) -> dict:
    f = entry["fields"]
    title, authors, year = f.get("title", ""), _engine_text._split_bib_authors(f.get("author", "")), _engine_registry_clients._year(f.get("year"))
    base = {"key": entry["key"], "via": "search", "provenance": entry["provenance"], "year_bib": year}
    if not title:
        return dict(base, status="UNRESOLVED", notes=["no identifier and no title — nothing to look up"])
    s = _engine_discovery.search_citation(title=title, author=_engine_text._surname(authors[0]) if authors else None, year=year, max_results=3)
    cands = s.get("candidates") or []
    if cands and cands[0]["confidence"] == "high":
        c = cands[0]
        return dict(base, status="FOUND", id=c["id"], ids=c["ids"], title_similarity=c.get("title_similarity"),
                    first_author_match=c.get("first_author_match"), year_registry=c.get("year"),
                    registry_title=c["title"],
                    notes=["entry carries no identifier; matched by search — replace it with the official "
                           f"entry: bib_add(items=[{{'identifier': '{c['id']}', 'key': '{entry['key']}'}}], replace=true)"])
    if cands and cands[0]["confidence"] == "medium":
        c = cands[0]
        return dict(base, status="PROBABLE", id=c["id"], ids=c["ids"], title_similarity=c.get("title_similarity"),
                    first_author_match=c.get("first_author_match"), year_registry=c.get("year"),
                    registry_title=c["title"],
                    notes=[f"closest registry match: '{c['title'][:90]}' ({c['id']}, similarity "
                           f"{c.get('title_similarity')}) — confirm by eye, then bib_add(replace=true)"])
    closest = f"; closest: '{cands[0]['title'][:70]}' ({cands[0].get('title_similarity')})" if cands else ""
    return dict(base, status="UNRESOLVED", notes=[f"no registry match for title '{title[:90]}'{closest}"])

_LINT_MAX_BYTES = 4 * 1024 * 1024

_LINT_MAX_ENTRIES = 2000

_LINT_CREATOR = ("author", "editor", "organization", "institution")

_LINT_DATE = ("year", "date")

_LINT_RULES = {
    "article": [
        ("title",),
        _LINT_CREATOR,
        _LINT_DATE,
        ("journal", "journaltitle"),
    ],
    "book": [("title",), _LINT_CREATOR, _LINT_DATE, ("publisher",)],
    "collection": [("title",), _LINT_CREATOR, _LINT_DATE, ("publisher",)],
    "inbook": [("title",), _LINT_CREATOR, _LINT_DATE, ("booktitle",)],
    "incollection": [("title",), _LINT_CREATOR, _LINT_DATE, ("booktitle",)],
    "inproceedings": [("title",), _LINT_CREATOR, _LINT_DATE, ("booktitle",)],
    "conference": [("title",), _LINT_CREATOR, _LINT_DATE, ("booktitle",)],
    "proceedings": [("title",), _LINT_DATE],
    "report": [
        ("title",),
        _LINT_CREATOR,
        _LINT_DATE,
        ("institution", "organization"),
    ],
    "techreport": [
        ("title",),
        _LINT_CREATOR,
        _LINT_DATE,
        ("institution", "organization"),
    ],
    "thesis": [
        ("title",),
        _LINT_CREATOR,
        _LINT_DATE,
        ("institution", "school"),
    ],
    "phdthesis": [
        ("title",),
        _LINT_CREATOR,
        _LINT_DATE,
        ("institution", "school"),
    ],
    "mastersthesis": [
        ("title",),
        _LINT_CREATOR,
        _LINT_DATE,
        ("institution", "school"),
    ],
    **{
        kind: [("title",), ("url", "doi", "repository", "howpublished")]
        for kind in (
            "software",
            "softwareversion",
            "softwaremodule",
            "codefragment",
            "dataset",
            "online",
            "electronic",
            "www",
        )
    },
    **{kind: [] for kind in ("misc", "manual", "unpublished", "xdata", "set")},
}

def _lint_deferred_fields(entry: dict[str, Any]) -> set[str]:
    """Identify unexpanded top-level field expressions in parsed input."""
    raw = entry["raw"]
    body = raw[raw.index(",") + 1 : -1] if "," in raw else ""
    deferred: set[str] = set()
    position = 0
    while match := _engine_parsing._FIELD_START.match(body, position):
        name, position = match.group(1).lower(), match.end()
        while position < len(body):
            while position < len(body) and body[position].isspace():
                position += 1
            start = position
            if body[position] == "{":
                position = _engine_parsing._find_close(body, position) + 1
            elif body[position] == '"':
                position += 1
                depth = 0
                while position < len(body):
                    character = body[position]
                    if character == "{":
                        depth += 1
                    elif character == "}":
                        depth -= 1
                    elif character == '"' and depth == 0:
                        position += 1
                        break
                    position += 1
            else:
                token = _engine_parsing._BARE.match(body, position)
                if token is None:
                    break  # The parser rejects this before linting.
                position = token.end()
                if not token.group().isdigit():
                    deferred.add(name)
            if re.search(r"\\[A-Za-z]+", body[start:position]):
                deferred.add(name)
            while position < len(body) and body[position].isspace():
                position += 1
            if position < len(body) and body[position] == "#":
                deferred.add(name)
                position += 1
                continue
            break
        position += 1  # Comma already validated by the parser.
    return deferred

def _lint_entry_ids(entry: dict[str, Any]) -> dict[str, str]:
    """Read literal work locators, excluding free-text notes and macros."""
    deferred = _lint_deferred_fields(entry)
    fields = {
        name: value
        for name, value in entry["fields"].items()
        if name not in deferred and name != "note"
    }
    return _engine_parsing._entry_ids(dict(entry, fields=fields))

def _lint_year(value: str, field: str) -> int | None:
    """Extract a supported literal year, deferring legitimate date statuses."""
    if value.lower() in {"forthcoming", "in press", "n.d.", "undated"}:
        return None
    pattern = (
        r"\d{4}(?:-\d{2}(?:-\d{2})?)?(?:[?~%]|/"
        r"(?:\d{4}(?:-\d{2}(?:-\d{2})?)?|\.\.))?"
    )
    if re.fullmatch(pattern if field == "date" else r"\d{4}", value):
        return int(value[:4])
    raise ValueError("not a supported literal year/date")

def _lint_local_issues(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Return conservative style advice, without resolving inherited data."""
    fields = entry["fields"]
    deferred = _lint_deferred_fields(entry)
    issues: list[dict[str, Any]] = []

    def add(code: str, field: str, message: str, action: str) -> None:
        issues.append(
            dict(code=code, field=field, message=message, action=action)
        )

    kind = entry["type"]
    if kind not in _LINT_RULES:
        add(
            "unknown-entry-type",
            "entrytype",
            f"No metadata rules are defined for @{kind}.",
            "Check that the selected bibliography style supports this type.",
        )
    inherited = bool(fields.get("crossref") or fields.get("xdata"))
    if inherited:
        add(
            "inheritance-not-expanded",
            "crossref" if fields.get("crossref") else "xdata",
            "Inherited fields have not been expanded.",
            "Check the resolved bibliography with its intended processor.",
        )
    relevant = {
        "title",
        "year",
        "date",
        "author",
        "editor",
        "organization",
        "institution",
        "school",
        "journal",
        "journaltitle",
        "booktitle",
        "publisher",
        "doi",
        "url",
        "repository",
        "code",
        "howpublished",
        "eprint",
        "bibcode",
        "adsurl",
        "eid",
        "note",
    }
    for field in sorted(deferred & relevant):
        add(
            "field-macro-unexpanded",
            field,
            "A macro or concatenation prevents a literal metadata check.",
            "Check the expanded value with the intended bibliography style.",
        )
    preprint = bool(_lint_entry_ids(entry).get("arxiv"))
    if not inherited:
        for alternatives in _LINT_RULES.get(kind, []):
            if preprint and alternatives[0] == "journal":
                continue
            if not any(fields.get(name) for name in alternatives):
                add(
                    "missing-field",
                    alternatives[0],
                    "No value for " + " or ".join(alternatives) + ".",
                    "Check the official export and style requirements; "
                    "do not invent missing metadata.",
                )
    if kind not in {"xdata", "set"}:
        for field in _LINT_DATE:
            value = fields.get(field)
            if not value or field in deferred:
                continue
            try:
                year = _lint_year(value, field)
            except ValueError:
                add(
                    "invalid-year",
                    field,
                    f"The literal {field} is outside supported date syntax.",
                    "Check the official export and date syntax for the style.",
                )
                continue
            if year and year > int(_engine_persistence._today()[:4]):
                add(
                    "future-year",
                    field,
                    "The date is in the future; forthcoming work may be valid.",
                    "Confirm the release date in the source export.",
                )
    return issues

def _lint_record_valid(record: Any) -> bool:
    """Check provider shape before using it as comparison input."""
    return (
        isinstance(record, dict)
        and record.get("resolved") is True
        and isinstance(record.get("id"), str)
        and bool(record["id"])
        and _engine_identifiers._classify(record["id"])[0] != "unknown"
        and isinstance(record.get("registries", []), list)
        and all(
            isinstance(registry, str)
            for registry in record.get("registries", [])
        )
        and isinstance(record.get("ids"), dict)
        and all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in record["ids"].items()
        )
        and isinstance(record.get("title"), str)
        and isinstance(record.get("authors"), list)
        and all(isinstance(author, str) for author in record["authors"])
        and (record.get("year") is None or type(record["year"]) is int)
        and isinstance(record.get("venue", ""), str)
        and isinstance(record.get("type", ""), str)
    )

def _lint_compare_entries(
    entries: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Compare own-ID metadata without title searches or file changes."""
    plans: dict[str, list[str]] = {}
    outcomes: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for entry in entries:
        if entry["type"] in {"xdata", "set"}:
            outcomes.append(
                dict(key=entry["key"], status="not-applicable", identifiers=[])
            )
            continue
        ids = _lint_entry_ids(entry)
        # Incidental code links in paper citations do not identify the paper.
        if any(name in ids for name in ("doi", "arxiv", "bibcode")):
            ids.pop("github", None)
        pinned = _engine_parsing._entry_arxiv_version(entry) or (
            ids.get("github") and _engine_parsing._entry_ref(entry)
        )
        identifiers = [f"{name}:{value}" for name, value in ids.items()]
        status = (
            "pinned-version-skipped"
            if pinned
            else "pending"
            if identifiers
            else "no-identifier"
        )
        if status == "pending":
            plans[entry["key"]] = identifiers
        outcomes.append(
            dict(key=entry["key"], status=status, identifiers=identifiers)
        )
    requested = list(
        dict.fromkeys(value for values in plans.values() for value in values)
    )
    try:
        rows = _engine_resolution._resolve_many(requested) if requested else []
    except (RuntimeError, OSError, ValueError):
        rows = []
    records = {}
    if isinstance(rows, list):
        for row in rows:
            if (
                isinstance(row, dict)
                and isinstance(row.get("input"), str)
                and row["input"] in requested
            ):
                # Duplicate responses are ambiguous, not independent evidence.
                key = row["input"]
                records[key] = None if key in records else row
    for entry, outcome in zip(entries, outcomes):
        if outcome["status"] == "not-applicable":
            continue
        code = "registry-comparison-unavailable"
        message = "No usable own-identifier registry comparison is available."
        if outcome["status"] == "pinned-version-skipped":
            code = "registry-version-unchecked"
            message = "Pinned versions are not compared with latest metadata."
        elif outcome["status"] == "pending":
            outcome["status"] = "unavailable"
            confirmed = None
            for identifier in plans[entry["key"]]:
                record = records.get(identifier)
                if not isinstance(record, dict) or not _lint_record_valid(
                    record
                ):
                    continue
                aliases = {_engine_identifiers._classify(record["id"])} | {
                    _engine_identifiers._classify(f"{name}:{value}")
                    for name, value in record["ids"].items()
                }
                if _engine_identifiers._classify(identifier) not in aliases:
                    outcome["status"] = "identity-unconfirmed"
                    continue
                # Deferred expressions cannot establish metadata identity.
                deferred = _lint_deferred_fields(entry)
                if deferred & {"title", "author", "year", "date"}:
                    outcome["status"] = "identity-unconfirmed"
                    continue
                comparison_entry = entry
                if not entry["fields"].get("year"):
                    date = entry["fields"].get("date", "")
                    try:
                        date_year = _lint_year(date, "date") if date else None
                    except ValueError:
                        date_year = None
                    if date_year:
                        comparison_entry = dict(
                            entry,
                            fields=dict(entry["fields"], year=str(date_year)),
                        )
                comparison = _compare(comparison_entry, record, identifier)
                if comparison["status"] == "VERIFIED":
                    confirmed = record
                    break
                outcome["status"] = "identity-unconfirmed"
            if confirmed is not None:
                outcome["status"] = "compared"
                outcome["resolved_id"] = confirmed["id"]
                fields = entry["fields"]
                year = _engine_registry_clients._year(fields.get("year") or fields.get("date"))
                if year and confirmed.get("year") and year != confirmed["year"]:
                    issues.append(
                        dict(
                            key=entry["key"],
                            field="year",
                            code="registry-year-difference",
                            message="The same-work registry record has a "
                            "different year; print dates may differ.",
                            action="Review the intended version and official "
                            "export before changing the date.",
                            evidence=dict(
                                id=confirmed["id"], year=confirmed["year"]
                            ),
                        )
                    )
                ids = _lint_entry_ids(entry)
                if (
                    ids.get("arxiv")
                    and not ids.get("doi")
                    and confirmed["ids"].get("doi")
                    and confirmed.get("venue")
                    and (
                        confirmed.get("type")
                        in {
                            "journal-article",
                            "article",
                            "proceedings-article",
                            "conference-paper",
                            "book-chapter",
                        }
                        or "arxiv" in (confirmed.get("registries") or [])
                    )
                    and not re.search(
                        r"arxiv|preprint", confirmed["venue"], re.I
                    )
                ):
                    issues.append(
                        dict(
                            key=entry["key"],
                            field="entrytype",
                            code="preprint-publication-review",
                            message="The own-ID record explicitly links this "
                            "preprint to a DOI and publication venue.",
                            action="Review whether the preprint or published "
                            "version is intended; retain intentional versions.",
                            evidence=dict(
                                id=confirmed["id"],
                                ids=confirmed["ids"],
                                venue=confirmed["venue"],
                            ),
                        )
                    )
                continue
            if outcome["status"] == "identity-unconfirmed":
                code = "registry-identity-unconfirmed"
                message = (
                    "Metadata or identifier aliases do not confirm "
                    "that this is the same work."
                )
        issues.append(
            dict(
                key=entry["key"],
                field="identifier",
                code=code,
                message=message,
                action="Resolve the intended "
                "work and inspect its official export manually.",
            )
        )
    return dict(
        requested=True,
        identifiers_requested=requested,
        identifier_count=len(requested),
        comparable_entries=sum(
            row["status"] != "not-applicable" for row in outcomes
        ),
        compared_entries=sum(row["status"] == "compared" for row in outcomes),
        outcomes=outcomes,
    ), issues

def lint_bib(
    bib_path: str,
    keys: list[str] | None = None,
    verify: bool = False,
) -> dict[str, Any]:
    """Advise on bibliography metadata, independently of citation readiness.

    Args:
        bib_path: UTF-8 bibliography file, at most 4 MiB and 2000 entries.
        keys: Optional entry keys to inspect; omitted means every entry.
        verify: Compare own-ID registry metadata using normal resolver caches.
            Counts describe identifiers, not HTTP requests. Default is offline.

    Returns:
        Advisory issues with exact entry byte/character spans. ``ok`` and
        ``input_complete`` concern input processing, never existence, official
        provenance, support, or submission readiness. No file is modified.
    """
    report: dict[str, Any] = dict(
        ok=False,
        input_complete=False,
        advisory_only=True,
        submission_ready=False,
        advisory_clean=False,
        comparison_complete=False if verify else None,
        input_sha256=None,
        entries=[],
        issues=[],
        comparison=dict(
            requested=verify,
            identifiers_requested=[],
            identifier_count=0,
            compared_entries=0,
            outcomes=[],
        ),
    )
    if (
        not isinstance(bib_path, str)
        or not bib_path
        or type(verify) is not bool
        or keys is not None
        and (
            not isinstance(keys, list)
            or any(not isinstance(key, str) or not key.strip() for key in keys)
        )
    ):
        return dict(report, error="Invalid path, keys, or verify argument.")
    path = os.path.abspath(os.path.expanduser(bib_path))
    try:
        if not os.path.isfile(path):
            raise ValueError("Bibliography must be a regular file.")
        with open(path, "rb") as stream:
            raw = stream.read(_LINT_MAX_BYTES + 1)
        if len(raw) > _LINT_MAX_BYTES:
            raise ValueError("Bibliography exceeds the 4 MiB input limit.")
        source = raw.decode("utf-8")
        report["input_sha256"] = hashlib.sha256(raw).hexdigest()
        parsed = _engine_parsing._parse_bib(source)
        if not parsed["complete"]:
            return dict(
                report,
                error="Bibliography parsing is incomplete.",
                parse_errors=parsed["errors"],
            )
        entries = parsed["entries"]
        if len(entries) > _LINT_MAX_ENTRIES:
            raise ValueError("Bibliography exceeds the 2000 entry limit.")
        missing = sorted(set(keys or []) - set(parsed["keys"]))
        if missing:
            return dict(
                report,
                error="Requested bibliography keys are absent.",
                missing_keys=missing,
            )
        selected = set(keys) if keys is not None else None
        locations = {}
        previous = byte_position = 0
        line = 1
        for entry in entries:
            start, end = entry["start"], entry["end"]
            gap = source[previous:start]
            byte_position += len(gap.encode("utf-8"))
            line += gap.count("\n")
            size = len(entry["raw"].encode("utf-8"))
            locations[entry["key"]] = dict(
                scope="entry",
                file=path,
                line=line,
                end_line=line + entry["raw"].count("\n"),
                start=start,
                end=end,
                byte_start=byte_position,
                byte_end=byte_position + size,
            )
            previous, byte_position = end, byte_position + size
            line += entry["raw"].count("\n")
        entries = [
            entry
            for entry in entries
            if selected is None or entry["key"] in selected
        ]
        issues = [
            dict(issue, key=entry["key"])
            for entry in entries
            for issue in _lint_local_issues(entry)
        ]
        if verify:
            comparison, comparison_issues = _lint_compare_entries(entries)
            report["comparison"] = comparison
            report["comparison_complete"] = (
                comparison["compared_entries"]
                == comparison["comparable_entries"]
            )
            issues.extend(comparison_issues)
        else:
            report["comparison"]["outcomes"] = [
                dict(key=entry["key"], status="not-requested", identifiers=[])
                for entry in entries
            ]
        with open(path, "rb") as stream:
            current = stream.read(_LINT_MAX_BYTES + 1)
        if current != raw:
            raise ValueError("Bibliography snapshot is stale; rerun lint.")
    except (OSError, ValueError, UnicodeError) as exc:
        return dict(
            report,
            error=str(exc),
            comparison_complete=False if verify else None,
        )
    report["issues"] = [
        dict(issue, severity="advisory", location=locations[issue["key"]])
        for issue in issues
    ]
    report["entries"] = [
        dict(
            key=entry["key"],
            type=entry["type"],
            issue_count=sum(issue["key"] == entry["key"] for issue in issues),
        )
        for entry in entries
    ]
    report.update(
        ok=True,
        input_complete=True,
        advisory_clean=not issues
        and (not verify or report["comparison_complete"]),
    )
    return report

def verify_bib(bib_path: str, keys: list[str] | None = None, tex_path: str | None = None,
               search_unresolved: bool = True) -> dict:
    """Existence check of every entry (or `keys`): resolve the entry's own
    DOI / arXiv id / bibcode — or, for software, the GitHub repository in its
    url / howpublished / repository field — and compare title, first author
    and year with the registry record (a repository entry's cited version
    must exist as a tag, branch or commit). Entries without any identifier
    are searched by title, author and year. Statuses: VERIFIED, FOUND (by search — replace with the
    official entry), PROBABLE (look), MISMATCH (real id, different paper),
    NOT_FOUND, UNRESOLVED (no identifier, or the lookup failed). ok=true only
    when every entry is VERIFIED or FOUND.
    """
    bib_path = os.path.abspath(bib_path)
    if not os.path.exists(bib_path):
        return {"error": f"{bib_path} not found"}
    with open(bib_path, errors="replace") as fh:
        parsed = _engine_parsing._parse_bib(fh.read())
    if not parsed["complete"]:
        return {"ok": False, "complete": False, "error": "; ".join(parsed["errors"]),
                "entries": [], "n": 0, "parse_errors": parsed["errors"]}
    wanted = set(keys) if keys else None
    entries = [e for e in parsed["entries"] if wanted is None or e["key"] in wanted]
    missing_keys = sorted(wanted - set(parsed["keys"])) if wanted else []
    plan = []
    for e in entries:
        ids = _engine_parsing._entry_ids(e)
        order = [(k, ids[k]) for k in ("doi", "arxiv") if ids.get(k)]
        if ids.get("bibcode") and _engine_credentials._ads_token():
            order.append(("bibcode", ids["bibcode"]))
        prov_id = (e["provenance"] or {}).get("id", "")
        if prov_id.startswith("github:") and _engine_identifiers._classify(prov_id)[0] == "github":
            ids["github"] = _engine_identifiers._classify(prov_id)[1]      # bib_add filed it as the repository (e.g. its DataCite export)
            order.insert(0, ("github", ids["github"]))
        elif ids.get("github"):
            order.append(("github", ids["github"]))
        plan.append((e, order))
    all_ids = list(dict.fromkeys(f"{k}:{v}" for _, order in plan for k, v in order))
    try:
        resolved = dict(zip(all_ids, _engine_resolution._resolve_many(all_ids))) if all_ids else {}
    except RuntimeError as exc:
        return {"error": f"registry lookup failed ({exc})"}
    out, to_search = [], []
    for e, order in plan:
        result, bad = None, []
        for k, v in order:
            r = resolved.get(f"{k}:{v}")
            if r and r.get("resolved"):
                version = _engine_parsing._entry_arxiv_version(e)
                if version and k != "github":
                    result = _compare_arxiv_version(e, r, version)
                else:
                    result = _compare_repo(e, r) if k == "github" else _compare(e, r, f"{k}:{v}")
                break
            bad.append(f"{k}:{v} — {(r or {}).get('reason', 'no result')}")
        if result and result["status"] == "MISMATCH" and result["via"].startswith("github:") and search_unresolved:
            found = _search_entry(e)
            if found["status"] in ("FOUND", "PROBABLE") and e["type"] not in _engine_parsing._SOFTWARE_TYPES:
                # an article whose url is its code: the paper is what is cited
                found["notes"].insert(0, f"its GitHub URL points at {result['ids']['github']}, which is not this work")
                result = found
            elif found["status"] in ("FOUND", "PROBABLE"):
                # a software entry with the wrong repository is the real-DOI-wrong-title case: still a failure
                result["notes"].append(f"a registry record with this title exists ({found['id']}) — fix the URL, "
                                       f"or bib_add(items=[{{'identifier': '{found['id']}', 'key': '{e['key']}'}}], replace=true)")
        if result:
            result["notes"] += [f"stale identifier in entry: {b}" for b in bad]
            out.append(result)
        elif order:
            failed = any((resolved.get(f"{k}:{v}") or {}).get("lookup_error") for k, v in order)
            out.append({"key": e["key"], "status": "UNRESOLVED" if failed else "NOT_FOUND", "via": None,
                        "notes": bad + (["the lookup itself failed — retry before calling this a fabrication"]
                                        if failed else []), "provenance": e["provenance"]})
        else:
            to_search.append(e)
    if to_search and search_unresolved:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
            out += list(_engine_budgets._context_map(ex, _search_entry, to_search))
    else:
        out += [{"key": e["key"], "status": "UNRESOLVED", "via": None, "provenance": e["provenance"],
                 "notes": ["no identifier; search skipped"]} for e in to_search]
    pos = {e["key"]: i for i, e in enumerate(entries)}
    out.sort(key=lambda r: pos.get(r["key"], 10 ** 9))
    counts = Counter(r["status"] for r in out)
    report = {"ok": all(r["status"] in _OK_STATUS for r in out) and not missing_keys,
              "bib": bib_path, "n": len(out), "counts": dict(counts), "missing_keys": missing_keys,
              "ads": bool(_engine_credentials._ads_token()), "checked": _engine_persistence._now_iso(), "entries": out}
    _engine_persistence._write_project(os.path.dirname(bib_path), "verify.json", report)
    return report
