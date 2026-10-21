"""Source text acquisition, content snapshots and passage retrieval."""

from collections import Counter
import hashlib
import json
import math
import os
import re
import typing
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from cite_check_engine import models as _engine_models
from cite_check_engine import config as _engine_config
from cite_check_engine import identifiers as _engine_identifiers
from cite_check_engine import persistence as _engine_persistence
from cite_check_engine import registry_clients as _engine_registry_clients
from cite_check_engine import resolution as _engine_resolution
from cite_check_engine import text as _engine_text
from cite_check_engine import transport as _engine_transport


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
        status, data = _engine_transport._http(url, binary=True, timeout=120, headers={"Accept": "application/pdf,*/*"})
    except RuntimeError:
        return False
    if status != 200 or not isinstance(data, bytes) or not data.startswith(b"%PDF") or len(data) > _engine_config.MAX_PDF_BYTES:
        return False
    with open(dest, "wb") as fh:
        fh.write(data)
    return True

def _obtain_text(rec: typing.Mapping[str, typing.Any], cid: str) -> tuple:
    """(text, basis, source) — arXiv HTML, arXiv PDF, an open-access PDF the
    registries point at, else the abstract, else nothing. A GitHub repository
    yields its README with its description and CITATION.cff abstract (basis
    readme)."""
    if rec.get("github"):
        return _github_text(rec)
    if rec.get("doi") and (not rec.get("arxiv") or not rec.get("abstract") or not rec.get("pdf_urls")):
        try:                                            # OpenAlex knows OA copies and abstracts
            oa = _engine_registry_clients._openalex_get("https://doi.org/" + rec["doi"])
        except RuntimeError:
            oa = None
        if oa:
            rec = _engine_resolution._merge_records(rec, oa)
            _engine_persistence._record_cache_put(rec)
    if rec.get("arxiv"):
        arxiv_id = rec.get("arxiv_version") or rec["arxiv"]
        try:
            status, body = _engine_transport._http(f"https://arxiv.org/html/{arxiv_id}", cache=False, timeout=60)
        except RuntimeError:
            status, body = 0, ""
        if status == 200 and "ltx_document" in body:
            text = _tidy_text(_html_to_text(body))
            if len(text) > 2000:
                return text, "fulltext", "arxiv-html"
        pdf = _engine_persistence._cache_file("pdf", _engine_identifiers._cache_key(cid) + ".pdf")
        if _download_pdf(f"https://arxiv.org/pdf/{arxiv_id}", pdf):
            text = _tidy_text(_pdf_to_text(pdf))
            if len(text) > 2000:
                return text, "fulltext", "arxiv-pdf"
    if rec.get("arxiv_version"):
        return "", "none", f"arxiv:{rec['arxiv_version']} unavailable"
    for url in rec.get("pdf_urls") or []:
        pdf = _engine_persistence._cache_file("pdf", _engine_identifiers._cache_key(cid) + ".pdf")
        if _download_pdf(url, pdf):
            text = _tidy_text(_pdf_to_text(pdf))
            if len(text) > 2000:
                return text, "fulltext", url
    if rec.get("abstract"):
        return rec.get("title", "") + "\n\n" + rec["abstract"], "abstract", ",".join(rec.get("registries") or [rec["registry"]])
    return "", "none", None

def _github_text(rec: typing.Mapping[str, typing.Any]) -> tuple:
    repo = rec.get("repo") or {}
    full = repo.get("full_name") or rec["github"]
    head = "\n\n".join(x for x in dict.fromkeys([rec.get("title", ""), repo.get("description") or "",
                                                  rec.get("abstract") or ""]) if x)
    query = "?" + urllib.parse.urlencode({"ref": rec["pinned_sha"]}) if rec.get("pinned_sha") else ""
    status, body = _engine_registry_clients._gh_api(f"/repos/{full}/readme{query}", accept="application/vnd.github.html+json")
    readme = _tidy_text(_html_to_text(body)) if status == 200 else ""
    if len(readme) > 200:
        return head + "\n\n" + readme, "readme", f"github-readme:{full}@{rec.get('pinned_sha', 'HEAD')}"
    if head.strip():
        return head, "abstract", f"github:{full}"
    return "", "none", None

