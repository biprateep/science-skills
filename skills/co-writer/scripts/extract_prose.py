#!/usr/bin/env python3
"""Turn a LaTeX paper into readable prose for voice extraction.

    python extract_prose.py main.tex [more.tex ...] [--out-dir DIR]

Writes one <parent-dir>--<stem>.prose.md per input (so five papers that are
all called main.tex do not collide), or prints to stdout for a single input
with no --out-dir.

What survives, and why:
  section headings      kept as Markdown headings -- the voice profile indexes
                        exemplars by section function (abstract, methods, ...)
  inline math           kept verbatim -- how symbols are woven into sentences
                        is part of the voice in physics writing
  display equations     replaced by a ⟨display equation⟩ line -- the prose that
                        introduces an equation matters, the equation does not
  citations             \\citet -> [Author et al.], \\citep/\\cite -> [cite] --
                        placement and density are visible, keys are not
  footnotes             inlined as (footnote: ...)
  figure/table captions collected in a trailing "Captions" section
What is dropped: preamble, author blocks, floats' bodies, tables, verbatim,
bibliography, acknowledgments and funding sections, comments.

Zero-argument \\newcommand macros are expanded first so that \\desi reads as
DESI. \\input/\\include are resolved relative to the input file.

Standard library only.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

MATH_ENVS = (
    "equation", "align", "eqnarray", "gather", "multline", "displaymath",
    "flalign", "alignat", "split",
)
FLOAT_ENVS = ("figure", "table", "subfigure", "wrapfigure", "deluxetable", "longtable")
DROP_ENVS = (
    "thebibliography", "verbatim", "lstlisting", "tabular", "tabularx",
    "keywords", "CJK",
)
ACK_ENVS = ("ack", "acknowledgments", "acknowledgements")

# Commands removed together with their braced arguments.
DROP_WITH_ARGS = (
    "label", "bibliography", "bibliographystyle", "includegraphics",
    "newcommand", "renewcommand", "providecommand", "DeclareRobustCommand",
    "usepackage", "documentclass", "PassOptionsToPackage",
    "title", "author", "affiliation", "affil", "email", "thanks", "altaffiliation",
    "date", "pubyear", "pagerange", "workshoptitle", "setlength", "vspace",
    "hspace", "hskip", "vskip", "url", "nolinkurl", "caption", "orcid",
    "collaboration", "correspondingauthor", "keywords", "shorttitle", "shortauthors",
)
# Commands whose braced argument IS prose and should be unwrapped.
KEEP_ARG = (
    "text", "textbf", "textit", "texttt", "textsc", "textrm", "textsf",
    "emph", "underline", "uppercase", "lowercase", "mbox", "hbox",
)
SECTION_LEVELS = {
    "section": "##", "subsection": "###", "subsubsection": "####",
    "paragraph": "#####", "chapter": "#", "part": "#",
}
CITE_TEXTUAL = ("citet", "citeauthor", "citealt")
CITE_PARENTHETICAL = ("citep", "cite", "citealp", "citeyear", "citeyearpar", "citenum")
REF_CMDS = ("ref", "eqref", "pageref", "autoref", "cref", "Cref")

DISPLAY_TOKEN = "\n\n\u27e8display equation\u27e9\n\n"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def strip_comments(tex: str) -> str:
    """Remove % comments, honouring the \\% escape."""
    out = []
    for line in tex.split("\n"):
        buf, i = [], 0
        while i < len(line):
            ch = line[i]
            if ch == "\\" and i + 1 < len(line):
                buf.append(line[i:i + 2])
                i += 2
                continue
            if ch == "%":
                break
            buf.append(ch)
            i += 1
        out.append("".join(buf))
    return "\n".join(out)


def _match_brace(text: str, open_idx: int) -> int:
    """Index just past the '}' matching the '{' at open_idx, or -1."""
    depth, i = 0, open_idx
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


def _braced_arg(text: str, start: int):
    """(inner, end) for the braced group starting at or after `start`."""
    open_idx = text.find("{", start)
    if open_idx == -1:
        return None, -1
    close = _match_brace(text, open_idx)
    if close == -1:
        return None, -1
    return text[open_idx + 1:close - 1], close


def resolve_inputs(path: Path, seen=None, depth: int = 0) -> str:
    """Inline \\input{file} / \\include{file} relative to `path`."""
    seen = seen or set()
    if path in seen or depth > 8:
        return ""
    seen.add(path)
    tex = strip_comments(path.read_text(encoding="utf-8", errors="replace"))

    def repl(m):
        name = m.group(2).strip()
        cand = path.parent / name
        if cand.suffix == "":
            cand = cand.with_suffix(".tex")
        return resolve_inputs(cand, seen, depth + 1) if cand.exists() else " "

    return re.sub(r"\\(input|include)\s*\{([^}]*)\}", repl, tex)


def expand_simple_macros(tex: str) -> str:
    """Expand zero-argument \\newcommand{\\x}{...} so \\desi reads as DESI."""
    macros = {}
    for m in re.finditer(r"\\(?:re)?newcommand\*?\s*\{?\\([A-Za-z@]+)\}?\s*(\[\d\])?\s*\{", tex):
        if m.group(2):  # takes arguments; leave alone
            continue
        body, _ = _braced_arg(tex, m.end() - 1)
        if body is not None and "\\newcommand" not in body and len(body) < 200:
            macros[m.group(1)] = body
    for _ in range(3):  # macros that reference macros
        for name, body in macros.items():
            tex = re.sub(r"\\" + re.escape(name) + r"(?![A-Za-z@])\s*(\{\})?", lambda _m: body, tex)
    return tex


def document_body(tex: str) -> str:
    start = re.search(r"\\begin\{document\}", tex)
    body = tex[start.end():] if start else tex
    end = re.search(r"\\end\{document\}", body)
    return body[:end.start()] if end else body


def find_environments(text: str, name: str):
    """Yield (start, end) spans of \\begin{name}...\\end{name}, nesting-aware."""
    pattern = re.compile(r"\\(begin|end)\{" + re.escape(name) + r"\*?\}")
    depth, start = 0, None
    for m in pattern.finditer(text):
        if m.group(1) == "begin":
            if depth == 0:
                start = m.start()
            depth += 1
        else:
            depth -= 1
            if depth == 0 and start is not None:
                yield (start, m.end())
                start = None
            if depth < 0:
                depth = 0


def replace_environments(text: str, names, replacement: str) -> str:
    for name in names:
        for start, end in reversed(list(find_environments(text, name))):
            text = text[:start] + replacement + text[end:]
    return text


def harvest_captions(text: str):
    captions = []
    while True:
        m = re.search(r"\\caption\*?\s*(\[[^\]]*\])?\s*\{", text)
        if not m:
            break
        inner, close = _braced_arg(text, m.end() - 1)
        if inner is None:
            text = text[:m.start()] + " " + text[m.end():]
            continue
        captions.append(inner)
        text = text[:m.start()] + " " + text[close:]
    return text, captions


def drop_ack_sections(text: str) -> str:
    """Drop \\section*{Acknowledg...}, funding and data-availability bodies."""
    pattern = re.compile(
        r"\\section\*?\s*\{[^}]*(?:acknowledg|funding|data availability)[^}]*\}",
        re.IGNORECASE,
    )
    while True:
        m = pattern.search(text)
        if not m:
            break
        nxt = re.search(r"\\(?:section|chapter|appendix|bibliography)\b", text[m.end():])
        end = m.end() + (nxt.start() if nxt else len(text) - m.end())
        text = text[:m.start()] + " " + text[end:]
    return text


def replace_citations(text: str) -> str:
    args = r"\*?\s*(?:\[[^\]]*\])*\s*\{[^}]*\}"
    text = re.sub(r"\\(?:" + "|".join(CITE_TEXTUAL) + r")" + args, "[Author et al.]", text)
    text = re.sub(r"\\(?:" + "|".join(CITE_PARENTHETICAL) + r")" + args, "[cite]", text)
    return text


def replace_refs(text: str) -> str:
    args = r"\*?\s*\{[^}]*\}"
    return re.sub(r"\\(?:" + "|".join(REF_CMDS) + r")" + args, "[ref]", text)


def inline_footnotes(text: str) -> str:
    while True:
        m = re.search(r"\\footnote\s*\{", text)
        if not m:
            break
        inner, close = _braced_arg(text, m.end() - 1)
        if inner is None:
            text = text[:m.start()] + " " + text[m.end():]
            continue
        text = text[:m.start()] + " (footnote: " + inner.strip() + ")" + text[close:]
    return text


def render_headings(text: str) -> str:
    for cmd, marks in SECTION_LEVELS.items():
        pattern = re.compile(r"\\" + cmd + r"\*?\s*(\[[^\]]*\])?\s*\{")
        while True:
            m = pattern.search(text)
            if not m:
                break
            inner, close = _braced_arg(text, m.end() - 1)
            if inner is None:
                text = text[:m.start()] + " " + text[m.end():]
                continue
            text = text[:m.start()] + f"\n\n{marks} {inner.strip()}\n\n" + text[close:]
    text = replace_environments(text, ("abstract",), "")  # handled below
    return text


def abstract_as_section(text: str) -> str:
    spans = list(find_environments(text, "abstract"))
    for start, end in reversed(spans):
        inner = re.sub(r"\\(begin|end)\{abstract\}", "", text[start:end])
        text = text[:start] + "\n\n## Abstract\n\n" + inner.strip() + "\n\n" + text[end:]
    return text


def strip_commands(text: str) -> str:
    """Unwrap prose-bearing commands, delete the rest."""
    for cmd in KEEP_ARG:
        pattern = re.compile(r"\\" + cmd + r"\s*\{")
        while True:
            m = pattern.search(text)
            if not m:
                break
            inner, close = _braced_arg(text, m.end() - 1)
            if inner is None:
                text = text[:m.start()] + " " + text[m.end():]
                continue
            text = text[:m.start()] + inner + text[close:]

    text = re.sub(r"\\href\s*\{[^}]*\}\s*\{", "{", text)  # \href{url}{shown} -> shown

    for cmd in DROP_WITH_ARGS:
        pattern = re.compile(r"\\" + cmd + r"\*?\s*(\[[^\]]*\])?\s*\{")
        while True:
            m = pattern.search(text)
            if not m:
                break
            _, close = _braced_arg(text, m.end() - 1)
            if close == -1:
                text = text[:m.start()] + " " + text[m.end():]
                continue
            text = text[:m.start()] + " " + text[close:]

    text = re.sub(r"\\begin\{[^}]*\}(\s*\[[^\]]*\])?", " ", text)
    text = re.sub(r"\\end\{[^}]*\}", " ", text)
    text = re.sub(r"\\item\b", "\n- ", text)
    text = re.sub(r"\\(?:ldots|dots)\b", "...", text)
    text = re.sub(r"\\(?:,|;|!|quad|qquad)", " ", text)
    text = re.sub(r"\\[a-zA-Z@]+\*?", " ", text)   # remaining bare commands
    text = re.sub(r"\\([&%_#$])", r"\1", text)      # \& \% \_ \# \$
    text = re.sub(r"\\[^a-zA-Z]", " ", text)
    text = text.replace("{", "").replace("}", "")
    text = text.replace("``", "\u201c").replace("''", "\u201d")
    text = text.replace("~", " ")
    return tidy(text)


def protect_math(text: str):
    """Swap inline math for placeholders so command stripping leaves it alone."""
    store = []

    def keep(m):
        store.append(m.group(0))
        return f"\u0002{len(store) - 1}\u0003"

    text = re.sub(r"\\\((.+?)\\\)", keep, text, flags=re.DOTALL)
    text = re.sub(r"(?<!\\)\$(?:[^$\\]|\\.)+?(?<!\\)\$", keep, text, flags=re.DOTALL)
    return text, store


def restore_math(text: str, store) -> str:
    return re.sub(r"\u0002(\d+)\u0003", lambda m: store[int(m.group(1))], text)


def tidy(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s+([,.;:!?%])", r"\1", text)
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"\s+\)", ")", text)
    text = re.sub(r"\(\s*\)", " ", text)
    text = re.sub(r"([,;:])\1+", r"\1", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def extract(path: Path) -> str:
    tex = resolve_inputs(path)
    tex = expand_simple_macros(tex)
    body = document_body(tex)

    body = abstract_as_section(body)
    body = drop_ack_sections(body)
    body = replace_environments(body, ACK_ENVS, " ")
    body = replace_environments(body, MATH_ENVS, DISPLAY_TOKEN)
    body = re.sub(r"\$\$.+?\$\$", DISPLAY_TOKEN, body, flags=re.DOTALL)
    body = re.sub(r"\\\[.+?\\\]", DISPLAY_TOKEN, body, flags=re.DOTALL)

    body, captions = harvest_captions(body)
    body = replace_environments(body, FLOAT_ENVS + DROP_ENVS, " ")

    body = inline_footnotes(body)
    body = replace_citations(body)
    body = replace_refs(body)
    body = render_headings(body)

    body, store = protect_math(body)
    prose = restore_math(strip_commands(body), store)

    paragraphs = []
    for p in re.split(r"\n\s*\n", prose):
        p = p.strip()
        if p.startswith("#") or p == "\u27e8display equation\u27e9" or len(p.split()) >= 4:
            paragraphs.append(p)
    out = "\n\n".join(paragraphs)

    if captions:
        rendered = []
        for c in captions:
            c, s = protect_math(replace_refs(replace_citations(c)))
            rendered.append(restore_math(strip_commands(c), s))
        out += "\n\n## Captions\n\n" + "\n\n".join(f"- {c}" for c in rendered if c)
    return out


def output_name(path: Path) -> str:
    parent = path.resolve().parent.name or "root"
    return f"{parent}--{path.stem}.prose.md"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="+")
    parser.add_argument("--out-dir", help="write <parent>--<stem>.prose.md files here")
    args = parser.parse_args(argv)

    paths = [Path(f).expanduser() for f in args.files]
    missing = [p for p in paths if not p.exists()]
    if missing:
        for p in missing:
            print(f"missing: {p}", file=sys.stderr)
        return 2

    if not args.out_dir:
        if len(paths) > 1:
            print("several inputs: pass --out-dir", file=sys.stderr)
            return 2
        print(extract(paths[0]))
        return 0

    out_dir = Path(args.out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    seen = {}
    for p in paths:
        name = output_name(p)
        if name in seen:  # same parent dir name twice; disambiguate loudly
            name = name.replace(".prose.md", f"-{seen[name]}.prose.md")
            print(f"note: duplicate output name, writing {name}", file=sys.stderr)
        seen[output_name(p)] = seen.get(output_name(p), 0) + 1
        text = extract(p)
        (out_dir / name).write_text(text + "\n", encoding="utf-8")
        words = len(re.findall(r"[A-Za-z][A-Za-z'-]*", text))
        heads = len(re.findall(r"^#{2,3} ", text, flags=re.M))
        print(f"{name}: {words} words, {heads} headings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
