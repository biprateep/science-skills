#!/usr/bin/env python3
r"""Turn a LaTeX paper into readable prose for voice extraction.

    python extract_prose.py main.tex [more.tex ...] [--out-dir DIR]

Writes one <parent-dir>--<stem>.prose.md per input (so five papers that are
all called main.tex do not collide), or prints to stdout for a single input
with no --out-dir.

What survives, and why:
  section headings      kept as Markdown headings -- the voice profile indexes
                        specimens by section function (abstract, methods, ...)
  inline math           kept verbatim -- how symbols are woven into sentences
                        is part of the voice in physics writing
  display equations     replaced by a ⟨display equation⟩ line -- the prose that
                        introduces an equation matters, the equation does not
  citations             \citet -> [Author et al.], \citep/\cite -> [cite] --
                        placement and density are visible, keys are not
  footnotes             inlined as (footnote: ...)
  figure/table captions collected in a trailing "Captions" section
What is dropped: preamble, author blocks, floats' bodies, tables, verbatim,
bibliography, acknowledgments and funding sections, comments.

Zero-argument \newcommand macros are expanded first so that \desi reads as
DESI. \input/\include are resolved relative to the input file.

Standard library only.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Iterator, Sequence
import pathlib
import re
import sys

MATH_ENVS = (
    "equation",
    "align",
    "eqnarray",
    "gather",
    "multline",
    "displaymath",
    "flalign",
    "alignat",
    "split",
)
FLOAT_ENVS = (
    "figure",
    "table",
    "subfigure",
    "wrapfigure",
    "deluxetable",
    "longtable",
)
DROP_ENVS = (
    "thebibliography",
    "verbatim",
    "lstlisting",
    "tabular",
    "tabularx",
    "keywords",
    "CJK",
)
ACK_ENVS = ("ack", "acknowledgments", "acknowledgements")

# Commands removed together with their braced arguments.
DROP_WITH_ARGS = (
    "label",
    "bibliography",
    "bibliographystyle",
    "includegraphics",
    "newcommand",
    "renewcommand",
    "providecommand",
    "DeclareRobustCommand",
    "usepackage",
    "documentclass",
    "PassOptionsToPackage",
    "title",
    "author",
    "affiliation",
    "affil",
    "email",
    "thanks",
    "altaffiliation",
    "date",
    "pubyear",
    "pagerange",
    "workshoptitle",
    "setlength",
    "vspace",
    "hspace",
    "hskip",
    "vskip",
    "url",
    "nolinkurl",
    "caption",
    "orcid",
    "collaboration",
    "correspondingauthor",
    "keywords",
    "shorttitle",
    "shortauthors",
)
# Commands whose braced argument IS prose and should be unwrapped.
KEEP_ARG = (
    "text",
    "textbf",
    "textit",
    "texttt",
    "textsc",
    "textrm",
    "textsf",
    "emph",
    "underline",
    "uppercase",
    "lowercase",
    "mbox",
    "hbox",
)
SECTION_LEVELS = {
    "section": "##",
    "subsection": "###",
    "subsubsection": "####",
    "paragraph": "#####",
    "chapter": "#",
    "part": "#",
}
CITE_TEXTUAL = ("citet", "citeauthor", "citealt")
CITE_PARENTHETICAL = (
    "citep",
    "cite",
    "citealp",
    "citeyear",
    "citeyearpar",
    "citenum",
)
REF_CMDS = ("ref", "eqref", "pageref", "autoref", "cref", "Cref")

DISPLAY_TOKEN = "\n\n\u27e8display equation\u27e9\n\n"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _splice(text: str, start: int, end: int, replacement: str) -> str:
    """Return text with text[start:end] replaced by replacement."""
    return f"{text[:start]}{replacement}{text[end:]}"


def strip_comments(tex: str) -> str:
    r"""Remove % comments, honouring the \% escape."""
    out = []
    for line in tex.split("\n"):
        kept: list[str] = []
        i = 0
        while i < len(line):
            char = line[i]
            if char == "\\" and i + 1 < len(line):
                kept.append(line[i : i + 2])
                i += 2
                continue
            if char == "%":
                break
            kept.append(char)
            i += 1
        out.append("".join(kept))
    return "\n".join(out)


def _match_brace(text: str, open_index: int) -> int:
    """Index just past the '}' matching the '{' at open_index, or -1."""
    depth, i = 0, open_index
    while i < len(text):
        char = text[i]
        if char == "\\":
            i += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


def _braced_arg(text: str, start: int) -> tuple[str | None, int]:
    """(inner, end) for the braced group starting at or after `start`."""
    open_index = text.find("{", start)
    if open_index == -1:
        return None, -1
    close = _match_brace(text, open_index)
    if close == -1:
        return None, -1
    return text[open_index + 1 : close - 1], close


def resolve_inputs(
    path: pathlib.Path, seen: set[pathlib.Path] | None = None, depth: int = 0
) -> str:
    r"""Inline \input{file} / \include{file} relative to `path`.

    Args:
      path: The .tex file.
      seen: The files already inlined, which are not inlined again.
      depth: How deeply path is nested; past 8, nothing is inlined.

    Returns:
      The file's text, comments removed, with every input inlined.
    """
    if seen is None:
        seen = set()
    if path in seen or depth > 8:
        return ""
    seen.add(path)
    tex = strip_comments(path.read_text(encoding="utf-8", errors="replace"))

    def inline(match: re.Match[str]) -> str:
        included = path.parent / match.group(2).strip()
        if not included.suffix:
            included = included.with_suffix(".tex")
        if not included.exists():
            return " "
        return resolve_inputs(included, seen, depth + 1)

    return re.sub(r"\\(input|include)\s*\{([^}]*)\}", inline, tex)


def expand_simple_macros(tex: str) -> str:
    r"""Expand zero-argument \newcommand{\x}{...} so \desi reads as DESI."""
    macros: dict[str, str] = {}
    definition = (
        r"\\(?:re)?newcommand\*?\s*\{?\\([A-Za-z@]+)\}?\s*(\[\d\])?\s*\{"
    )
    for match in re.finditer(definition, tex):
        if match.group(2):  # takes arguments; leave alone
            continue
        body, _ = _braced_arg(tex, match.end() - 1)
        if body is not None and "\\newcommand" not in body and len(body) < 200:
            macros[match.group(1)] = body
    for _ in range(3):  # macros that reference macros
        for name, body in macros.items():
            use = r"\\%s(?![A-Za-z@])\s*(\{\})?" % re.escape(name)
            tex = re.sub(use, lambda _: body, tex)  # noqa: B023 - re.sub calls the lambda within this iteration.
    return tex


def document_body(tex: str) -> str:
    """Return the part of tex inside the document environment."""
    start = re.search(r"\\begin\{document\}", tex)
    body = tex[start.end() :] if start else tex
    end = re.search(r"\\end\{document\}", body)
    return body[: end.start()] if end else body


def find_environments(text: str, name: str) -> Iterator[tuple[int, int]]:
    r"""Yield (start, end) spans of \begin{name}...\end{name}, nesting-aware.

    Args:
      text: LaTeX source.
      name: The environment's name; its starred form counts too.

    Yields:
      A tuple (start, end) per outermost environment, end exclusive.
    """
    pattern = re.compile(r"\\(begin|end)\{%s\*?\}" % re.escape(name))
    depth = 0
    start: int | None = None
    for match in pattern.finditer(text):
        if match.group(1) == "begin":
            if depth == 0:
                start = match.start()
            depth += 1
        else:
            depth -= 1
            if depth == 0 and start is not None:
                yield (start, match.end())
                start = None
            if depth < 0:
                depth = 0


def replace_environments(
    text: str, names: Iterable[str], replacement: str
) -> str:
    """Replace each whole environment of the given names by replacement."""
    for name in names:
        for start, end in reversed(list(find_environments(text, name))):
            text = _splice(text, start, end, replacement)
    return text


def harvest_captions(text: str) -> tuple[str, list[str]]:
    r"""Cut every \caption out of text.

    Returns:
      A tuple (text, captions): the text without its captions, and what the
      captions said, in order.
    """
    captions = []
    while True:
        match = re.search(r"\\caption\*?\s*(\[[^\]]*\])?\s*\{", text)
        if not match:
            break
        inner, close = _braced_arg(text, match.end() - 1)
        if inner is None:
            text = _splice(text, match.start(), match.end(), " ")
            continue
        captions.append(inner)
        text = _splice(text, match.start(), close, " ")
    return text, captions


def drop_ack_sections(text: str) -> str:
    r"""Drop \section*{Acknowledg...}, funding and data-availability bodies."""
    pattern = re.compile(
        r"\\section\*?\s*\{[^}]*"
        r"(?:acknowledg|funding|data availability)[^}]*\}",
        re.IGNORECASE,
    )
    while True:
        match = pattern.search(text)
        if not match:
            break
        following = re.search(
            r"\\(?:section|chapter|appendix|bibliography)\b",
            text[match.end() :],
        )
        end = match.end() + (
            following.start() if following else len(text) - match.end()
        )
        text = _splice(text, match.start(), end, " ")
    return text


def replace_citations(text: str) -> str:
    """Replace textual citations by [Author et al.] and the rest by [cite]."""
    arguments = r"\*?\s*(?:\[[^\]]*\])*\s*\{[^}]*\}"
    textual = r"\\(?:%s)%s" % ("|".join(CITE_TEXTUAL), arguments)
    parenthetical = r"\\(?:%s)%s" % ("|".join(CITE_PARENTHETICAL), arguments)
    text = re.sub(textual, "[Author et al.]", text)
    text = re.sub(parenthetical, "[cite]", text)
    return text


def replace_refs(text: str) -> str:
    r"""Replace every \ref-like command by [ref]."""
    arguments = r"\*?\s*\{[^}]*\}"
    pattern = r"\\(?:%s)%s" % ("|".join(REF_CMDS), arguments)
    return re.sub(pattern, "[ref]", text)


def inline_footnotes(text: str) -> str:
    r"""Replace every \footnote{...} by (footnote: ...) in the running text."""
    while True:
        match = re.search(r"\\footnote\s*\{", text)
        if not match:
            break
        inner, close = _braced_arg(text, match.end() - 1)
        if inner is None:
            text = _splice(text, match.start(), match.end(), " ")
            continue
        footnote = f" (footnote: {inner.strip()})"
        text = _splice(text, match.start(), close, footnote)
    return text


def render_headings(text: str) -> str:
    """Turn sectioning commands into Markdown headings."""
    for command, marks in SECTION_LEVELS.items():
        pattern = re.compile(r"\\%s\*?\s*(\[[^\]]*\])?\s*\{" % command)
        while True:
            match = pattern.search(text)
            if not match:
                break
            inner, close = _braced_arg(text, match.end() - 1)
            if inner is None:
                text = _splice(text, match.start(), match.end(), " ")
                continue
            heading = f"\n\n{marks} {inner.strip()}\n\n"
            text = _splice(text, match.start(), close, heading)
    text = replace_environments(text, ("abstract",), "")  # handled below
    return text


def abstract_as_section(text: str) -> str:
    """Turn each abstract environment into an "## Abstract" section."""
    spans = list(find_environments(text, "abstract"))
    for start, end in reversed(spans):
        inner = re.sub(r"\\(begin|end)\{abstract\}", "", text[start:end])
        section = f"\n\n## Abstract\n\n{inner.strip()}\n\n"
        text = _splice(text, start, end, section)
    return text


def _unwrap_commands(text: str, commands: Iterable[str]) -> str:
    """Replace each command of the given names by its braced argument."""
    for command in commands:
        pattern = re.compile(r"\\%s\s*\{" % command)
        while True:
            match = pattern.search(text)
            if not match:
                break
            inner, close = _braced_arg(text, match.end() - 1)
            if inner is None:
                text = _splice(text, match.start(), match.end(), " ")
                continue
            text = _splice(text, match.start(), close, inner)
    return text


def _drop_commands(text: str, commands: Iterable[str]) -> str:
    """Delete each command of the given names with its braced argument."""
    for command in commands:
        pattern = re.compile(r"\\%s\*?\s*(\[[^\]]*\])?\s*\{" % command)
        while True:
            match = pattern.search(text)
            if not match:
                break
            _, close = _braced_arg(text, match.end() - 1)
            if close == -1:
                text = _splice(text, match.start(), match.end(), " ")
                continue
            text = _splice(text, match.start(), close, " ")
    return text


def strip_commands(text: str) -> str:
    """Unwrap prose-bearing commands, delete the rest."""
    text = _unwrap_commands(text, KEEP_ARG)
    # \href{url}{shown} keeps only what it shows.
    text = re.sub(r"\\href\s*\{[^}]*\}\s*\{", "{", text)
    text = _drop_commands(text, DROP_WITH_ARGS)
    text = re.sub(r"\\begin\{[^}]*\}(\s*\[[^\]]*\])?", " ", text)
    text = re.sub(r"\\end\{[^}]*\}", " ", text)
    text = re.sub(r"\\item\b", "\n- ", text)
    text = re.sub(r"\\(?:ldots|dots)\b", "...", text)
    text = re.sub(r"\\(?:,|;|!|quad|qquad)", " ", text)
    text = re.sub(r"\\[a-zA-Z@]+\*?", " ", text)  # remaining bare commands
    text = re.sub(r"\\([&%_#$])", r"\1", text)  # \& \% \_ \# \$
    text = re.sub(r"\\[^a-zA-Z]", " ", text)
    text = text.replace("{", "").replace("}", "")
    text = text.replace("``", "\u201c").replace("''", "\u201d")
    text = text.replace("~", " ")
    return tidy(text)


def protect_math(text: str) -> tuple[str, list[str]]:
    """Swap inline math for placeholders so command stripping leaves it alone.

    Returns:
      A tuple (text, store): the text with each inline math span replaced by
      a numbered placeholder, and the spans, for restore_math().
    """
    store: list[str] = []

    def keep(match: re.Match[str]) -> str:
        store.append(match.group(0))
        return f"\u0002{len(store) - 1}\u0003"

    text = re.sub(r"\\\((.+?)\\\)", keep, text, flags=re.DOTALL)
    text = re.sub(
        r"(?<!\\)\$(?:[^$\\]|\\.)+?(?<!\\)\$", keep, text, flags=re.DOTALL
    )
    return text, store


def restore_math(text: str, store: Sequence[str]) -> str:
    """Put back the math spans that protect_math() replaced."""
    return re.sub(
        r"\u0002(\d+)\u0003", lambda match: store[int(match.group(1))], text
    )


def tidy(text: str) -> str:
    """Normalize the spaces and punctuation that command stripping leaves."""
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


def extract(path: pathlib.Path) -> str:
    """Extract the readable prose of a LaTeX paper.

    Args:
      path: The paper's main .tex file.

    Returns:
      The prose as Markdown, ending in a Captions section when the paper has
      captions.
    """
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

    out = "\n\n".join(_prose_paragraphs(prose))
    if captions:
        out += "\n\n## Captions\n\n" + _render_captions(captions)
    return out


def _prose_paragraphs(prose: str) -> list[str]:
    """Keep headings, display-equation lines and paragraphs of 4+ words."""
    paragraphs = []
    for paragraph in re.split(r"\n\s*\n", prose):
        paragraph = paragraph.strip()
        if (
            paragraph.startswith("#")
            or paragraph == "\u27e8display equation\u27e9"
            or len(paragraph.split()) >= 4
        ):
            paragraphs.append(paragraph)
    return paragraphs


def _render_captions(captions: Iterable[str]) -> str:
    """Render captions as a Markdown list, in the prose's conventions."""
    rendered = []
    for caption in captions:
        protected, store = protect_math(
            replace_refs(replace_citations(caption))
        )
        rendered.append(restore_math(strip_commands(protected), store))
    return "\n\n".join(f"- {text}" for text in rendered if text)