def fetch_text(identifier: str, pdf_path: str | None = None, text_path: str | None = None,
               refresh: bool = False, max_chars: int = 0,
               version: str | None = None) -> dict:
    """Get the cited paper's text for support checking and cache it: arXiv
    HTML → arXiv PDF → open-access PDF → abstract only. For paywalled papers
    pass pdf_path (or text_path) to ingest your own copy. Returns basis
    (fulltext | readme | abstract | none), source, chars, the cache path, and
    the abstract; max_chars>0 inlines that much text. A GitHub repository's
    text is its README, description and CITATION.cff abstract (basis readme).
    """
    rec = _engine_resolution._full_record(identifier)
    if rec is None:
        r = _engine_resolution.resolve_citation(identifier)
        return {"error": f"cannot resolve {identifier}: {r.get('reason') or r.get('error')}"}
    try:
        rec = _engine_resolution._with_pin(rec, identifier, version)
    except (RuntimeError, ValueError) as exc:
        return {"error": str(exc)}
    cid = _engine_identifiers._text_identity(rec)
    tp, mp = _engine_persistence._text_paths(cid)
    meta = None if (refresh or pdf_path or text_path) else _engine_persistence._load_text_meta(cid)
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
        meta = {"id": _engine_identifiers._canonical(rec), "cache_id": cid,
                "requested_version": rec.get("requested_version") or rec.get("arxiv_version"), "basis": basis, "source": source, "chars": len(text),
                "fetched": _engine_persistence._now_iso(), "title": rec.get("title", ""),
                "extraction_version": _engine_config.TEXT_EXTRACTION_VERSION,
                "version": rec.get("pinned_sha") or rec.get("arxiv_version")}
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        snapshot = os.path.join(os.path.dirname(tp), digest + ".txt")
        meta["text_sha256"] = digest
        with _engine_persistence._file_lock(tp):
            # Immutable snapshot first; metadata is the single commit point.
            _engine_persistence._atomic_write(snapshot, text)
            _engine_persistence._atomic_write(mp, json.dumps(meta))
        meta["path"] = snapshot
    out = dict(meta)
    out["abstract"] = ("" if rec.get("arxiv_version") else (rec.get("abstract") or "")[:2500])
    if max_chars and out["basis"] != "none":
        with open(out["path"], encoding="utf-8", errors="replace") as fh:
            out["text"] = fh.read()[:max_chars]
    if out["basis"] == "none":
        out["note"] = "no text obtainable — pass pdf_path= with your copy of the paper, or judge UNVERIFIABLE"
    elif out["basis"] == "abstract":
        out["note"] = ("description only (the repository has no README)" if rec.get("github") else
                       "abstract only (paywalled, no open-access copy found) — pass pdf_path= for a full-text check")
    elif out["basis"] == "readme":
        out["note"] = ("repository README, description and CITATION.cff abstract — the code itself is not read; a "
                       "claim about what the code does that its documentation does not state is UNVERIFIABLE")
    return out

def _sentences(text: str) -> list:
    out = []
    for para in re.split(r"\n\s*\n", text):
        para = re.sub(r"\s+", " ", para).strip()
        if len(para) >= 20:
            out += _engine_text._split_sentences(para)
    return [s for s in out if len(s) >= 25]

def find_passages(identifier: str, claims: list[str] | str, k: int = 6, window: int = 2,
                  version: str | None = None) -> dict:
    """For each claim, the top-k passages (windows of `window` sentences) of
    the cited paper ranked by content-word and bigram overlap, plus the
    abstract. This is what the judge reads before quoting evidence.
    """
    if (not isinstance(k, int) or isinstance(k, bool) or k < 1
            or not isinstance(window, int) or isinstance(window, bool) or window < 1):
        return {"error": "k and window must be positive integers"}
    if not isinstance(claims, (list, str)) or not claims:
        return {"error": "claims must be a nonempty string or list of strings"}
    if isinstance(claims, str):
        claims = [claims]
    if any(not isinstance(claim, str) or not claim.strip() for claim in claims):
        return {"error": "claims must contain nonempty strings"}
    meta = fetch_text(identifier, version=version)
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
    words = [set(_engine_text._content_words(s)) for s in sents]
    n = len(sents)
    df = Counter(w for ws in words for w in ws)

    def idf(w):
        return math.log((n + 1) / (df.get(w, 0) + 1)) + 1

    results = []
    for claim in claims:
        cw = _engine_text._content_words(claim)
        cset, bigrams = set(cw), set(zip(cw, cw[1:]))
        scored = []
        for i in range(n):
            win = set().union(*words[i:i + window])
            s = sum(idf(w) for w in cset if w in win)
            if s and bigrams:
                wtext = " ".join(_engine_text._content_words(" ".join(sents[i:i + window])))
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

def _current_source_identity(
    identifier: str,
) -> _engine_models.SourceSnapshot | None:
    meta = _engine_persistence._load_text_meta(identifier)
    if meta is None:
        return None
    try:
        with open(meta["path"], encoding="utf-8", errors="replace") as source:
            return _engine_identifiers._source_identity(meta, source.read())
    except OSError:
        return None
