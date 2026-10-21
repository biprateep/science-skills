"""Registry adapters and canonical record construction."""

import html
import json
import re
import typing
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any
from cite_check_engine import models as _engine_models
from cite_check_engine import credentials as _engine_credentials
from cite_check_engine import identifiers as _engine_identifiers
from cite_check_engine import parsing as _engine_parsing
from cite_check_engine import persistence as _engine_persistence
from cite_check_engine import publication_status as _engine_publication_status
from cite_check_engine import text as _engine_text
from cite_check_engine import transport as _engine_transport


def _record(**kw: typing.Any) -> _engine_models.Work:
    rec: _engine_models.Work = {"registry": None, "title": "", "authors": [], "year": None, "venue": "",
           "doi": None, "arxiv": None, "bibcode": None, "openalex": None, "inspire": None,
           "github": None, "abstract": "", "type": "", "url": "", "citation_count": None, "pdf_urls": []}
    # Provider adapters supply additional normalized JSON fields.
    typing.cast(dict[str, typing.Any], rec).update(
        {k: v for k, v in kw.items() if v is not None}
    )
    if rec["doi"]:
        rec["doi"] = rec["doi"].lower()
        m = re.match(r"^10\.48550/arxiv\.(.+)$", rec["doi"])
        if m and _engine_identifiers._ARXIV_RE.match(m.group(1)):          # DataCite's arXiv DOIs: one identity, not two
            rec["arxiv"], rec["doi"] = rec["arxiv"] or _engine_identifiers._strip_arxiv_version(m.group(1)), None
    if rec["arxiv"]:
        rec["arxiv"] = _engine_identifiers._strip_arxiv_version(rec["arxiv"])
    if rec["github"]:
        rec["github"] = rec["github"].lower()
    return rec

def _year(v) -> int | None:
    m = re.search(r"(19|20)\d{2}", str(v or ""))
    return int(m.group(0)) if m else None

_DISCOVERY_SOURCES = {"semanticscholar", "pubmed", "dblp"}

_S2_SEARCH = "https://api.semanticscholar.org/graph/v1/paper/search"

_PUBMED_API = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"

_DBLP_SEARCH = "https://dblp.org/search/publ/api"

_DISCOVERY_LIMIT = 10

def _discovery_json(
    source: str, url: str, headers: dict[str, str] | None = None
) -> dict[str, Any]:
    """Read a public API envelope, preserving errors rather than empty hits."""
    status, payload = _engine_transport._get_json(url, headers=headers)
    if status != 200:
        outcome = (
            "rate-limited"
            if status == 429
            else "authentication-required"
            if status in {401, 403}
            else "unavailable"
        )
        raise RegistryLookupError(source, outcome, status)
    if not isinstance(payload, dict) or payload.get("error"):
        raise RegistryLookupError(source, "malformed-response", status)
    return payload

def _discovery_rows(
    source: str,
    rows: Any,
    total: Any = None,
    sent: Any = None,
) -> list[Any]:
    """Check bounded result counts, distinguishing empty from partial data."""
    if not isinstance(rows, list) or len(rows) > _DISCOVERY_LIMIT:
        raise RegistryLookupError(source, "malformed-response", 200)
    for name, value in (("total", total), ("sent", sent)):
        if value is None:
            continue
        if type(value) is not int and not (
            isinstance(value, str) and re.fullmatch(r"[0-9]+", value)
        ):
            raise RegistryLookupError(source, "malformed-response", 200)
        count = int(value)
        size = min(count, _DISCOVERY_LIMIT) if name == "total" else count
        if count < 0 or size != len(rows):
            raise RegistryLookupError(source, "incomplete-response", 200)
    return rows

def _discovery_string(source: str, value: Any, required: bool = False) -> str:
    """Validate provider strings without converting structured data to text."""
    if value is None and not required:
        return ""
    if not isinstance(value, str) or (required and not value.strip()):
        raise RegistryLookupError(source, "malformed-response", 200)
    return value.strip()

def _discovery_authors(
    source: str, value: Any, name_field: str = "name"
) -> list[str]:
    """Normalize the documented provider author shapes."""
    if value is None:
        return []
    if isinstance(value, (str, dict)) and source == "dblp":
        value = [value]
    if not isinstance(value, list):
        raise RegistryLookupError(source, "malformed-response", 200)
    authors = []
    for row in value:
        name = row.get(name_field) if isinstance(row, dict) else row
        if not isinstance(row, dict) and source != "dblp":
            raise RegistryLookupError(source, "malformed-response", 200)
        authors.append(_discovery_string(source, name, required=True))
    return authors

def _discovery_year(source: str, value: Any) -> int | None:
    """Validate numeric publication years when the provider supplies them."""
    if value is None or value == "":
        return None
    if type(value) is int and 1000 <= value <= 9999:
        return value
    if (
        source == "dblp"
        and isinstance(value, str)
        and re.fullmatch(r"\d{4}", value)
    ):
        return int(value)
    raise RegistryLookupError(source, "malformed-response", 200)

def _discovery_alias(source: str, value: Any, kind: str) -> str:
    """Validate a suggested alias without establishing work identity."""
    text = _discovery_string(source, value, required=True)
    actual, identifier = _engine_identifiers._classify(text if ":" in text else f"{kind}:{text}")
    if actual not in ({"doi", "arxiv"} if kind == "doi" else {kind}):
        raise RegistryLookupError(source, "malformed-response", 200)
    return f"{actual}:{identifier}"

def _discovery_record(
    source: str,
    native_id: str,
    title: str,
    authors: list[str],
    year: int | None,
    venue: str,
    suggested_ids: list[str],
    publication_type: str = "",
) -> _engine_models.Work:
    """Build an isolated discovery candidate with a fixed-origin source URL."""
    if source == "semanticscholar":
        if not re.fullmatch(r"[0-9a-fA-F]{40}", native_id):
            raise RegistryLookupError(source, "malformed-response", 200)
        native_id = native_id.lower()
        identifier = "semanticscholar:" + native_id
        url = "https://www.semanticscholar.org/paper/" + native_id
    elif source == "pubmed":
        if not re.fullmatch(r"[1-9]\d*", native_id):
            raise RegistryLookupError(source, "malformed-response", 200)
        identifier = "pmid:" + native_id
        url = "https://pubmed.ncbi.nlm.nih.gov/" + native_id + "/"
    else:
        if (
            not re.fullmatch(r"[A-Za-z0-9._/-]+", native_id)
            or "/" not in native_id
            or any(part in {"", ".", ".."} for part in native_id.split("/"))
        ):
            raise RegistryLookupError(source, "malformed-response", 200)
        identifier = "dblp:" + native_id
        url = "https://dblp.org/rec/" + native_id
    return _record(
        registry=source,
        title=title,
        authors=authors,
        year=year,
        venue=venue,
        type=publication_type,
        url=url,
        discovery_only=True,
        discovery_id=identifier,
        suggested_ids=list(dict.fromkeys(suggested_ids)),
        provenance=dict(source=source, record_id=native_id, url=url),
    )

