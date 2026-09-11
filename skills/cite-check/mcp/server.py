#!/usr/bin/env python3
"""cite-check MCP toolbox — citation existence, provenance and claim-support checks.

Dual interface, same code paths:

  python3 server.py                          # MCP stdio server (needs `mcp` pkg)
  python3 server.py call <tool> '<json>'     # CLI mode (no `mcp` pkg needed)

Every verdict the skill relies on is computed here rather than narrated by the
agent: registry lookups, title/author/year comparison, official BibTeX export,
verbatim-quote verification against the cited paper's own text, and the audit
gate. See skills/cite-check/SKILL.md and references/registries.md.
"""

import concurrent.futures
from collections import Counter
import difflib
import hashlib
import html
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html.parser import HTMLParser

VERSION = "0.1.0"

# ---------------------------------------------------------------------------
# configuration, cache, HTTP
# ---------------------------------------------------------------------------

CACHE_DIR = os.environ.get("CITE_CHECK_CACHE") or os.path.join(
    os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "cite-check")
META_TTL = int(os.environ.get("CITE_CHECK_TTL_DAYS", "14")) * 86400   # registry metadata
NEG_TTL = 86400                                                       # cached 404s
PROJECT_DIR = ".cite-check"                                           # per-manuscript state
MAX_PDF_BYTES = 40 * 1024 * 1024

# Registries publish these as their politeness rules (arXiv: one request per
# three seconds). Batched lookups keep the arXiv wait from dominating.
_HOST_INTERVAL = {
    "export.arxiv.org": 3.0, "arxiv.org": 1.0, "api.crossref.org": 0.15,
    "api.openalex.org": 0.15, "api.adsabs.harvard.edu": 0.25,
    "inspirehep.net": 0.5, "api.datacite.org": 0.25,
}
_host_last: dict = {}
_host_lock = threading.Lock()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cache_file(kind: str, name: str) -> str:
    d = os.path.join(CACHE_DIR, kind)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name)


# ---------------------------------------------------------------------------
# API keys — OS keychain when there is one, else a 0600 file. Secrets never
# travel through argv (visible in `ps`), harness config files, or logs.
# ---------------------------------------------------------------------------

_SERVICE = "cite-check"
KEYS = {
    "ads": {"label": "NASA ADS API token", "secret": True,
            "env": ("ADS_API_TOKEN", "ADS_DEV_KEY", "ADS_TOKEN"),
            "legacy_files": ("~/.ads/dev_key", "~/.config/cite-check/ads_token"),
            "url": "https://ui.adsabs.harvard.edu/user/settings/token",
            "enables": "ADS search, bibcode resolution and ADS BibTeX export (astronomy/physics)"},
    "mailto": {"label": "contact e-mail for the Crossref/OpenAlex polite pools", "secret": False,
               "env": ("CITE_CHECK_MAILTO",), "legacy_files": (), "url": None,
               "enables": "faster, more reliable Crossref and OpenAlex answers (optional, not a key)"},
}
_key_cache: dict = {"values": {}}


def _config_dir() -> str:
    return os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), _SERVICE)


def _keyring_backend() -> str | None:
    """'macos-keychain' | 'secret-tool' | None, probed once per process.
    CITE_CHECK_KEYRING=file forces the file store; =off disables stored keys."""
    if "backend" in _key_cache:
        return _key_cache["backend"]
    backend = None
    if os.environ.get("CITE_CHECK_KEYRING", "auto").lower() == "auto":
        try:
            if sys.platform == "darwin" and shutil.which("security"):
                backend = "macos-keychain"
            elif shutil.which("secret-tool") and os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
                r = subprocess.run(["secret-tool", "lookup", "service", _SERVICE, "key", "__probe__"],
                                   capture_output=True, text=True, timeout=8)
                if r.returncode in (0, 1) and not r.stderr.strip():   # 1 = not found, no daemon error
                    backend = "secret-tool"
        except (subprocess.TimeoutExpired, OSError):
            backend = None
    _key_cache["backend"] = backend
    return backend


def _keyring_get(name: str) -> str | None:
    b = _keyring_backend()
    try:
        if b == "macos-keychain":
            r = subprocess.run(["security", "find-generic-password", "-s", _SERVICE, "-a", name, "-w"],
                               capture_output=True, text=True, timeout=10)
        elif b == "secret-tool":
            r = subprocess.run(["secret-tool", "lookup", "service", _SERVICE, "key", name],
                               capture_output=True, text=True, timeout=10)
        else:
            return None
        return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None
    except (subprocess.TimeoutExpired, OSError):
        return None


def _keyring_set(name: str, value: str) -> bool:
    b = _keyring_backend()
    try:
        if b == "macos-keychain":   # `security -i` reads the command from stdin: the secret stays off argv
            cmd = f'add-generic-password -U -s "{_SERVICE}" -a "{name}" -l "{_SERVICE} {name}" -w "{value}"\n'
            r = subprocess.run(["security", "-i"], input=cmd, capture_output=True, text=True, timeout=15)
        elif b == "secret-tool":
            r = subprocess.run(["secret-tool", "store", f"--label={_SERVICE} {name}", "service", _SERVICE, "key", name],
                               input=value, capture_output=True, text=True, timeout=15)
        else:
            return False
        return r.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _keyring_delete(name: str) -> bool:
    b = _keyring_backend()
    try:
        if b == "macos-keychain":
            r = subprocess.run(["security", "delete-generic-password", "-s", _SERVICE, "-a", name],
                               capture_output=True, text=True, timeout=10)
        elif b == "secret-tool":
            r = subprocess.run(["secret-tool", "clear", "service", _SERVICE, "key", name],
                               capture_output=True, text=True, timeout=10)
        else:
            return False
        return r.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _file_key_path(name: str) -> str:
    return os.path.join(_config_dir(), "keys", name)


def _file_get(name: str) -> str | None:
    path = _file_key_path(name)
    if not os.path.exists(path):
        return None
    if os.stat(path).st_mode & 0o077:
        _key_cache.setdefault("warnings", []).append(f"{path} is readable by others — run: chmod 600 {path}")
    with open(path) as fh:
        return fh.read().strip() or None


def _file_set(name: str, value: str) -> None:
    path = _file_key_path(name)
    d = os.path.dirname(path)
    os.makedirs(d, mode=0o700, exist_ok=True)
    os.chmod(_config_dir(), 0o700)      # makedirs applies the mode to the leaf only
    os.chmod(d, 0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(value + "\n")
    os.chmod(path, 0o600)


def _config_read() -> dict:
    path = os.path.join(_config_dir(), "config.json")
    if os.path.exists(path):
        try:
            with open(path) as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}
    return {}


def _config_write(cfg: dict) -> None:
    os.makedirs(_config_dir(), mode=0o700, exist_ok=True)
    os.chmod(_config_dir(), 0o700)
    path = os.path.join(_config_dir(), "config.json")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(cfg, fh, indent=2)


def key_value(name: str) -> tuple:
    """(value | None, source) for a configured key: environment first, then
    the keychain, the 0600 file, legacy files; non-secrets from config.json.
    Cached per process — the keychain is a subprocess call."""
    spec = KEYS[name]
    for var in spec["env"]:
        if os.environ.get(var, "").strip():
            return os.environ[var].strip(), f"env:{var}"
    if name in _key_cache["values"]:
        return _key_cache["values"][name]
    value, source = None, "none"
    if os.environ.get("CITE_CHECK_KEYRING", "auto").lower() != "off":
        if spec["secret"]:
            value = _keyring_get(name)
            source = _keyring_backend() or "none"
            if not value:
                value, source = _file_get(name), "file"
            if not value:
                for lf in spec["legacy_files"]:
                    path = os.path.expanduser(lf)
                    if os.path.exists(path):
                        with open(path) as fh:
                            value = fh.read().strip() or None
                        if value:
                            source = f"legacy-file:{lf}"
                            break
        else:
            value, source = _config_read().get(name), "config"
    if not value:
        source = "none"
    _key_cache["values"][name] = (value, source)
    return value, source


def _mask(value: str) -> str:
    return ("…" + value[-4:]) if len(value) >= 8 else "…"


def _ads_test(token: str) -> dict:
    """Live check of a token against ADS (one tiny query, not cached)."""
    url = f"{_ADS}/search/query?{urllib.parse.urlencode({'q': 'bibcode:2016A&A...594A..13P', 'fl': 'bibcode', 'rows': 1})}"
    try:
        status, _ = _http(url, headers={"Authorization": f"Bearer {token}"}, cache=False, timeout=20)
    except RuntimeError as exc:
        return {"ok": None, "detail": f"could not reach ADS ({exc}); stored untested"}
    if status == 200:
        return {"ok": True, "detail": "ADS accepted the token"}
    if status == 401:
        return {"ok": False, "detail": "ADS rejected the token (HTTP 401)"}
    return {"ok": None, "detail": f"ADS answered HTTP {status}; stored untested"}


def key_store(name: str, value: str, test: bool = True) -> dict:
    if name not in KEYS:
        return {"stored": False, "error": f"unknown key {name!r}; one of {list(KEYS)}"}
    spec, value = KEYS[name], (value or "").strip()
    if not value:
        return {"stored": False, "error": "empty value — nothing stored"}
    if spec["secret"] and re.search(r"[\s\"']", value):
        return {"stored": False, "error": "a token cannot contain whitespace or quotes — check the paste"}
    if name == "mailto" and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", value):
        return {"stored": False, "error": "that does not look like an e-mail address"}
    tested = None
    if name == "ads" and test:
        tested = _ads_test(value)
        if tested["ok"] is False:
            return {"stored": False, "error": tested["detail"], "tested": tested}
    if spec["secret"]:
        backend = _keyring_backend() if os.environ.get("CITE_CHECK_KEYRING", "auto").lower() == "auto" else None
        if backend and _keyring_set(name, value):
            _file_delete(name)
        else:
            _file_set(name, value)
            backend = "file"
    else:
        cfg = _config_read()
        cfg[name] = value
        _config_write(cfg)
        backend = "config"
    _key_cache["values"].pop(name, None)
    return {"stored": True, "backend": backend, "masked": _mask(value) if spec["secret"] else value,
            "tested": tested, "where": _file_key_path(name) if backend == "file" else
            (os.path.join(_config_dir(), "config.json") if backend == "config" else backend)}


def _file_delete(name: str) -> bool:
    path = _file_key_path(name)
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


def key_delete(name: str) -> dict:
    if name not in KEYS:
        return {"deleted": False, "error": f"unknown key {name!r}"}
    removed = []
    if KEYS[name]["secret"]:
        if _keyring_delete(name):
            removed.append(_keyring_backend())
        if _file_delete(name):
            removed.append("file")
    else:
        cfg = _config_read()
        if name in cfg:
            del cfg[name]
            _config_write(cfg)
            removed.append("config")
    _key_cache["values"].pop(name, None)
    return {"deleted": bool(removed), "removed_from": removed}


def key_status() -> list:
    out = []
    for name, spec in KEYS.items():
        value, source = key_value(name)
        out.append({"name": name, "label": spec["label"], "secret": spec["secret"], "url": spec["url"],
                    "enables": spec["enables"], "configured": bool(value), "source": source,
                    "masked": (_mask(value) if spec["secret"] else value) if value else None})
    return out


def _mailto() -> str:
    return (key_value("mailto")[0] or "").strip()


def _user_agent() -> str:
    ua = f"cite-check/{VERSION} (+https://github.com/biprateep/science-skills"
    return ua + (f"; mailto:{_mailto()})" if _mailto() else ")")


def _throttle(host: str) -> None:
    interval = _HOST_INTERVAL.get(host, 0.2)
    with _host_lock:
        wait = _host_last.get(host, 0.0) + interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _host_last[host] = time.monotonic()


def _http(url: str, method: str = "GET", data: bytes | None = None, headers: dict | None = None,
          timeout: int = 30, cache: bool = True, binary: bool = False, retries: int = 3):
    """Return (status, body). body is str, or bytes when binary=True.

    200 and 404 text responses are cached (404 for one day: a fabricated
    identifier stays fabricated; a freshly minted DOI shows up tomorrow).
    429/5xx are retried with backoff. Network failure raises RuntimeError.
    """
    hdrs = {"User-Agent": _user_agent(), "Accept": "application/json, text/plain, */*"}
    hdrs.update(headers or {})
    cache_key = hashlib.sha1(
        f"{method} {url} {data.decode('utf-8', 'replace') if data else ''} "
        f"{hdrs.get('Accept', '')}".encode()).hexdigest()
    path = _cache_file("http", cache_key + ".json")
    if cache and not binary and os.path.exists(path):
        try:
            with open(path) as fh:
                hit = json.load(fh)
            ttl = META_TTL if hit["status"] == 200 else NEG_TTL
            if time.time() - hit["at"] < ttl:
                return hit["status"], hit["body"]
        except (OSError, ValueError, KeyError):
            pass
    host = urllib.parse.urlparse(url).netloc
    last_error = None
    for attempt in range(1, retries + 1):
        _throttle(host)
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                status = resp.status
            body = raw if binary else raw.decode("utf-8", errors="replace")
            if cache and not binary and status == 200:
                with open(path, "w") as fh:
                    json.dump({"status": status, "body": body, "at": time.time(), "url": url}, fh)
            return status, body
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                try:
                    delay = float(retry_after) if retry_after else 2.0 ** attempt
                except ValueError:
                    delay = 2.0 ** attempt
                time.sleep(min(delay, 30))
                last_error = exc
                continue
            body = b"" if binary else exc.read().decode("utf-8", errors="replace")
            if cache and not binary and exc.code == 404:
                with open(path, "w") as fh:
                    json.dump({"status": 404, "body": "", "at": time.time(), "url": url}, fh)
            return exc.code, body
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(2.0 ** attempt)
                continue
    raise RuntimeError(f"{host}: {type(last_error).__name__}: {last_error}")


