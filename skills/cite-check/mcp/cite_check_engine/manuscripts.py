"""Manuscript parsing, review mappings and isolated PDF extraction."""

import dataclasses
import functools
from collections import Counter
import hashlib
import importlib.metadata
import io
import logging
import json
import math
import os
import re
import subprocess
import sys
from typing import Any
from cite_check_engine import budgets as _engine_budgets
from cite_check_engine import config as _engine_config
from cite_check_engine import identifiers as _engine_identifiers
from cite_check_engine import models as _engine_models
from cite_check_engine import parsing as _engine_parsing
from cite_check_engine import persistence as _engine_persistence
from cite_check_engine import text as _engine_text


_INPUT_POLICY = "manuscript-input-v1"

_INPUT_MAX_BYTES = 20 * 1024 * 1024

_INPUT_MAX_PAGES = 500

_INPUT_MAX_TEXT = 2 * 1024 * 1024

_INPUT_PDF_TIMEOUT = 30.0

_INPUT_KEY = re.compile(r"[\w][\w:./+\-]*", re.UNICODE)

def _input_format(path: str) -> str:
    """Select only supported manuscript formats from their extensions."""
    extension = os.path.splitext(path)[1].lower()
    formats = {
        ".tex": "latex",
        ".ltx": "latex",
        ".latex": "latex",
        ".md": "markdown",
        ".markdown": "markdown",
        ".txt": "text",
        ".pdf": "pdf",
        "": "latex",
    }
    if extension not in formats:
        raise ValueError("unsupported manuscript format")
    return formats[extension]

def _input_manifest_path(path: str) -> str:
    """Keep review mappings separate for each main manuscript."""
    identifier = hashlib.sha256(os.path.abspath(path).encode()).hexdigest()
    return os.path.join(
        os.path.dirname(os.path.abspath(path)),
        _engine_config.PROJECT_DIR,
        "input-" + identifier + ".json",
    )

def _input_pdf_backend() -> dict[str, Any]:
    """Identify the extractor independently of manuscript contents."""
    try:
        version = importlib.metadata.version("pypdf")
    except importlib.metadata.PackageNotFoundError:
        version = None
    return {
        "name": "pypdf",
        "version": version,
        "policy": _INPUT_POLICY,
        "options": {"strict": True, "mode": "plain"},
    }

def _input_pdf_worker() -> None:
    """Extract bounded page text in a separate, time-limited process."""
    pypdf = importlib.import_module("pypdf")

    logging.getLogger("pypdf").setLevel(logging.CRITICAL)
    raw = sys.stdin.buffer.read(_INPUT_MAX_BYTES + 1)
    if len(raw) > _INPUT_MAX_BYTES:
        raise ValueError("PDF exceeds the 20 MiB input limit")
    reader = pypdf.PdfReader(io.BytesIO(raw), strict=True)
    if reader.is_encrypted:
        raise ValueError("encrypted PDF cannot establish extraction scope")
    count = len(reader.pages)
    if not 0 < count <= _INPUT_MAX_PAGES:
        raise ValueError("PDF must have between 1 and 500 pages")
    pages, size = [], 0
    for number, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ""
        size += len(text.encode("utf-8"))
        if size > _INPUT_MAX_TEXT:
            raise ValueError("PDF exceeds the 2 MiB extracted-text limit")
        pages.append({"page": number, "text": text})
    print(
        json.dumps(
            {"pages": pages, "extractor": _input_pdf_backend()},
            ensure_ascii=False,
        )
    )