def _discovery_deduplicate(
    records: list[_engine_models.Work],
) -> list[_engine_models.Work]:
    """Collapse identical native rows; reject conflicting same-ID responses."""
    indexed: dict[str, _engine_models.Work] = {}
    for record in records:
        identifier = record["discovery_id"]
        if identifier in indexed and indexed[identifier] != record:
            raise RegistryLookupError(
                typing.cast(str, record["registry"]),
                "conflicting-native-records", 200
            )
        indexed[identifier] = record
    return list(indexed.values())

def _semanticscholar_search(
    title: str | None = None,
    author: str | None = None,
    words: list[str] | None = None,
    year: int | None = None,
) -> list[_engine_models.Work]:
    """Search a bounded Semantic Scholar page for unverified candidates."""
    source = "semanticscholar"
    query = " ".join(filter(None, [title, author, " ".join(words or [])]))
    params: dict[str, Any] = dict(
        query=_engine_text._strip_latex(query),
        limit=_DISCOVERY_LIMIT,
        fields="title,authors,year,venue,externalIds",
    )
    if year is not None:
        params["year"] = f"{year - 1}-{year + 1}"
    key = _engine_credentials.key_value(source)[0]
    if key and re.search(r"[\s\"']", key):
        raise RegistryLookupError(source, "invalid-credential", 0)
    payload = _discovery_json(
        source,
        _S2_SEARCH + "?" + urllib.parse.urlencode(params),
        {"x-api-key": key} if key else None,
    )
    rows = _discovery_rows(source, payload.get("data"), payload.get("total"))
    records = []
    for row in rows:
        if not isinstance(row, dict):
            raise RegistryLookupError(source, "malformed-response", 200)
        external = row.get("externalIds")
        if external is None:
            external = {}
        if not isinstance(external, dict):
            raise RegistryLookupError(source, "malformed-response", 200)
        aliases = [
            _discovery_alias(source, external[name], kind)
            for name, kind in (("DOI", "doi"), ("ArXiv", "arxiv"))
            if name in external and external[name] is not None
        ]
        records.append(
            _discovery_record(
                source,
                _discovery_string(source, row.get("paperId"), True),
                _discovery_string(source, row.get("title"), True),
                _discovery_authors(source, row.get("authors")),
                _discovery_year(source, row.get("year")),
                _discovery_string(source, row.get("venue")),
                aliases,
            )
        )
    return _discovery_deduplicate(records)

def _pubmed_search(
    title: str | None = None,
    author: str | None = None,
    words: list[str] | None = None,
    year: int | None = None,
) -> list[_engine_models.Work]:
    """Search PubMed UIDs and retrieve one bounded batch of summaries."""
    source = "pubmed"
    query = " ".join(filter(None, [title, author, " ".join(words or [])]))
    common = dict(db="pubmed", retmode="json", tool="cite-check")
    if _engine_credentials._mailto():
        common["email"] = _engine_credentials._mailto()
    params = dict(
        common,
        term=_engine_text._strip_latex(query),
        retmax=_DISCOVERY_LIMIT,
        sort="relevance",
    )
    if year is not None:
        params.update(
            datetype="pdat", mindate=str(year - 1), maxdate=str(year + 1)
        )
    payload = _discovery_json(
        source, _PUBMED_API + "esearch.fcgi?" + urllib.parse.urlencode(params)
    )
    found = payload.get("esearchresult")
    if (
        not isinstance(found, dict)
        or found.get("ERROR")
        or found.get("errorlist")
        or not isinstance(found.get("idlist"), list)
    ):
        raise RegistryLookupError(source, "malformed-response", 200)
    identifiers = _discovery_rows(source, found["idlist"], found.get("count"))
    if len(identifiers) > _DISCOVERY_LIMIT or any(
        not isinstance(uid, str) or not re.fullmatch(r"[1-9]\d*", uid)
        for uid in identifiers
    ):
        raise RegistryLookupError(source, "malformed-response", 200)
    identifiers = list(dict.fromkeys(identifiers))
    if not identifiers:
        return []
    summary = _discovery_json(
        source,
        _PUBMED_API
        + "esummary.fcgi?"
        + urllib.parse.urlencode(dict(common, id=",".join(identifiers))),
    )
    result = summary.get("result")
    if (
        not isinstance(result, dict)
        or not isinstance(result.get("uids"), list)
        or len(result["uids"]) != len(identifiers)
        or any(not isinstance(uid, str) for uid in result["uids"])
        or set(result["uids"]) != set(identifiers)
    ):
        raise RegistryLookupError(source, "malformed-response", 200)
    records = []
    for identifier in identifiers:
        row = result.get(identifier)
        if (
            not isinstance(row, dict)
            or row.get("uid") != identifier
            or row.get("error")
        ):
            raise RegistryLookupError(source, "malformed-response", 200)
        article_ids = row.get("articleids", [])
        if not isinstance(article_ids, list):
            raise RegistryLookupError(source, "malformed-response", 200)
        aliases = []
        for alias in article_ids:
            if not isinstance(alias, dict):
                raise RegistryLookupError(source, "malformed-response", 200)
            if (
                alias.get("idtype") == "pubmed"
                and alias.get("value") != identifier
            ):
                raise RegistryLookupError(source, "identity-mismatch", 200)
            if alias.get("idtype") == "doi":
                aliases.append(
                    _discovery_alias(source, alias.get("value"), "doi")
                )
        date = _discovery_string(source, row.get("pubdate"))
        match = re.search(r"\b\d{4}\b", date)
        records.append(
            _discovery_record(
                source,
                identifier,
                _discovery_string(source, row.get("title"), True),
                _discovery_authors(source, row.get("authors")),
                int(match.group()) if match else None,
                _discovery_string(
                    source, row.get("fulljournalname") or row.get("source")
                ),
                aliases,
            )
        )
    return _discovery_deduplicate(records)