def _get_json(url: str, headers: dict | None = None, timeout: int = 30):
    status, body = _http(url, headers=headers, timeout=timeout)
    if status != 200:
        return status, None
    try:
        return status, json.loads(body)
    except ValueError:
        return status, None


def _chunks(seq, n):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


# ---------------------------------------------------------------------------
# text normalisation, similarity, names
# ---------------------------------------------------------------------------

_STOPWORDS = set("""a an and are as at be been but by can could did do does for from had has have
he her his how i if in into is it its may might more most no nor not of on one or our
own same she should so some such than that the their them then there these they this
those through to too under until up upon us use used using very via was we were what when made make makes based
where which while who whom why will with within without would you your also however
here paper show shows shown results result recent new find found given""".split())


def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()


def _strip_latex(s: str) -> str:
    s = re.sub(r"\\[a-zA-Z]+\*?\s*(?:\[[^\]]*\])?", " ", s or "")
    return s.replace("{", "").replace("}", "").replace("$", "").replace("~", " ")


def _norm_title(s: str) -> str:
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    s = _ascii(_strip_latex(s)).lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _title_sim(a: str, b: str) -> float:
    """Normalised title similarity in [0, 1]. Sequence ratio, or token
    containment for titles that merely reorder or extend each other (a
    Crossref title+subtitle against the same title written on one line)."""
    na, nb = _norm_title(a), _norm_title(b)
    if not na or not nb:
        return 0.0
    ratio = difflib.SequenceMatcher(None, na, nb).ratio()
    ta, tb = set(na.split()), set(nb.split())
    lo, hi = min(len(ta), len(tb)), max(len(ta), len(tb))
    if lo >= 4:      # word-order shuffles count; a title that merely contains the other does not
        ratio = max(ratio, 0.97 * (len(ta & tb) / lo) * (lo / hi) ** 0.35)
    return round(ratio, 3)


_PARTICLES = {"da", "de", "del", "della", "der", "di", "du", "la", "le", "van", "von", "den", "ter", "af"}
_COLLAB = re.compile(r"\b(collaboration|consortium|team|group|survey)\b", re.I)


def _surname(name: str) -> str:
    """Comparable surname token: 'Vaswani, Ashish' / 'Ashish Vaswani' / '{Planck
    Collaboration}' / 'van der Waals, J.' all reduce to one lowercase string."""
    name = _ascii(html.unescape(_strip_latex(name or ""))).strip()
    if not name:
        return ""
    if _COLLAB.search(name):
        words = [w for w in re.split(r"\s+", name) if w and not _COLLAB.match(w)
                 and w.lower() not in ("the", "scientific", "and")]
        return re.sub(r"[^a-z]", "", "".join(words).lower())
    if "," in name:
        fam = name.split(",", 1)[0]
    else:
        toks = name.split()
        fam = toks[-1] if toks else ""
        i = len(toks) - 2
        while i >= 0 and toks[i].lower() in _PARTICLES:   # J. D. van der Waals
            fam = toks[i] + fam
            i -= 1
    return re.sub(r"[^a-z]", "", fam.lower())


def _split_bib_authors(field: str) -> list:
    field = (field or "").replace("\n", " ")
    parts = re.split(r"\s+and\s+", field, flags=re.I)
    return [p.strip(" {}") for p in parts if p.strip(" {}")]


def _author_match(a: list, b: list) -> dict:
    """Compare two author lists (any name format). first: first surnames agree;
    any: some surname of a appears in b."""
    sa = [_surname(x) for x in (a or []) if _surname(x)]
    sb = [_surname(x) for x in (b or []) if _surname(x)]
    if not sa or not sb:
        return {"first": None, "any": None}
    return {"first": sa[0] == sb[0] or sa[0] in sb[0] or sb[0] in sa[0],
            "any": bool(set(sa) & set(sb))}


def _content_words(text: str) -> list:
    text = re.sub(r"\u27e8[^\u27e9]*\u27e9", " ", text or "")       # ⟨cite:…⟩ placeholders
    text = _ascii(_strip_latex(html.unescape(text))).lower()
    words = re.findall(r"[a-z][a-z0-9\-]{2,}|\d+(?:\.\d+)?", text)
    out = []
    for w in words:
        if w in _STOPWORDS:
            continue
        out.append(_stem(w))
    return out


def _stem(w: str) -> str:
    for suf in ("ies", "sses", "ing", "ed", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[:-len("ies")] + "y" if suf == "ies" else w[:-len(suf)]
    return w


# ---------------------------------------------------------------------------
# identifiers
# ---------------------------------------------------------------------------

_ARXIV_CORE = r"(?:\d{4}\.\d{4,5}|[a-z\-]+(?:\.[A-Za-z]{2})?/\d{7})"
_ARXIV_RE = re.compile(rf"^{_ARXIV_CORE}(?:v\d+)?$", re.I)
_ARXIV_ANY = re.compile(rf"(?<![\w/]){_ARXIV_CORE}(?:v\d+)?(?!\d)", re.I)
_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.I)
_DOI_ANY = re.compile(r"10\.\d{4,9}/[^\s\"'<>{}]+", re.I)
_BIBCODE_RE = re.compile(r"^\d{4}[A-Za-z0-9&.]{14}[A-Za-z.:]$")
_OPENALEX_RE = re.compile(r"^W\d{4,}$", re.I)


def _strip_arxiv_version(s: str) -> str:
    return re.sub(r"v\d+$", "", s, flags=re.I)


def _classify(raw: str) -> tuple:
    """Map any identifier spelling (bare, prefixed, or URL) to (kind, value).
    kind ∈ arxiv | doi | bibcode | openalex | inspire | unknown."""
    s = (raw or "").strip().strip("<>").rstrip(".,;)")
    s = re.sub(r"^(?:https?://)?(?:www\.)?", "", s, flags=re.I)
    m = re.match(r"^(arxiv|doi|bibcode|ads|openalex|inspire):\s*(.+)$", s, re.I)
    prefix, s = (m.group(1).lower(), m.group(2).strip()) if m else (None, s)
    url_rules = [
        (r"^arxiv\.org/(?:abs|pdf|html)/(.+?)(?:\.pdf)?/?$", "arxiv"),
        (r"^(?:dx\.)?doi\.org/(.+)$", "doi"),
        (r"^ui\.adsabs\.harvard\.edu/abs/([^/]+)(?:/.*)?$", "bibcode"),
        (r"^(?:api\.)?openalex\.org/(?:works/)?(W\d+)$", "openalex"),
        (r"^inspirehep\.net/(?:literature|api/literature)/(\d+)", "inspire"),
    ]
    for pat, kind in url_rules:
        m = re.match(pat, s, re.I)
        if m:
            prefix, s = kind, m.group(1)
            break
    if prefix in ("ads",):
        prefix = "bibcode"
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


def _canonical(rec: dict) -> str:
    """Stable identity for the ledger and caches: DOI first (survives the
    preprint → journal transition), then arXiv, bibcode, OpenAlex, INSPIRE."""
    for k, tag in (("doi", "doi"), ("arxiv", "arXiv"), ("bibcode", "bibcode"),
                   ("openalex", "openalex"), ("inspire", "inspire")):
        if rec.get(k):
            return f"{tag}:{rec[k]}"
    return ""


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s)[:120]


# ---------------------------------------------------------------------------
# registry clients — every function returns the same record shape:
#   {registry, title, authors[], year, venue, doi, arxiv, bibcode, openalex,
#    inspire, abstract, type, url, citation_count, pdf_urls[]}
# ---------------------------------------------------------------------------

def _record(**kw) -> dict:
    rec = {"registry": None, "title": "", "authors": [], "year": None, "venue": "",
           "doi": None, "arxiv": None, "bibcode": None, "openalex": None, "inspire": None,
           "abstract": "", "type": "", "url": "", "citation_count": None, "pdf_urls": []}
    rec.update({k: v for k, v in kw.items() if v is not None})
    if rec["doi"]:
        rec["doi"] = rec["doi"].lower()
        m = re.match(r"^10\.48550/arxiv\.(.+)$", rec["doi"])
        if m and _ARXIV_RE.match(m.group(1)):          # DataCite's arXiv DOIs: one identity, not two
            rec["arxiv"], rec["doi"] = rec["arxiv"] or _strip_arxiv_version(m.group(1)), None
    if rec["arxiv"]:
        rec["arxiv"] = _strip_arxiv_version(rec["arxiv"])
    return rec


def _year(v) -> int | None:
    m = re.search(r"(19|20)\d{2}", str(v or ""))
    return int(m.group(0)) if m else None


# --- arXiv -------------------------------------------------------------------

_ATOM = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom"}
_ARXIV_API = "https://export.arxiv.org/api/query"


def _arxiv_parse(body: str) -> list:
    out = []
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return out
    for e in root.findall("a:entry", _ATOM):
        title = re.sub(r"\s+", " ", e.findtext("a:title", "", _ATOM)).strip()
        eid = e.findtext("a:id", "", _ATOM)
        if not title or title == "Error" or "/api/errors" in eid:
            continue
        m = re.search(r"arxiv\.org/abs/(.+)$", eid)
        aid = _strip_arxiv_version(m.group(1)) if m else None
        cat = e.find("x:primary_category", _ATOM)
        out.append(_record(
            registry="arxiv", title=title, arxiv=aid,
            authors=[a.findtext("a:name", "", _ATOM) for a in e.findall("a:author", _ATOM)],
            year=_year(e.findtext("a:published", "", _ATOM)),
            doi=(e.findtext("x:doi", "", _ATOM) or None),
            venue=(e.findtext("x:journal_ref", "", _ATOM) or "arXiv"),
            abstract=re.sub(r"\s+", " ", e.findtext("a:summary", "", _ATOM)).strip(),
            type="preprint", url=f"https://arxiv.org/abs/{aid}" if aid else eid,
            primary_class=cat.get("term") if cat is not None else None,
            pdf_urls=[f"https://arxiv.org/pdf/{aid}"] if aid else []))
    return out


def _arxiv_lookup(ids: list) -> dict:
    found = {}
    for chunk in _chunks(ids, 50):
        status, body = _http(f"{_ARXIV_API}?id_list={','.join(chunk)}&max_results={len(chunk)}")
        if status != 200:
            continue
        for rec in _arxiv_parse(body):
            found[rec["arxiv"].lower()] = rec
    return found


def _arxiv_query(q: str, max_results: int = 10) -> list:
    url = f"{_ARXIV_API}?search_query={urllib.parse.quote(q)}&max_results={max_results}"
    status, body = _http(url)
    return _arxiv_parse(body) if status == 200 else []


def _arxiv_search(title=None, author=None, words=None, year=None, max_results=10) -> list:
    parts = []
    if title:
        parts.append('ti:"%s"' % re.sub(r'["\\]', " ", _strip_latex(title)).strip())
    if author:
        parts.append('au:"%s"' % author.replace('"', ""))
    if words and not title:
        parts.append("(" + " OR ".join(f"ti:{w} OR abs:{w}" for w in words[:4]) + ")")
    if year and (author or title):
        parts.append(f"submittedDate:[{year - 1}01010000 TO {year + 1}12312359]")
    return _arxiv_query(" AND ".join(parts), max_results) if parts else []


# --- Crossref / DataCite ------------------------------------------------------

_CROSSREF = "https://api.crossref.org/works"


def _cr_record(msg: dict) -> dict:
    title = " ".join(msg.get("title") or []).strip()
    sub = " ".join(msg.get("subtitle") or []).strip()
    if sub and _norm_title(sub) not in _norm_title(title):
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
                   citation_count=msg.get("is-referenced-by-count"), pdf_urls=pdfs)


def _crossref_work(doi: str):
    status, data = _get_json(f"{_CROSSREF}/{urllib.parse.quote(doi, safe='')}")
    return _cr_record(data["message"]) if status == 200 and data else None


