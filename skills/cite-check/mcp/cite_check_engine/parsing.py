"""Pure BibTeX parsing and shared citation syntax."""

import re
import urllib.error
import urllib.parse
import urllib.request
from cite_check_engine import identifiers as _engine_identifiers


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
            if body[i:].strip().strip(",").strip():
                raise ValueError("malformed bibliography field")
            break
        name, i, parts = m.group(1).lower(), m.end(), []
        while True:
            while i < n and body[i].isspace():
                i += 1
            if i >= n:
                raise ValueError("missing bibliography field value")
            if body[i] == "{":
                j = _find_close(body, i)
                if j < 0:
                    raise ValueError("unterminated bibliography field")
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
                if j >= n:
                    raise ValueError("unterminated quoted bibliography field")
                parts.append(body[i + 1:j])
                i = j + 1
            else:
                m2 = _BARE.match(body, i)
                if not m2:
                    raise ValueError("missing bibliography field value")
                parts.append(m2.group(0))
                i = m2.end()
            while i < n and body[i].isspace():
                i += 1
            if i < n and body[i] == "#":
                i += 1
                continue
            break
        fields[name] = re.sub(r"\s+", " ", "".join(parts)).strip()
        if i < n and body[i] != ",":
            raise ValueError("missing comma between bibliography fields")
        i += 1
    return fields

def _parse_prov(s: str) -> dict:
    out = {}
    for part in re.split(r";\s*", s):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip().strip('"')
    return out

def _next_bib_entry(text: str, start: int) -> int:
    """Find an entry marker outside percent comments between entries."""
    while start < len(text):
        marker = re.search(r"[%@]", text[start:])
        if marker is None:
            return -1
        position = start + marker.start()
        if text[position] == "@":
            return position
        newline = text.find("\n", position)
        if newline < 0:
            return -1
        start = newline + 1
    return -1

def _parse_bib(text: str) -> dict:
    """Entries with raw text and span, plus @comment/@string/@preamble blocks.
    A `@comment{cite-check: …}` directly before an entry becomes its provenance."""
    entries, comments, keys, errors = [], [], {}, []
    i, last_prov, last_prov_end = 0, None, -1
    head = re.compile(r"@\s*([A-Za-z]+)\s*([{(])")
    while True:
        at = _next_bib_entry(text, i)
        if at < 0:
            break
        m = head.match(text, at)
        if not m:
            errors.append(f"malformed entry at character {at}")
            i = at + 1
            continue
        etype, open_idx = m.group(1).lower(), m.end() - 1
        close = _find_close(text, open_idx)
        if close < 0:
            errors.append(f"unterminated entry at character {at}")
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
        km = re.match(r"\s*([^,\s]+)\s*,", body)
        key = km.group(1) if km else ""
        try:
            if not km:
                raise ValueError("missing entry key or comma")
            fields = _parse_fields(body[km.end():])
        except ValueError as exc:
            errors.append(f"{key or at}: {exc}")
            i = close + 1
            continue
        if key in keys:
            errors.append(f"duplicate bibliography key: {key}")
        prov = _parse_prov(last_prov) if last_prov and not text[last_prov_end:at].strip() else None
        last_prov = None
        entry = {"type": etype, "key": key, "fields": fields, "raw": raw,
                 "start": at, "end": close + 1, "provenance": prov}
        entries.append(entry)
        keys.setdefault(key, entry)
        i = close + 1
    return {"entries": entries, "comments": comments, "keys": keys,
            "errors": errors, "complete": not errors}

def _entry_ids(entry: dict) -> dict:
    """Identifiers an entry carries: doi / arxiv / bibcode, from wherever
    authors and export tools put them (doi, eprint, url, adsurl, note, eid…)."""
    f, ids = entry["fields"], {}
    for src in (f.get("doi", ""), f.get("url", ""), f.get("note", "")):
        m = _engine_identifiers._DOI_ANY.search(src)
        if m:
            k, v = _engine_identifiers._classify(m.group(0))
            if k in ("doi", "arxiv"):
                ids.setdefault(k, v)
    ep = f.get("eprint", "").strip()
    if ep and _engine_identifiers._classify(ep)[0] == "arxiv":
        ids["arxiv"] = _engine_identifiers._classify(ep)[1]
    if "arxiv" not in ids:
        blob = " ".join(f.get(k, "") for k in ("url", "adsurl", "note", "howpublished", "eid", "journal", "eprint"))
        m = re.search(r"(?:arxiv:|arxiv\.org/(?:abs|pdf|html)/)\s*(" + _engine_identifiers._ARXIV_CORE + r")", blob, re.I)
        if m:
            ids["arxiv"] = _engine_identifiers._strip_arxiv_version(m.group(1))
    bc = f.get("bibcode", "").strip()
    m = re.search(r"/abs/([^/\s}]+)", f.get("adsurl", ""))
    if m:
        bc = urllib.parse.unquote(m.group(1))
    if bc and _engine_identifiers._BIBCODE_RE.match(bc):
        ids["bibcode"] = bc
    srcs = ["url", "howpublished", "repository", "code"]          # the entry's locator, not a "code at…" remark
    if entry["type"] in _SOFTWARE_TYPES:
        srcs.append("note")
    for k in srcs:
        m = _engine_identifiers._GITHUB_ANY.search(f.get(k, ""))
        if m:
            kind, val = _engine_identifiers._classify("github.com/" + m.group(1) + "/" + m.group(2))
            if kind == "github":
                ids["github"] = val
                break
    return ids

_SOFTWARE_TYPES = {"software", "softwareversion", "softwaremodule", "codefragment", "misc", "online",
                   "electronic", "www", "manual", "unpublished"}

def _entry_ref(entry: dict) -> str | None:
    """The version a repository entry cites: its version field, or the
    tag / branch / commit in its GitHub URL."""
    f = entry["fields"]
    if f.get("version", "").strip():
        return re.sub(r"[{}]", "", f["version"]).strip()
    for k in ("url", "howpublished", "repository", "note"):
        m = _engine_identifiers._GITHUB_REF.search(f.get(k, ""))
        if m:
            return urllib.parse.unquote(m.group(1))
    return None

def _entry_arxiv_version(entry: dict) -> str | None:
    """Return a version named in the entry's identifier-bearing fields."""
    fields = entry["fields"]
    for key in ("eprint", "arxiv", "url", "doi"):
        match = re.search(_engine_identifiers._ARXIV_CORE + r"v\d+", fields.get(key, ""), re.I)
        if match:
            return match.group(0)
    return None

_CITE_CMD = re.compile(
    r"\\(?P<cmd>[Cc]ite[a-zA-Z]*|[Pp]arencites?|[Tt]extcites?|[Aa]utocites?|"
    r"[Ff]oot(?:full)?cites?(?:text)?|[Ss]martcites?|[Ss]upercites?|[Ff]ullcite|nocite)\*?(?![a-zA-Z])")

_CITE_EXCLUDE = {"citetext", "citestyle", "citeindextype", "citename", "citeauthoryear", "citenumfont"}

_CITE_TOKEN = re.compile(r"\u27e8cite#(\d+)\u27e9")

_TEX_MATH = re.compile(
    r"\\begin\{(?P<math_env>(?:equation|align|gather|multline|eqnarray|"
    r"displaymath|flalign|alignat)\*?)\}.*?\\end\{(?P=math_env)\}"
    r"|\\\[.*?\\\]|\$\$.*?\$\$|\\\(.*?\\\)"
    r"|(?<!\\)\$(?!\$)(?:\\.|[^$\\])*\$",
    re.S,
)