def _dblp_search(
    title: str | None = None,
    author: str | None = None,
    words: list[str] | None = None,
    year: int | None = None,
) -> list[_engine_models.Work]:
    """Search dblp publications without accepting its BibTeX as an export."""
    source = "dblp"
    query = " ".join(
        filter(
            None,
            [
                title,
                author,
                " ".join(words or []),
                str(year) if year is not None else None,
            ],
        )
    )
    payload = _discovery_json(
        source,
        _DBLP_SEARCH
        + "?"
        + urllib.parse.urlencode(
            dict(q=_engine_text._strip_latex(query), format="json", h=_DISCOVERY_LIMIT, c=0)
        ),
    )
    result = payload.get("result")
    hits = result.get("hits") if isinstance(result, dict) else None
    if not isinstance(hits, dict):
        raise RegistryLookupError(source, "malformed-response", 200)
    rows = hits.get("hit", [])
    if isinstance(rows, dict):
        rows = [rows]
    rows = _discovery_rows(source, rows, hits.get("@total"), hits.get("@sent"))
    if not rows and "@total" not in hits:
        raise RegistryLookupError(source, "malformed-response", 200)
    records = []
    for hit in rows:
        row = hit.get("info") if isinstance(hit, dict) else None
        if not isinstance(row, dict):
            raise RegistryLookupError(source, "malformed-response", 200)
        authors = row.get("authors")
        if authors is None:
            authors = {}
        if not isinstance(authors, dict):
            raise RegistryLookupError(source, "malformed-response", 200)
        links = row.get("ee")
        if links is None:
            links = []
        if isinstance(links, str):
            links = [links]
        if not isinstance(links, list):
            raise RegistryLookupError(source, "malformed-response", 200)
        aliases = []
        for link in links:
            link = _discovery_string(source, link, True)
            kind, value = _engine_identifiers._classify(link)
            if kind in {"doi", "arxiv"}:
                aliases.append(f"{kind}:{value}")
        records.append(
            _discovery_record(
                source,
                _discovery_string(source, row.get("key"), True),
                _discovery_string(source, row.get("title"), True),
                _discovery_authors(source, authors.get("author"), "text"),
                _discovery_year(source, row.get("year")),
                _discovery_string(source, row.get("venue")),
                aliases,
                _discovery_string(source, row.get("type")),
            )
        )
    return _discovery_deduplicate(records)

_ATOM = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom"}

_ARXIV_API = "https://export.arxiv.org/api/query"

def _arxiv_parse(body: str) -> list:
    out = []
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise RegistryLookupError("arxiv", "malformed-response", 200) from exc
    if root.tag != "{http://www.w3.org/2005/Atom}feed":
        raise RegistryLookupError("arxiv", "malformed-response", 200)
    for e in root.findall("a:entry", _ATOM):
        title = re.sub(r"\s+", " ", e.findtext("a:title", "", _ATOM)).strip()
        eid = e.findtext("a:id", "", _ATOM)
        m = re.fullmatch(r"https?://arxiv\.org/abs/(.+)", eid)
        if (not title or title == "Error" or not m
                or not _engine_identifiers._ARXIV_RE.fullmatch(m.group(1))):
            raise RegistryLookupError("arxiv", "malformed-response", 200)
        aid = _engine_identifiers._strip_arxiv_version(m.group(1))
        cat = e.find("x:primary_category", _ATOM)
        out.append(_record(
            registry="arxiv", title=title, arxiv=aid,
            arxiv_api_version=(m.group(1) if re.search(r"v[1-9]\d*$", m.group(1), re.I) else None),
            authors=[a.findtext("a:name", "", _ATOM) for a in e.findall("a:author", _ATOM)],
            year=_year(e.findtext("a:published", "", _ATOM)),
            doi=(e.findtext("x:doi", "", _ATOM) or None),
            venue=(e.findtext("x:journal_ref", "", _ATOM) or "arXiv"),
            abstract=re.sub(r"\s+", " ", e.findtext("a:summary", "", _ATOM)).strip(),
            type="preprint", url=f"https://arxiv.org/abs/{aid}" if aid else eid,
            primary_class=cat.get("term") if cat is not None else None,
            pdf_urls=[f"https://arxiv.org/pdf/{aid}"] if aid else []))
    return out

class RegistryLookupError(RuntimeError):
    """A non-definitive registry outcome; never evidence of absence."""

    def __init__(self, registry: str, outcome: str, status: int = 0):
        self.outcome = outcome
        super().__init__(f"{registry}: {outcome} (HTTP {status})")

def _registry_status(registry: str, status: int) -> bool:
    if status == 404:
        return False
    if status != 200:
        raise RegistryLookupError(
            registry, "rate-limited" if status == 429 else "unavailable", status
        )
    return True

def _arxiv_lookup(ids: list) -> dict:
    found = {}
    for chunk in _engine_transport._chunks(ids, 50):
        status, body = _engine_transport._http(f"{_ARXIV_API}?id_list={','.join(chunk)}&max_results={len(chunk)}")
        if not _registry_status("arxiv", status):
            continue
        for rec in _arxiv_parse(body):
            found[rec["arxiv"].lower()] = rec
            if rec.get("arxiv_api_version"):
                found[rec["arxiv_api_version"].lower()] = rec
    return found

def _arxiv_query(q: str, max_results: int = 10) -> list:
    url = f"{_ARXIV_API}?search_query={urllib.parse.quote(q)}&max_results={max_results}"
    status, body = _engine_transport._http(url)
    return _arxiv_parse(body) if _registry_status("arxiv", status) else []

def _arxiv_search(title=None, author=None, words=None, year=None, max_results=10) -> list:
    parts = []
    if title:
        parts.append('ti:"%s"' % re.sub(r'["\\]', " ", _engine_text._strip_latex(title)).strip())
    if author:
        parts.append('au:"%s"' % author.replace('"', ""))
    if words and not title:
        parts.append("(" + " OR ".join(f"ti:{w} OR abs:{w}" for w in words[:4]) + ")")
    if year and (author or title):
        parts.append(f"submittedDate:[{year - 1}01010000 TO {year + 1}12312359]")
    return _arxiv_query(" AND ".join(parts), max_results) if parts else []

_CROSSREF = "https://api.crossref.org/works"

def _registry_list(
    data: dict, key: str, item_type: type, registry: str,
) -> list:
    """Validate optional registry arrays before converting their contents."""
    value = data.get(key)
    if value is None:
        return []
    if not isinstance(value, list) or any(
        not isinstance(item, item_type) for item in value
    ):
        raise RegistryLookupError(registry, "malformed-response", 200)
    return value

def _registry_strings(data: dict, keys: tuple[str, ...], registry: str) -> None:
    """Reject non-string scalar fields in a registry response."""
    if any(data.get(key) is not None and not isinstance(data[key], str)
           for key in keys):
        raise RegistryLookupError(registry, "malformed-response", 200)