def _crossref_search(title=None, author=None, words=None, year=None, rows=10) -> list:
    params = {"rows": rows, "select": "DOI,title,subtitle,author,issued,published-print,"
                                      "published-online,created,container-title,type,"
                                      "is-referenced-by-count,abstract,link,URL"}
    biblio = _strip_latex(title) if title else " ".join(words or [])
    if biblio.strip():
        params["query.bibliographic"] = biblio.strip()
    if author:
        params["query.author"] = author
    if year:
        params["filter"] = f"from-pub-date:{year - 1}-01-01,until-pub-date:{year + 1}-12-31"
    if _mailto():
        params["mailto"] = _mailto()
    if "query.bibliographic" not in params and "query.author" not in params:
        return []
    status, data = _get_json(f"{_CROSSREF}?{urllib.parse.urlencode(params)}")
    if status != 200 or not data:
        return []
    return [_cr_record(m) for m in data.get("message", {}).get("items", [])]


def _datacite_doi(doi: str):
    status, data = _get_json(f"https://api.datacite.org/dois/{urllib.parse.quote(doi, safe='')}")
    if status != 200 or not data:
        return None
    a = data.get("data", {}).get("attributes", {})
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


# --- OpenAlex -----------------------------------------------------------------

_OPENALEX = "https://api.openalex.org/works"


def _oa_abstract(inv: dict | None) -> str:
    if not inv:
        return ""
    pos = sorted((p, w) for w, ps in inv.items() for p in ps)
    return " ".join(w for _, w in pos)


def _oa_record(w: dict) -> dict:
    ids = w.get("ids") or {}
    doi = (ids.get("doi") or w.get("doi") or "").replace("https://doi.org/", "") or None
    arxiv = None
    for loc in [w.get("primary_location")] + (w.get("locations") or []):
        for u in ((loc or {}).get("landing_page_url"), (loc or {}).get("pdf_url")):
            m = re.search(r"arxiv\.org/(?:abs|pdf)/(" + _ARXIV_CORE + r")", u or "", re.I)
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
    if _mailto():
        extra = dict(extra, mailto=_mailto())
    return urllib.parse.urlencode(extra)


def _openalex_get(ident: str):
    status, data = _get_json(f"{_OPENALEX}/{urllib.parse.quote(ident, safe=':/')}?{_oa_params({})}")
    return _oa_record(data) if status == 200 and data else None


def _openalex_batch_dois(dois: list) -> dict:
    found = {}
    for chunk in _chunks(dois, 40):
        q = _oa_params({"filter": "doi:" + "|".join(chunk), "per-page": 50})
        status, data = _get_json(f"{_OPENALEX}?{q}")
        for w in (data or {}).get("results", []) if status == 200 else []:
            rec = _oa_record(w)
            if rec["doi"]:
                found[rec["doi"]] = rec
    return found


def _openalex_search(title=None, author=None, words=None, year=None, per_page=10) -> list:
    search = _strip_latex(title) if title else " ".join(words or [])
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
    status, data = _get_json(f"{_OPENALEX}?{_oa_params(params)}")
    if status != 200 and author:          # filter syntax rejected: retry without it
        params["filter"] = ",".join(f for f in filters if not f.startswith("raw_author"))
        status, data = _get_json(f"{_OPENALEX}?{_oa_params(params)}")
    if status != 200 or not data:
        return []
    return [_oa_record(w) for w in data.get("results", [])]


# --- INSPIRE-HEP --------------------------------------------------------------

_INSPIRE = "https://inspirehep.net/api"
_INSPIRE_FIELDS = ("titles,authors.full_name,dois,arxiv_eprints,publication_info,earliest_date,"
                   "abstracts,control_number,citation_count,document_type,imprints")


def _insp_record(hit: dict) -> dict:
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
    status, data = _get_json(f"{_INSPIRE}/{path}/{urllib.parse.quote(value, safe='')}")
    return _insp_record(data) if status == 200 and data and data.get("metadata") else None


def _inspire_search(title=None, author=None, words=None, year=None, size=10) -> list:
    clauses = []
    if title:
        clauses.append('t "%s"' % re.sub(r'["\\]', " ", _strip_latex(title)).strip())
    if author:
        clauses.append(f"a {author}")
    if words and not title:
        clauses.append("(" + " or ".join(f"t {w}" for w in words[:4]) + ")")
    if year and (author or title):
        clauses.append(f"date {year - 1}->{year + 1}")
    if not clauses:
        return []
    q = urllib.parse.urlencode({"q": " and ".join(clauses), "size": size, "fields": _INSPIRE_FIELDS})
    status, data = _get_json(f"{_INSPIRE}/literature?{q}")
    if status != 200 or not data:
        return []
    return [_insp_record(h) for h in data.get("hits", {}).get("hits", [])]


# --- NASA ADS -----------------------------------------------------------------

_ADS = "https://api.adsabs.harvard.edu/v1"
_ADS_FL = "bibcode,title,author,year,doi,identifier,pub,abstract,doctype,citation_count,bibstem,property"


def _ads_token() -> str:
    return key_value("ads")[0] or ""


def _ads_arxiv_id(identifiers: list) -> str | None:
    for v in identifiers or []:
        m = re.match(r"^arxiv:(" + _ARXIV_CORE + r")$", str(v).strip(), re.I)
        if m:
            return m.group(1)
    return None


def _ads_record(doc: dict) -> dict:
    return _record(registry="ads", title=(doc.get("title") or [""])[0], authors=doc.get("author") or [],
                   year=_year(doc.get("year")), venue=doc.get("pub", ""),
                   doi=(doc.get("doi") or [None])[0], arxiv=_ads_arxiv_id(doc.get("identifier")),
                   bibcode=doc.get("bibcode"), abstract=doc.get("abstract", ""),
                   type=doc.get("doctype", ""), citation_count=doc.get("citation_count"),
                   url=f"https://ui.adsabs.harvard.edu/abs/{doc.get('bibcode')}/abstract")


def _ads_query(q: str, rows: int = 10) -> list:
    tok = _ads_token()
    if not tok:
        return []
    url = f"{_ADS}/search/query?{urllib.parse.urlencode({'q': q, 'fl': _ADS_FL, 'rows': rows})}"
    status, data = _get_json(url, headers={"Authorization": f"Bearer {tok}"})
    if status == 401:
        raise RuntimeError("ADS rejected the API token (HTTP 401) — check ADS_API_TOKEN / ~/.ads/dev_key")
    if status != 200 or not data:
        return []
    return [_ads_record(d) for d in data.get("response", {}).get("docs", [])]


def _ads_lookup(kind: str, values: list) -> dict:
    """Batch lookup by arXiv id / DOI / bibcode. Returns {value.lower(): record}."""
    found = {}
    if not values or not _ads_token():
        return found
    for chunk in _chunks(values, 25):
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
        parts.append('title:"%s"' % re.sub(r'["\\]', " ", _strip_latex(title)).strip())
    elif words:
        parts.append("(" + " OR ".join(f"abs:{w}" for w in words[:5]) + ")")
    if not parts or (not title and not author):
        return []
    return _ads_query(" ".join(parts), rows=rows)


def _ads_export(bibcodes: list, journal_format: int = 2, max_author: int = 10,
                key_format: str | None = None) -> dict:
    """Official ADS BibTeX export. Returns {bibcode: bibtex_entry}."""
    tok = _ads_token()
    if not tok or not bibcodes:
        return {}
    payload = {"bibcode": list(bibcodes), "journalformat": int(journal_format),
               "maxauthor": int(max_author), "authorcutoff": max(int(max_author), 1) + 190}
    if key_format:
        payload["keyformat"] = key_format
    status, body = _http(f"{_ADS}/export/bibtex", method="POST", data=json.dumps(payload).encode(),
                         headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
                         cache=False)
    if status != 200:
        return {}
    try:
        text = json.loads(body).get("export", "")
    except ValueError:
        return {}
    out = {}
    for entry in _parse_bib(text)["entries"]:
        m = re.search(r"adsurl\s*=\s*\{[^}]*/abs/([^}/]+)", entry["raw"])
        bib = m.group(1) if m else entry["key"]
        out[bib] = entry["raw"]
    return out


# ---------------------------------------------------------------------------
# resolve — identifier → bibliographic record from the registry that owns it
# ---------------------------------------------------------------------------

_AUTHORITY = {"ads": 5, "crossref": 4, "datacite": 4, "inspire": 3, "openalex": 2, "arxiv": 1}
_ID_KEYS = ("doi", "arxiv", "bibcode", "openalex", "inspire")


def _record_cache_put(rec: dict) -> None:
    cid = _canonical(rec)
    if cid:
        with open(_cache_file("records", _slug(cid) + ".json"), "w") as fh:
            json.dump(rec, fh)


def _record_cache_get(cid: str, max_age: float | None = None) -> dict | None:
    path = _cache_file("records", _slug(cid) + ".json")
    if os.path.exists(path) and (max_age is None or time.time() - os.path.getmtime(path) < max_age):
        with open(path) as fh:
            return json.load(fh)
    return None


def _alias_put(kind: str, value: str, cid: str) -> None:
    with open(_cache_file("records", "alias_" + _slug(f"{kind}_{value}") + ".json"), "w") as fh:
        json.dump({"id": cid}, fh)


def _alias_get(kind: str, value: str) -> str | None:
    path = _cache_file("records", "alias_" + _slug(f"{kind}_{value}") + ".json")
    if os.path.exists(path):
        with open(path) as fh:
            return json.load(fh).get("id")
    return None


def _merge_records(base: dict, extra: dict) -> dict:
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
    return out


