"""Pure identifier classification, hashes and source identity construction."""

import hashlib
import json
import re
import typing
import urllib.error
import urllib.parse
import urllib.request
from cite_check_engine import models as _engine_models
from cite_check_engine import config as _engine_config


_ARXIV_CORE = r"(?:\d{4}\.\d{4,5}|[a-z\-]+(?:\.[A-Za-z]{2})?/\d{7})"

_ARXIV_RE = re.compile(rf"^{_ARXIV_CORE}(?:v\d+)?$", re.I)

_ARXIV_ANY = re.compile(rf"(?<![\w/]){_ARXIV_CORE}(?:v\d+)?(?!\d)", re.I)

_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.I)

_DOI_ANY = re.compile(r"10\.\d{4,9}/[^\s\"'<>{}]+", re.I)

_BIBCODE_RE = re.compile(r"^\d{4}[A-Za-z0-9&.]{14}[A-Za-z.:]$")

_OPENALEX_RE = re.compile(r"^W\d{4,}$", re.I)

_GITHUB_RE = re.compile(r"^([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/([A-Za-z0-9._-]{1,100})$")

_GITHUB_ANY = re.compile(r"(?<!gist\.)github\.com[/:]([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/([A-Za-z0-9._-]{1,100})", re.I)

_GITHUB_REF = re.compile(r"github\.com/[^/\s]+/[^/\s]+/(?:tree|blob|commit|releases/tag)/([^/\s?#}]+)", re.I)

_GITHUB_RESERVED = {"about", "apps", "collections", "contact", "customer-stories", "enterprise", "events",
                    "explore", "features", "issues", "login", "marketplace", "new", "notifications", "orgs",
                    "organizations", "pricing", "pulls", "search", "security", "settings", "site", "sponsors",
                    "topics", "trending", "users"}

def _strip_arxiv_version(s: str) -> str:
    return re.sub(r"v\d+$", "", s, flags=re.I)

def _classify(raw: str) -> tuple:
    """Map any identifier spelling (bare, prefixed, or URL) to (kind, value).
    kind ∈ arxiv | doi | bibcode | openalex | inspire | github | unknown."""
    s = (raw or "").strip().strip("<>").rstrip(".,;)")
    s = re.sub(r"^(?:https?://)?(?:www\.)?", "", s, flags=re.I)
    m = re.match(r"^(arxiv|doi|bibcode|ads|openalex|inspire|github|gh):\s*(.+)$", s, re.I)
    prefix, s = (m.group(1).lower(), m.group(2).strip()) if m else (None, s)
    url_rules = [
        (r"^arxiv\.org/(?:abs|pdf|html)/(.+?)(?:\.pdf)?/?$", "arxiv"),
        (r"^(?:dx\.)?doi\.org/(.+)$", "doi"),
        (r"^ui\.adsabs\.harvard\.edu/abs/([^/]+)(?:/.*)?$", "bibcode"),
        (r"^(?:api\.)?openalex\.org/(?:works/)?(W\d+)$", "openalex"),
        (r"^inspirehep\.net/(?:literature|api/literature)/(\d+)", "inspire"),
        (r"^(?:git@)?github\.com[/:]([^/\s]+/[^/\s#?]+)", "github"),
    ]
    for pat, kind in url_rules:
        m = re.match(pat, s, re.I)
        if m:
            prefix, s = kind, m.group(1)
            break
    if prefix in ("ads",):
        prefix = "bibcode"
    if prefix == "gh":
        prefix = "github"
    if prefix == "github":
        m = _GITHUB_RE.match(re.sub(r"\.git$", "", s.split("#")[0].split("?")[0].rstrip("/"), flags=re.I))
        if m and m.group(1).lower() not in _GITHUB_RESERVED and m.group(2) not in (".", ".."):
            return "github", f"{m.group(1)}/{m.group(2)}".lower()
        return "unknown", raw
    if prefix == "arxiv" or (prefix is None and _ARXIV_RE.match(s)):
        s = urllib.parse.unquote(s)
        return ("arxiv", _strip_arxiv_version(s)) if _ARXIV_RE.match(s) else ("unknown", raw)
    if prefix == "doi" or (prefix is None and _DOI_RE.match(s)):
        s = urllib.parse.unquote(s).lower()
        m = re.match(r"^10\.48550/arxiv\.(.+)$", s)
        if m and _ARXIV_RE.match(m.group(1)):
            return "arxiv", _strip_arxiv_version(m.group(1))
        return ("doi", s) if _DOI_RE.match(s) else ("unknown", raw)
    if prefix == "bibcode" or (prefix is None and _BIBCODE_RE.match(s)):
        s = urllib.parse.unquote(s)
        return ("bibcode", s) if _BIBCODE_RE.match(s) else ("unknown", raw)
    if prefix == "openalex" or (prefix is None and _OPENALEX_RE.match(s)):
        return ("openalex", s.upper()) if _OPENALEX_RE.match(s) else ("unknown", raw)
    if prefix == "inspire" and s.isdigit():
        return "inspire", s
    return "unknown", raw

def _canonical(rec: typing.Mapping[str, typing.Any]) -> str:
    """Stable identity for the ledger and caches: DOI first (survives the
    preprint → journal transition), then arXiv, bibcode, OpenAlex, INSPIRE.
    A GitHub repository is always github:owner/repo — its software DOI, when
    it has one, is a field, so the DataCite record of that DOI never
    overwrites the repository's cached record."""
    if rec.get("github"):
        return f"github:{rec['github']}"
    for k, tag in (("doi", "doi"), ("arxiv", "arXiv"), ("bibcode", "bibcode"),
                   ("openalex", "openalex"), ("inspire", "inspire")):
        if rec.get(k):
            return f"{tag}:{rec[k]}"
    return ""

def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s)[:120]

def _cache_key(identifier: str) -> str:
    return hashlib.sha256(identifier.encode("utf-8")).hexdigest()

def _text_identity(rec: typing.Mapping[str, typing.Any]) -> str:
    version = rec.get("pinned_sha") or rec.get("arxiv_version")
    return _canonical(rec) + ("@" + version if version else "")

def _claim_hash(claim: str) -> str:
    # Whitespace is layout; scientific Unicode, case and citation markers are not.
    text = re.sub(r"\s+", " ", claim or "").strip()
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def _source_identity(
    meta: typing.Mapping[str, typing.Any], text: str
) -> _engine_models.SourceSnapshot:
    """Bind judgments to the actual cached bytes and acquisition policy."""
    return {
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "id": meta.get("id"), "basis": meta.get("basis"),
        "source": meta.get("source"), "version": meta.get("version"),
        "extraction": meta.get("extraction_version", "legacy"),
        "policy": _engine_config.EVIDENCE_POLICY,
    }

def _atomic_digest(value: object) -> str:
    """Hash exact JSON content without normalizing scientific symbols."""
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