def output_name(path: pathlib.Path) -> str:
    """Return <parent-dir>--<stem>.prose.md, the name of path's prose file."""
    parent = path.resolve().parent.name or "root"
    return f"{parent}--{path.stem}.prose.md"


def section_counts(text: str) -> list[tuple[str, int]]:
    """Count the words under each heading, in order.

    The trim measures with this before proposing cuts.

    Args:
      text: Prose, as extract() returns it.

    Returns:
      A tuple (heading, words) per "##" or "###" heading, after one for the
      text before the first heading if that has any words.
    """
    counts: list[tuple[str, int]] = []
    heading = "(before first heading)"
    section_lines: list[str] = []

    def flush() -> None:
        n_words = len(
            re.findall(r"[A-Za-z][A-Za-z'-]*", " ".join(section_lines))
        )
        if heading != "(before first heading)" or n_words:
            counts.append((heading, n_words))

    for line in text.splitlines():
        if re.match(r"^#{2,3} ", line):
            flush()
            heading, section_lines = line.strip(), []
        else:
            section_lines.append(line)
    flush()
    return counts


def print_counts(name: str, text: str) -> None:
    """Print the words per section of one paper's prose."""
    rows = section_counts(text)
    total = sum(n_words for _, n_words in rows)
    print(f"\n{name}: {total} words")
    for heading, n_words in rows:
        indent = "  " if heading.startswith("### ") else ""
        print(f"  {indent}{n_words:6d}  {heading.lstrip('# ')}")


