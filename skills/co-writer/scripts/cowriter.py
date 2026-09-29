#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""co-writer's store: one log format, one location, whichever agent writes.

Every rewrite co-writer delivers is recorded here, and every edit the author
later makes to that text is found here. The store lives outside every
repository, at ``$CO_WRITER_HOME`` (default ``~/.co-writer``), so the
location never depends on the agent's working directory::

    ~/.co-writer/
    ├── papers.json               paper id -> repository root, .tex files
    ├── papers/<paper>/log/       YYYY-MM-DD-NN.md, one per rewrite or session
    ├── papers/<paper>/snapshots/ the .tex as found at each harvest
    ├── pairs.jsonl               the database: draft -> delivered -> accepted
    ├── pairs.md                  the same, readable, newest first
    ├── packets/                  what the next digest reads
    ├── proposals/                what a digest proposes; the author rules
    └── state.json                harvest cache, digest bookkeeping

Subcommands::

    cowriter.py log      --file TEX --agent A --slot S --register R
                         --input IN --output OUT [--note ..] [--unsure ..]
    cowriter.py session  --file TEX --agent A --asked .. --produced ..
                         --wrong ..
    cowriter.py harvest  [--paper P] [--rebuild] [--add TEX]
    cowriter.py status   [--brief]
    cowriter.py packet
    cowriter.py file     PACKET
    cowriter.py migrate  DIR [DIR ...]

``log`` and ``session`` are the only way an entry is written; agents call
them instead of writing the file. ``harvest`` reads the co-writer logs, the
paper's git history, the Claude Code transcripts under ``~/.claude/projects``
and the Antigravity conversations under ``~/.gemini/antigravity`` (SQLite
with protobuf payloads, decoded without a schema), and joins them into
records of what the author wrote, what an agent delivered, and what the
author kept. ``packet`` collects the records a digest has not yet seen, and
``file`` records the proposal the digest wrote from them.

Standard library only.
"""

from __future__ import annotations

import argparse
import ast
from collections.abc import Iterable, Iterator, Sequence
import dataclasses
import datetime
import difflib
import hashlib
import json
import os
import pathlib
import re
import sqlite3
import subprocess
import sys
from typing import Any

SKILL_DIR = pathlib.Path(__file__).resolve().parent.parent
PROFILE = SKILL_DIR / "references" / "voice-profile.md"
CLAUDE_PROJECTS = pathlib.Path.home() / ".claude" / "projects"
ANTIGRAVITY_CONVERSATIONS = (
    pathlib.Path.home() / ".gemini" / "antigravity" / "conversations"
)

SLOTS = (
    "abstract",
    "intro-opener",
    "gap",
    "methods",
    "definition",
    "equation",
    "results",
    "interpretation",
    "limitation",
    "close",
    "caption",
    "appendix",
    "mixed",
)
REGISTERS = ("journal", "workshop")
AGENTS = ("claude-code", "antigravity", "other")
FRONTMATTER_KEYS = (
    "id",
    "date",
    "agent",
    "profile_version",
    "paper",
    "file",
    "slot",
    "register",
    "cold_read",
    "session",
    "legacy",
)

# A unit shorter than this many words is markup or a heading, not prose.
MIN_WORDS = 12
# Word-level similarity above which two units are the same paragraph.
SAME_PARAGRAPH = 0.55
# Similarity above which a unit is the same text, give or take whitespace.
IDENTICAL = 0.995
# Similarity above which an observed unit is taken to be an agent's text.
AGENT_TEXT = 0.98
# Loosest similarity at which an earlier unit counts as the author's draft.
DRAFT_MATCH = 0.3
# Similarity above which an earlier unit is an agent's, so not a draft.
DRAFT_AGENT = 0.9


# ---------------------------------------------------------------------------
# Store paths and the paper registry.
# ---------------------------------------------------------------------------


def store_home() -> pathlib.Path:
    """Returns the store root, creating it if needed."""
    home = pathlib.Path(
        os.environ.get("CO_WRITER_HOME", pathlib.Path.home() / ".co-writer")
    ).expanduser()
    home.mkdir(parents=True, exist_ok=True)
    return home


def _read_json(path: pathlib.Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: pathlib.Path, data: Any) -> None:
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, sort_keys=True)
    tmp.replace(path)


def git_root(path: pathlib.Path) -> pathlib.Path | None:
    """Returns the git work tree holding ``path``, or None outside one."""
    start = path if path.is_dir() else path.parent
    result = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return pathlib.Path(result.stdout.strip())


def register_paper(tex: pathlib.Path, paper: str | None = None) -> str:
    """Records the paper a .tex file belongs to and returns its id.

    The id is the name of the git repository holding the file (for example
    ``manuscript-fm4pz``), so it is the same from any working directory.

    Args:
        tex: Path of the .tex file, absolute or relative to the cwd.
        paper: An explicit id, overriding the repository name.

    Returns:
        The paper id.
    """
    tex = tex.expanduser().resolve()
    root = git_root(tex) or tex.parent
    if paper is None:
        paper = root.name
    registry_path = store_home() / "papers.json"
    registry = _read_json(registry_path, {})
    entry = registry.setdefault(paper, {"root": str(root), "files": []})
    entry["root"] = str(root)
    relative = str(tex.relative_to(root)) if tex.is_relative_to(root) else ""
    if relative and relative not in entry["files"]:
        entry["files"].append(relative)
    _write_json(registry_path, registry)
    return paper


def paper_dir(paper: str) -> pathlib.Path:
    """Returns ``papers/<paper>`` in the store, creating its subdirectories."""
    base = store_home() / "papers" / paper
    for sub in ("log", "snapshots"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    return base


def profile_version() -> str:
    """Returns the Version field at the top of voice-profile.md."""
    match = re.search(
        r"\*\*Version:\*\*\s*([0-9][^\s·]*)",
        PROFILE.read_text(encoding="utf-8"),
    )
    return match.group(1) if match else "unknown"


# ---------------------------------------------------------------------------
# Log entries.
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class Entry:
    """One file in ``papers/<paper>/log/``.

    Attributes:
        meta: Frontmatter fields, keys from FRONTMATTER_KEYS.
        sections: Body sections by title (Input, Output, Note, Unsure), in
            the order they are written.
        path: Where the entry is stored, once written or read.
    """

    meta: dict[str, str]
    sections: dict[str, str]
    path: pathlib.Path | None = None

    def render(self) -> str:
        """Returns the entry as the text of its file."""
        lines = ["---"]
        lines += [
            f"{key}: {self.meta[key]}"
            for key in FRONTMATTER_KEYS
            if self.meta.get(key)
        ]
        lines.append("---")
        for title in ("Input", "Output", "Note", "Unsure"):
            body = self.sections.get(title, "").strip("\n")
            if body.strip():
                lines += [f"## {title}", body]
        return "\n".join(lines) + "\n"


def parse_entry(path: pathlib.Path) -> Entry | None:
    """Reads a log entry, in the canonical or any legacy layout.

    Args:
        path: The markdown file.

    Returns:
        The entry, or None if the file has no frontmatter.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.match(r"---\s*\n(.*?)\n---\s*\n", text, flags=re.DOTALL)
    if not match:
        return None
    meta = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
    sections = {}
    pattern = r"^##\s+(\w+)\s*\n(.*?)(?=^##\s+\w+\s*$|\Z)"
    for title, body in re.findall(pattern, text[match.end() :], re.S | re.M):
        sections[title.capitalize()] = body.rstrip("\n")
    return Entry(meta, sections, path)


def _next_entry_path(log_dir: pathlib.Path, day: str) -> pathlib.Path:
    taken = {
        int(m.group(1))
        for p in log_dir.glob(f"{day}-*.md")
        if (m := re.fullmatch(rf"{day}-(\d+)\.md", p.name))
    }
    number = max(taken, default=0) + 1
    return log_dir / f"{day}-{number:02d}.md"