def _input_pdf_extract(raw: bytes) -> dict[str, Any]:
    """Isolate PDF decoding with a deadline; never silently fall back to OCR."""
    budget = _engine_budgets._request_budget.get()
    timeout = (
        min(_INPUT_PDF_TIMEOUT, budget.remaining())
        if budget
        else _INPUT_PDF_TIMEOUT
    )
    try:
        completed = subprocess.run(
            [sys.executable, _engine_config.ENTRYPOINT, "_extract-pdf"],
            input=raw,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise ValueError(
            "PDF extraction timed out; scope is unknown"
        ) from error
    if budget:
        budget.remaining()
    if completed.returncode:
        raise ValueError(
            "PDF extraction failed (missing pypdf, encrypted, "
            "malformed or oversized PDF); scope is unknown"
        )
    if len(completed.stdout) > _INPUT_MAX_TEXT * 6 + 100000:
        raise ValueError("PDF extractor output exceeds its bound")
    try:
        result = json.loads(completed.stdout)
    except (ValueError, UnicodeError) as error:
        raise ValueError("invalid PDF extractor output") from error
    return result

def _input_snapshot(path: str) -> dict[str, Any]:
    """Read one original byte snapshot and its format-specific text views."""
    kind = _input_format(path)
    if kind == "latex":
        raise ValueError("explicit mappings apply to Markdown, text or PDF")
    if not os.path.isfile(path):
        raise ValueError("manuscript must be a regular file")
    with open(path, "rb") as source:
        raw = source.read(_INPUT_MAX_BYTES + 1)
    if len(raw) > _INPUT_MAX_BYTES:
        raise ValueError("manuscript exceeds the 20 MiB input limit")
    if kind == "pdf":
        data = _input_pdf_extract(raw)
        if (
            not isinstance(data, dict)
            or set(data) != {"pages", "extractor"}
            or not isinstance(data["pages"], list)
            or not 0 < len(data["pages"]) <= _INPUT_MAX_PAGES
            or data["extractor"] != _input_pdf_backend()
        ):
            raise ValueError("malformed or inconsistent PDF extraction")
        pages = data["pages"]
        for number, page in enumerate(pages, 1):
            if (
                not isinstance(page, dict)
                or set(page) != {"page", "text"}
                or type(page["page"]) is not int
                or page["page"] != number
                or not isinstance(page["text"], str)
            ):
                raise ValueError("malformed PDF page extraction")
        if sum(len(page["text"].encode()) for page in pages) > _INPUT_MAX_TEXT:
            raise ValueError("PDF exceeds the extracted-text limit")
        if not any(page["text"].strip() for page in pages):
            raise ValueError(
                "PDF has no extractable text; scan/OCR scope is unknown"
            )
        extractor = data["extractor"]
    else:
        pages = [{"page": None, "text": raw.decode("utf-8")}]
        if not pages[0]["text"].strip():
            raise ValueError("empty manuscript; citation scope is unknown")
        extractor = {"name": "utf-8", "policy": _INPUT_POLICY}
    fingerprint = {
        "format": kind,
        "extractor": extractor,
        "pages": [
            hashlib.sha256(page["text"].encode()).hexdigest() for page in pages
        ],
    }
    return {
        "input_format": kind,
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "pages": pages,
        "fingerprint": fingerprint,
    }

def _input_blank(value: str) -> str:
    """Mask excluded syntax without changing character offsets or newlines."""
    return "".join("\n" if character == "\n" else " " for character in value)

def _input_mask(text: str, kind: str, *, math: bool = True) -> str:
    """Exclude Markdown code/comments/link syntax and URLs from markers."""
    if kind == "markdown":
        lines = text.splitlines(keepends=True)
        fence, width = None, 0
        masked = []
        for line in lines:
            match = re.match(r" {0,3}(`{3,}|~{3,})", line)
            if fence:
                masked.append(_input_blank(line))
                if (
                    match
                    and match[1][0] == fence
                    and len(match[1]) >= width
                    and not line[match.end() :].strip()
                ):
                    fence = None
            elif match:
                fence, width = match[1][0], len(match[1])
                masked.append(_input_blank(line))
            elif line.startswith("    ") or line.startswith("\t"):
                masked.append(_input_blank(line))
            else:
                masked.append(line)
        text = "".join(masked)
        text = re.sub(
            r"<!--.*?(?:-->|\Z)",
            lambda match: _input_blank(match[0]),
            text,
            flags=re.S,
        )
        if math:
            text = re.sub(
                r"(?<!\\)(`+)(?!`)(.*?)\1(?!`)",
                lambda match: _input_blank(match[0]),
                text,
                flags=re.S,
            )
        text = re.sub(
            r"\[[^\]\n]*\]\([^\n)]*\)",
            lambda match: (
                match[0][: match[0].index("]") + 1]
                + _input_blank(match[0][match[0].index("]") + 1 :])
            ),
            text,
        )
        # Front matter is metadata, not manuscript prose. The caller passes
        # the authoritative bibliography explicitly to audit/job tools.
        text = re.sub(
            r"\A---\s*\r?\n.*?\r?\n(?:---|\.\.\.)[^\n]*(?:\n|\Z)",
            lambda match: _input_blank(match[0]),
            text,
            flags=re.S,
        )
    text = re.sub(
        r"(?:https?://|mailto:)[^\s<>]+",
        lambda match: _input_blank(match[0]),
        text,
    )
    return (
        _engine_parsing._TEX_MATH.sub(lambda match: _input_blank(match[0]), text)
        if math
        else text
    )

def _input_references(text: str, kind: str) -> tuple[str, list[dict[str, Any]]]:
    """Retain printed references as raw, unverified manuscript records."""
    records = []
    visible = _input_mask(text, kind, math=False)
    native_keys = {
        key
        for marker in _input_native_markers(_input_mask(text, kind))[0]
        for key in marker["keys"]
    }
    heading = re.search(
        r"(?im)^[ \t]*(?:#{1,6}[ \t]+)?"
        r"(?:References|Bibliography)[ \t]*:?[ \t]*\r?$",
        visible,
    )
    spans: list[tuple[int, int, str | None]] = []
    if kind == "markdown":
        metadata = re.match(
            r"\A---[^\n]*\r?\n(.*?)\r?\n(?:---|\.\.\.)[^\n]*(?:\n|\Z)",
            text,
            re.S,
        )
        if metadata and re.search(
            r"(?im)^[ \t]*[\"']?references[\"']?[ \t]*:", metadata[1]
        ):
            spans.append((metadata.start(), metadata.end(), None))
    if heading:
        spans.append((heading.start(), len(text), None))
    for match in re.finditer(
        r"(?m)^[ \t]{0,3}\[(@?[\w][\w:./+\-]*)\]:[^\n]*(?:\n(?:[ \t]+[^\n]*))*",
        visible,
    ):
        # Ordinary Markdown link definitions contain only a URL/title;
        # citation-looking definitions remain explicit unverified metadata.
        body = text[match.start() : match.end()].split("]:", 1)[1].strip()
        if match[1].lstrip("@") not in native_keys and re.fullmatch(
            r"<?https?://[^\s>]+>?(?:\s+[\"'].+[\"'])?", body
        ):
            continue
        if not any(start <= match.start() < end for start, end, _ in spans):
            spans.append((match.start(), match.end(), match[1].lstrip("@")))
    chars = list(text)
    for start, end, key in spans:
        records.append(
            {
                "key": key,
                "raw": text[start:end],
                "start": start,
                "end": end,
                "kind": "printed-reference-block",
                "line": text.count("\n", 0, start) + 1,
            }
        )
        chars[start:end] = _input_blank(text[start:end])
    return "".join(chars), records

def _input_native_markers(
    text: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Parse explicit Pandoc-style keys, retaining uncertain marker syntax."""
    markers, diagnostics, occupied = [], [], []
    for match in re.finditer(r"(?<!\\)\[([^\[\]\n]*)\]", text):
        body = match[1]
        keys = re.findall(r"(?<![\w\\])@([\w][\w:./+\-]*)", body)
        if "@" in body and (not keys or body.rstrip().endswith(";")):
            diagnostics.append(
                {
                    "code": "malformed-citation-marker",
                    "message": "Malformed explicit citation marker",
                    "start": match.start(),
                    "end": match.end(),
                }
            )
            occupied.append((match.start(), match.end()))
        elif keys:
            if "@" in re.sub(r"(?<![\w\\])@[\w][\w:./+\-]*", "", body):
                diagnostics.append(
                    {
                        "code": "malformed-citation-marker",
                        "message": "Ambiguous explicit citation marker",
                        "start": match.start(),
                        "end": match.end(),
                    }
                )
            else:
                markers.append(
                    {"start": match.start(), "end": match.end(), "keys": keys}
                )
            occupied.append((match.start(), match.end()))
        elif re.fullmatch(r"\s*\d+(?:\s*[,;\-–]\s*\d+)*\s*", body):
            diagnostics.append(
                {
                    "code": "unsupported-citation-syntax",
                    "message": (
                        "Numeric marker needs an explicit review mapping"
                    ),
                    "start": match.start(),
                    "end": match.end(),
                }
            )
    for match in re.finditer(
        r"\[\s*\d+(?:[ ,;–-]\d+)*(?=[^\]\n]*(?:\n|\Z))", text
    ):
        if (
            "]"
            not in text[
                match.end() : text.find("\n", match.end())
                if "\n" in text[match.end() :]
                else len(text)
            ]
        ):
            diagnostics.append(
                {
                    "code": "malformed-citation-marker",
                    "message": "Unclosed numeric citation marker",
                    "start": match.start(),
                    "end": match.end(),
                }
            )
    remainder = list(text)
    for start, end in occupied:
        remainder[start:end] = _input_blank(text[start:end])
    remaining = "".join(remainder)
    for match in re.finditer(r"(?<![\w\\@])@([\w][\w:./+\-]*)", remaining):
        # Unclosed bracket syntax is never silently reinterpreted as a
        # complete narrative citation.
        before = remaining[
            max(0, remaining.rfind("\n", 0, match.start())) : match.start()
        ]
        if before.count("[") > before.count("]"):
            diagnostics.append(
                {
                    "code": "malformed-citation-marker",
                    "message": "Unclosed citation cluster",
                    "start": match.start(),
                    "end": match.end(),
                }
            )
        else:
            key = match[1].rstrip(".:/")
            markers.append(
                {
                    "start": match.start(),
                    "end": match.start() + 1 + len(key),
                    "keys": [key],
                }
            )
    for match in re.finditer(
        r"[\[(][^()\[\]\n]*(?:18|19|20)\d{2}[a-z]?"
        r"[^()\[\]\n]*(?:[\])]|(?=\n|\Z))",
        remaining,
    ):
        diagnostics.append(
            {
                "code": "unsupported-citation-syntax",
                "message": (
                    "Author-year marker needs an explicit review mapping"
                ),
                "start": match.start(),
                "end": match.end(),
            }
        )
    return sorted(markers, key=lambda item: item["start"]), diagnostics

def _input_validate_mappings(
    snapshot: dict[str, Any], values: Any
) -> list[dict[str, Any]]:
    """Validate exact, nonoverlapping review bindings."""
    if not isinstance(values, list) or len(values) > 2000:
        raise ValueError("citations must be a list of at most 2000 mappings")
    pages = {page["page"]: page["text"] for page in snapshot["pages"]}
    result: list[dict[str, Any]] = []
    visible_pages = {
        page: _input_mask(
            _input_references(text, snapshot["input_format"])[0],
            snapshot["input_format"],
        )
        for page, text in pages.items()
    }
    native_pages = {
        page: _input_native_markers(text)[0]
        for page, text in visible_pages.items()
    }
    for item in values:
        value = (
            dataclasses.asdict(item)
            if isinstance(item, _engine_models.InputCitation)
            else item
        )
        if (
            not isinstance(value, dict)
            or not {"start", "end", "key", "marker"} <= set(value)
            or set(value) - {"start", "end", "key", "marker", "page"}
        ):
            raise ValueError(
                "mapping requires start, end, key and exact marker"
            )
        value = dict(value)
        value.setdefault("page", None)
        start, end, page = value["start"], value["end"], value["page"]
        if (
            type(start) is not int
            or type(end) is not int
            or (page is not None and type(page) is not int)
            or page not in pages
            or not 0 <= start < end <= len(pages[page])
            or not isinstance(value["marker"], str)
            or pages[page][start:end] != value["marker"]
            or not isinstance(value["key"], str)
            or _INPUT_KEY.fullmatch(value["key"]) is None
        ):
            raise ValueError(
                "mapping does not match exact current page/text offsets"
            )
        visible = visible_pages[page]
        if visible[start:end] != pages[page][start:end]:
            raise ValueError(
                "mapping overlaps excluded code, math, comments or URL syntax"
            )
        native = native_pages[page]
        if any(
            start < marker["end"] and end > marker["start"] for marker in native
        ):
            raise ValueError(
                "explicit native citations do not need review mappings"
            )
        for previous in result:
            if previous["page"] != page:
                continue
            if start < previous["end"] and end > previous["start"]:
                if (start, end) != (
                    previous["start"],
                    previous["end"],
                ) or value["key"] == previous["key"]:
                    raise ValueError(
                        "overlapping or duplicate citation mappings"
                    )
        result.append(value)
    return sorted(
        result,
        key=lambda value: (
            value["page"] or 0,
            value["start"],
            value["end"],
            value["key"],
        ),
    )

def _input_manifest_safe(path: str, manuscript: str) -> None:
    """Protect original inputs and ledger before creating a mapping lock."""
    if os.path.islink(os.path.dirname(path)):
        raise ValueError("input manifest directory is a symlink")
    inputs = [
        manuscript,
        os.path.join(os.path.dirname(manuscript), _engine_config.PROJECT_DIR, "ledger.json"),
    ]
    for output in (path, path + ".lock"):
        if (
            os.path.islink(output)
            or os.path.exists(output)
            and os.stat(output).st_nlink > 1
        ):
            raise ValueError("input manifest or lock is a symlink or hardlink")
        for source in inputs:
            if (
                os.path.realpath(output) == os.path.realpath(source)
                or os.path.exists(output)
                and os.path.exists(source)
                and os.path.samefile(output, source)
            ):
                raise ValueError("input manifest or lock aliases an input")

def register_input(
    tex_path: str, citations: list[_engine_models.InputCitation], reason: str
) -> dict[str, Any]:
    """Bind explicit review mappings to unchanged Markdown/text/PDF snapshots.

    Args:
        tex_path: Manuscript path; the legacy parameter name is retained.
        citations: Exact offset/key/marker mappings, with a page for PDFs.
        reason: Substantive explanation of the caller's interpretation.

    Returns:
        The saved manifest location. Mappings never establish identity or
        completeness and always remain review-only when nonempty.
    """
    try:
        if (
            not isinstance(tex_path, str)
            or not tex_path
            or not isinstance(reason, str)
            or len(reason.strip()) < 15
        ):
            raise ValueError(
                "give a manuscript path and substantive mapping reason"
            )
        path = os.path.abspath(tex_path)
        snapshot = _input_snapshot(path)
        mappings = _input_validate_mappings(snapshot, citations)
        manifest = _input_manifest_path(path)
        _input_manifest_safe(manifest, path)
        with _engine_persistence._file_lock(manifest):
            if _engine_persistence._audit_file_digest(path) != snapshot["raw_sha256"]:
                raise ValueError(
                    "manuscript changed while mapping; extract again"
                )
            _input_manifest_safe(manifest, path)
            value = {
                "schema_version": 1,
                "path": path,
                "raw_sha256": snapshot["raw_sha256"],
                "fingerprint": snapshot["fingerprint"],
                "citations": mappings,
                "reason": reason.strip(),
                "policy": _INPUT_POLICY,
            }
            serialized = json.dumps(value, ensure_ascii=False, indent=2)
            if len(serialized.encode("utf-8")) > 1024 * 1024:
                raise ValueError("input mapping manifest exceeds 1 MiB")
            _engine_persistence._atomic_write(manifest, serialized)
        return {
            "ok": True,
            "registered": True,
            "manifest_path": manifest,
            "n_mappings": len(mappings),
            "review_only": True,
        }
    except (OSError, ValueError, RuntimeError) as error:
        return {"ok": False, "registered": False, "error": str(error)}

def _input_mappings(
    path: str, snapshot: dict[str, Any]
) -> tuple[list[dict[str, Any]], str | None]:
    """Read mappings bound to the exact bytes and extraction policy."""
    manifest = _input_manifest_path(path)
    _input_manifest_safe(manifest, path)
    if not os.path.exists(manifest):
        return [], None
    with open(manifest, "rb") as source:
        raw = source.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError("input manifest exceeds its size limit")
    value = json.loads(raw)
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "schema_version",
            "path",
            "raw_sha256",
            "fingerprint",
            "citations",
            "reason",
            "policy",
        }
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or value["path"] != path
        or value["raw_sha256"] != snapshot["raw_sha256"]
        or value["fingerprint"] != snapshot["fingerprint"]
        or value["policy"] != _INPUT_POLICY
        or not isinstance(value["reason"], str)
        or len(value["reason"].strip()) < 15
    ):
        raise ValueError(
            "input mapping is stale or malformed; register_input again"
        )
    return _input_validate_mappings(
        snapshot, value["citations"]
    ), hashlib.sha256(raw).hexdigest()

def _strip_tex_comments(text: str) -> str:
    """Blank comments while preserving source character offsets and lines."""
    def blank(match: re.Match) -> str:
        return "".join("\n" if char == "\n" else " " for char in match[0])

    text = re.sub(r"(?<!\\)%[^\n]*", blank, text)
    text = re.sub(
        r"\\begin\{comment\}.*?\\end\{comment\}", blank, text, flags=re.S
    )
    return re.sub(r"\\iffalse.*?\\fi", blank, text, flags=re.S)

def _braced(text: str, i: int) -> tuple:
    """text[i] == '{' → (inner, index after the matching '}')."""
    j = _engine_parsing._find_close(text, i)
    return (text[i + 1:j], j + 1) if j > 0 else ("", i + 1)

def _tex_file_arguments(text: str, commands: tuple[str, ...]) -> list[str]:
    """Read literal filenames, failing on malformed or dynamic declarations."""
    arguments = []
    pattern = r"\\(" + "|".join(re.escape(cmd) for cmd in commands) + r")\b"
    for match in re.finditer(pattern, text):
        index = match.end()
        while index < len(text) and text[index].isspace():
            index += 1
        if index < len(text) and text[index] == "[":
            closing = text.find("]", index + 1)
            if closing < 0:
                raise ValueError(f"unterminated options for \\{match[1]}")
            index = closing + 1
            while index < len(text) and text[index].isspace():
                index += 1
        if index < len(text) and text[index] == "{":
            closing = _engine_parsing._find_close(text, index)
            if closing < 0:
                raise ValueError(f"unterminated filename for \\{match[1]}")
            argument = text[index + 1:closing].strip()
        elif match[1] == "input":
            filename = re.match(r"[^\\{}\s]+", text[index:])
            argument = filename[0] if filename else ""
        else:
            argument = ""
        if not argument or re.search(r"[\\{}#$]", argument):
            raise ValueError(
                f"missing, malformed or dynamic filename for \\{match[1]}"
            )
        arguments.append(argument)
    return arguments

def _gather_tex(main_path: str, seen: set | None = None,
                root: str | None = None,
                snapshots: dict[str, str] | None = None) -> list:
    """[(path, comment-stripped text)] for the main file and every
    \\input / \\include / \\subfile it pulls in."""
    seen = seen if seen is not None else set()
    main_path = os.path.abspath(main_path)
    root = root if root is not None else os.path.dirname(main_path)
    if main_path in seen:
        return []
    if not os.path.isfile(main_path):
        raise ValueError(f"missing included TeX file: {main_path}")
    seen.add(main_path)
    with open(main_path, encoding="utf-8", newline="") as fh:
        original = fh.read()
    if snapshots is not None:
        snapshots[main_path] = original
    text = _strip_tex_comments(original)
    files = [(main_path, text)]
    for argument in _tex_file_arguments(text, ("input", "include", "subfile")):
        cand = os.path.join(root, argument)
        if not os.path.splitext(cand)[1]:
            cand += ".tex"
        files += _gather_tex(cand, seen, root, snapshots)
    return files

def _cite_instances(text: str):
    """Yield (cmd, keys, start, end) for each citation command; \\cites-style
    commands carry several ([pre][post]{keys}) groups."""
    n = len(text)
    for m in _engine_parsing._CITE_CMD.finditer(text):
        cmd = m.group("cmd")
        if cmd.lower() in _engine_parsing._CITE_EXCLUDE:
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
    """LaTeX → readable prose, preserving citations and mathematical content."""
    math = []
    t = _engine_parsing._TEX_MATH.sub(
        lambda match: (
            math.append(re.sub(r"\s+", " ", match[0])),
            f"\u27e8m{len(math) - 1}\u27e9"
        )[1],
        t,
    )
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

def _extract_tex_cites(tex_path: str) -> dict:
    """Every citation instance in a LaTeX document (following \\input /
    \\include), each with the sentence making the claim (`claim`, with
    ⟨cite:key⟩ marking where the citation sits), one sentence of context each
    side, file and line. Also reports the cite keys, declared .bib files and
    documentclass. \\nocite instances are flagged nocite=true.
    """
    tex_path = os.path.abspath(tex_path)
    if not os.path.exists(tex_path):
        return {"error": f"{tex_path} not found"}
    source_snapshots = {}
    try:
        files = _gather_tex(tex_path, snapshots=source_snapshots)
    except (OSError, ValueError) as exc:
        return {"ok": False, "complete": False, "error": str(exc)}
    cites: list[_engine_models.CitationInstance] = []
    bib_files, docclass = [], None
    inline_bibliography = []
    sentences = []
    for path, text in files:
        for env in re.finditer(
            r"\\begin\{thebibliography\}(?:\{[^}]*\})?"
            r"(.*?)\\end\{thebibliography\}", text, re.S
        ):
            items = list(
                re.finditer(r"\\bibitem(?:\[[^\]]*\])?\{([^}]+)\}", env[1])
            )
            parsed_items = {item.start() for item in items}
            if (
                not items
                or any(token.start() not in parsed_items
                       for token in re.finditer(r"\\bibitem\b", env[1]))
                or any(_INPUT_KEY.fullmatch(item[1]) is None for item in items)
            ):
                return {
                    "ok": False,
                    "complete": False,
                    "scope_complete": False,
                    "error": "malformed or unsupported inline "
                             "bibliography item",
                }
            for index, item in enumerate(items):
                start = env.start(1) + item.start()
                end = env.start(1) + (
                    items[index + 1].start()
                    if index + 1 < len(items)
                    else len(env[1])
                )
                raw = source_snapshots[path]
                inline_bibliography.append({
                    "key": item[1], "raw": raw[start:end], "file": path,
                    "line": raw.count("\n", 0, start) + 1,
                    "start": start, "end": end,
                    "kind": "inline-bibliography-entry",
                    "source_byte_start": len(raw[:start].encode("utf-8")),
                    "source_byte_end": len(raw[:end].encode("utf-8")),
                })
        text = re.sub(
            r"\\begin\{thebibliography\}.*?\\end\{thebibliography\}",
            lambda match: _input_blank(match[0]),
            text,
            flags=re.S,
        )
        if re.search(r"\\(?:bibitem|begin\{thebibliography\})", text):
            return {
                "ok": False,
                "complete": False,
                "error": "malformed inline bibliography",
            }
        m = re.search(r"\\documentclass(?:\[[^\]]*\])?\{([^}]+)\}", text)
        if m and not docclass:
            docclass = m.group(1)
        try:
            declarations = _tex_file_arguments(
                text, ("bibliography", "addbibresource")
            )
        except ValueError as exc:
            return {"ok": False, "complete": False, "error": f"{path}: {exc}"}
        for declaration in declarations:
            for b in declaration.split(","):
                b = b.strip()
                if b:
                    p = os.path.join(os.path.dirname(tex_path), b)
                    bib_files.append(p if p.endswith(".bib") else p + ".bib")
        instances = list(_cite_instances(text))
        parsed_starts = {instance[2] for instance in instances}
        for command in _engine_parsing._CITE_CMD.finditer(text):
            if (command.group("cmd").lower() not in _engine_parsing._CITE_EXCLUDE
                    and command.start() not in parsed_starts):
                return {"ok": False, "complete": False,
                        "error": f"malformed citation in {path}"}
        if any(not item[1] for item in instances):
            return {"ok": False, "complete": False,
                    "error": f"empty or malformed citation in {path}"}
        tokens, out, last = {}, [], 0
        for n, (cmd, keys, s, e) in enumerate(instances):
            out.append(text[last:s])
            out.append(f" \u27e8cite#{n}\u27e9 ")
            last = e
            tokens[n] = {
                "cmd": cmd, "keys": keys, "line": text.count("\n", 0, s) + 1,
                "source_start": s, "source_end": e, "source_index": n,
            }
        out.append(text[last:])
        joined = "".join(out)
        m = re.search(r"\\begin\{document\}", joined)
        document = joined[m.end():] if m else joined
        prose = _clean_tex(document)
        if Counter(_engine_parsing._CITE_TOKEN.findall(document)) != Counter(
            _engine_parsing._CITE_TOKEN.findall(prose)
        ):
            return {
                "ok": False, "complete": False,
                "error": f"citation lost in unsupported TeX structure in {path}",
            }

        def render(s):
            s = _engine_parsing._CITE_TOKEN.sub(lambda mm: "\u27e8cite:" + ",".join(tokens[int(mm.group(1))]["keys"]) + "\u27e9", s)
            return re.sub(r"\u27e9 (?=[,.;:)\]])", "\u27e9", s)

        sents = []
        for para in re.split(r"\n\s*\n", prose):
            sents.extend(_engine_text._split_sentences(re.sub(r"\s+", " ", para).strip()))
        source_text = source_snapshots[path]
        for si, sent in enumerate(sents):
            matches = list(_engine_parsing._CITE_TOKEN.finditer(sent))
            if not matches:
                continue
            claim = render(sent)
            context = " ".join(
                render(value) for value in sents[max(0, si - 1):si + 2]
            )
            anchors = [tokens[int(match[1])] for match in matches]
            location_id = _engine_identifiers._atomic_digest(
                [tex_path, path, anchors[0]["source_index"]]
            )
            sentence_id = _engine_identifiers._atomic_digest(
                [tex_path, path, anchors, claim, context]
            )
            sentence = {
                "sentence_id": sentence_id, "location_id": location_id,
                "file": path, "tex_path": tex_path,
                "claim": claim, "context": context,
                "citation_ids": [], "offset_unit": "unicode-codepoint",
            }
            for tm in matches:
                t = tokens[int(tm.group(1))]
                marker = "⟨cite:" + ",".join(t["keys"]) + "⟩"
                marker_start = len(render(sent[:tm.start()]))
                marker_end = marker_start + len(marker)
                for key_index, key in enumerate(t["keys"]):
                    occurrence_id = _engine_identifiers._atomic_digest(
                        [sentence_id, t["source_index"], key_index, key]
                    )
                    sentence["citation_ids"].append(occurrence_id)
                    cites.append({
                        "key": key, "cmd": t["cmd"], "file": path,
                        "tex_path": tex_path,
                        "line": t["line"], "claim": claim, "context": context,
                        "nocite": t["cmd"].lower() == "nocite" or key == "*",
                        "occurrence_id": occurrence_id,
                        "sentence_id": sentence_id,
                        "location_id": location_id,
                        "marker_start": marker_start, "marker_end": marker_end,
                        "source_start": t["source_start"],
                        "source_end": t["source_end"],
                        "source_byte_start": len(
                            source_text[:t["source_start"]].encode("utf-8")
                        ),
                        "source_byte_end": len(
                            source_text[:t["source_end"]].encode("utf-8")
                        ),
                        "source_command": source_text[
                            t["source_start"]:t["source_end"]
                        ],
                    })
            sentences.append(sentence)
    keys = sorted({c["key"] for c in cites if c["key"] != "*"})
    by_key = {}
    for i, c in enumerate(cites):
        by_key.setdefault(c["key"], []).append(i)
    return {
        "input_format": "latex",
        "scope_complete": len({item["key"] for item in inline_bibliography})
        == len(inline_bibliography),
        "review_only": bool(inline_bibliography),
        "inline_bibliography": inline_bibliography,
        "diagnostics": [
            {
                "code": "inline-bibliography-unverified",
                "message": "Printed inline references require migration "
                           "to verified official exports",
                **item,
            }
            for item in inline_bibliography
        ],
        "complete": True,
        "main": tex_path,
        "files": [p for p, _ in files],
        "documentclass": docclass,
        "bib_files": list(dict.fromkeys(bib_files)),
        "n_instances": len(cites),
        "n_keys": len(keys),
        "keys": keys,
        "cites": cites,
        "by_key": by_key,
        "sentences": sentences,
        "source_digests": {
            path: hashlib.sha256(raw.encode("utf-8")).hexdigest()
            for path, raw in source_snapshots.items()
        },
    }

def _input_render(value: str, tokens: dict[int, dict[str, Any]]) -> str:
    """Render internal occurrence tokens without altering claim semantics."""
    value = _engine_parsing._CITE_TOKEN.sub(
        lambda token: "⟨cite:" + ",".join(tokens[int(token[1])]["keys"]) + "⟩",
        value,
    )
    return re.sub(r"⟩ (?=[,.;:)\]])", "⟩", value)

def extract_cites(tex_path: str) -> dict[str, Any]:
    """Extract exact citation occurrences from TeX, Markdown, text, or PDF.

    PDF and explicit review mappings never establish complete strict scope.
    Original text offsets are Unicode codepoints; PDF offsets are page-local.

    Args:
        tex_path: Main manuscript path; legacy parameter name is retained.

    Returns:
        Observed citations, exact source locations, extraction diagnostics
        and explicit completeness and review-only flags.
    """
    try:
        path = os.path.abspath(tex_path)
        if _input_format(path) == "latex":
            return _extract_tex_cites(path)
        snapshot = _input_snapshot(path)
        mappings, manifest_digest = _input_mappings(path, snapshot)
        kind = snapshot["input_format"]
        if any(_engine_parsing._CITE_TOKEN.search(page["text"]) for page in snapshot["pages"]):
            raise ValueError("reserved internal citation token in manuscript")
        fingerprint = snapshot["fingerprint"]
        cites: list[_engine_models.CitationInstance] = []
        sentences, diagnostics = [], []
        views: list[str] = []
        inline_bibliography = []
        for page in snapshot["pages"]:
            raw, number = page["text"], page["page"]
            body, references = _input_references(raw, kind)
            for item in references:
                item.update(
                    file=path,
                    page=number,
                    offset_unit="extracted-page-unicode-codepoint"
                    if number
                    else "unicode-codepoint",
                    source_byte_start=None
                    if number
                    else len(raw[: item["start"]].encode("utf-8")),
                    source_byte_end=None
                    if number
                    else len(raw[: item["end"]].encode("utf-8")),
                )
                inline_bibliography.append(item)
                diagnostics.append(
                    {
                        "code": "printed-reference-unverified",
                        "message": (
                            "Printed references require migration to "
                            "verified official exports"
                        ),
                        **item,
                    }
                )
            visible = _input_mask(body, kind, math=False)
            detection = _input_mask(body, kind)
            markers, issues = _input_native_markers(detection)
            manual = [item for item in mappings if item.get("page") == number]
            for item in manual:
                existing = next(
                    (
                        marker
                        for marker in markers
                        if marker["start"] == item["start"]
                        and marker["end"] == item["end"]
                    ),
                    None,
                )
                if existing:
                    existing["keys"].append(item["key"])
                else:
                    markers.append(
                        {
                            "start": item["start"],
                            "end": item["end"],
                            "keys": [item["key"]],
                        }
                    )
            issues = [
                item
                for item in issues
                if not any(
                    mapping["start"] <= item["start"]
                    and mapping["end"] >= item["end"]
                    for mapping in manual
                )
            ]
            diagnostics.extend(
                {**item, "file": path, "page": number} for item in issues
            )
            markers.sort(key=lambda item: item["start"])
            parts, last, tokens = [], 0, {}
            display_base = sum(value.count("\n") + 1 for value in views)
            if number is not None:
                views.append(f"Page {number}\n" + raw)
            for index, marker in enumerate(markers):
                parts.extend(
                    [visible[last : marker["start"]], f" ⟨cite#{index}⟩ "]
                )
                last = marker["end"]
                tokens[index] = marker
            parts.append(visible[last:])
            prose = "".join(parts)
            sents = []
            for paragraph in re.split(r"\n\s*\n", prose):
                sents.extend(
                    _engine_text._split_sentences(re.sub(r"\s+", " ", paragraph).strip())
                )

            render = functools.partial(_input_render, tokens=tokens)

            for index, sent in enumerate(sents):
                matches = list(_engine_parsing._CITE_TOKEN.finditer(sent))
                if not matches:
                    continue
                claim = render(sent)
                context = " ".join(
                    render(value)
                    for value in sents[max(0, index - 1) : index + 2]
                )
                anchors = [tokens[int(match[1])] for match in matches]
                location = _engine_identifiers._atomic_digest([path, number, anchors[0]["start"]])
                identity = _engine_identifiers._atomic_digest(
                    [
                        path,
                        number,
                        anchors,
                        claim,
                        context,
                        snapshot["raw_sha256"],
                        fingerprint,
                        manifest_digest,
                    ]
                )
                sentence = {
                    "sentence_id": identity,
                    "location_id": location,
                    "file": path,
                    "tex_path": path,
                    "claim": claim,
                    "context": context,
                    "citation_ids": [],
                    "offset_unit": "unicode-codepoint",
                    "page": number,
                }
                for match in matches:
                    marker = tokens[int(match[1])]
                    marker_start = len(render(sent[: match.start()]))
                    for key_index, key in enumerate(marker["keys"]):
                        occurrence = _engine_identifiers._atomic_digest(
                            [identity, int(match[1]), key_index, key]
                        )
                        sentence["citation_ids"].append(occurrence)
                        start, end = marker["start"], marker["end"]
                        page_line = raw.count("\n", 0, start) + 1
                        cites.append(
                            {
                                "key": key,
                                "cmd": "input-cite",
                                "file": path,
                                "tex_path": path,
                                "line": page_line
                                + display_base
                                + (1 if number else 0),
                                "page_line": page_line,
                                "page": number,
                                "claim": claim,
                                "context": context,
                                "nocite": False,
                                "occurrence_id": occurrence,
                                "sentence_id": identity,
                                "location_id": location,
                                "marker_start": marker_start,
                                "marker_end": marker_start
                                + len(
                                    "⟨cite:" + ",".join(marker["keys"]) + "⟩"
                                ),
                                "source_start": start,
                                "source_end": end,
                                "source_command": raw[start:end],
                                "source_byte_start": None
                                if number
                                else len(raw[:start].encode("utf-8")),
                                "source_byte_end": None
                                if number
                                else len(raw[:end].encode("utf-8")),
                                "source_offset_unit": (
                                    "extracted-page-unicode-codepoint"
                                    if number
                                    else "unicode-codepoint"
                                ),
                            }
                        )
                sentences.append(sentence)
        if kind == "pdf":
            diagnostics.append(
                {
                    "code": "pdf-extraction-uncertain",
                    "message": (
                        "PDF layout and citation coverage require manual review"
                    ),
                }
            )
        if mappings:
            diagnostics.append(
                {
                    "code": "manual-input-binding",
                    "message": (
                        "Explicit review mappings do not certify "
                        "citation identity or complete scope"
                    ),
                }
            )
        keys = sorted({cite["key"] for cite in cites})
        by_key = {
            key: [
                index for index, cite in enumerate(cites) if cite["key"] == key
            ]
            for key in keys
        }
        digests = {
            path: snapshot["raw_sha256"],
            _input_manifest_path(path): manifest_digest,
        }
        if any(
            _engine_persistence._audit_file_digest(source) != digest
            for source, digest in digests.items()
        ):
            raise ValueError(
                "manuscript or input mappings changed during extraction"
            )
        return {
            "complete": True,
            "main": path,
            "files": [path],
            "documentclass": None,
            "bib_files": [],
            "input_format": kind,
            "scope_complete": not diagnostics,
            "review_only": kind == "pdf"
            or bool(mappings)
            or bool(inline_bibliography),
            "diagnostics": diagnostics,
            "inline_bibliography": inline_bibliography,
            "n_instances": len(cites),
            "n_keys": len(keys),
            "keys": keys,
            "cites": cites,
            "by_key": by_key,
            "sentences": sentences,
            "source_digests": digests,
            "extraction_metadata": fingerprint,
            "source_texts": {path: "\n".join(views)} if kind == "pdf" else {},
        }
    except (OSError, ValueError, RuntimeError) as exc:
        return {
            "ok": False,
            "complete": False,
            "scope_complete": False,
            "error": str(exc),
        }