def _cr_record(msg: dict) -> _engine_models.Work:
    """Convert valid Crossref records and classify malformed nested fields."""
    if not isinstance(msg, dict):
        raise RegistryLookupError("crossref", "malformed-response", 200)
    _registry_strings(msg, ("DOI", "abstract", "type", "URL"), "crossref")
    if not _engine_identifiers._DOI_RE.fullmatch(msg.get("DOI") or ""):
        raise RegistryLookupError("crossref", "malformed-response", 200)
    if msg.get("is-referenced-by-count") is not None and type(
        msg["is-referenced-by-count"]
    ) is not int:
        raise RegistryLookupError("crossref", "malformed-response", 200)
    for key in ("title", "subtitle", "container-title"):
        _registry_list(msg, key, str, "crossref")
    for author in _registry_list(msg, "author", dict, "crossref"):
        _registry_strings(author, ("family", "given", "name"), "crossref")
    for link in _registry_list(msg, "link", dict, "crossref"):
        _registry_strings(link, ("URL", "content-type"), "crossref")
    try:
        return _cr_record_fields(msg)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
        raise RegistryLookupError("crossref", "malformed-response", 200) from exc

def _cr_record_fields(msg: dict) -> _engine_models.Work:
    title = " ".join(msg.get("title") or []).strip()
    sub = " ".join(msg.get("subtitle") or []).strip()
    if sub and _engine_text._norm_title(sub) not in _engine_text._norm_title(title):
        title = f"{title}: {sub}"
    authors = []
    for a in msg.get("author") or []:
        if a.get("family"):
            authors.append(f"{a['family']}, {a.get('given', '')}".strip(", "))
        elif a.get("name"):
            authors.append(a["name"])
    year = None
    for k in ("published-print", "published-online", "issued", "created"):
        parts = (msg.get(k) or {}).get("date-parts") or [[None]]
        if parts and parts[0] and parts[0][0]:
            year = int(parts[0][0])
            break
    abstract = re.sub(r"<[^>]+>", " ", msg.get("abstract") or "")
    pdfs = [l["URL"] for l in msg.get("link") or []
            if l.get("content-type") == "application/pdf" and l.get("URL")]
    clean = lambda v: re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", v or ""))).strip()
    return _record(registry="crossref", title=clean(title), authors=authors, year=year,
                   venue=clean((msg.get("container-title") or [""])[0]),
                   doi=msg.get("DOI"), type=msg.get("type", ""),
                   abstract=re.sub(r"\s+", " ", html.unescape(abstract)).strip(),
                   url=f"https://doi.org/{msg.get('DOI')}" if msg.get("DOI") else msg.get("URL", ""),
                   citation_count=msg.get("is-referenced-by-count"), pdf_urls=pdfs,
                   publication_status=_engine_publication_status.normalize(msg))

def _crossref_work(doi: str):
    status, data = _engine_transport._get_json(f"{_CROSSREF}/{urllib.parse.quote(doi, safe='')}")
    if not _registry_status("crossref", status):
        return None
    message = data.get("message") if isinstance(data, dict) else None
    if not isinstance(message, dict) or not message.get("DOI"):
        raise RegistryLookupError("crossref", "malformed-response", status)
    return _cr_record(message)

def _crossref_search(title=None, author=None, words=None, year=None, rows=10) -> list:
    params = {"rows": rows, "select": "DOI,title,subtitle,author,issued,published-print,"
                                      "published-online,created,container-title,type,"
                                      "is-referenced-by-count,abstract,link,URL"}
    biblio = _engine_text._strip_latex(title) if title else " ".join(words or [])
    if biblio.strip():
        params["query.bibliographic"] = biblio.strip()
    if author:
        params["query.author"] = author
    if year:
        params["filter"] = f"from-pub-date:{year - 1}-01-01,until-pub-date:{year + 1}-12-31"
    if _engine_credentials._mailto():
        params["mailto"] = _engine_credentials._mailto()
    if "query.bibliographic" not in params and "query.author" not in params:
        return []
    status, data = _engine_transport._get_json(f"{_CROSSREF}?{urllib.parse.urlencode(params)}")
    if status != 200 or not data:
        return []
    records = [_cr_record(m) for m in data.get("message", {}).get("items", [])]
    for record in records:
        record["publication_status"] = _engine_publication_status.unknown(
            "Publication-status fields were not requested in the discovery projection."
        )
    return records

def _datacite_doi(doi: str):
    status, data = _engine_transport._get_json(f"https://api.datacite.org/dois/{urllib.parse.quote(doi, safe='')}")
    if not _registry_status("datacite", status):
        return None
    try:
        a = data["data"]["attributes"]
        if not isinstance(a, dict) or not a.get("doi"):
            raise ValueError("missing DOI")
    except (KeyError, TypeError, ValueError) as exc:
        raise RegistryLookupError("datacite", "malformed-response", status) from exc
    _registry_strings(a, ("doi", "publisher", "url"), "datacite")
    if not _engine_identifiers._DOI_RE.fullmatch(a.get("doi") or ""):
        raise RegistryLookupError("datacite", "malformed-response", status)
    for title in _registry_list(a, "titles", dict, "datacite"):
        _registry_strings(title, ("title",), "datacite")
    for creator in _registry_list(a, "creators", dict, "datacite"):
        _registry_strings(
            creator, ("familyName", "givenName", "name"), "datacite"
        )
    for description in _registry_list(a, "descriptions", dict, "datacite"):
        _registry_strings(description, ("description",), "datacite")
    if a.get("types") is not None and not isinstance(a["types"], dict):
        raise RegistryLookupError("datacite", "malformed-response", status)
    _registry_strings(
        a.get("types") or {}, ("resourceTypeGeneral",), "datacite"
    )
    if a.get("publicationYear") is not None and type(a["publicationYear"]) is not int:
        raise RegistryLookupError("datacite", "malformed-response", status)
    try:
        return _datacite_record_fields(a)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
        raise RegistryLookupError("datacite", "malformed-response", status) from exc

def _datacite_record_fields(a: dict) -> _engine_models.Work:
    authors = []
    for c in a.get("creators") or []:
        if c.get("familyName"):
            authors.append(f"{c['familyName']}, {c.get('givenName', '')}".strip(", "))
        elif c.get("name"):
            authors.append(c["name"])
    desc = next((d.get("description", "") for d in a.get("descriptions") or []), "")
    return _record(registry="datacite", title=(a.get("titles") or [{}])[0].get("title", ""),
                   authors=authors, year=a.get("publicationYear"), venue=a.get("publisher", ""),
                   doi=a.get("doi"), type=(a.get("types") or {}).get("resourceTypeGeneral", ""),
                   abstract=re.sub(r"\s+", " ", desc).strip(), url=a.get("url", ""))

_OPENALEX = "https://api.openalex.org/works"