def write_entry(paper: str, entry: Entry) -> pathlib.Path:
    """Stores an entry under the next free number of its day.

    Args:
        paper: The paper id.
        entry: The entry; ``meta["date"]`` is an ISO timestamp.

    Returns:
        The path written.
    """
    log_dir = paper_dir(paper) / "log"
    path = _next_entry_path(log_dir, entry.meta["date"][:10])
    entry.meta["id"] = path.stem
    entry.meta["paper"] = paper
    with path.open("x", encoding="utf-8") as f:
        f.write(entry.render())
    entry.path = path
    return path


def _read_text_arg(value: str) -> str:
    """Reads ``-`` as stdin, an existing path as its file, else the string."""
    if value == "-":
        return sys.stdin.read()
    candidate = pathlib.Path(value).expanduser()
    if len(value) < 4096 and candidate.is_file():
        return candidate.read_text(encoding="utf-8")
    return value


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="minutes")


def command_log(args: argparse.Namespace) -> int:
    """Implements ``cowriter.py log``: one entry per delivered rewrite."""
    tex = pathlib.Path(args.file) if args.file else None
    if tex is None and not args.paper:
        raise SystemExit("log: give --file TEX, or --paper for inline mode")
    paper = register_paper(tex, args.paper) if tex else args.paper
    root = pathlib.Path(
        _read_json(store_home() / "papers.json", {})
        .get(paper, {})
        .get("root", ".")
    )
    relative = ""
    if tex:
        resolved = tex.expanduser().resolve()
        relative = (
            str(resolved.relative_to(root))
            if resolved.is_relative_to(root)
            else str(resolved)
        )
    output = _read_text_arg(args.output)
    if not output.strip():
        raise SystemExit("log: --output is empty; log the delivered text")
    meta = {
        "date": args.date or _now(),
        "agent": args.agent,
        "profile_version": profile_version(),
        "file": relative,
        "slot": args.slot,
        "register": args.register,
        "cold_read": args.cold_read,
        "session": args.session_id or "",
    }
    sections = {
        "Input": _read_text_arg(args.input),
        "Output": output,
        "Note": _read_text_arg(args.note) if args.note else "",
        "Unsure": _read_text_arg(args.unsure) if args.unsure else "",
    }
    path = write_entry(paper, Entry(meta, sections))
    if relative and tex:
        # The file as it stands now, before the author edits the delivery;
        # harvest otherwise sees only committed states and its own runs.
        snapshot(paper, root, relative)
    print(path)
    return 0


def command_session(args: argparse.Namespace) -> int:
    """Implements ``cowriter.py session``: the note that closes a session."""
    paper = register_paper(pathlib.Path(args.file), args.paper)
    note = "\n".join(
        (
            f"Asked: {_read_text_arg(args.asked).strip()}",
            f"Produced: {_read_text_arg(args.produced).strip()}",
            f"Said was wrong: {_read_text_arg(args.wrong).strip()}",
        )
    )
    tex = pathlib.Path(args.file).expanduser().resolve()
    root = git_root(tex) or tex.parent
    meta = {
        "date": args.date or _now(),
        "agent": args.agent,
        "profile_version": profile_version(),
        "file": str(tex.relative_to(root)),
        "slot": "session",
        "register": args.register,
        "session": args.session_id or "",
    }
    path = write_entry(paper, Entry(meta, {"Note": note}))
    print(path)
    return 0


def command_migrate(args: argparse.Namespace) -> int:
    """Implements ``cowriter.py migrate``: moves old per-repo logs in.

    Each ``DIR`` is a ``.co-writer`` directory from the old layout. Entries
    are renumbered into the store (the old name is kept as ``legacy``), their
    ``file`` field is made relative to the paper's repository, and the
    originals are deleted only after every copy has been written and read
    back.
    """
    moved = []
    for directory in args.dirs:
        base = pathlib.Path(directory).expanduser().resolve()
        for path in sorted((base / "log").glob("*.md")):
            entry = parse_entry(path)
            if entry is None:
                print(f"skip (no frontmatter): {path}")
                continue
            file_field = entry.meta.get("file", "main.tex")
            tex = (base.parent / file_field).resolve()
            paper = register_paper(tex, args.paper)
            root = git_root(tex) or tex.parent
            entry.meta["file"] = str(tex.relative_to(root))
            entry.meta["legacy"] = str(path)
            if entry.meta.get("slot") == "session":
                # The old Input and Output, if any, stay beside the new Note.
                entry.sections.update(_legacy_session_note(entry.sections))
            entry.meta.pop("id", None)
            new_path = write_entry(paper, entry)
            if parse_entry(new_path) is None:
                raise SystemExit(f"migrate: could not read back {new_path}")
            moved.append(path)
            print(f"{path} -> {new_path}")
    if args.delete:
        for path in moved:
            path.unlink()
    return 0


def _legacy_session_note(sections: dict[str, str]) -> dict[str, str]:
    """Reshapes an old session note into Asked / Produced / Said was wrong."""
    note = sections.get("Note", "")
    if re.search(r"^Asked:", note, re.M):
        return {"Note": note}
    labels = {
        "asked": r"(?:What was asked|Asked)",
        "produced": r"(?:What was produced|Produced)",
        "wrong": r"(?:What the user said(?: was wrong)?|User said was wrong)",
    }
    found = {}
    for key, label in labels.items():
        match = re.search(
            rf"{label}:\s*(.*?)(?=\n(?:What|Asked|Produced|User)[^\n]*:|\Z)",
            note,
            re.S,
        )
        found[key] = match.group(1).strip() if match else ""
    if not found["asked"] and sections.get("Input"):
        found["asked"] = sections["Input"].strip()
    if not found["produced"] and sections.get("Output"):
        found["produced"] = sections["Output"].strip()
    if not any(found.values()):
        found["wrong"] = note.strip()
    return {
        "Note": "\n".join(
            (
                f"Asked: {found['asked']}",
                f"Produced: {found['produced']}",
                f"Said was wrong: {found['wrong']}",
            )
        )
    }


# ---------------------------------------------------------------------------
# Text units: paragraphs and captions.
# ---------------------------------------------------------------------------

_WORD = re.compile(r"\S+")
_LINE_NUMBER = re.compile(r"^\s*\d+(?::|\t|→) ?", re.M)
_VIEW_FOOTER = re.compile(
    r"\s*The above content (?:does NOT show|shows) the entire file.*\Z", re.S
)


def _clean_view(text: str) -> str:
    """Drops line-number prefixes and the viewer's trailing notice."""
    return _VIEW_FOOTER.sub("", _LINE_NUMBER.sub("", text))


def _strip_comments(text: str) -> str:
    lines = []
    for line in text.splitlines():
        cut = re.search(r"(?<!\\)%", line)
        lines.append(line[: cut.start()] if cut else line)
    return "\n".join(lines)


def _caption_spans(text: str) -> list[tuple[int, int, int]]:
    r"""Returns (start, body start, end) of every \caption{...} in ``text``."""
    spans = []
    for match in re.finditer(r"\\caption(?:\[[^\]]*\])?\{", text):
        depth, i = 1, match.end()
        while i < len(text) and depth:
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        # An unclosed caption runs to the end; mark it by a missing brace.
        spans.append((match.start(), match.end(), i if not depth else i + 1))
    return spans


_FLOAT_MARKUP = re.compile(
    r"\\(?:includegraphics(?:\[[^\]]*\])?\{[^}]*\}|label\{[^}]*\}"
    r"|centering|small|footnotesize|scriptsize|setlength\{[^}]*\}\{[^}]*\})"
)


def _is_prose(unit: str) -> bool:
    words = _WORD.findall(unit)
    if len(words) < MIN_WORDS:
        return False
    alphabetic = sum(1 for w in words if re.fullmatch(r"[A-Za-z,.;:()'-]+", w))
    return alphabetic >= 0.5 * len(words)


def _complete_paragraphs(text: str) -> str:
    """Cuts a fragment back to the paragraphs it holds whole.

    A partial file view or an edit chunk may start or end mid-paragraph;
    what precedes its first blank line and follows its last is dropped.
    """
    first = re.search(r"\n\s*\n", text)
    if first is None:
        return ""
    last = list(re.finditer(r"\n\s*\n", text))[-1]
    return text[first.end() : last.start()]