def _public(rec: dict, raw: str, kind: str) -> dict:
    return {"resolved": True, "input": raw, "kind": kind, "id": _canonical(rec),
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
    kinds = [_classify(i) for i in identifiers]
    arxiv_ids = sorted({v for k, v in kinds if k == "arxiv"})
    dois = sorted({v for k, v in kinds if k == "doi"})
    bibcodes = sorted({v for k, v in kinds if k == "bibcode"})
    others = sorted({(k, v) for k, v in kinds if k in ("openalex", "inspire")})

    arxiv_found = _arxiv_lookup(arxiv_ids) if arxiv_ids else {}

    def by_doi(d):
        try:
            return d, (_crossref_work(d) or _datacite_doi(d))
        except RuntimeError as exc:
            return d, {"error": str(exc)}

    def by_other(kv):
        k, v = kv
        try:
            return kv, (_openalex_get(v) if k == "openalex" else _inspire_get("inspire", v))
        except RuntimeError as exc:
            return kv, {"error": str(exc)}

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        doi_found = dict(ex.map(by_doi, dois))
        other_found = dict(ex.map(by_other, others))

    ads, ads_error = {}, None
    if _ads_token():
        try:
            ads.update(_ads_lookup("arxiv", arxiv_ids))
            ads.update(_ads_lookup("doi", dois))
            ads.update(_ads_lookup("bibcode", bibcodes))
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
            reason = ads_error or ("bibcode not found in ADS" if _ads_token() else
                                   "bibcode lookup needs an ADS API token (ADS_API_TOKEN or ~/.ads/dev_key)")
        elif kind in ("openalex", "inspire"):
            rec = other_found.get((kind, value))
            reason = f"{kind} returned no record for {value}"
        else:
            reason = ("unrecognized identifier — expected an arXiv id, DOI (10.*), ADS bibcode, "
                      "OpenAlex Wnnn, or inspire:nnn")
        if isinstance(rec, dict) and rec.get("error"):
            reason, rec = rec["error"], None
        if not rec:
            results.append({"resolved": False, "input": raw, "kind": kind, "reason": reason})
            continue
        rec = dict(rec)
        rec.setdefault("registries", [rec["registry"]])
        for key in (rec.get("arxiv"), rec.get("doi"), rec.get("bibcode")):
            hit = ads.get((key or "").lower())
            if hit and hit is not rec:
                rec = _merge_records(rec, hit)
                break
        _record_cache_put(rec)
        _alias_put(kind, value, _canonical(rec))
        results.append(_public(rec, raw, kind))
    return results


def resolve_citation(identifier) -> dict:
    """Resolve an identifier (or a list of them) to real bibliographic metadata.

    Accepts arXiv ids, DOIs, ADS bibcodes, OpenAlex W-ids, inspire:nnn, in bare,
    prefixed or URL form. resolved=false with a reason when the registry has no
    such record. A resolved result is existence only — verify_bib / search
    compare titles, authors and years to catch real ids attached to the wrong
    paper.
    """
    many = isinstance(identifier, list)
    idents = [str(x) for x in (identifier if many else [identifier])]
    try:
        res = _resolve_many(idents)
    except RuntimeError as exc:
        return {"error": f"registry lookup failed ({exc}) — retry, or mark the citation UNVERIFIED"}
    if many:
        return {"results": res, "resolved": all(r.get("resolved") for r in res), "n": len(res)}
    return res[0]


def _full_record(identifier) -> dict | None:
    """The internal record (with abstract and pdf urls) for an identifier —
    from the local record cache when it was resolved within the TTL (no
    network), else resolved now."""
    kind, value = _classify(str(identifier))
    cid = _alias_get(kind, value) if kind != "unknown" else None
    rec = _record_cache_get(cid, META_TTL) if cid else None
    if rec:
        return rec
    r = resolve_citation(identifier)
    if not r.get("resolved"):
        return None
    return _record_cache_get(r["id"])


# ---------------------------------------------------------------------------
# search — a description of a paper → ranked real candidates
# ---------------------------------------------------------------------------

_HINT_RE = re.compile(r"^([A-Za-z][A-Za-z'\-\s]*?)[_:\-]?((?:19|20)\d{2}|\d{2})([A-Za-z0-9_\-]*)$")


def _parse_hint(hint: str) -> dict:
    """Rough cite key → {surname, initial, year, word}. Understands Vaswani2017,
    vaswani2017attention, Vaswani17, Vaswani_2017, Smith2019a, LiW25, JSmith05,
    VanDerWaals1910, planck2016cosmological. Identifiers pass through as `id`."""
    h = (hint or "").strip().strip("{}")
    if not h:
        return {}
    if _classify(h)[0] != "unknown":
        return {"id": h}
    s = _ascii(h).replace("{", "").replace("}", "")
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


def _identity_keys(rec: dict) -> list:
    keys = []
    if rec.get("arxiv"):
        keys.append("arxiv:" + rec["arxiv"].lower())
    if rec.get("doi"):
        keys.append("doi:" + rec["doi"].lower())
    if rec.get("bibcode"):
        keys.append("bibcode:" + rec["bibcode"])
    t = _norm_title(rec.get("title", ""))
    fa = _surname(rec["authors"][0]) if rec.get("authors") else ""
    if t and fa:
        keys.append(f"work:{t}:{fa}")
    return keys


def _merge_candidates(records: list) -> list:
    """Collapse the same work reported by several registries into one
    candidate. Records must arrive most-authoritative first."""
    merged, index = [], {}
    for rec in records:
        keys = _identity_keys(rec)
        hit = next((index[k] for k in keys if k in index), None)
        if hit is None:
            rec = dict(rec)
            rec["registries"] = [rec["registry"]]
            hit = len(merged)
            merged.append(rec)
        else:
            merged[hit] = _merge_records(merged[hit], rec)
        for k in keys + _identity_keys(merged[hit]):
            index.setdefault(k, hit)
    return merged


def _given_initial(name: str) -> str:
    name = _ascii(_strip_latex(name or "")).strip()
    if "," in name:
        given = name.split(",", 1)[1].strip()
    else:
        toks = name.split()
        given = " ".join(toks[:-1]) if len(toks) > 1 else ""
    return given[:1].lower()


def _score_candidate(c: dict, title, author, initial, year, words) -> dict:
    s, d = 0.0, {}
    if title:
        d["title_similarity"] = _title_sim(title, c.get("title", ""))
        s += 100 * d["title_similarity"]
    if words:
        want = set(words)
        in_title = set(_content_words(c.get("title", "")))
        in_abs = set(_content_words((c.get("abstract") or "")[:1500]))
        ov_t = len(want & in_title) / len(want)
        ov_a = len(want & in_abs) / len(want)
        s += 40 * ov_t + 12 * ov_a
        d["context_overlap"] = round(max(ov_t, ov_a), 2)
    if author:
        am = _author_match([author], c.get("authors") or [])
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


def search_citation(query: str | None = None, title: str | None = None, author: str | None = None,
                    year: int | None = None, hint: str | None = None, context: str | None = None,
                    registries: list | None = None, max_results: int = 8) -> dict:
    """Find real papers matching a description; returns ranked candidates.

    Give as much as you know: `title` (best), `author` (first-author surname),
    `year`, a rough cite key as `hint` ("Vaswani2017", "planck2016cosmological"),
    and/or the sentence being written as `context`. `query` is free text, or a
    bare identifier (then this is just a resolve). Candidates are ranked by
    cite-check's own title/author/year/context scoring — registry ranking is
    not trusted. Nothing here is verified: pick a candidate, then fetch_bibtex
    / bib_add it by its `id`.
    """
    h = _parse_hint(hint) if hint else {}
    direct = h.get("id") or (query if query and _classify(query)[0] != "unknown" else None)
    if direct:
        r = resolve_citation(direct)
        r["confidence"] = "high" if r.get("resolved") else "none"
        return {"direct": True, "query": direct, "candidates": [r] if r.get("resolved") else [],
                "n_candidates": 1 if r.get("resolved") else 0, "errors": {} if r.get("resolved") else {"resolve": r.get("reason")}}
    if query and not title:
        title = query
    author = author or h.get("surname")
    year = int(year) if year else h.get("year")
    initial = h.get("initial")
    words = [h["word"]] if h.get("word") else []
    if context:
        words += [w for w in _content_words(context) if len(w) >= 4][:8]
    words = list(dict.fromkeys(words))
    if not (title or author or words):
        return {"error": "give a title/query, an author+year hint, or the sentence as context"}

    enabled = [r for r in (registries or ["ads", "arxiv", "crossref", "openalex", "inspire"])]
    if not _ads_token():
        enabled = [r for r in enabled if r != "ads"]
    fns = {"ads": _ads_search, "arxiv": _arxiv_search, "crossref": _crossref_search,
           "openalex": _openalex_search, "inspire": _inspire_search}
    kwargs = dict(title=title, author=author, words=words or None, year=year)

    def run(name):
        try:
            return name, fns[name](**kwargs), None
        except Exception as exc:  # one registry down must not sink the search
            return name, [], f"{type(exc).__name__}: {exc}"

    records, errors = [], {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        for name, recs, err in ex.map(run, [r for r in enabled if r in fns]):
            records += recs
            if err:
                errors[name] = err
    records.sort(key=lambda r: -_AUTHORITY.get(r["registry"], 0))
    scored = []
    for c in _merge_candidates(records):
        d = _score_candidate(c, title, author, initial, year, words)
        d["confidence"] = _confidence(d, title, author, year)
        pub = _public(c, "", "search")
        for k in ("resolved", "input", "kind"):
            pub.pop(k, None)
        scored.append(dict(pub, **d))
        _record_cache_put(c)          # fetch_bibtex / fetch_text reuse it by id
    scored.sort(key=lambda x: -x["score"])
    return {"query": {"title": title, "author": author, "initial": initial, "year": year,
                      "words": words, "hint": hint},
            "registries": enabled, "errors": errors, "n_candidates": len(scored),
            "candidates": scored[:max_results],
            "note": ("ranked by cite-check scoring, not by the registries; confirm the pick "
                     "with fetch_bibtex / bib_add by its id — a candidate is not a verification")}


# ---------------------------------------------------------------------------
# BibTeX — parsing, official export, insertion with provenance, verification
# ---------------------------------------------------------------------------

_PROV_RE = re.compile(r"cite-check:\s*(.*)", re.S)


def _find_close(text: str, open_idx: int) -> int:
    """Index of the '}' or ')' closing the group opened at open_idx, else -1.
    Braces nest; a paren-delimited entry closes at the first ')' at depth 0."""
    paren = text[open_idx] == "("
    depth = 0
    for i in range(open_idx, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if not paren and depth == 0:
                return i
        elif paren and ch == ")" and depth == 0:
            return i
    return -1


_FIELD_START = re.compile(r"\s*([A-Za-z0-9_\-:.+/]+)\s*=\s*")
_BARE = re.compile(r"[^,#\s}]+")


def _parse_fields(body: str) -> dict:
    """`name = value, …` after the key. Values may be {…} (nested), "…",
    bare tokens/macros, and `#`-concatenations. Outer delimiters are removed."""
    fields, i, n = {}, 0, len(body)
    while i < n:
        m = _FIELD_START.match(body, i)
        if not m:
            break
        name, i, parts = m.group(1).lower(), m.end(), []
        while True:
            while i < n and body[i].isspace():
                i += 1
            if i >= n:
                break
            if body[i] == "{":
                j = _find_close(body, i)
                j = j if j >= 0 else n
                parts.append(body[i + 1:j])
                i = j + 1
            elif body[i] == '"':
                j, depth = i + 1, 0
                while j < n:
                    if body[j] == "{":
                        depth += 1
                    elif body[j] == "}":
                        depth -= 1
                    elif body[j] == '"' and depth == 0:
                        break
                    j += 1
                parts.append(body[i + 1:j])
                i = j + 1
            else:
                m2 = _BARE.match(body, i)
                if not m2:
                    break
                parts.append(m2.group(0))
                i = m2.end()
            while i < n and body[i].isspace():
                i += 1
            if i < n and body[i] == "#":
                i += 1
                continue
            break
        fields[name] = re.sub(r"\s+", " ", "".join(parts)).strip()
        while i < n and body[i] != ",":
            i += 1
        i += 1
    return fields


def _parse_prov(s: str) -> dict:
    out = {}
    for part in re.split(r";\s*", s):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip().strip('"')
    return out


def _parse_bib(text: str) -> dict:
    """Entries with raw text and span, plus @comment/@string/@preamble blocks.
    A `@comment{cite-check: …}` directly before an entry becomes its provenance."""
    entries, comments, keys = [], [], {}
    i, last_prov, last_prov_end = 0, None, -1
    head = re.compile(r"@\s*([A-Za-z]+)\s*([{(])")
    while True:
        at = text.find("@", i)
        if at < 0:
            break
        m = head.match(text, at)
        if not m:
            i = at + 1
            continue
        etype, open_idx = m.group(1).lower(), m.end() - 1
        close = _find_close(text, open_idx)
        if close < 0:
            break
        body, raw = text[open_idx + 1:close], text[at:close + 1]
        if etype in ("comment", "string", "preamble"):
            pm = _PROV_RE.search(body) if etype == "comment" else None
            comments.append({"type": etype, "start": at, "end": close + 1, "raw": raw,
                             "cite_check": pm.group(1).strip() if pm else None})
            if pm:
                last_prov, last_prov_end = pm.group(1).strip(), close + 1
            i = close + 1
            continue
        km = re.match(r"\s*([^,\s]+)\s*,?", body)
        key = km.group(1) if km else ""
        fields = _parse_fields(body[km.end():]) if km else {}
        prov = _parse_prov(last_prov) if last_prov and not text[last_prov_end:at].strip() else None
        last_prov = None
        entry = {"type": etype, "key": key, "fields": fields, "raw": raw,
                 "start": at, "end": close + 1, "provenance": prov}
        entries.append(entry)
        keys.setdefault(key, entry)
        i = close + 1
    return {"entries": entries, "comments": comments, "keys": keys}


def _entry_ids(entry: dict) -> dict:
    """Identifiers an entry carries: doi / arxiv / bibcode, from wherever
    authors and export tools put them (doi, eprint, url, adsurl, note, eid…)."""
    f, ids = entry["fields"], {}
    for src in (f.get("doi", ""), f.get("url", ""), f.get("note", "")):
        m = _DOI_ANY.search(src)
        if m:
            k, v = _classify(m.group(0))
            if k in ("doi", "arxiv"):
                ids.setdefault(k, v)
    ep = f.get("eprint", "").strip()
    if ep and _classify(ep)[0] == "arxiv":
        ids["arxiv"] = _classify(ep)[1]
    if "arxiv" not in ids:
        blob = " ".join(f.get(k, "") for k in ("url", "adsurl", "note", "howpublished", "eid", "journal", "eprint"))
        m = re.search(r"(?:arxiv:|arxiv\.org/(?:abs|pdf|html)/)\s*(" + _ARXIV_CORE + r")", blob, re.I)
        if m:
            ids["arxiv"] = _strip_arxiv_version(m.group(1))
    bc = f.get("bibcode", "").strip()
    m = re.search(r"/abs/([^/\s}]+)", f.get("adsurl", ""))
    if m:
        bc = urllib.parse.unquote(m.group(1))
    if bc and _BIBCODE_RE.match(bc):
        ids["bibcode"] = bc
    return ids


_DEFAULT_PREFER = ["ads", "crossref", "datacite", "inspire", "arxiv"]
_MACRO_CLASSES = re.compile(r"\\documentclass(?:\[[^\]]*\])?\{(?:aastex\w*|aasjournal\w*|mnras|emulateapj|apj\w*|aa)\}")


def _journal_format_for(tex_path: str | None) -> int:
    """ADS journal macros (\\apj, \\mnras) compile only where the class defines
    them; everywhere else ask ADS for journal abbreviations instead."""
    if not tex_path or not os.path.exists(tex_path):
        return 2
    with open(tex_path, errors="replace") as fh:
        return 1 if _MACRO_CLASSES.search(fh.read(6000)) else 2


def _official_bibtex(rec: dict, prefer=None, journal_format: int = 2, max_author: int = 10) -> dict:
    """BibTeX from a registry's own export, in `prefer` order. Never synthesised."""
    tried = []
    for src in (prefer or _DEFAULT_PREFER):
        bib = None
        try:
            if src == "ads":
                if not _ads_token():
                    tried.append("ads: no API token")
                    continue
                bibcode = rec.get("bibcode")
                if not bibcode:
                    for kind, val in (("doi", rec.get("doi")), ("arxiv", rec.get("arxiv"))):
                        hit = _ads_lookup(kind, [val]).get(val.lower()) if val else None
                        if hit:
                            bibcode = rec["bibcode"] = hit["bibcode"]
                            break
                if not bibcode:
                    tried.append("ads: record not indexed")
                    continue
                bib = _ads_export([bibcode], journal_format, max_author).get(bibcode)
            elif src == "crossref" and rec.get("doi"):
                status, body = _http(f"{_CROSSREF}/{urllib.parse.quote(rec['doi'], safe='')}"
                                     "/transform/application/x-bibtex")
                bib = body if status == 200 and body.lstrip().startswith("@") else None
            elif src == "datacite" and rec.get("doi"):
                status, body = _http(f"https://api.datacite.org/dois/{urllib.parse.quote(rec['doi'], safe='')}",
                                     headers={"Accept": "application/x-bibtex"})
                bib = body if status == 200 and body.lstrip().startswith("@") else None
            elif src == "inspire":
                for kind, val in (("arxiv", rec.get("arxiv")), ("doi", rec.get("doi")), ("inspire", rec.get("inspire"))):
                    if not val:
                        continue
                    path = {"arxiv": "arxiv", "doi": "doi", "inspire": "literature"}[kind]
                    status, body = _http(f"{_INSPIRE}/{path}/{urllib.parse.quote(val, safe='')}?format=bibtex")
                    if status == 200 and body.lstrip().startswith("@"):
                        bib = body
                        break
            elif src == "arxiv" and rec.get("arxiv"):
                status, body = _http(f"https://arxiv.org/bibtex/{rec['arxiv']}")
                bib = body if status == 200 and body.lstrip().startswith("@") else None
            else:
                continue
        except RuntimeError as exc:
            tried.append(f"{src}: {exc}")
            continue
        if not bib:
            tried.append(f"{src}: no export")
            continue
        parsed = _parse_bib(bib)["entries"]
        if not parsed:
            tried.append(f"{src}: unparsable export")
            continue
        entry = parsed[0]
        sim = _title_sim(rec.get("title", ""), entry["fields"].get("title", ""))
        if rec.get("title") and entry["fields"].get("title") and sim < 0.6:
            tried.append(f"{src}: export title mismatch ({sim})")
            continue
        return {"bibtex": _sanitize_bibtex(entry, rec), "source": src, "title_similarity": sim, "tried": tried}
    return {"bibtex": None, "source": None, "tried": tried}


_MONTHS = {"jan": "jan", "january": "jan", "feb": "feb", "february": "feb", "mar": "mar", "march": "mar",
           "apr": "apr", "april": "apr", "may": "may", "jun": "jun", "june": "jun", "jul": "jul", "july": "jul",
           "aug": "aug", "august": "aug", "sep": "sep", "sept": "sep", "september": "sep", "oct": "oct",
           "october": "oct", "nov": "nov", "november": "nov", "dec": "dec", "december": "dec"}


def _sanitize_bibtex(entry: dict, rec: dict) -> str:
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


def _prov_comment(rec: dict, source: str) -> str:
    title = re.sub(r"[{}@\n\"]", " ", rec.get("title", ""))[:100].strip()
    body = f'cite-check: source={source}; id={_canonical(rec)}; fetched={_today()}; title="{title}"'
    return "@comment{" + body.replace("@", "(at)") + "}"


def _default_key(rec: dict, existing: set) -> str:
    fam = re.sub(r"[^a-z]", "", _surname(rec["authors"][0]) if rec.get("authors") else "") or "anon"
    base = f"{fam.capitalize()}{rec.get('year') or ''}"
    key, n = base, 0
    while key in existing:
        n += 1
        key = base + ("abcdefghijklmnopqrstuvwxyz"[n - 1] if n <= 26 else str(n))
    return key


def fetch_bibtex(identifier: str, key: str | None = None, prefer: list | None = None,
                 journal_format: int | None = None, tex_path: str | None = None,
                 max_author: int = 10) -> dict:
    """Official BibTeX for one identifier, from ADS / Crossref / DataCite /
    INSPIRE / arXiv (first that has it, in `prefer` order). `key` renames the
    entry. journal_format (ADS): 1 macros, 2 abbreviations, 3 full names —
    auto-detected from tex_path's documentclass when omitted. bibtex=null means
    no registry exports one: do not hand-write it.
    """
    rec = _full_record(identifier)
    if rec is None:
        r = resolve_citation(identifier)
        return {"bibtex": None, "resolved": False, "reason": r.get("reason") or r.get("error")}
    jf = int(journal_format) if journal_format else _journal_format_for(tex_path)
    got = _official_bibtex(rec, prefer, jf, max_author)
    if not got["bibtex"]:
        return {"bibtex": None, "resolved": True, "id": _canonical(rec), "tried": got["tried"],
                "reason": ("no registry offers a BibTeX export for this record — do not hand-write "
                           "one; cite a version that has a DOI or arXiv id, or record the gap")}
    bib = _rewrite_key(got["bibtex"], key) if key else got["bibtex"]
    return {"bibtex": bib, "key": _parse_bib(bib)["entries"][0]["key"], "source": got["source"],
            "id": _canonical(rec), "ids": {k: rec[k] for k in _ID_KEYS if rec.get(k)},
            "title": rec["title"], "provenance": _prov_comment(rec, got["source"]), "tried": got["tried"]}


def bib_add(bib_path: str, items: list, prefer: list | None = None, journal_format: int | None = None,
            tex_path: str | None = None, replace: bool = False, max_author: int = 10) -> dict:
    """Add official entries to a .bib. items: [{"identifier": …, "key": …}] (key
    optional → Surname2017). Each entry is written with a provenance comment.
    Duplicates (same DOI/arXiv/bibcode already present) are reported, not
    added; an existing key is left alone unless replace=true, which swaps a
    hand-written entry for the official one under the same key.
    """
    bib_path = os.path.abspath(bib_path)
    text = ""
    if os.path.exists(bib_path):
        with open(bib_path, errors="replace") as fh:
            text = fh.read()
    if isinstance(items, (str, dict)):
        items = [items]
    parsed = _parse_bib(text)
    by_id = {}
    for e in parsed["entries"]:
        for k, v in _entry_ids(e).items():
            by_id.setdefault(f"{k}:{v.lower()}", e["key"])
    jf = int(journal_format) if journal_format else _journal_format_for(tex_path)
    results, additions, replacements = [], [], {}
    taken = set(parsed["keys"])
    for item in items:
        if isinstance(item, str):
            item = {"identifier": item}
        ident, want = item.get("identifier") or item.get("id"), item.get("key")
        rec = _full_record(ident) if ident else None
        if rec is None:
            results.append({"identifier": ident, "key": want, "status": "unresolved"})
            continue
        dup = next((by_id[f"{k}:{rec[k].lower()}"] for k in ("doi", "arxiv", "bibcode")
                    if rec.get(k) and f"{k}:{rec[k].lower()}" in by_id), None)
        if dup and dup != want and not replace:
            results.append({"identifier": ident, "key": want, "status": "duplicate", "existing_key": dup,
                            "note": f"already in the .bib as {dup} — cite that key"})
            continue
        key = want or dup or _default_key(rec, taken)
        if key in parsed["keys"] and not replace:
            have = _entry_ids(parsed["keys"][key])
            same = any(have.get(k) and rec.get(k) and have[k].lower() == rec[k].lower() for k in ("doi", "arxiv", "bibcode"))
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
        for k in ("doi", "arxiv", "bibcode"):
            if rec.get(k):
                by_id[f"{k}:{rec[k].lower()}"] = key
        results.append({"identifier": ident, "key": key, "status": status, "source": got["source"],
                        "id": _canonical(rec), "title": rec["title"]})
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
        tmp = bib_path + ".tmp"
        with open(tmp, "w") as fh:
            fh.write(new)
        os.replace(tmp, bib_path)
    return {"bib": bib_path, "results": results,
            "ok": all(r["status"] in ("added", "replaced", "exists", "duplicate") for r in results)}


_OK_STATUS = {"VERIFIED", "FOUND"}


def _compare(entry: dict, pub: dict, via: str) -> dict:
    """Entry fields vs the registry record: the actual existence test."""
    f = entry["fields"]
    title, authors, year = f.get("title", ""), _split_bib_authors(f.get("author", "")), _year(f.get("year"))
    sim = _title_sim(title, pub["title"]) if title else None
    am = _author_match(authors, pub["authors"])
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


def _search_entry(entry: dict) -> dict:
    f = entry["fields"]
    title, authors, year = f.get("title", ""), _split_bib_authors(f.get("author", "")), _year(f.get("year"))
    base = {"key": entry["key"], "via": "search", "provenance": entry["provenance"], "year_bib": year}
    if not title:
        return dict(base, status="UNRESOLVED", notes=["no identifier and no title — nothing to look up"])
    s = search_citation(title=title, author=_surname(authors[0]) if authors else None, year=year, max_results=3)
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


def verify_bib(bib_path: str, keys: list | None = None, tex_path: str | None = None,
               search_unresolved: bool = True) -> dict:
    """Existence check of every entry (or `keys`): resolve the entry's own
    DOI / arXiv id / bibcode and compare title, first author and year with the
    registry record. Entries without any identifier are searched by title,
    author and year. Statuses: VERIFIED, FOUND (by search — replace with the
    official entry), PROBABLE (look), MISMATCH (real id, different paper),
    NOT_FOUND, UNRESOLVED. ok=true only when every entry is VERIFIED or FOUND.
    """
    bib_path = os.path.abspath(bib_path)
    if not os.path.exists(bib_path):
        return {"error": f"{bib_path} not found"}
    with open(bib_path, errors="replace") as fh:
        parsed = _parse_bib(fh.read())
    wanted = set(keys) if keys else None
    entries = [e for e in parsed["entries"] if wanted is None or e["key"] in wanted]
    missing_keys = sorted(wanted - set(parsed["keys"])) if wanted else []
    plan = []
    for e in entries:
        ids = _entry_ids(e)
        order = [(k, ids[k]) for k in ("doi", "arxiv") if ids.get(k)]
        if ids.get("bibcode") and _ads_token():
            order.append(("bibcode", ids["bibcode"]))
        plan.append((e, order))
    all_ids = list(dict.fromkeys(f"{k}:{v}" for _, order in plan for k, v in order))
    try:
        resolved = dict(zip(all_ids, _resolve_many(all_ids))) if all_ids else {}
    except RuntimeError as exc:
        return {"error": f"registry lookup failed ({exc})"}
    out, to_search = [], []
    for e, order in plan:
        result, bad = None, []
        for k, v in order:
            r = resolved.get(f"{k}:{v}")
            if r and r.get("resolved"):
                result = _compare(e, r, f"{k}:{v}")
                break
            bad.append(f"{k}:{v} — {(r or {}).get('reason', 'no result')}")
        if result:
            result["notes"] += [f"stale identifier in entry: {b}" for b in bad]
            out.append(result)
        elif order:
            out.append({"key": e["key"], "status": "NOT_FOUND", "via": None, "notes": bad,
                        "provenance": e["provenance"]})
        else:
            to_search.append(e)
    if to_search and search_unresolved:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
            out += list(ex.map(_search_entry, to_search))
    else:
        out += [{"key": e["key"], "status": "UNRESOLVED", "via": None, "provenance": e["provenance"],
                 "notes": ["no identifier; search skipped"]} for e in to_search]
    pos = {e["key"]: i for i, e in enumerate(entries)}
    out.sort(key=lambda r: pos.get(r["key"], 10 ** 9))
    counts = Counter(r["status"] for r in out)
    report = {"ok": all(r["status"] in _OK_STATUS for r in out) and not missing_keys,
              "bib": bib_path, "n": len(out), "counts": dict(counts), "missing_keys": missing_keys,
              "ads": bool(_ads_token()), "checked": _now_iso(), "entries": out}
    _write_project(os.path.dirname(bib_path), "verify.json", report)
    return report


# ---------------------------------------------------------------------------
# LaTeX — every citation instance with the sentence that makes the claim
# ---------------------------------------------------------------------------

_CITE_CMD = re.compile(
    r"\\(?P<cmd>[Cc]ite[a-zA-Z]*|[Pp]arencites?|[Tt]extcites?|[Aa]utocites?|"
    r"[Ff]oot(?:full)?cites?(?:text)?|[Ss]martcites?|[Ss]upercites?|[Ff]ullcite|nocite)\*?(?![a-zA-Z])")
_CITE_EXCLUDE = {"citetext", "citestyle", "citeindextype", "citename", "citeauthoryear", "citenumfont"}
_ABBREV = ("e.g", "i.e", "et al", "cf", "vs", "viz", "ca", "approx", "resp", "Fig", "Figs", "Eq", "Eqs",
           "Sec", "Secs", "Sect", "Ref", "Refs", "Tab", "Tabs", "Dr", "Prof", "Mr", "Ms", "Mrs", "No", "Nos",
           "Vol", "vol", "pp", "p", "Phys", "Rev", "Astrophys", "Astron", "Ann", "Proc", "J", "Ser", "Lett",
           "Suppl", "Chap", "Ch", "St", "Univ", "Inc", "Ltd", "approx", "min", "max")
_CITE_TOKEN = re.compile(r"\u27e8cite#(\d+)\u27e9")


def _strip_tex_comments(text: str) -> str:
    text = "\n".join(re.sub(r"(?<!\\)%.*$", "", line) for line in text.split("\n"))
    text = re.sub(r"\\begin\{comment\}.*?\\end\{comment\}", " ", text, flags=re.S)
    return re.sub(r"\\iffalse.*?\\fi", " ", text, flags=re.S)


def _braced(text: str, i: int) -> tuple:
    """text[i] == '{' → (inner, index after the matching '}')."""
    j = _find_close(text, i)
    return (text[i + 1:j], j + 1) if j > 0 else ("", i + 1)


def _gather_tex(main_path: str, seen: set | None = None) -> list:
    """[(path, comment-stripped text)] for the main file and every
    \\input / \\include / \\subfile it pulls in."""
    seen = seen if seen is not None else set()
    main_path = os.path.abspath(main_path)
    if main_path in seen or not os.path.exists(main_path):
        return []
    seen.add(main_path)
    with open(main_path, errors="replace") as fh:
        text = _strip_tex_comments(fh.read())
    files = [(main_path, text)]
    base = os.path.dirname(main_path)
    for m in re.finditer(r"\\(?:input|include|subfile)\s*\{([^}]+)\}", text):
        cand = os.path.join(base, m.group(1).strip())
        if not os.path.splitext(cand)[1]:
            cand += ".tex"
        files += _gather_tex(cand, seen)
    return files


def _cite_instances(text: str):
    """Yield (cmd, keys, start, end) for each citation command; \\cites-style
    commands carry several ([pre][post]{keys}) groups."""
    n = len(text)
    for m in _CITE_CMD.finditer(text):
        cmd = m.group("cmd")
        if cmd.lower() in _CITE_EXCLUDE:
            continue
        i, keys, groups = m.end(), [], 0
        while True:
            j = i
            while j < n and text[j].isspace():
                j += 1
            while j < n and text[j] == "[":
                k = text.find("]", j)
                if k < 0:
                    break
                j = k + 1
                while j < n and text[j].isspace():
                    j += 1
            if j < n and text[j] == "{":
                inner, i = _braced(text, j)
                keys += [k.strip() for k in inner.split(",") if k.strip()]
                groups += 1
                if cmd.lower().endswith("cites"):
                    continue
            break
        if groups:
            yield cmd, keys, m.start(), i


def _replace_cmd_arg(text: str, cmd: str, fn) -> str:
    """\\cmd[opt]{arg} → fn(arg), brace-aware, for every occurrence."""
    pat = re.compile(r"\\" + cmd + r"\*?\s*(?:\[[^\]]*\])?\s*\{")
    out, i = [], 0
    while True:
        m = pat.search(text, i)
        if not m:
            out.append(text[i:])
            return "".join(out)
        inner, end = _braced(text, m.end() - 1)
        out.append(text[i:m.start()])
        out.append(fn(inner))
        i = end


def _clean_tex(t: str) -> str:
    """LaTeX → readable prose; ⟨cite#n⟩ tokens and $inline math$ survive."""
    t = re.sub(r"\\begin\{(equation|align|gather|multline|eqnarray|displaymath|flalign|alignat)\*?\}.*?\\end\{\1\*?\}",
               " \u27e8display equation\u27e9 ", t, flags=re.S)
    t = re.sub(r"\\\[.*?\\\]|\$\$.*?\$\$", " \u27e8display equation\u27e9 ", t, flags=re.S)
    math = []
    t = re.sub(r"\$[^$\n]+\$", lambda m: (math.append(m.group(0)), f"\u27e8m{len(math) - 1}\u27e9")[1], t)
    t = re.sub(r"\\(?:includegraphics|label|vspace|hspace|bibliographystyle|bibliography|addbibresource|"
               r"graphicspath|usepackage|documentclass|setlength|newcommand|renewcommand|def|input|include|"
               r"subfile|affiliation|affil|author|email|correspondingauthor|orcid|keywords|received|revised|accepted|"
               r"submitjournal|shorttitle|shortauthors|thanks|date)\*?(?:\[[^\]]*\])?(?:\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})?",
               " ", t)
    t = _replace_cmd_arg(t, "footnote", lambda a: f" (footnote: {a.strip()}) ")
    t = _replace_cmd_arg(t, "href", lambda a: "")          # url part
    for cmd in ("section", "subsection", "subsubsection", "paragraph", "chapter", "title"):
        t = _replace_cmd_arg(t, cmd, lambda a: f"\n\n{a.strip()}.\n\n")
    for cmd in ("emph", "textbf", "textit", "texttt", "textsc", "textrm", "textsf", "text", "mbox", "underline",
                "url", "caption", "textsuperscript", "textsubscript", "textcolor", "abstract", "quote"):
        t = _replace_cmd_arg(t, cmd, lambda a: a)
    t = re.sub(r"\\(?:ref|eqref|cref|Cref|autoref|pageref|citetext|nameref)\*?\{[^}]*\}", "[ref]", t)
    t = re.sub(r"\\(?:begin|end)\{[^}]*\}(?:\[[^\]]*\])?(?:\{[^{}]*\})*", "\n", t)
    t = re.sub(r"\\item\b", "\n- ", t)
    for a, b in (("\\ldots", "..."), ("\\dots", "..."), ("\\%", "%"), ("\\&", "&"), ("\\_", "_"), ("\\#", "#"),
                 ("\\$", "$"), ("~", " "), ("---", " -- "), ("``", '"'), ("''", '"'), ("\\,", " "), ("\\ ", " ")):
        t = t.replace(a, b)
    t = re.sub(r"\\[a-zA-Z]+\*?(?![a-zA-Z])", " ", t)
    t = re.sub(r"[{}]", "", t)
    t = re.sub(r"\u27e8m(\d+)\u27e9", lambda m: math[int(m.group(1))], t)
    t = re.sub(r"[ \t]+", " ", t)
    return t


def _split_sentences(paragraph: str) -> list:
    prot = paragraph
    for ab in _ABBREV:
        prot = re.sub(r"\b" + re.escape(ab) + r"\.", ab.replace(".", "<DOT>") + "<DOT>", prot)
    prot = re.sub(r"\b([A-Z])\.", r"\1<DOT>", prot)              # initials
    prot = re.sub(r"(\d)\.(\d)", r"\1<DOT>\2", prot)              # decimals
    prot = re.sub(r"\$([^$]*)\$", lambda m: "$" + m.group(1).replace(".", "<DOT>") + "$", prot)
    parts = re.split(r"(?<=[.!?])\s+(?=[\"'(\[\u27e8$A-Z0-9\\])", prot)
    return [p.replace("<DOT>", ".").strip() for p in parts if p.strip()]


def extract_cites(tex_path: str) -> dict:
    """Every citation instance in a LaTeX document (following \\input /
    \\include), each with the sentence making the claim (`claim`, with
    ⟨cite:key⟩ marking where the citation sits), one sentence of context each
    side, file and line. Also reports the cite keys, declared .bib files and
    documentclass. \\nocite instances are flagged nocite=true.
    """
    tex_path = os.path.abspath(tex_path)
    if not os.path.exists(tex_path):
        return {"error": f"{tex_path} not found"}
    files = _gather_tex(tex_path)
    cites, bib_files, docclass = [], [], None
    for path, text in files:
        m = re.search(r"\\documentclass(?:\[[^\]]*\])?\{([^}]+)\}", text)
        if m and not docclass:
            docclass = m.group(1)
        for m in re.finditer(r"\\(?:bibliography|addbibresource)\s*\{([^}]+)\}", text):
            for b in m.group(1).split(","):
                b = b.strip()
                if b:
                    p = os.path.join(os.path.dirname(path), b)
                    bib_files.append(p if p.endswith(".bib") else p + ".bib")
        tokens, out, last = {}, [], 0
        for n, (cmd, keys, s, e) in enumerate(_cite_instances(text)):
            out.append(text[last:s])
            out.append(f" \u27e8cite#{n}\u27e9 ")
            last = e
            tokens[n] = {"cmd": cmd, "keys": keys, "line": text.count("\n", 0, s) + 1}
        out.append(text[last:])
        joined = "".join(out)
        m = re.search(r"\\begin\{document\}", joined)
        prose = _clean_tex(joined[m.end():] if m else joined)

        def render(s):
            s = _CITE_TOKEN.sub(lambda mm: "\u27e8cite:" + ",".join(tokens[int(mm.group(1))]["keys"]) + "\u27e9", s)
            return re.sub(r"\u27e9 (?=[,.;:)\]])", "\u27e9", s)

        for para in re.split(r"\n\s*\n", prose):
            if "\u27e8cite#" not in para:
                continue
            sents = _split_sentences(re.sub(r"\s+", " ", para).strip())
            for si, sent in enumerate(sents):
                for tm in _CITE_TOKEN.finditer(sent):
                    t = tokens[int(tm.group(1))]
                    claim = render(sent)
                    context = " ".join(render(x) for x in sents[max(0, si - 1):si + 2])
                    for key in t["keys"]:
                        cites.append({"key": key, "cmd": t["cmd"], "file": path, "line": t["line"],
                                      "claim": claim, "context": context,
                                      "nocite": t["cmd"].lower() == "nocite" or key == "*"})
    keys = sorted({c["key"] for c in cites if c["key"] != "*"})
    by_key = {}
    for i, c in enumerate(cites):
        by_key.setdefault(c["key"], []).append(i)
    return {"main": tex_path, "files": [p for p, _ in files], "documentclass": docclass,
            "bib_files": list(dict.fromkeys(bib_files)), "n_instances": len(cites),
            "n_keys": len(keys), "keys": keys, "cites": cites, "by_key": by_key}


# ---------------------------------------------------------------------------
# full text — fetch, cache, passage retrieval for the judge
# ---------------------------------------------------------------------------

class _HTMLText(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "header", "footer", "button", "annotation"}
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "tr",
             "figcaption", "blockquote", "table"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def _html_to_text(body: str) -> str:
    p = _HTMLText()
    p.feed(body)
    return "".join(p.parts)


def _tidy_text(t: str) -> str:
    t = t.replace("\r", "").replace("\x0c", "\n")
    t = re.sub(r"(\w)-\n(?=[a-z])", r"\1", t)                 # de-hyphenate line breaks
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    last = None
    for m in re.finditer(r"\n\s*(?:\d+\.?\s*)?(?:References|REFERENCES|Bibliography|BIBLIOGRAPHY)\s*\n", t):
        last = m
    if last and last.start() > 0.6 * len(t):                   # drop the reference list
        t = t[:last.start()]
    return t.strip()


def _pdf_to_text(path: str) -> str:
    if shutil.which("pdftotext"):
        r = subprocess.run(["pdftotext", "-enc", "UTF-8", path, "-"], capture_output=True, timeout=180)
        if r.returncode == 0 and len(r.stdout) > 200:
            return r.stdout.decode("utf-8", "replace")
    try:
        import pypdf
    except ImportError:
        raise RuntimeError("no PDF text extractor: install poppler's pdftotext, or pypdf in mcp/.venv")
    reader = pypdf.PdfReader(path)
    return "\n".join((pg.extract_text() or "") for pg in reader.pages)


def _download_pdf(url: str, dest: str) -> bool:
    try:
        status, data = _http(url, binary=True, timeout=120, headers={"Accept": "application/pdf,*/*"})
    except RuntimeError:
        return False
    if status != 200 or not isinstance(data, bytes) or not data.startswith(b"%PDF") or len(data) > MAX_PDF_BYTES:
        return False
    with open(dest, "wb") as fh:
        fh.write(data)
    return True


def _text_paths(cid: str) -> tuple:
    return _cache_file("text", _slug(cid) + ".txt"), _cache_file("text", _slug(cid) + ".json")


def _load_text_meta(cid: str) -> dict | None:
    tp, mp = _text_paths(cid)
    if os.path.exists(mp) and os.path.exists(tp):
        with open(mp) as fh:
            meta = json.load(fh)
        meta["path"] = tp
        return meta
    return None


def _obtain_text(rec: dict, cid: str) -> tuple:
    """(text, basis, source) — arXiv HTML, arXiv PDF, an open-access PDF the
    registries point at, else the abstract, else nothing."""
    if rec.get("doi") and (not rec.get("arxiv") or not rec.get("abstract") or not rec.get("pdf_urls")):
        try:                                            # OpenAlex knows OA copies and abstracts
            oa = _openalex_get("https://doi.org/" + rec["doi"])
        except RuntimeError:
            oa = None
        if oa:
            rec = _merge_records(rec, oa)
            _record_cache_put(rec)
    if rec.get("arxiv"):
        try:
            status, body = _http(f"https://arxiv.org/html/{rec['arxiv']}", cache=False, timeout=60)
        except RuntimeError:
            status, body = 0, ""
        if status == 200 and "ltx_document" in body:
            text = _tidy_text(_html_to_text(body))
            if len(text) > 2000:
                return text, "fulltext", "arxiv-html"
        pdf = _cache_file("pdf", _slug(cid) + ".pdf")
        if _download_pdf(f"https://arxiv.org/pdf/{rec['arxiv']}", pdf):
            text = _tidy_text(_pdf_to_text(pdf))
            if len(text) > 2000:
                return text, "fulltext", "arxiv-pdf"
    for url in rec.get("pdf_urls") or []:
        pdf = _cache_file("pdf", _slug(cid) + ".pdf")
        if _download_pdf(url, pdf):
            text = _tidy_text(_pdf_to_text(pdf))
            if len(text) > 2000:
                return text, "fulltext", url
    if rec.get("abstract"):
        return rec.get("title", "") + "\n\n" + rec["abstract"], "abstract", ",".join(rec.get("registries") or [rec["registry"]])
    return "", "none", None


def fetch_text(identifier: str, pdf_path: str | None = None, text_path: str | None = None,
               refresh: bool = False, max_chars: int = 0) -> dict:
    """Get the cited paper's text for support checking and cache it: arXiv
    HTML → arXiv PDF → open-access PDF → abstract only. For paywalled papers
    pass pdf_path (or text_path) to ingest your own copy. Returns basis
    (fulltext | abstract | none), source, chars, the cache path, and the
    abstract; max_chars>0 inlines that much text.
    """
    rec = _full_record(identifier)
    if rec is None:
        r = resolve_citation(identifier)
        return {"error": f"cannot resolve {identifier}: {r.get('reason') or r.get('error')}"}
    cid = _canonical(rec)
    tp, mp = _text_paths(cid)
    meta = None if (refresh or pdf_path or text_path) else _load_text_meta(cid)
    if meta and meta.get("basis") == "none":
        meta = None
    if meta is None:
        try:
            if text_path or pdf_path:
                src = os.path.abspath(text_path or pdf_path)
                if not os.path.exists(src):
                    return {"error": f"{src} not found"}
                if text_path:
                    with open(src, errors="replace") as fh:
                        text = fh.read()
                else:
                    text = _pdf_to_text(src)
                text, basis, source = _tidy_text(text), "fulltext", f"local:{os.path.basename(src)}"
            else:
                text, basis, source = _obtain_text(rec, cid)
        except RuntimeError as exc:
            return {"error": str(exc)}
        with open(tp, "w") as fh:
            fh.write(text)
        meta = {"id": cid, "basis": basis, "source": source, "chars": len(text),
                "fetched": _now_iso(), "title": rec.get("title", "")}
        with open(mp, "w") as fh:
            json.dump(meta, fh)
        meta["path"] = tp
    out = dict(meta)
    out["abstract"] = (rec.get("abstract") or "")[:2500]
    if max_chars and out["basis"] != "none":
        with open(tp, errors="replace") as fh:
            out["text"] = fh.read()[:max_chars]
    if out["basis"] == "none":
        out["note"] = "no text obtainable — pass pdf_path= with your copy of the paper, or judge UNVERIFIABLE"
    elif out["basis"] == "abstract":
        out["note"] = "abstract only (paywalled, no open-access copy found) — pass pdf_path= for a full-text check"
    return out


def _sentences(text: str) -> list:
    out = []
    for para in re.split(r"\n\s*\n", text):
        para = re.sub(r"\s+", " ", para).strip()
        if len(para) >= 20:
            out += _split_sentences(para)
    return [s for s in out if len(s) >= 25]


def find_passages(identifier: str, claims: list, k: int = 6, window: int = 2) -> dict:
    """For each claim, the top-k passages (windows of `window` sentences) of
    the cited paper ranked by content-word and bigram overlap, plus the
    abstract. This is what the judge reads before quoting evidence.
    """
    if isinstance(claims, str):
        claims = [claims]
    meta = fetch_text(identifier)
    if meta.get("error"):
        return meta
    text = ""
    if meta["basis"] != "none":
        with open(meta["path"], errors="replace") as fh:
            text = fh.read()
    sents = _sentences(text)
    base = {"id": meta["id"], "basis": meta["basis"], "source": meta.get("source"),
            "n_sentences": len(sents), "abstract": meta["abstract"]}
    if not sents:
        return dict(base, results=[{"claim": c, "passages": []} for c in claims],
                    note=meta.get("note") or "no sentences to search")
    words = [set(_content_words(s)) for s in sents]
    n = len(sents)
    df = Counter(w for ws in words for w in ws)

    def idf(w):
        return math.log((n + 1) / (df.get(w, 0) + 1)) + 1

    results = []
    for claim in claims:
        cw = _content_words(claim)
        cset, bigrams = set(cw), set(zip(cw, cw[1:]))
        scored = []
        for i in range(n):
            win = set().union(*words[i:i + window])
            s = sum(idf(w) for w in cset if w in win)
            if s and bigrams:
                wtext = " ".join(_content_words(" ".join(sents[i:i + window])))
                s += 2 * sum(1 for a, b in bigrams if f"{a} {b}" in wtext)
            scored.append((s, i))
        scored.sort(reverse=True)
        chosen, used = [], set()
        for s, i in scored:
            if s <= 0 or len(chosen) >= k:
                break
            if any(j in used for j in range(i, i + window)):
                continue
            used.update(range(i, i + window))
            chosen.append({"score": round(s, 2), "at": i, "text": " ".join(sents[i:i + window])})
        results.append({"claim": claim, "passages": chosen})
    return dict(base, results=results)


# ---------------------------------------------------------------------------
# ledger — support verdicts, accepted only with verbatim evidence
# ---------------------------------------------------------------------------

_VERDICTS = ("SUPPORTS", "PARTIAL", "UNSUPPORTED", "CONTRADICTS", "UNVERIFIABLE")


def _project_path(workdir: str, name: str) -> str:
    d = os.path.join(os.path.abspath(workdir), PROJECT_DIR)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name)


def _write_project(workdir: str, name: str, obj) -> str:
    path = _project_path(workdir, name)
    with open(path, "w") as fh:
        json.dump(obj, fh, indent=2)
    return path


def _load_ledger(workdir: str) -> dict:
    path = _project_path(workdir, "ledger.json")
    if os.path.exists(path):
        with open(path) as fh:
            return json.load(fh)
    return {"version": 1, "entries": {}}


def _claim_hash(claim: str) -> str:
    t = re.sub(r"\u27e8[^\u27e9]*\u27e9", " ", claim or "")
    t = re.sub(r"\s+", " ", _ascii(t).lower()).strip()
    return hashlib.sha1(t.encode()).hexdigest()[:12]


def _norm_quote(s: str) -> str:
    s = _ascii(html.unescape(s or "")).lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _locate_quote(text: str, quote: str) -> dict:
    """Is `quote` in `text` verbatim (after normalisation) or near-verbatim
    (≥ 0.85 similarity, which absorbs PDF-extraction damage: ligatures,
    broken hyphens, dropped superscripts)?"""
    nt, nq = _norm_quote(text), _norm_quote(quote)
    if len(nq) < 15:
        return {"found": False, "match": 0.0, "reason": "quote too short (< 15 characters after normalisation)"}
    idx = nt.find(nq)
    if idx >= 0:
        return {"found": True, "match": 1.0, "at": idx}
    L, best = len(nq), (0.0, -1)
    stride = max(1, L // 6)
    sm = difflib.SequenceMatcher(None, "", nq, autojunk=False)
    for i in range(0, max(1, len(nt) - L + 1), stride):
        sm.set_seq1(nt[i:i + L])
        if sm.real_quick_ratio() < 0.85 or sm.quick_ratio() < 0.85:
            continue
        r = sm.ratio()
        if r > best[0]:
            best = (r, i)
    if best[1] >= 0:
        for i in range(max(0, best[1] - stride), min(len(nt) - L, best[1] + stride) + 1):
            sm.set_seq1(nt[i:i + L])
            r = sm.ratio()
            if r > best[0]:
                best = (r, i)
    if best[0] >= 0.85:
        return {"found": True, "match": round(best[0], 3), "at": best[1]}
    return {"found": False, "match": round(best[0], 3),
            "reason": f"not found verbatim in the paper text (best fuzzy match {best[0]:.2f})"}


def record_support(workdir: str, key: str, claim: str, verdict: str, identifier: str,
                   quotes: list | None = None, note: str | None = None, judge: str | None = None,
                   file: str | None = None, line: int | None = None) -> dict:
    """Record a support verdict for one (cite key, claim sentence) pair.

    verdict ∈ SUPPORTS | PARTIAL | UNSUPPORTED | CONTRADICTS | UNVERIFIABLE.
    SUPPORTS / PARTIAL / CONTRADICTS are refused unless at least one `quote`
    is found verbatim in the cited paper's fetched text (fetch_text first).
    PARTIAL / CONTRADICTS / UNSUPPORTED / UNVERIFIABLE need a `note` saying
    what the paper does and does not say; UNVERIFIABLE is refused when full
    text is available. `claim` must be the exact sentence extract_cites gave.
    """
    verdict = (verdict or "").strip().upper()
    if verdict not in _VERDICTS:
        return {"recorded": False, "error": f"verdict must be one of {list(_VERDICTS)}"}
    rec = _full_record(identifier)
    if rec is None:
        return {"recorded": False, "error": f"cannot resolve {identifier}"}
    cid = _canonical(rec)
    meta = _load_text_meta(cid) or fetch_text(identifier)
    if meta.get("error"):
        return {"recorded": False, "error": meta["error"]}
    basis = meta["basis"]
    text = ""
    if basis != "none":
        with open(meta["path"], errors="replace") as fh:
            text = fh.read()
    quotes = [q.strip() for q in (quotes or []) if q and q.strip()]
    checks = [dict({"text": q}, **_locate_quote(text, q)) for q in quotes]
    n_found = sum(1 for c in checks if c["found"])
    note = (note or "").strip()
    if verdict in ("SUPPORTS", "PARTIAL", "CONTRADICTS") and n_found == 0:
        return {"recorded": False, "basis": basis, "quotes": checks,
                "error": f"{verdict} needs at least one quote found verbatim in the paper's "
                         f"{'text' if basis == 'fulltext' else basis} — quote the paper, not your paraphrase"}
    if verdict in ("PARTIAL", "CONTRADICTS", "UNSUPPORTED", "UNVERIFIABLE") and len(note) < 15:
        return {"recorded": False, "error": f"{verdict} needs a note (≥ 15 characters) saying what the paper does and does not say"}
    if verdict == "UNVERIFIABLE" and basis == "fulltext":
        return {"recorded": False, "error": "full text is available — read it and decide (SUPPORTS / PARTIAL / "
                                            "UNSUPPORTED / CONTRADICTS); UNVERIFIABLE is only for papers whose text could not be obtained"}
    ledger = _load_ledger(workdir)
    lid = f"{key}|{_claim_hash(claim)}"
    ledger["entries"][lid] = {"key": key, "id": cid, "claim": claim, "verdict": verdict, "basis": basis,
                              "quotes": checks, "note": note or None, "judge": judge or None,
                              "file": file, "line": line, "recorded": _now_iso()}
    _write_project(workdir, "ledger.json", ledger)
    return {"recorded": True, "ledger_id": lid, "verdict": verdict, "basis": basis,
            "quotes_found": n_found, "quotes": checks}


def ledger_read(workdir: str) -> dict:
    """Read the support ledger of a manuscript directory."""
    return {"path": _project_path(workdir, "ledger.json"), "ledger": _load_ledger(workdir)}


# ---------------------------------------------------------------------------
# audit — the gate
# ---------------------------------------------------------------------------

def _audit_markdown(rep: dict, ver: dict, coverage: dict) -> str:
    lines = [f"# cite-check audit — {'PASS' if rep['ok'] else 'FAIL'}", "",
             f"- manuscript: `{rep['tex']}`", f"- bib: {', '.join('`%s`' % b for b in rep['bibs']) or '(none)'}",
             f"- citation instances: {rep['n_instances']} over {rep['n_keys']} keys",
             f"- existence: {rep['existence_counts']}", f"- support: {rep['support_counts']} "
             f"(missing: {rep['support_missing']})", f"- checked: {rep['checked']}", ""]
    for title, items in (("Failures", rep["failures"]), ("Warnings", rep["warnings"])):
        lines += [f"## {title} ({len(items)})", ""]
        for it in items:
            where = f" ({os.path.basename(it['file'])}:{it['line']})" if it.get("file") else ""
            lines.append(f"- **{it['type']}** `{it.get('key', '')}`{where}: {it.get('status') or it.get('verdict') or ''} "
                         f"{it.get('detail') or ''}".rstrip())
            if it.get("claim"):
                lines.append(f"  > {it['claim']}")
        lines.append("")
    lines += ["## Per key", "", "| key | existence | id | support verdicts |", "|---|---|---|---|"]
    for key in sorted(coverage):
        v = ver.get(key, {})
        lines.append(f"| `{key}` | {v.get('status', '—')} | {v.get('id', '')} | {coverage[key]} |")
    return "\n".join(lines) + "\n"


def audit(tex_path: str, bib_path: str | None = None, require_support: bool = True,
          verify: bool = True) -> dict:
    """The gate. Fails on: cite keys missing from the .bib; entries whose
    identifier resolves to a different paper, does not resolve, or cannot be
    found; citation instances with an UNSUPPORTED / CONTRADICTS verdict, a
    verdict recorded against a different paper than the entry now resolves
    to, or (require_support) no verdict at all. Warns on PROBABLE / FOUND
    entries, PARTIAL / UNVERIFIABLE verdicts, abstract-only SUPPORTS, uncited
    entries. Writes .cite-check/audit.md and audit.json next to the .tex.
    """
    ex = extract_cites(tex_path)
    if ex.get("error"):
        return ex
    workdir = os.path.dirname(os.path.abspath(tex_path))
    bibs = [os.path.abspath(b) for b in ([bib_path] if bib_path else ex["bib_files"]) if b and os.path.exists(b)]
    failures, warnings = [], []
    if not bibs:
        failures.append({"type": "no-bib", "detail": "no readable .bib — pass bib_path or declare \\bibliography{…}"})
    entries = {}
    for b in bibs:
        with open(b, errors="replace") as fh:
            for e in _parse_bib(fh.read())["entries"]:
                entries.setdefault(e["key"], (b, e))
    cite_keys = set(ex["keys"])
    nocite_all = any(c["key"] == "*" for c in ex["cites"])
    for k in sorted(cite_keys - set(entries)):
        failures.append({"type": "undefined-cite", "key": k, "detail": "cited in the .tex but in no .bib"})
    if not nocite_all:
        for k in sorted(set(entries) - cite_keys):
            warnings.append({"type": "uncited-entry", "key": k, "detail": "in the .bib but never cited"})
    ver, unofficial = {}, []
    if verify:
        for b in bibs:
            keys_here = [k for k, (bb, _) in entries.items() if bb == b and k in cite_keys]
            if not keys_here:
                continue
            rep = verify_bib(b, keys=keys_here, tex_path=tex_path)
            if rep.get("error"):
                failures.append({"type": "verify-error", "detail": rep["error"]})
                continue
            for r in rep["entries"]:
                ver[r["key"]] = r
        for k, r in ver.items():
            detail = "; ".join(r.get("notes") or [])
            if r["status"] in _OK_STATUS - {"FOUND"}:
                pass
            elif r["status"] in ("PROBABLE", "FOUND"):
                warnings.append({"type": "existence", "key": k, "status": r["status"], "detail": detail})
            else:
                failures.append({"type": "existence", "key": k, "status": r["status"], "detail": detail})
            if not r.get("provenance"):
                unofficial.append(k)
    ledger = _load_ledger(workdir)["entries"]
    verdicts, coverage, missing = Counter(), {}, []
    for c in ex["cites"]:
        if c["nocite"]:
            continue
        L = ledger.get(f"{c['key']}|{_claim_hash(c['claim'])}")
        loc = {"key": c["key"], "file": c["file"], "line": c["line"], "claim": c["claim"][:240]}
        if not L:
            missing.append(c)
            coverage[c["key"]] = coverage.get(c["key"], "") + " MISSING"
            continue
        vid = (ver.get(c["key"]) or {}).get("id")
        if vid and L["id"] != vid:
            failures.append(dict(loc, type="support-stale", verdict=L["verdict"],
                                 detail=f"verdict was judged against {L['id']} but the entry now resolves to {vid} — re-judge"))
            coverage[c["key"]] = coverage.get(c["key"], "") + " STALE"
            continue
        verdicts[L["verdict"]] += 1
        coverage[c["key"]] = coverage.get(c["key"], "") + " " + L["verdict"] + ("(abs)" if L["basis"] == "abstract" else "")
        if L["verdict"] in ("UNSUPPORTED", "CONTRADICTS"):
            failures.append(dict(loc, type="support", verdict=L["verdict"], detail=L.get("note")))
        elif L["verdict"] in ("PARTIAL", "UNVERIFIABLE"):
            warnings.append(dict(loc, type="support", verdict=L["verdict"], detail=L.get("note")))
        elif L["basis"] == "abstract":
            warnings.append(dict(loc, type="support-basis", verdict=L["verdict"],
                                 detail="judged from the abstract only — pass pdf_path to fetch_text for a full-text check"))
    for c in missing:
        (failures if require_support else warnings).append(
            {"type": "support-missing", "key": c["key"], "file": c["file"], "line": c["line"],
             "claim": c["claim"][:240], "detail": "no support verdict recorded for this citation instance"})
    for k in cite_keys:
        coverage.setdefault(k, "")
    report = {"ok": not failures, "tex": os.path.abspath(tex_path), "bibs": bibs,
              "n_instances": ex["n_instances"], "n_keys": ex["n_keys"],
              "existence_counts": dict(Counter(r["status"] for r in ver.values())),
              "support_counts": dict(verdicts), "support_missing": len(missing),
              "unofficial_entries": sorted(unofficial), "failures": failures, "warnings": warnings,
              "checked": _now_iso()}
    coverage = {k: v.strip() or "—" for k, v in coverage.items()}
    md_path = _project_path(workdir, "audit.md")
    with open(md_path, "w") as fh:
        fh.write(_audit_markdown(report, ver, coverage))
    report["report"] = md_path
    _write_project(workdir, "audit.json", report)
    report["summary"] = (f"{'PASS' if report['ok'] else 'FAIL'}: {len(failures)} failure(s), {len(warnings)} warning(s); "
                         f"{ex['n_instances']} citation instances, {len(missing)} without a support verdict; "
                         f"existence {report['existence_counts']}")
    return report


# ---------------------------------------------------------------------------
# ping + dispatch
# ---------------------------------------------------------------------------

def ping() -> dict:
    """Liveness and capability check: token, PDF extractor, cache location."""
    info = {"ok": True, "server": "cite-check", "version": VERSION, "python": sys.version.split()[0],
            "ads_token": bool(_ads_token()), "ads_token_source": key_value("ads")[1],
            "keyring": _keyring_backend() or "file", "config_dir": _config_dir(),
            "pdftotext": bool(shutil.which("pdftotext")), "cache_dir": CACHE_DIR, "mailto": _mailto() or None}
    if _key_cache.get("warnings"):
        info["key_warnings"] = sorted(set(_key_cache["warnings"]))
    try:
        import pypdf
        info["pypdf"] = pypdf.__version__
    except ImportError:
        info["pypdf"] = None
    try:
        import importlib.metadata as md
        info["mcp"] = md.version("mcp")
    except Exception:
        info["mcp"] = None
    if not info["ads_token"]:
        info["note"] = ("no ADS token — ADS search/export disabled (others active). Get one at "
                        "https://ui.adsabs.harvard.edu/user/settings/token and store it with "
                        "`bash mcp/setup_mcp.sh --keys` (or export ADS_API_TOKEN)")
    if not info["pdftotext"] and not info["pypdf"]:
        info["warning"] = "no PDF text extractor — full-text support checks limited to arXiv HTML and abstracts"
    return info


TOOLS = {
    "ping": ping,
    "resolve_citation": resolve_citation,
    "search_citation": search_citation,
    "fetch_bibtex": fetch_bibtex,
    "bib_add": bib_add,
    "verify_bib": verify_bib,
    "extract_cites": extract_cites,
    "fetch_text": fetch_text,
    "find_passages": find_passages,
    "record_support": record_support,
    "ledger_read": ledger_read,
    "audit": audit,
}


def _run_mcp_server():
    try:
        from mcp.server import MCPServer as ServerClass          # mcp >= 2.0
    except ImportError:
        try:
            from mcp.server.fastmcp import FastMCP as ServerClass  # mcp 1.x
        except ImportError:
            sys.exit("The `mcp` package is not installed. Run mcp/setup_mcp.sh, or use "
                     "CLI mode: server.py call <tool> '<json>'")
    app = ServerClass("cite-check")
    for fn in TOOLS.values():
        app.tool()(fn)
    app.run()


def _run_keys(argv):
    """server.py keys names | backend | fields <name> | list [--json] | set <name> [--no-test]
    (value on stdin) | test <name> | delete <name>|--all. Plain text for shell use."""
    sub = argv[0] if argv else "list"
    if sub == "names":
        print("\n".join(KEYS))
    elif sub == "backend":
        print(_keyring_backend() or f"file ({os.path.join(_config_dir(), 'keys')}, mode 0600)")
    elif sub == "fields" and len(argv) > 1 and argv[1] in KEYS:
        st = next(k for k in key_status() if k["name"] == argv[1])
        # unit separator: bash `read` keeps empty fields only for a non-blank IFS
        print("\x1f".join([st["label"], st["source"] if st["configured"] else "none", st["masked"] or "",
                           st["url"] or "", st["enables"], "1" if st["secret"] else "0"]))
    elif sub == "list":
        rows = key_status()
        if "--json" in argv:
            print(json.dumps(rows, indent=2, ensure_ascii=False))
        else:
            for k in rows:
                state = f"{k['source']} ({k['masked']})" if k["configured"] else "not configured"
                print(f"{k['name']:8s} {k['label']}: {state}")
            for w in sorted(set(_key_cache.get("warnings", []))):
                print(f"WARNING: {w}")
    elif sub == "set" and len(argv) > 1:
        value = sys.stdin.read().strip()
        r = key_store(argv[1], value, test="--no-test" not in argv)
        if not r["stored"]:
            sys.exit(f"not stored: {r['error']}")
        line = f"stored in {r['backend']}" + (f" at {r['where']}" if r["backend"] in ("file", "config") else "")
        if r.get("tested"):
            line += f"; {r['tested']['detail']}"
        print(line)
    elif sub == "test" and len(argv) > 1 and argv[1] == "ads":
        tok = _ads_token()
        if not tok:
            sys.exit("no ADS token configured")
        r = _ads_test(tok)
        print(r["detail"])
        sys.exit(0 if r["ok"] else 1)
    elif sub == "delete" and len(argv) > 1:
        names = list(KEYS) if argv[1] == "--all" else [argv[1]]
        for n in names:
            r = key_delete(n)
            print(f"{n}: " + (f"removed from {', '.join(r['removed_from'])}" if r["deleted"] else r.get("error") or "nothing stored"))
    else:
        sys.exit("usage: server.py keys names|backend|fields <name>|list [--json]|set <name> [--no-test]|test ads|delete <name>|--all")


def _run_cli(argv):
    if argv and argv[0] == "keys":
        return _run_keys(argv[1:])
    if not argv or argv[0] in ("-h", "--help") or argv[0] != "call":
        names = "\n  ".join(TOOLS)
        sys.exit(f"usage: server.py                      (MCP stdio server)\n"
                 f"       server.py call <tool> '<json-args>'\n"
                 f"       server.py keys list|set <name>|delete <name>|test ads   (API keys)\n\ntools:\n  {names}")
    if len(argv) < 2 or argv[1] not in TOOLS:
        sys.exit(f"unknown tool {argv[1] if len(argv) > 1 else '(none)'!r} — one of: {', '.join(TOOLS)}")
    try:
        kwargs = json.loads(argv[2]) if len(argv) > 2 else {}
    except json.JSONDecodeError as exc:
        sys.exit(f"invalid JSON args: {exc}")
    result = TOOLS[argv[1]](**kwargs)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if isinstance(result, dict) and (result.get("error") or result.get("ok") is False
                                     or result.get("resolved") is False or result.get("recorded") is False
                                     or (argv[1] == "fetch_bibtex" and not result.get("bibtex"))):
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        _run_cli(sys.argv[1:])
    else:
        _run_mcp_server()