def _oa_abstract(inv: dict | None) -> str:
    if not inv:
        return ""
    pos = sorted((p, w) for w, ps in inv.items() for p in ps)
    return " ".join(w for _, w in pos)

def _oa_record(w: dict) -> _engine_models.Work:
    ids = w.get("ids") or {}
    doi = (ids.get("doi") or w.get("doi") or "").replace("https://doi.org/", "") or None
    arxiv = None
    for loc in [w.get("primary_location")] + (w.get("locations") or []):
        for u in ((loc or {}).get("landing_page_url"), (loc or {}).get("pdf_url")):
            m = re.search(r"arxiv\.org/(?:abs|pdf)/(" + _engine_identifiers._ARXIV_CORE + r")", u or "", re.I)
            if m:
                arxiv = m.group(1)
                break
        if arxiv:
            break
    oa = w.get("best_oa_location") or {}
    return _record(registry="openalex", title=w.get("display_name") or "",
                   authors=[(a.get("author") or {}).get("display_name", "") for a in w.get("authorships") or []],
                   year=w.get("publication_year"),
                   venue=(((w.get("primary_location") or {}).get("source") or {}).get("display_name") or ""),
                   doi=doi, arxiv=arxiv, openalex=(ids.get("openalex") or w.get("id") or "").rsplit("/", 1)[-1] or None,
                   abstract=_oa_abstract(w.get("abstract_inverted_index")), type=w.get("type", ""),
                   url=w.get("id", ""), citation_count=w.get("cited_by_count"),
                   pdf_urls=[oa["pdf_url"]] if oa.get("pdf_url") else [])

def _oa_params(extra: dict) -> str:
    if _engine_credentials._mailto():
        extra = dict(extra, mailto=_engine_credentials._mailto())
    return urllib.parse.urlencode(extra)

def _openalex_get(ident: str):
    status, data = _engine_transport._get_json(f"{_OPENALEX}/{urllib.parse.quote(ident, safe=':/')}?{_oa_params({})}")
    return _oa_record(data) if status == 200 and data else None

def _openalex_batch_dois(dois: list) -> dict:
    found = {}
    for chunk in _engine_transport._chunks(dois, 40):
        q = _oa_params({"filter": "doi:" + "|".join(chunk), "per-page": 50})
        status, data = _engine_transport._get_json(f"{_OPENALEX}?{q}")
        for w in (data or {}).get("results", []) if status == 200 else []:
            rec = _oa_record(w)
            if rec["doi"]:
                found[rec["doi"]] = rec
    return found

def _openalex_search(title=None, author=None, words=None, year=None, per_page=10) -> list:
    search = _engine_text._strip_latex(title) if title else " ".join(words or [])
    filters = []
    if year:
        filters.append(f"publication_year:{year - 1}|{year}|{year + 1}")
    if author:
        filters.append(f"raw_author_name.search:{author}")
    if not search.strip() and not author:
        return []
    params = {"per-page": per_page}
    if search.strip():
        params["search"] = search.strip()
    if filters:
        params["filter"] = ",".join(filters)
    status, data = _engine_transport._get_json(f"{_OPENALEX}?{_oa_params(params)}")
    if status != 200 and author:          # filter syntax rejected: retry without it
        params["filter"] = ",".join(f for f in filters if not f.startswith("raw_author"))
        status, data = _engine_transport._get_json(f"{_OPENALEX}?{_oa_params(params)}")
    if status != 200 or not data:
        return []
    return [_oa_record(w) for w in data.get("results", [])]

_INSPIRE = "https://inspirehep.net/api"

_INSPIRE_FIELDS = ("titles,authors.full_name,dois,arxiv_eprints,publication_info,earliest_date,"
                   "abstracts,control_number,citation_count,document_type,imprints")

def _insp_record(hit: dict) -> _engine_models.Work:
    m = hit.get("metadata") or {}
    pub = (m.get("publication_info") or [{}])[0]
    year = _year(m.get("earliest_date")) or _year(pub.get("year")) or _year((m.get("imprints") or [{}])[0].get("date"))
    return _record(registry="inspire", title=(m.get("titles") or [{}])[0].get("title", ""),
                   authors=[a.get("full_name", "") for a in m.get("authors") or []],
                   year=year, venue=pub.get("journal_title", ""),
                   doi=(m.get("dois") or [{}])[0].get("value"),
                   arxiv=(m.get("arxiv_eprints") or [{}])[0].get("value"),
                   inspire=str(m.get("control_number") or hit.get("id") or "") or None,
                   abstract=(m.get("abstracts") or [{}])[0].get("value", ""),
                   type=",".join(m.get("document_type") or []),
                   url=f"https://inspirehep.net/literature/{m.get('control_number')}" if m.get("control_number") else "",
                   citation_count=m.get("citation_count"))

def _inspire_get(kind: str, value: str):
    path = {"arxiv": "arxiv", "doi": "doi", "inspire": "literature"}[kind]
    status, data = _engine_transport._get_json(f"{_INSPIRE}/{path}/{urllib.parse.quote(value, safe='')}")
    return _insp_record(data) if status == 200 and data and data.get("metadata") else None

def _inspire_search(title=None, author=None, words=None, year=None, size=10) -> list:
    clauses = []
    if title:
        clauses.append('t "%s"' % re.sub(r'["\\]', " ", _engine_text._strip_latex(title)).strip())
    if author:
        clauses.append(f"a {author}")
    if words and not title:
        clauses.append("(" + " or ".join(f"t {w}" for w in words[:4]) + ")")
    if year and (author or title):
        clauses.append(f"date {year - 1}->{year + 1}")
    if not clauses:
        return []
    q = urllib.parse.urlencode({"q": " and ".join(clauses), "size": size, "fields": _INSPIRE_FIELDS})
    status, data = _engine_transport._get_json(f"{_INSPIRE}/literature?{q}")
    if status != 200 or not data:
        return []
    return [_insp_record(h) for h in data.get("hits", {}).get("hits", [])]

_ADS = "https://api.adsabs.harvard.edu/v1"

_ADS_FL = "bibcode,title,author,year,doi,identifier,pub,abstract,doctype,citation_count,bibstem,property"

def _ads_arxiv_id(identifiers: list) -> str | None:
    for v in identifiers or []:
        m = re.match(r"^arxiv:(" + _engine_identifiers._ARXIV_CORE + r")$", str(v).strip(), re.I)
        if m:
            return m.group(1)
    return None