def text_units(text: str, partial: bool = False) -> list[str]:
    """Splits LaTeX into the units an author edits: paragraphs and captions.

    Comments are dropped; every caption, inside a float or not, is its own
    unit with the float's markup stripped; headings and environment
    boundaries end a paragraph; whitespace is collapsed, so two versions of
    a paragraph compare equal when only line breaks differ.

    Args:
        text: LaTeX source, a whole file or a fragment.
        partial: The text is a fragment that may begin or end inside a
            paragraph; only the paragraphs it holds whole are returned.

    Returns:
        The prose units, in order.
    """
    text = _strip_comments(text)
    units: list[str] = []
    pieces, cursor = [], 0
    for start, body, end in _caption_spans(text):
        if text[end - 1 : end] == "}":  # Unclosed: the fragment ends in it.
            units.append(text[body : end - 1])
        pieces.append(text[cursor:start])
        cursor = end
    pieces.append(text[cursor:])
    body_text = "\n\n".join(pieces)
    if partial:
        body_text = _complete_paragraphs(body_text)
    body_text = re.sub(r"\\(?:sub)*section\*?\{[^}]*\}", "\n\n", body_text)
    body_text = re.sub(r"\\(?:begin|end)\{[a-z*]+\}", "\n\n", body_text)
    units.extend(re.split(r"\n\s*\n", body_text))
    cleaned = (" ".join(_FLOAT_MARKUP.sub(" ", u).split()) for u in units)
    return [unit for unit in cleaned if _is_prose(unit)]


def _grams(text: str, size: int = 6) -> set[tuple[str, ...]]:
    words = text.split()
    return {tuple(words[i : i + size]) for i in range(len(words) - size + 1)}


def _overlaps(unit: str, target: str) -> bool:
    """Whether a unit shares a six-word run with ``target``, or holds it."""
    flat = " ".join(target.split())
    if len(flat.split()) < 6:
        return bool(flat) and flat in unit
    return bool(_grams(unit) & _grams(flat))


def similarity(first: str, second: str) -> float:
    """Returns the word-level SequenceMatcher ratio of two units, in [0, 1]."""
    matcher = difflib.SequenceMatcher(
        None, first.split(), second.split(), autojunk=False
    )
    return matcher.ratio()


def word_diff(before: str, after: str) -> str:
    """Returns ``[-removed-] {+added+}`` word diff of two units."""
    old, new = before.split(), after.split()
    parts = []
    matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            parts.append(" ".join(old[i1:i2]))
            continue
        if i2 > i1:
            parts.append(f"[-{' '.join(old[i1:i2])}-]")
        if j2 > j1:
            parts.append(f"{{+{' '.join(new[j1:j2])}+}}")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Events: what was written, delivered or seen, and when.
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class Event:
    """One timestamped piece of text about a paper.

    Attributes:
        time: ISO timestamp, local time, to the second.
        kind: ``deliver`` (an agent put this text in or returned it),
            ``observe`` (the file or part of it as it stood), ``paste``
            (text the author typed into the chat), or ``message`` (any
            other author turn, kept for its words).
        text: The text; for observe events, the whole or partial file.
        source: Where it came from, e.g. ``git:1a2b3c4 subject`` or
            ``antigravity:<conversation>#<step>``.
        agent: The agent for deliver events, else empty.
        profile_version: For deliveries from a log entry, the version.
        slot: For deliveries from a log entry, its slot.
        before: For an edit, the text it replaced.
        partial: The text may begin or end inside a paragraph.
        flag: ``chat`` for text an agent wrote in the conversation rather
            than the file; ``ai-touched`` for a commit that carries an
            agent's fingerprints although no transcript here produced it.
    """

    time: str
    kind: str
    text: str
    source: str
    agent: str = ""
    profile_version: str = ""
    slot: str = ""
    before: str = ""
    partial: bool = False
    flag: str = ""


def _iso(seconds: float) -> str:
    return datetime.datetime.fromtimestamp(seconds).isoformat(
        timespec="seconds"
    )


def _utc_to_local(stamp: str) -> str:
    moment = datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    return (
        moment.astimezone().replace(tzinfo=None).isoformat(timespec="seconds")
    )


def events_from_logs(paper: str) -> Iterator[Event]:
    """Yields each logged Output as a delivery and each Input as a paste."""
    for path in sorted((paper_dir(paper) / "log").glob("*.md")):
        entry = parse_entry(path)
        if entry is None or entry.meta.get("slot") == "session":
            continue
        stamp = entry.meta.get("date", path.stem[:10])
        source = f"log:{path.stem}"
        output = entry.sections.get("Output", "")
        if output:
            yield Event(
                stamp,
                "deliver",
                output,
                source,
                entry.meta.get("agent", ""),
                entry.meta.get("profile_version", ""),
                entry.meta.get("slot", ""),
            )
        if entry.sections.get("Input"):
            yield Event(stamp, "paste", entry.sections["Input"], source)


