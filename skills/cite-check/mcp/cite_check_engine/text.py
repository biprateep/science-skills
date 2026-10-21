"""Pure scientific-text normalization and comparison helpers."""

import difflib
import html
import re
import unicodedata
from cite_check_engine import parsing as _engine_parsing


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

_ABBREV = ("e.g", "i.e", "et al", "cf", "vs", "viz", "ca", "approx", "resp", "Fig", "Figs", "Eq", "Eqs",
           "Sec", "Secs", "Sect", "Ref", "Refs", "Tab", "Tabs", "Dr", "Prof", "Mr", "Ms", "Mrs", "No", "Nos",
           "Vol", "vol", "pp", "p", "Phys", "Rev", "Astrophys", "Astron", "Ann", "Proc", "J", "Ser", "Lett",
           "Suppl", "Chap", "Ch", "St", "Univ", "Inc", "Ltd", "approx", "min", "max")

def _split_sentences(paragraph: str) -> list:
    prot = paragraph
    for ab in _ABBREV:
        prot = re.sub(r"\b" + re.escape(ab) + r"\.", ab.replace(".", "<DOT>") + "<DOT>", prot)
    prot = re.sub(r"\b([A-Z])\.", r"\1<DOT>", prot)              # initials
    prot = re.sub(r"(\d)\.(\d)", r"\1<DOT>\2", prot)              # decimals
    prot = _engine_parsing._TEX_MATH.sub(
        lambda match: match[0].replace(".", "<DOT>"), prot
    )
    parts = re.split(r"(?<=[.!?])\s+(?=[\"'(\[\u27e8$A-Z0-9\\])", prot)
    return [p.replace("<DOT>", ".").strip() for p in parts if p.strip()]