def _ads_record(doc: dict) -> _engine_models.Work:
    return _record(registry="ads", title=(doc.get("title") or [""])[0], authors=doc.get("author") or [],
                   year=_year(doc.get("year")), venue=doc.get("pub", ""),
                   doi=(doc.get("doi") or [None])[0], arxiv=_ads_arxiv_id(doc.get("identifier")),
                   bibcode=doc.get("bibcode"), abstract=doc.get("abstract", ""),
                   type=doc.get("doctype", ""), citation_count=doc.get("citation_count"),
                   url=f"https://ui.adsabs.harvard.edu/abs/{doc.get('bibcode')}/abstract")

def _ads_query(q: str, rows: int = 10) -> list:
    tok = _engine_credentials._ads_token()
    if not tok:
        return []
    url = f"{_ADS}/search/query?{urllib.parse.urlencode({'q': q, 'fl': _ADS_FL, 'rows': rows})}"
    status, data = _engine_transport._get_json(url, headers={"Authorization": f"Bearer {tok}"})
    if status == 401:
        raise RuntimeError("ADS rejected the API token (HTTP 401) — check ADS_API_TOKEN / ~/.ads/dev_key")
    if status != 200 or not data:
        return []
    return [_ads_record(d) for d in data.get("response", {}).get("docs", [])]

def _ads_lookup(kind: str, values: list) -> dict:
    """Batch lookup by arXiv id / DOI / bibcode. Returns {value.lower(): record}."""
    found = {}
    if not values or not _engine_credentials._ads_token():
        return found
    for chunk in _engine_transport._chunks(values, 25):
        if kind == "bibcode":
            q = "bibcode:(" + " OR ".join(f'"{v}"' for v in chunk) + ")"
        elif kind == "arxiv":
            q = "identifier:(" + " OR ".join(f'"arXiv:{v}"' for v in chunk) + ")"
        else:
            q = "doi:(" + " OR ".join(f'"{v}"' for v in chunk) + ")"
        for rec in _ads_query(q, rows=len(chunk) * 2):
            for key in (rec["bibcode"], rec["doi"], rec["arxiv"]):
                if key:
                    found[key.lower()] = rec
    return found

def _ads_search(title=None, author=None, words=None, year=None, rows=12) -> list:
    parts = []
    if author:
        parts.append('first_author:"%s"' % author.replace('"', ""))
    if year:
        parts.append(f"year:{year - 1}-{year + 1}")
    if title:
        parts.append('title:"%s"' % re.sub(r'["\\]', " ", _engine_text._strip_latex(title)).strip())
    elif words:
        parts.append("(" + " OR ".join(f"abs:{w}" for w in words[:5]) + ")")
    if not parts or (not title and not author):
        return []
    return _ads_query(" ".join(parts), rows=rows)

def _ads_export(bibcodes: list, journal_format: int = 2, max_author: int = 10,
                key_format: str | None = None) -> dict:
    """Official ADS BibTeX export. Returns {bibcode: bibtex_entry}."""
    tok = _engine_credentials._ads_token()
    if not tok or not bibcodes:
        return {}
    payload = {"bibcode": list(bibcodes), "journalformat": int(journal_format),
               "maxauthor": int(max_author), "authorcutoff": max(int(max_author), 1) + 190}
    if key_format:
        payload["keyformat"] = key_format
    status, body = _engine_transport._http(f"{_ADS}/export/bibtex", method="POST", data=json.dumps(payload).encode(),
                         headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
                         cache=False)
    if status != 200:
        return {}
    try:
        text = json.loads(body).get("export", "")
    except ValueError:
        return {}
    out = {}
    for entry in _engine_parsing._parse_bib(text)["entries"]:
        m = re.search(r"adsurl\s*=\s*\{[^}]*/abs/([^}/]+)", entry["raw"])
        bib = m.group(1) if m else entry["key"]
        out[bib] = entry["raw"]
    return out

_GITHUB_API = "https://api.github.com"

_GITHUB_RAW = "https://raw.githubusercontent.com"

_ZENODO_DOI = re.compile(r"^10\.5281/zenodo\.\d+$")