def events_from_git(root: pathlib.Path, relative: str) -> Iterator[Event]:
    """Yields every committed version of a file as an observation."""
    listing = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "log",
            "--format=%H%x09%ct%x09%s",
            "--",
            relative,
        ],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    for line in listing.splitlines():
        sha, seconds, subject = line.split("\t", 2)
        shown = subprocess.run(
            ["git", "-C", str(root), "show", f"{sha}:{relative}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if shown.returncode == 0:
            yield Event(
                _iso(int(seconds)),
                "observe",
                shown.stdout,
                f"git:{sha[:7]} {subject}",
                flag="ai-touched" if _agent_fingerprints(root, sha) else "",
            )


# Lines an agent adds and an author does not: cite-check's provenance
# comments, banner comments, CUT notes; and latexdiff output files.
_FINGERPRINTS = re.compile(
    r"^\+(?:@comment\{cite-check|\s*%\s*#{10,}|\s*%\s*(?:WARNING|CUT)\b)"
    r"|^\+\+\+ b/\S*_diff\.tex$",
    re.M,
)


def _agent_fingerprints(root: pathlib.Path, sha: str) -> bool:
    """Whether a commit adds text only an agent writes (see _FINGERPRINTS)."""
    patch = subprocess.run(
        ["git", "-C", str(root), "show", "--format=", sha],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    return bool(_FINGERPRINTS.search(patch))


def events_from_snapshots(paper: str) -> Iterator[Event]:
    """Yields the working-tree snapshots taken by earlier harvests."""
    for path in sorted((paper_dir(paper) / "snapshots").glob("*.tex")):
        stamp = path.name.split("__", 1)[0]
        yield Event(
            stamp.replace("_", ":"),
            "observe",
            path.read_text(encoding="utf-8", errors="replace"),
            f"snapshot:{path.name}",
        )


def snapshot(paper: str, root: pathlib.Path, relative: str) -> Event | None:
    """Stores the working-tree file if it changed since the last snapshot."""
    tex = root / relative
    if not tex.exists():
        return None
    text = tex.read_text(encoding="utf-8", errors="replace")
    safe = relative.replace("/", "%")
    existing = sorted((paper_dir(paper) / "snapshots").glob(f"*__{safe}"))
    if existing and existing[-1].read_text(encoding="utf-8") == text:
        return None
    stamp = _iso(tex.stat().st_mtime)
    path = paper_dir(paper) / "snapshots" / f"{stamp.replace(':', '_')}__{safe}"
    path.write_text(text, encoding="utf-8")
    return Event(stamp, "observe", text, f"snapshot:{path.name}")


# Claude Code ----------------------------------------------------------------


def _claude_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def _is_author_turn(text: str) -> bool:
    stripped = text.lstrip()
    return bool(stripped) and not stripped.startswith(
        (
            "<",
            "This session is being continued",
            "Another Claude session",
            "Base directory for this skill",
        )
    )


_HEREDOC = re.compile(
    r"cat\s*>+\s*(\S+\.tex)\s*<<-?\s*'?(\w+)'?\n(.*?)\n\2", re.S
)
_PYTHON_HEREDOC = re.compile(
    r"python3?\s+-\s*<<-?\s*'?(\w+)'?\n(.*?)\n\1", re.S
)


def _string_value(node: ast.AST, names: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return names.get(node.id)
    return None


def _python_edits(source: str) -> Iterator[tuple[str, str]]:
    """Yields (before, after) for each replacement a Python script makes.

    Found in the ways the agents write them: ``s.replace(old, new)`` with
    literals or names, ``(old, new)`` pairs in a list or tuple, and
    ``old = ...`` / ``new = ...`` assignments. A long string literal that
    is none of these is yielded as ``("", text)``, new text with nothing
    known about what it replaced.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return
    names: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            value = _string_value(node.value, names)
            if isinstance(target, ast.Name) and value is not None:
                names[target.id] = value
    used: set[str] = set()
    for node in ast.walk(tree):
        before: str | None = None
        after: str | None = None
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "replace"
            and len(node.args) >= 2
        ):
            before = _string_value(node.args[0], names)
            after = _string_value(node.args[1], names)
        elif isinstance(node, ast.Tuple) and len(node.elts) == 2:
            before = _string_value(node.elts[0], names)
            after = _string_value(node.elts[1], names)
        if before is not None and after is not None:
            used.update((before, after))
            yield before, after
    olds = [v for k, v in names.items() if k.startswith("old")]
    news = [v for k, v in names.items() if not k.startswith("old")]
    for old, new in zip(olds, news, strict=False):
        if old not in used and new not in used:
            used.update((old, new))
            yield old, new
    for node in ast.walk(tree):
        value = _string_value(node, {})
        if value and value not in used and len(value.split()) >= MIN_WORDS:
            used.add(value)
            yield "", value


def _bash_tex_edits(command: str) -> Iterator[tuple[str, str]]:
    """Yields (before, after) for prose a Bash command writes into a .tex."""
    for _, body in _PYTHON_HEREDOC.findall(command):
        yield from _python_edits(body)
    for _, _, body in _HEREDOC.findall(command):
        yield "", body


def events_from_claude(
    root: pathlib.Path, cache: dict[str, Any]
) -> Iterator[Event]:
    """Yields the events in every Claude Code session that touches ``root``.

    Sessions are found by content, not by project slug, because the paper is
    usually edited from a parent directory. A file whose size and mtime are
    unchanged since the last harvest is read from ``cache``.

    Args:
        root: The paper's repository root.
        cache: ``state.json``'s per-source cache, updated in place.

    Yields:
        Deliveries (Edit/Write/MultiEdit on a .tex under ``root``, and
        triple-quoted or heredoc text in Bash commands that write one),
        observations (Read results and ``old`` strings), pastes (long author
        turns) and messages (every other author turn).
    """
    if not CLAUDE_PROJECTS.exists():
        return
    needle = str(root)
    for path in sorted(CLAUDE_PROJECTS.glob("*/*.jsonl")):
        key = f"claude:{path}:{needle}"
        stat = path.stat()
        signature = [stat.st_size, int(stat.st_mtime)]
        cached = cache.get(key)
        if cached and cached["signature"] == signature:
            events = [Event(**event) for event in cached["events"]]
        else:
            events = list(_scan_claude_session(path, needle))
            cache[key] = {
                "signature": signature,
                "events": [dataclasses.asdict(e) for e in events],
            }
        yield from events


def _scan_claude_session(path: pathlib.Path, needle: str) -> Iterator[Event]:
    """Yields a session's events, if the session read or wrote the paper."""
    with path.open("rb") as f:
        if needle.encode() not in f.read():
            return
    events: list[Event] = []
    shell = _ClaudeShell()
    with path.open(encoding="utf-8", errors="replace") as f:
        for number, line in enumerate(f):
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("timestamp"):
                events.extend(
                    _claude_record(
                        record,
                        needle,
                        f"claude:{path.stem[:8]}#{number}",
                        shell,
                    )
                )
    # A session counts if it read or wrote the paper; its chat is then a
    # source of delivered text the author may paste or retype.
    if any(
        e.kind == "observe" or (e.kind == "deliver" and e.flag != "chat")
        for e in events
    ):
        yield from events


@dataclasses.dataclass
class _ClaudeShell:
    """What a session's transcript implies about its shell, line by line.

    Attributes:
        in_repo: The last ``cd`` went into the paper's repository.
        reads: Tool calls that read the paper and await their result, by
            tool-use id, to whether the read shows only part of the file.
    """

    in_repo: bool = False
    reads: dict[str, bool] = dataclasses.field(default_factory=dict)


# A Bash command that prints a .tex: the whole file only for a bare cat.
_BASH_READ = re.compile(r"\b(cat|sed|head|tail|awk)\b[^|;&]*\.tex\b")
_BASH_WHOLE = re.compile(r"^\s*(?:cd \S+ && )?cat(?: -n)? \S+\.tex\s*$")


def _claude_record(
    record: dict[str, Any],
    needle: str,
    source: str,
    shell: _ClaudeShell,
) -> Iterator[Event]:
    """Yields the events in one transcript line.

    Args:
        record: One parsed line of a session's JSONL.
        needle: The paper's repository root, as a string.
        source: The source label for the events.
        shell: The session's inferred shell state; updated in place.

    Yields:
        Deliveries, observations, pastes and messages.
    """
    stamp = _utc_to_local(record["timestamp"])
    content = (record.get("message") or {}).get("content")
    pending_reads = shell.reads
    if record.get("type") == "assistant" and isinstance(content, list):
        for block in content:
            if block.get("type") == "text" and block.get("text"):
                yield Event(
                    stamp,
                    "deliver",
                    block["text"],
                    source,
                    "claude-code",
                    flag="chat",
                )
            if block.get("type") != "tool_use":
                continue
            arguments = block.get("input", {})
            command = arguments.get("command", "")
            for directory in re.findall(r"\bcd\s+(\S+)", command):
                shell.in_repo = directory.startswith(needle)
            in_repo = shell.in_repo or str(record.get("cwd", "")).startswith(
                needle
            )
            yield from _claude_tool_use(block, needle, stamp, source, in_repo)
            if (
                block.get("name") == "Bash"
                and (in_repo or needle in command)
                and _BASH_READ.search(command)
                and not re.search(r"<<|>\s*\S+\.tex", command)
            ):
                pending_reads[block["id"]] = not _BASH_WHOLE.match(command)
            target = arguments.get("file_path", "")
            if (
                block.get("name") == "Read"
                and target.startswith(needle)
                and target.endswith(".tex")
            ):
                pending_reads[block["id"]] = bool(
                    arguments.get("offset") or arguments.get("limit")
                )
        return
    if record.get("type") != "user":
        return
    if isinstance(content, list):
        for block in content:
            if (
                block.get("type") == "tool_result"
                and block.get("tool_use_id") in pending_reads
            ):
                yield Event(
                    stamp,
                    "observe",
                    _clean_view(_claude_text(block.get("content"))),
                    source,
                    partial=pending_reads.pop(block["tool_use_id"]),
                )
    text = _claude_text(content)
    if _is_author_turn(text):
        kind = "paste" if len(text) > 400 else "message"
        yield Event(stamp, kind, text, source)


def _claude_tool_use(
    block: dict[str, Any],
    needle: str,
    stamp: str,
    source: str,
    in_repo: bool,
) -> Iterator[Event]:
    name, arguments = block.get("name"), block.get("input", {})
    target = arguments.get("file_path", "")
    if name in ("Edit", "Write", "MultiEdit") and target.endswith(".tex"):
        if not target.startswith(needle):
            return
        edits = arguments.get("edits") or [arguments]
        for edit in edits:
            new = edit.get("new_string") or edit.get("content") or ""
            if new:
                yield Event(
                    stamp,
                    "deliver",
                    new,
                    source,
                    "claude-code",
                    before=edit.get("old_string", ""),
                )
    if name == "Bash":
        command = arguments.get("command", "")
        if re.search(r"\.tex\b", command) and (in_repo or needle in command):
            for before, after in _bash_tex_edits(command):
                yield Event(
                    stamp,
                    "deliver",
                    after,
                    source,
                    "claude-code",
                    before=before,
                )


# Antigravity ----------------------------------------------------------------


def _varint(data: bytes, i: int) -> tuple[int, int]:
    shift = result = 0
    while True:
        byte = data[i]
        i += 1
        result |= (byte & 0x7F) << shift
        shift += 7
        if byte < 0x80:
            return result, i


def _protobuf_fields(data: bytes) -> list[tuple[int, int, Any]] | None:
    """Parses one protobuf message without a schema, or returns None."""
    fields, i = [], 0
    try:
        while i < len(data):
            key, i = _varint(data, i)
            number, wire = key >> 3, key & 7
            value: int | bytes
            if number == 0:
                return None
            if wire == 0:
                value, i = _varint(data, i)
            elif wire == 1:
                value, i = data[i : i + 8], i + 8
            elif wire == 5:
                value, i = data[i : i + 4], i + 4
            elif wire == 2:
                size, i = _varint(data, i)
                value, i = data[i : i + size], i + size
                if i > len(data):
                    return None
            else:
                return None
            fields.append((number, wire, value))
    except IndexError:
        return None
    return fields


def _looks_like_text(data: bytes) -> str | None:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if len(text) < 3:
        return None
    readable = sum(ch.isalpha() or ch.isspace() for ch in text)
    return text if readable > 0.6 * len(text) else None


def protobuf_strings(
    data: bytes, path: tuple[int, ...] = (), depth: int = 0
) -> Iterator[tuple[str, str]]:
    """Yields (dotted field path, string) for every string in a message.

    A length-delimited field that decodes as mostly readable UTF-8 is taken
    as a string; otherwise it is parsed as a nested message.

    Args:
        data: A serialized protobuf message.
        path: Field numbers leading here, for recursion.
        depth: Recursion depth, capped at 12.

    Yields:
        Pairs such as ``("19.2", "<the author's message>")``.
    """
    fields = _protobuf_fields(data) if depth < 12 else None
    if fields is None:
        return
    for number, wire, value in fields:
        if wire != 2:
            continue
        here = (*path, number)
        text = _looks_like_text(value)
        if text is not None and (
            _protobuf_fields(value) is None or "\n" in text or " " in text
        ):
            yield ".".join(map(str, here)), text
        else:
            yield from protobuf_strings(value, here, depth + 1)


def _step_time(data: bytes) -> str:
    for number, wire, value in _protobuf_fields(data) or []:
        if number != 5 or wire != 2:
            continue
        for sub_number, sub_wire, sub_value in _protobuf_fields(value) or []:
            if sub_number == 1 and sub_wire == 2:
                inner = _protobuf_fields(sub_value) or []
                if inner and inner[0][1] == 0:
                    return _iso(inner[0][2])
    return ""


_AG_EDIT_TOOLS = (
    "replace_file_content",
    "multi_replace_file_content",
    "write_to_file",
)


def events_from_antigravity(
    root: pathlib.Path, cache: dict[str, Any]
) -> Iterator[Event]:
    """Yields the events in every Antigravity conversation touching ``root``.

    Conversations are SQLite files whose ``steps.step_payload`` is protobuf.
    The fields used, found by inspection: step type 14 is an author turn
    (text at 19.2); type 15 is a model turn whose tool calls sit at 20.7
    (name at .2, JSON arguments at .3); a tool result's text is at 140.2.1,
    and a ``view_file`` result starts with ``File Path: `file://<path>```.

    Args:
        root: The paper's repository root.
        cache: ``state.json``'s per-source cache, updated in place.

    Yields:
        Deliveries (ReplacementContent / CodeContent of edits to a .tex
        under ``root``), observations (TargetContent and view_file results),
        pastes and messages (author turns).
    """
    if not ANTIGRAVITY_CONVERSATIONS.exists():
        return
    needle = str(root)
    for path in sorted(ANTIGRAVITY_CONVERSATIONS.glob("*.db")):
        key = f"antigravity:{path}:{needle}"
        stat = path.stat()
        signature = [stat.st_size, int(stat.st_mtime)]
        cached = cache.get(key)
        if cached and cached["signature"] == signature:
            events = [Event(**event) for event in cached["events"]]
        else:
            events = list(_scan_antigravity(path, needle))
            cache[key] = {
                "signature": signature,
                "events": [dataclasses.asdict(e) for e in events],
            }
        yield from events


def _scan_antigravity(path: pathlib.Path, needle: str) -> Iterator[Event]:
    uri = f"file:{path}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        rows = connection.execute(
            "SELECT idx, step_type, step_payload FROM steps ORDER BY idx"
        ).fetchall()
    conversation = path.stem[:8]
    events, touched = [], False
    for index, step_type, payload in rows:
        if payload is None:
            continue
        stamp = _step_time(payload)
        source = f"antigravity:{conversation}#{index}"
        strings = list(protobuf_strings(payload))
        if step_type == 14:
            for key, text in strings:
                if key == "19.2" and _is_author_turn(text):
                    kind = "paste" if len(text) > 400 else "message"
                    events.append(Event(stamp, kind, text, source))
            continue
        tool_name = ""
        for key, text in strings:
            if key == "20.1":
                events.append(
                    Event(
                        stamp,
                        "deliver",
                        text,
                        source,
                        "antigravity",
                        flag="chat",
                    )
                )
            elif key.endswith("20.7.2"):
                tool_name = text
            elif key.endswith("20.7.3") and tool_name in _AG_EDIT_TOOLS:
                found = list(_antigravity_edit(text, needle, stamp, source))
                touched = touched or bool(found)
                events.extend(found)
            elif key == "140.2.1" and text.startswith("File Path: `file://"):
                viewed = text.split("`", 2)[1].removeprefix("file://")
                if viewed.startswith(needle) and viewed.endswith(".tex"):
                    events.append(_antigravity_view(text, stamp, source))
    if touched:
        yield from events


def _antigravity_view(text: str, stamp: str, source: str) -> Event:
    """Returns a ``view_file`` result as an observation, partial or whole."""
    total = re.search(r"^Total Lines: (\d+)", text, re.M)
    shown = re.search(r"^Showing lines (\d+) to (\d+)", text, re.M)
    whole = bool(
        total
        and shown
        and shown.group(1) == "1"
        and shown.group(2) == total.group(1)
    )
    body = text.split("\n", 5)[-1]
    return Event(stamp, "observe", _clean_view(body), source, partial=not whole)


def _antigravity_edit(
    arguments: str, needle: str, stamp: str, source: str
) -> Iterator[Event]:
    try:
        call = json.loads(arguments)
    except json.JSONDecodeError:
        return
    target = call.get("TargetFile", "")
    if not (target.startswith(needle) and target.endswith(".tex")):
        return
    chunks = call.get("ReplacementChunks") or [call]
    for chunk in chunks:
        new = chunk.get("ReplacementContent") or chunk.get("CodeContent")
        if new:
            yield Event(
                stamp,
                "deliver",
                new,
                source,
                "antigravity",
                before=chunk.get("TargetContent", ""),
            )


# ---------------------------------------------------------------------------
# Joining events into records.
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class _Unit:
    text: str
    time: str
    source: str
    kind: str
    agent: str = ""
    profile_version: str = ""
    slot: str = ""


def _guess_slot(unit: str, context: str) -> str:
    """Guesses a unit's slot from where it sits in the file it was seen in."""
    flat = " ".join(_FLOAT_MARKUP.sub(" ", _strip_comments(context)).split())
    position = flat.find(unit[:60])
    if position < 0:
        return ""
    before = flat[:position]
    if re.search(r"\\caption(?:\[[^\]]*\])?\{\s*$", before):
        return "caption"
    if re.search(r"\\begin\{abstract\}(?!.*\\end\{abstract\})", before):
        return "abstract"
    headings = re.findall(r"\\section\*?\{([^}]*)\}", before)
    heading = headings[-1].lower() if headings else ""
    if "\\appendix" in before:
        return "appendix"
    for word, slot in (
        ("introduction", "intro"),
        ("method", "methods"),
        ("result", "results"),
        ("discussion", "results"),
        ("conclusion", "close"),
        ("summary", "close"),
    ):
        if word in heading:
            return slot
    return heading


def _agent_insertions(
    delivered: str, accepted: str, agent_grams: dict[tuple[str, ...], str]
) -> tuple[list[str], int, int]:
    """Splits what the author's version adds into agent text and the rest.

    An author who merges two delivered paragraphs, or pastes an agent's
    chat suggestion in, adds an agent's words; those are not an edit. An
    inserted word counts as the agent's when a six-word run through it
    appears in text an agent delivered before the accepted version was seen.

    Args:
        delivered: The delivered unit.
        accepted: The version the author kept.
        agent_grams: Six-word runs of agent text that predate ``accepted``.

    Returns:
        As a tuple (spans, removed, added): the inserted runs that are agent
        text, the number of delivered words the author removed or replaced,
        and the number of inserted words that are not agent text.
    """
    old, new = delivered.split(), accepted.split()
    covered = [False] * len(new)
    for i in range(len(new) - 5):
        if tuple(new[i : i + 6]) in agent_grams:
            covered[i : i + 6] = [True] * 6
    spans, removed, added = [], 0, 0
    matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        removed += i2 - i1
        run: list[str] = []
        for j in range(j1, j2):
            if covered[j]:
                run.append(new[j])
                continue
            added += 1
            if run:
                spans.append(" ".join(run))
                run = []
        if run:
            spans.append(" ".join(run))
    return spans, removed, added


class _Matcher:
    """Memoized similarity between units, with a cheap bag-of-words filter."""

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], float] = {}
        self._bags: dict[str, set[str]] = {}

    def _bag(self, text: str) -> set[str]:
        if text not in self._bags:
            self._bags[text] = set(text.lower().split())
        return self._bags[text]

    def __call__(self, first: str, second: str) -> float:
        if first == second:
            return 1.0
        key = (first, second) if first < second else (second, first)
        if key not in self._cache:
            bag_a, bag_b = self._bag(first), self._bag(second)
            overlap = len(bag_a & bag_b) / max(1, len(bag_a | bag_b))
            self._cache[key] = (
                similarity(first, second) if overlap >= 0.2 else 0.0
            )
        return self._cache[key]


def _normalize_times(events: Iterable[Event]) -> list[Event]:
    """Drops untimed events, pads minute stamps to seconds, sorts by time."""
    timed = [e for e in events if e.time]
    for event in timed:
        stamp = event.time
        event.time = f"{stamp}:00" if len(stamp) == 16 else stamp[:19]
    timed.sort(key=lambda e: e.time)
    return timed


def _expand_edits(events: Sequence[Event]) -> list[Event]:
    """Replaces each edit by the whole paragraphs it changed.

    An edit call carries a fragment: a sentence, part of a caption, a run
    of lines. Applied to the file as last seen whole, it yields the
    paragraph before (an observation) and after (the delivery). The file
    as last seen is the newest observation, whole or partial, that holds
    the fragment, with every expanded edit applied since. An edit whose
    fragment is in none keeps its fragment, cut back to the paragraphs and
    captions it holds whole.

    Args:
        events: Events in time order.

    Returns:
        The events, with edits expanded.
    """
    # Recent states of the file, newest last: (text, partial). An edit is
    # applied to the newest that holds its fragment, and the result becomes
    # the newest state.
    states: list[tuple[str, bool]] = []
    expanded = []
    for event in events:
        if event.kind == "observe":
            states = [*states[-40:], (event.text, event.partial)]
        if event.kind != "deliver" or event.flag == "chat" or not event.before:
            if event.kind == "deliver" and "\\begin{document}" in event.text:
                states = [*states[-40:], (event.text, False)]
            expanded.append(event)
            continue
        observed = dataclasses.replace(
            event, kind="observe", text=event.before, agent="", before=""
        )
        delivered = dataclasses.replace(event, before="")
        holder = next(
            (state for state in reversed(states) if event.before in state[0]),
            None,
        )
        if holder is None:
            observed.partial = delivered.partial = True
        else:
            text, partial = holder
            after = text.replace(event.before, event.text, 1)
            observed.text = "\n\n".join(
                u
                for u in text_units(text, partial)
                if _overlaps(u, event.before)
            )
            delivered.text = "\n\n".join(
                u
                for u in text_units(after, partial)
                if _overlaps(u, event.text)
            )
            states = [*states[-40:], (after, partial)]
        expanded += [observed, delivered]
    return expanded


def _delivered_units(
    events: Iterable[Event], first_seen: dict[str, Event]
) -> dict[str, _Unit]:
    """Returns each distinct delivered unit, first delivery wins.

    A unit in an agent's chat reply that was already in the paper is a
    quotation and is skipped.

    When the same text is both logged and in a transcript, the transcript's
    time and source are kept (a log entry's time is to the minute and
    written after the fact) and the log's profile version and slot.
    """
    deliveries: dict[str, _Unit] = {}
    for event in events:
        if event.kind != "deliver":
            continue
        for text in text_units(event.text, event.partial):
            seen = first_seen.get(text)
            if event.flag == "chat" and seen and seen.time < event.time:
                continue  # The agent quoting the paper, not writing it.
            known = deliveries.get(text)
            if known is None:
                deliveries[text] = _Unit(
                    text,
                    event.time,
                    event.source,
                    "deliver",
                    event.agent,
                    event.profile_version,
                    event.slot,
                )
                continue
            if known.source.startswith("log:") and not (
                event.source.startswith("log:")
            ):
                known.time, known.source = event.time, event.source
                known.agent = known.agent or event.agent
            if event.profile_version:
                known.profile_version = event.profile_version
                known.slot = known.slot or event.slot
    return deliveries


class _Joiner:
    """Finds, for each delivered unit, the author's draft and accepted text.

    Attributes:
        deliveries: Distinct delivered units by text.
        observed: (event, units) for every observation and paste, in time
            order. A paste is both what the author kept of the last
            delivery and the draft of the next.
        turns: The author's chat turns, in time order.
    """

    def __init__(self, events: Sequence[Event]) -> None:
        self.match = _Matcher()
        self.observed = [
            (e, text_units(e.text, e.partial))
            for e in events
            if e.kind in ("observe", "paste")
        ]
        self.first_seen: dict[str, Event] = {}
        for event, units in self.observed:
            for unit in units:
                self.first_seen.setdefault(unit, event)
        self.deliveries = _delivered_units(events, self.first_seen)
        self.turns = [e for e in events if e.kind in ("message", "paste")]
        self.agent_grams: dict[tuple[str, ...], str] = {}
        for delivery in self.deliveries.values():
            for gram in _grams(delivery.text):
                if delivery.time < self.agent_grams.get(gram, "9999"):
                    self.agent_grams[gram] = delivery.time
        self._ranked: dict[str, list[_Unit]] = {}

    def best_delivery(self, text: str, before: str) -> _Unit | None:
        """Returns the delivery made before ``before`` most like ``text``."""
        if text not in self._ranked:
            self._ranked[text] = sorted(
                self.deliveries.values(),
                key=lambda d: self.match(text, d.text),
                reverse=True,
            )
        for delivery in self._ranked[text]:
            if delivery.time < before:
                return delivery
        return None

    def is_agent_text(self, text: str, seen: str, threshold: float) -> bool:
        """Whether a delivery made before ``seen`` explains ``text``."""
        return any(
            self.match(text, d.text) >= threshold
            for d in self.deliveries.values()
            if d.time < seen
        )

    def accepted(self, unit: _Unit) -> tuple[str, Event] | None:
        """Returns the last version seen before an agent next rewrote it.

        An edit call's TargetContent shares its step's timestamp with the
        delivery that replaces it and is the state before it, so an
        observation at the horizon itself counts.
        """
        horizon = min(
            (
                d.time
                for d in self.deliveries.values()
                if d.time > unit.time
                and d.text != unit.text
                and self.match(d.text, unit.text) >= SAME_PARAGRAPH
            ),
            default="9999",
        )
        found = None
        for event, units in self.observed:
            if not unit.time < event.time <= horizon:
                continue
            best = max(
                units, key=lambda u: self.match(u, unit.text), default=""
            )
            if not best or self.match(best, unit.text) < SAME_PARAGRAPH:
                continue
            # Mutual best match: sibling captions that differ only in model
            # names and numbers must not stand in for one another.
            rival = self.best_delivery(best, event.time)
            if rival is None or self.match(best, rival.text) <= self.match(
                best, unit.text
            ):
                found = (best, event)
        return found

    def draft(self, unit: _Unit) -> tuple[str, Event] | None:
        """Returns the author's latest text before the delivery rewrote it."""
        found = None
        for event, units in self.observed:
            if event.time >= unit.time:
                break
            candidates = [
                u
                for u in units
                if u != unit.text and self.match(u, unit.text) >= DRAFT_MATCH
            ]
            best = max(
                candidates, key=lambda u: self.match(u, unit.text), default=""
            )
            if best and not self.is_agent_text(best, event.time, DRAFT_AGENT):
                found = (best, event)
        return found

    def _slot(self, *texts: str) -> str:
        """Guesses the slot from the newest whole file holding any text."""
        for event, _ in reversed(self.observed):
            if event.partial or "\\begin{document}" not in event.text:
                continue
            for text in texts:
                slot = _guess_slot(text, event.text)
                if slot:
                    return slot
        return ""

    def _provenance(self, accepted: str) -> str:
        """Returns ``uncertain`` if an agent may have written ``accepted``.

        That is, if the text first appeared in a commit carrying an agent's
        fingerprints; else ``clear``.
        """
        first = self.first_seen.get(accepted)
        return "uncertain" if first and first.flag == "ai-touched" else "clear"

    def record(self, paper: str, unit: _Unit) -> dict[str, Any] | None:
        """Returns the record for one delivered unit, or None if there is none.

        None when the unit was never seen again, when an agent's own text
        explains the change, or when all it gained is merged agent text.
        """
        found = self.accepted(unit)
        if found is None:
            return None
        accepted, seen = found
        score = self.match(accepted, unit.text)
        edited = score < IDENTICAL
        if edited and self.is_agent_text(accepted, seen.time, AGENT_TEXT):
            return None
        grams = {
            gram: time
            for gram, time in self.agent_grams.items()
            if time < seen.time
        }
        spans, removed, added = _agent_insertions(unit.text, accepted, grams)
        if edited and not removed + added:
            return None
        draft = self.draft(unit)
        feedback = [
            turn.text.strip()[:600]
            for turn in self.turns
            if unit.time < turn.time <= seen.time
        ][:4]
        digest = hashlib.sha1(
            "\x00".join((paper, unit.text, accepted)).encode()
        ).hexdigest()
        return {
            "id": digest[:12],
            "paper": paper,
            "kind": "edited" if edited else "kept",
            "slot": unit.slot or self._slot(accepted, unit.text),
            "agent": unit.agent,
            "profile_version": unit.profile_version,
            "delivered": unit.text,
            "delivered_at": unit.time,
            "delivered_from": unit.source,
            "accepted": accepted,
            "accepted_at": seen.time,
            "accepted_from": seen.source,
            "distance": round(1.0 - score, 4),
            "agent_spans": spans,
            "provenance": self._provenance(accepted),
            "draft": draft[0] if draft else "",
            "draft_from": draft[1].source if draft else "",
            "feedback": feedback,
        }


def build_records(paper: str, events: Sequence[Event]) -> list[dict[str, Any]]:
    """Joins a paper's events into draft -> delivered -> accepted records.

    For every delivered unit: the **accepted** version is the last observed
    version of the same paragraph before an agent next delivers a version of
    it, provided no agent delivered that exact text; the **draft** is the
    latest author text before the delivery that the delivered unit
    rewrites; the **feedback** is what the author said in between.

    Args:
        paper: The paper id, copied into every record.
        events: All events for the paper, any order.

    Returns:
        One record per delivered unit that was seen again afterwards, with
        ``kind`` ``edited`` (the author changed it) or ``kept`` (it stands
        verbatim).
    """
    joiner = _Joiner(_expand_edits(_normalize_times(events)))
    records = (joiner.record(paper, u) for u in joiner.deliveries.values())
    return [record for record in records if record is not None]


# ---------------------------------------------------------------------------
# harvest / status / packet.
# ---------------------------------------------------------------------------


def _load_records() -> dict[str, dict[str, Any]]:
    path = store_home() / "pairs.jsonl"
    records = {}
    if path.exists():
        with path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    record = json.loads(line)
                    records[record["id"]] = record
    return records


def _save_records(records: dict[str, dict[str, Any]]) -> None:
    ordered = sorted(records.values(), key=lambda r: r["delivered_at"])
    path = store_home() / "pairs.jsonl"
    with path.with_suffix(".tmp").open("w", encoding="utf-8") as f:
        for record in ordered:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    path.with_suffix(".tmp").replace(path)
    _write_readable(ordered)


def _write_readable(ordered: Sequence[dict[str, Any]]) -> None:
    lines = [
        "# co-writer pairs",
        "",
        "Generated by `cowriter.py harvest`; do not edit. "
        "`[-removed-] {+added+}` is delivered -> accepted.",
        "",
    ]
    for record in reversed(ordered):
        if record["kind"] != "edited":
            continue
        lines += [
            f"## {record['id']} · {record['paper']} · "
            f"{record['slot'] or '?'} · {record['agent'] or '?'} · "
            f"distance {record['distance']}",
            f"delivered {record['delivered_at']} ({record['delivered_from']})"
            f" · accepted {record['accepted_at']} "
            f"({record['accepted_from']})",
            "",
        ]
        if record["draft"]:
            lines += ["**Draft (author):** " + record["draft"], ""]
        diff = word_diff(record["delivered"], record["accepted"])
        for span in record.get("agent_spans", []):
            diff = diff.replace(f"{{+{span}+}}", f"{{+[agent] {span}+}}")
        lines += ["**Diff:** " + diff, ""]
        for said in record["feedback"]:
            lines.append("> " + " ".join(said.split())[:300])
        lines.append("")
    (store_home() / "pairs.md").write_text("\n".join(lines), encoding="utf-8")


def harvest_paper(
    paper: str, info: dict[str, Any], cache: dict[str, Any]
) -> list[dict[str, Any]]:
    """Collects every event for one paper and returns its records."""
    root = pathlib.Path(info["root"])
    events: list[Event] = list(events_from_logs(paper))
    for relative in info.get("files") or ["main.tex"]:
        if (root / ".git").exists():
            events.extend(events_from_git(root, relative))
        snapshot(paper, root, relative)
    events.extend(events_from_snapshots(paper))
    events.extend(events_from_claude(root, cache))
    events.extend(events_from_antigravity(root, cache))
    return build_records(paper, events)


def command_harvest(args: argparse.Namespace) -> int:
    """Implements ``cowriter.py harvest``."""
    home = store_home()
    for tex in args.add or []:
        print(f"registered {tex} as {register_paper(pathlib.Path(tex))}")
    registry = _read_json(home / "papers.json", {})
    state = _read_json(home / "state.json", {})
    cache = {} if args.rebuild else state.setdefault("cache", {})
    records = {} if args.rebuild else _load_records()
    before = set(records)
    papers = [args.paper] if args.paper else sorted(registry)
    for paper in papers:
        for record in harvest_paper(paper, registry[paper], cache):
            record["first_seen"] = records.get(record["id"], {}).get(
                "first_seen", _now()
            )
            records[record["id"]] = record
    state["cache"] = cache
    state["last_harvest"] = _now()
    _write_json(home / "state.json", state)
    _save_records(records)
    new = [records[i] for i in set(records) - before]
    edited = sum(r["kind"] == "edited" for r in new)
    print(
        f"records: {len(records)} ({len(new)} new, {edited} new edits) "
        f"-> {home / 'pairs.jsonl'}"
    )
    return 0


def _undigested(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    state = _read_json(store_home() / "state.json", {})
    seen = set(state.get("digested", []))
    return [r for r in records if r["kind"] == "edited" and r["id"] not in seen]


def _pending_proposals() -> list[pathlib.Path]:
    directory = store_home() / "proposals"
    if not directory.exists():
        return []
    return [
        path
        for path in sorted(directory.glob("*.md"))
        if "status: ruled" not in path.read_text(encoding="utf-8")
    ]


def command_status(args: argparse.Namespace) -> int:
    """Implements ``cowriter.py status``."""
    records = _load_records()
    pending = _pending_proposals()
    new = _undigested(records.values())
    if args.brief:
        if pending:
            print(
                f"co-writer: {len(pending)} digest proposal(s) await the "
                f"author's ruling: {pending[0]}"
            )
        return 0
    state = _read_json(store_home() / "state.json", {})
    print(f"store: {store_home()}")
    print(f"last harvest: {state.get('last_harvest', 'never')}")
    print(f"last packet: {state.get('last_packet', 'never')}")
    print(f"last proposal: {state.get('last_proposal', 'never')}")
    by_kind: dict[str, int] = {}
    for record in records.values():
        by_kind[record["kind"]] = by_kind.get(record["kind"], 0) + 1
    print(f"records: {by_kind}; edited and not yet digested: {len(new)}")
    by_version: dict[str, list[float]] = {}
    for record in records.values():
        version = record.get("profile_version") or "unlogged"
        by_version.setdefault(version, []).append(record["distance"])
    for version, distances in sorted(by_version.items()):
        mean = sum(distances) / len(distances)
        print(
            f"  profile {version:>9}: n={len(distances):3d}  "
            f"mean edit distance {mean:.3f}"
        )
    for path in pending:
        print(f"awaiting ruling: {path}")
    return 0


def command_packet(args: argparse.Namespace) -> int:
    """Implements ``cowriter.py packet``: the digest's reading.

    Written whenever at least one edited record is undigested; the author
    decides when to run it. The packet is a directory holding everything the
    digest reads, so the agent that runs it needs access to nothing else:
    the undigested records, the log entries with a Note or Unsure since the
    last proposal, and copies of the profile, the counterexamples and the
    digest brief. Records are marked digested only when ``file`` records the
    proposal. Exit status 0 means a packet was written (its path is
    printed), 3 means there was nothing new to digest.
    """
    del args  # Unused.
    home = store_home()
    state = _read_json(home / "state.json", {})
    new = _undigested(_load_records().values())
    last = state.get("last_proposal")
    if not new:
        print(f"nothing to digest: no new edits since {last or 'the start'}")
        return 3
    directory = home / "packets" / _now().replace(":", "")
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "pairs.jsonl").open("w", encoding="utf-8") as f:
        for record in sorted(new, key=lambda r: r["delivered_at"]):
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    (directory / "notes.md").write_text(
        "\n\n".join(_notes_since(last or "")), encoding="utf-8"
    )
    references = SKILL_DIR / "references"
    for name in ("voice-profile.md", "counterexamples.md", "digest.md"):
        (directory / name).write_text(
            (references / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    state["last_packet"] = _now()
    _write_json(home / "state.json", state)
    print(directory)
    return 0


def _notes_since(since: str) -> list[str]:
    """Returns log entries dated from ``since`` with the author's words."""
    notes = []
    for paper in _read_json(store_home() / "papers.json", {}):
        for path in sorted((paper_dir(paper) / "log").glob("*.md")):
            entry = parse_entry(path)
            if entry is None or entry.meta.get("date", "") < since:
                continue
            if entry.sections.get("Note") or entry.sections.get("Unsure"):
                notes.append(entry.render())
    return notes


def command_file(args: argparse.Namespace) -> int:
    """Implements ``cowriter.py file``: records a finished digest proposal.

    Moves ``PACKET/proposal.md`` to ``proposals/<packet name>.md`` and marks
    the packet's records digested, so the next packet starts after them.
    """
    home = store_home()
    packet = pathlib.Path(args.packet).expanduser().resolve()
    proposal = packet / "proposal.md"
    if not proposal.exists():
        raise SystemExit(f"file: no proposal.md in {packet}")
    text = proposal.read_text(encoding="utf-8")
    if "status: pending" not in text:
        raise SystemExit("file: proposal.md lacks 'status: pending' header")
    target = home / "proposals" / f"{packet.name}.md"
    target.parent.mkdir(exist_ok=True)
    proposal.replace(target)
    ids = set()
    with (packet / "pairs.jsonl").open(encoding="utf-8") as f:
        ids = {json.loads(line)["id"] for line in f if line.strip()}
    state = _read_json(home / "state.json", {})
    state["digested"] = sorted(set(state.get("digested", [])) | ids)
    state["last_proposal"] = _now()
    _write_json(home / "state.json", state)
    print(target)
    return 0


# ---------------------------------------------------------------------------
# Command line.
# ---------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = parser.add_subparsers(dest="command", required=True)

    log = commands.add_parser("log", help="record one delivered rewrite")
    log.add_argument("--file", help="the .tex the text belongs to")
    log.add_argument("--paper", help="paper id; inline mode, or override")
    log.add_argument("--agent", required=True, choices=AGENTS)
    log.add_argument("--slot", required=True, choices=SLOTS)
    log.add_argument("--register", required=True, choices=REGISTERS)
    log.add_argument("--cold-read", default="n/a", choices=("yes", "no", "n/a"))
    log.add_argument(
        "--input", required=True, help="path, '-' for stdin, or text"
    )
    log.add_argument("--output", required=True, help="path or text")
    log.add_argument("--note", help="the author's words on it, verbatim")
    log.add_argument("--unsure", help="passages the writer is least sure of")
    log.add_argument("--session-id", help="the agent's session id")
    log.add_argument("--date", help="ISO timestamp (default: now)")
    log.set_defaults(handler=command_log)

    session = commands.add_parser("session", help="close a session")
    session.add_argument("--file", required=True)
    session.add_argument("--paper")
    session.add_argument("--agent", required=True, choices=AGENTS)
    session.add_argument("--register", default="", choices=("", *REGISTERS))
    session.add_argument("--asked", required=True)
    session.add_argument("--produced", required=True)
    session.add_argument("--wrong", required=True, help="verbatim, or none")
    session.add_argument("--session-id")
    session.add_argument("--date")
    session.set_defaults(handler=command_session)

    harvest = commands.add_parser("harvest", help="rebuild the pairs")
    harvest.add_argument("--paper")
    harvest.add_argument("--rebuild", action="store_true")
    harvest.add_argument(
        "--add",
        action="append",
        metavar="TEX",
        help="register a .tex for harvesting before anything is logged",
    )
    harvest.set_defaults(handler=command_harvest)

    status = commands.add_parser("status", help="counts and pending rulings")
    status.add_argument("--brief", action="store_true")
    status.set_defaults(handler=command_status)

    packet = commands.add_parser("packet", help="write a digest packet")
    packet.set_defaults(handler=command_packet)

    filing = commands.add_parser("file", help="record a digest proposal")
    filing.add_argument("packet", help="the packet directory")
    filing.set_defaults(handler=command_file)

    migrate = commands.add_parser("migrate", help="import old .co-writer dirs")
    migrate.add_argument("dirs", nargs="+")
    migrate.add_argument("--paper")
    migrate.add_argument(
        "--delete", action="store_true", help="remove the originals"
    )
    migrate.set_defaults(handler=command_migrate)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Runs the command line."""
    args = _parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