def _parse_arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    """Parse the command line."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("files", nargs="+")
    parser.add_argument(
        "--out-dir", help="write <parent>--<stem>.prose.md files here"
    )
    parser.add_argument(
        "--counts",
        action="store_true",
        help="print words per section (the trim's measurement) instead of"
        " the prose",
    )
    return parser.parse_args(argv)


def _print_all_counts(files: Sequence[str]) -> int:
    """Print the words per section of each file; return the exit status."""
    for name in files:
        path = pathlib.Path(name).expanduser()
        if not path.exists():
            print(f"missing: {path}", file=sys.stderr)
            return 2
        print_counts(str(path), extract(path))
    return 0


def _write_prose_files(
    paths: Sequence[pathlib.Path], out_dir: pathlib.Path
) -> None:
    """Write each paper's prose to its own file in out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    seen: dict[str, int] = {}
    for path in paths:
        name = output_name(path)
        if name in seen:  # same parent dir name twice; disambiguate loudly
            name = name.replace(".prose.md", f"-{seen[name]}.prose.md")
            print(
                f"note: duplicate output name, writing {name}", file=sys.stderr
            )
        seen[output_name(path)] = seen.get(output_name(path), 0) + 1
        text = extract(path)
        (out_dir / name).write_text(text + "\n", encoding="utf-8")
        n_words = len(re.findall(r"[A-Za-z][A-Za-z'-]*", text))
        n_headings = len(re.findall(r"^#{2,3} ", text, flags=re.M))
        print(f"{name}: {n_words} words, {n_headings} headings")


def main(argv: Sequence[str] | None = None) -> int:
    """Extract the prose of the papers named on the command line.

    Args:
      argv: The arguments after the program name; None reads sys.argv.

    Returns:
      The exit status: 2 for a missing file, or several files without
      --out-dir; 0 otherwise.
    """
    args = _parse_arguments(argv)
    if args.counts:
        return _print_all_counts(args.files)

    paths = [pathlib.Path(name).expanduser() for name in args.files]
    missing = [path for path in paths if not path.exists()]
    if missing:
        for path in missing:
            print(f"missing: {path}", file=sys.stderr)
        return 2

    if not args.out_dir:
        if len(paths) > 1:
            print("several inputs: pass --out-dir", file=sys.stderr)
            return 2
        print(extract(paths[0]))
        return 0

    _write_prose_files(paths, pathlib.Path(args.out_dir).expanduser())
    return 0


if __name__ == "__main__":
    sys.exit(main())