def _gh_api(path: str, accept: str | None = None, token: str | None = None) -> tuple:
    """(status, body) from the GitHub REST API. A spent rate limit raises
    instead of reading as "not found"."""
    hdrs = {"Accept": accept or "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    tok = token if token is not None else _engine_credentials._github_token()
    if tok:
        hdrs["Authorization"] = f"Bearer {tok}"
    status, body = _engine_transport._http(_GITHUB_API + path, headers=hdrs, cache=token is None)
    if status in (403, 429) and "rate limit" in (body or "").lower():
        raise RuntimeError("GitHub API rate limit reached (60 requests/hour without a token) — store a "
                           "token with `bash mcp/setup_mcp.sh --keys` or export GITHUB_TOKEN, or retry later")
    return status, body

def _gh_json(path: str, accept: str | None = None):
    status, body = _gh_api(path, accept)
    if status != 200:
        return status, None
    try:
        return status, json.loads(body)
    except ValueError:
        return status, None

def _cff_people(people) -> list:
    """CITATION.cff authors → [(name, is_entity)]; persons as 'Family, Given'."""
    out = []
    for p in people or []:
        if not isinstance(p, dict):
            continue
        fam = " ".join(str(p[k]).strip() for k in ("name-particle", "family-names") if p.get(k))
        if fam:
            given = " ".join(str(p[k]).strip() for k in ("given-names", "name-suffix") if p.get(k))
            out.append((f"{fam}, {given}" if given else fam, False))
        elif p.get("name"):
            out.append((str(p["name"]).strip(), True))
    return out

def _cff_ids(block: dict) -> dict:
    """DOI / arXiv id a CFF block declares: doi, identifiers[], url."""
    ids = {}
    vals = [block.get("doi")] + [i.get("value") for i in block.get("identifiers") or [] if isinstance(i, dict)]
    vals += [block.get("url")]
    for v in vals:
        if not v:
            continue
        k, val = _engine_identifiers._classify(str(v))
        if k in ("doi", "arxiv"):
            ids.setdefault(k, val)
    return ids

def _cff_load(text: str) -> tuple:
    try:
        import yaml
    except ImportError:
        return None, "PyYAML is missing, so CITATION.cff was not read — re-run mcp/setup_mcp.sh"
    try:
        d = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return None, f"CITATION.cff is not valid YAML ({type(exc).__name__})"
    return (d, None) if isinstance(d, dict) else (None, "CITATION.cff has no top-level mapping")

def _readme_ids(body: str) -> list:
    """DOIs and arXiv ids a README links or mentions, in order, deduplicated."""
    t = html.unescape(body or "")
    found = []
    for m in _engine_identifiers._DOI_ANY.finditer(t):
        raw = re.sub(r"(?:/status|/badge)?\.(?:svg|png|jpe?g)$", "", m.group(0).split("?")[0].rstrip(".,;)]"), flags=re.I)
        k, v = _engine_identifiers._classify(raw)
        if k in ("doi", "arxiv"):
            found.append(("doi:" if k == "doi" else "arXiv:") + v)
    for m in re.finditer(r"(?:arxiv\.org/(?:abs|pdf|html)/|arxiv:\s*)(" + _engine_identifiers._ARXIV_CORE + r")", t, re.I):
        found.append("arXiv:" + _engine_identifiers._strip_arxiv_version(m.group(1)))
    return list(dict.fromkeys(found))[:12]

def _zenodo_names_repo(doi: str, full_name: str) -> bool:
    """Is this Zenodo DOI a software archive of this repository? (the
    GitHub–Zenodo integration records the repository as a related URL)."""
    status, data = _engine_transport._get_json(f"https://api.datacite.org/dois/{urllib.parse.quote(doi, safe='')}")
    if status != 200 or not data:
        return False
    a = data.get("data", {}).get("attributes", {})
    if (a.get("types") or {}).get("resourceTypeGeneral") != "Software":
        return False
    want = f"github.com/{full_name}".lower()
    urls = [r.get("relatedIdentifier", "") for r in a.get("relatedIdentifiers") or []] + [a.get("url") or ""]
    return any(re.search(re.escape(want) + r"(?:\.git)?(?:[/#?]|$)", (u or "").lower()) for u in urls)

def _github_get(full: str, ref: str | None = None):
    """Repository record for owner/repo, or None when GitHub has no public
    repository there. Follows renames; reports private repositories."""
    status, r = _gh_json(f"/repos/{full}")
    if status in (404, 451) or (status == 200 and not r):
        return None
    if status != 200:
        raise RuntimeError(f"api.github.com: HTTP {status}")
    if r.get("private"):
        return {"error": f"github:{full} is a private repository — only public repositories can be cited",
                "final": True}
    full_name, owner = r["full_name"], r.get("owner") or {}
    info = {"full_name": full_name, "html_url": r.get("html_url"), "description": r.get("description") or "",
            "owner": owner.get("login"), "owner_type": owner.get("type"), "owner_name": None,
            "archived": bool(r.get("archived")), "fork": bool(r.get("fork")),
            "parent": (r.get("parent") or {}).get("full_name"), "stars": r.get("stargazers_count"),
            "license": (r.get("license") or {}).get("spdx_id"), "default_branch": r.get("default_branch"),
            "created": (r.get("created_at") or "")[:10], "pushed": (r.get("pushed_at") or "")[:10],
            "homepage": r.get("homepage") or None, "topics": r.get("topics") or [],
            "moved_from": full if full_name.lower() != full.lower() else None,
            "citation_file": None, "cff": None, "preferred_citation": None, "readme_ids": [],
            "software_doi_source": None, "notes": []}
    if ref:
        info["description"] = ""  # repository settings are not historical evidence
    title, authors, year, doi, abstract = r.get("name"), [], None, None, info["description"]

    status, text = _engine_transport._http(f"{_GITHUB_RAW}/{full_name}/{ref or 'HEAD'}/CITATION.cff")
    if status == 200 and text.strip():
        info["citation_file"] = "CITATION.cff"
        cff, problem = _cff_load(text)
        if problem:
            info["notes"].append(problem)
        if cff:
            people = _cff_people(cff.get("authors"))
            ids = _cff_ids(cff)
            info["cff"] = {"title": str(cff.get("title") or "").strip() or None, "authors": people,
                           "version": str(cff["version"]) if cff.get("version") is not None else None,
                           "date_released": str(cff.get("date-released") or "")[:10] or None,
                           "doi": ids.get("doi"), "url": cff.get("repository-code") or cff.get("url"),
                           "message": str(cff.get("message") or "").strip()[:300] or None}
            title = info["cff"]["title"] or title
            authors = [n for n, _ in people]
            year = _year(info["cff"]["date_released"])
            abstract = str(cff.get("abstract") or "").strip() or abstract
            if ids.get("doi"):
                doi, info["software_doi_source"] = ids["doi"], "CITATION.cff"
            pc = cff.get("preferred-citation")
            if isinstance(pc, dict):
                info["preferred_citation"] = {
                    "title": str(pc.get("title") or "").strip(), "authors": [n for n, _ in _cff_people(pc.get("authors"))][:6],
                    "year": _year(pc.get("year") or pc.get("date-published")), "type": pc.get("type"),
                    "ids": _cff_ids(pc), "source": "CITATION.cff preferred-citation"}
    if not info["preferred_citation"]:
        status, text = _engine_transport._http(f"{_GITHUB_RAW}/{full_name}/{ref or 'HEAD'}/CITATION.bib")
        entries = _engine_parsing._parse_bib(text)["entries"] if status == 200 else []
        if entries:
            e = entries[0]
            info["citation_file"] = info["citation_file"] or "CITATION.bib"
            info["preferred_citation"] = {
                "title": re.sub(r"[{}]", "", e["fields"].get("title", "")).strip(),
                "authors": _engine_text._split_bib_authors(e["fields"].get("author", ""))[:6],
                "year": _year(e["fields"].get("year")), "type": e["type"], "ids": _engine_parsing._entry_ids(e),
                "source": "CITATION.bib"}

    query = "?" + urllib.parse.urlencode({"ref": ref}) if ref else ""
    status, readme = _gh_api(f"/repos/{full_name}/readme{query}", accept="application/vnd.github.html+json")
    if status == 200:
        info["readme_ids"] = _readme_ids(readme)
    if not doi:
        for rid in info["readme_ids"]:
            d = rid[4:] if rid.startswith("doi:") else ""
            if _ZENODO_DOI.match(d) and _zenodo_names_repo(d, full_name):
                doi, info["software_doi_source"] = d, "Zenodo archive linked from the README"
                break
    if not authors:
        u_status, u = _gh_json(f"/users/{info['owner']}") if info["owner"] else (0, None)
        info["owner_name"] = (u or {}).get("name") or None
        authors = [info["owner_name"] or info["owner"]] if info["owner"] else []
    if info["archived"]:
        info["notes"].append("archived: the repository is read-only and no longer maintained")
    if info["fork"]:
        info["notes"].append(f"fork of {info['parent'] or 'another repository'} — cite the upstream "
                             "unless this fork is the work being cited")
    if info["moved_from"]:
        info["notes"].append(f"moved: {info['moved_from']} now redirects to {full_name} — update the URL")
    pc = info["preferred_citation"]
    if pc and pc.get("title"):
        target = next(iter(pc["ids"].values()), None)
        info["notes"].append(f"the authors ask that '{pc['title'][:90]}' be cited ({pc['source']})"
                             + (f" — add it too: bib_add(identifier='{target}')" if target else ""))
    return _record(registry="github", title=title or full_name, authors=authors, year=year, venue="GitHub",
                   doi=doi, github=full_name, abstract=abstract, type="software", url=info["html_url"],
                   citation_count=r.get("stargazers_count"), repo=info)

def _github_ref(full: str, ref: str) -> dict:
    """Does `ref` (tag, branch or commit; 'v' prefix tolerated) exist in the
    repository? found, the ref as it exists, its commit sha and date."""
    ref = (ref or "").strip()
    bare = re.sub(r"^v(?=\d)", "", ref, flags=re.I)
    for cand in dict.fromkeys([ref, bare, "v" + bare]):
        params = urllib.parse.urlencode({"sha": cand, "per_page": 1})
        status, data = _gh_json(f"/repos/{full}/commits?{params}")
        if status not in (200, 404, 422):
            raise RegistryLookupError("github", "unavailable", status)
        if status == 200 and isinstance(data, list) and data:
            c = data[0]
            return {"found": True, "ref": cand, "sha": c["sha"],
                    "date": ((c.get("commit") or {}).get("committer") or {}).get("date", "")[:10]}
    return {"found": False, "ref": ref}

def _gh_search_record(it: dict) -> _engine_models.Work:
    owner = it.get("owner") or {}
    return _record(registry="github", title=it.get("name", ""), authors=[owner.get("login")] if owner.get("login") else [],
                   venue="GitHub", github=it.get("full_name"), abstract=it.get("description") or "",
                   type="software", url=it.get("html_url", ""), citation_count=it.get("stargazers_count"),
                   repo={"full_name": it.get("full_name"), "description": it.get("description") or "",
                         "archived": bool(it.get("archived")), "fork": bool(it.get("fork")), "partial": True})

def _github_search(title=None, author=None, words=None, year=None, per_page=10) -> list:
    """Repository search by name/description — opt-in (registries=["github"])."""
    q = title or " ".join(words or [])
    if not q:
        return []
    params = urllib.parse.urlencode({"q": f"{q} in:name,description", "per_page": per_page})
    status, data = _gh_json(f"/search/repositories?{params}")
    if status != 200 or not data:
        return []
    return [_gh_search_record(it) for it in data.get("items") or []]

def _bib_escape(s: str) -> str:
    s = re.sub(r"[{}]", "", str(s or ""))
    return re.sub(r"(?<!\\)([_%#$])", r"\\\1", s)

def _github_pin(full: str, repo: dict, version: str | None) -> dict | None:
    """The state an entry cites: the requested tag / branch / commit, else the
    latest release, else the default branch's current commit. None when the
    requested version does not exist."""
    if not version:
        status, rel = _gh_json(f"/repos/{full}/releases/latest")
        if status == 200 and rel and rel.get("tag_name"):
            return {"version": rel["tag_name"], "note": None,
                    "year": (rel.get("published_at") or rel.get("created_at") or "")[:4]}
    ref = _github_ref(full, version or repo.get("default_branch") or "HEAD")
    if not ref["found"]:
        return None
    commit = f"Commit {ref['sha']} ({ref['date']})"
    if version and not re.match(r"^[0-9a-f]{7,40}$", ref["ref"]):
        return {"version": ref["ref"], "note": commit, "year": ref["date"][:4]}
    return {"version": None, "note": commit, "year": ref["date"][:4]}

def _github_bibtex(rec: typing.Mapping[str, typing.Any]) -> tuple:
    """(bibtex, source) for a repository with no registry export: laid out
    field for field from the authors' CITATION.cff (source citation-cff), else
    from the GitHub record with the cited version — rec["pin"], else the
    latest release, else the default branch's commit — pinned (source
    github). Never from model memory."""
    repo = rec.get("repo") or {}
    full = repo.get("full_name") or rec["github"]
    if repo.get("partial"):
        full_rec = _github_get(full)
        if not full_rec or full_rec.get("error"):
            return None, "github"
        rec, repo = dict(full_rec, pin=rec.get("pin")), full_rec["repo"]
    cff, version = repo.get("cff"), rec.get("pin")
    frozen_pin = None
    if rec.get("pinned_sha"):
        requested = rec.get("requested_version") or rec["pinned_sha"]
        date = rec.get("pinned_date") or ""
        frozen_pin = {
            "version": None if requested == rec["pinned_sha"] else requested,
            "note": f"Commit {rec['pinned_sha']} ({date})",
            "year": date[:4],
        }
    fields = []
    if cff and cff.get("title") and cff.get("authors"):
        source = "citation-cff"
        pin = frozen_pin or (_github_pin(full, repo, version) if version else None)
        if version and not pin:
            return None, source
        fields += [("author", " and ".join(("{%s}" % _bib_escape(n)) if ent else _bib_escape(n)
                                           for n, ent in cff["authors"])),
                   ("title", "{%s}" % _bib_escape(cff["title"]))]
        if pin:
            fields += [("version", _bib_escape(pin["version"] or "")), ("note", pin["note"])]
        elif cff.get("version"):
            fields.append(("version", _bib_escape(cff["version"])))
        if cff.get("doi"):
            fields.append(("doi", cff["doi"]))
        fields.append(("url", cff.get("url") or repo.get("html_url")))
        year = pin["year"] if pin else (cff.get("date_released") or "")[:4]
        fields.append(("year", year) if year else ("note", f"Accessed {_engine_persistence._today()}"))
    else:
        source = "github"
        pin = frozen_pin or _github_pin(full, repo, version)
        if not pin:
            return None, source
        owner = repo.get("owner_name") or repo.get("owner") or full.split("/")[0]
        entity = repo.get("owner_type") == "Organization" or not repo.get("owner_name")
        fields += [("author", ("{%s}" % _bib_escape(owner)) if entity else _bib_escape(owner)),
                   ("title", "{%s}" % _bib_escape(full.split("/")[1])),
                   ("version", _bib_escape(pin["version"] or "")), ("note", pin["note"])]
        if rec.get("doi"):
            fields.append(("doi", rec["doi"]))
        fields += [("publisher", "GitHub"), ("url", repo.get("html_url") or f"https://github.com/{full}"),
                   ("year", pin["year"])]
    if rec.get("pinned_sha"):
        fields = [(key, value) for key, value in fields if key != "url"]
        fields.append(("url", f"https://github.com/{full}/tree/{rec['pinned_sha']}"))
    body = ",\n".join(f"  {k} = {{{v}}}" for k, v in fields if v)
    return f"@software{{{_engine_identifiers._slug(full.replace('/', '_'))},\n{body}\n}}", source
