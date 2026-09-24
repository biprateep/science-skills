#!/usr/bin/env python3
"""Gather a paper's chat transcripts into <repo>/.co-writer/transcripts/.

    python collect_transcripts.py [--repo DIR] [--copy]

Transcripts are context for the digest step (SKILL.md, "Maintenance"), not
the training signal -- that is .co-writer/corrections.md. This script makes
the context findable from the paper repo instead of scattered across two
agents' home directories.

Claude Code   ~/.claude/projects/<slug>/*.jsonl, where <slug> is the repo path
              with "/" replaced by "-" (worktree slugs share the prefix). Each
              session is linked (or copied with --copy) and indexed: dates,
              branch, user turns, first prompt, how often "co-writer" occurs.
Antigravity   ~/.gemini/antigravity/brain/<conversation-id>/*.md -- the
              markdown artefacts (task.md, implementation_plan.md, ...) of
              conversations whose artefacts mention this repo's path. The
              conversations themselves live in ~/.gemini/antigravity/
              conversations/ in a binary format and are not parsed; the
              session note co-writer writes to .co-writer/log/ is the
              readable record for Antigravity sessions.

Writes .co-writer/transcripts/index.md. Idempotent. Standard library only.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import datetime
import json
import pathlib
import re
import shutil
import sys
from typing import Any

CLAUDE_DIR = pathlib.Path.home() / ".claude" / "projects"
ANTIGRAVITY_BRAIN = pathlib.Path.home() / ".gemini" / "antigravity" / "brain"
OUT = ".co-writer/transcripts"


def slug_for(repo: pathlib.Path) -> str:
    """Returns the name Claude Code gives the project directory of repo."""
    return "-" + str(repo).strip("/").replace("/", "-")


def first_text(content: object) -> str:
    """Returns the text of a message's content, or its first text block."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                return block.get("text", "")
    return ""


def index_claude_session(path: pathlib.Path) -> dict[str, Any]:
    """Summarizes one Claude Code session transcript.

    Args:
      path: The session's .jsonl file.

    Returns:
      Its id, first and last timestamps, git branch, number of user turns,
      first prompt, mentions of "co-writer" and size in bytes.
    """
    info: dict[str, Any] = {
        "id": path.stem,
        "first": None,
        "last": None,
        "branch": None,
        "user_turns": 0,
        "first_prompt": "",
        "cowriter_mentions": 0,
        "bytes": path.stat().st_size,
    }
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            info["cowriter_mentions"] += line.count("co-writer")
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            timestamp = record.get("timestamp")
            if timestamp:
                info["first"] = info["first"] or timestamp
                info["last"] = timestamp
            if record.get("type") == "user":
                info["branch"] = info["branch"] or record.get("gitBranch")
                text = first_text(record.get("message", {}).get("content"))
                # Skip tool results and system-shaped turns.
                if text and not text.startswith("<"):
                    info["user_turns"] += 1
                    if not info["first_prompt"]:
                        info["first_prompt"] = re.sub(r"\s+", " ", text)[:120]
    return info


def link_or_copy(src: pathlib.Path, dst: pathlib.Path, copy: bool) -> None:
    """Links dst to src, or copies src to dst, replacing what is there.

    Args:
      src: The file to link to or copy.
      dst: Where the link or copy goes.
      copy: Whether to copy; a copy that is not older than src is kept.
    """
    if dst.exists() or dst.is_symlink():
        if copy and dst.stat().st_mtime >= src.stat().st_mtime:
            return
        dst.unlink()
    if copy:
        shutil.copy2(src, dst)
    else:
        dst.symlink_to(src)


def collect_claude(
    repo: pathlib.Path, out: pathlib.Path, copy: bool
) -> list[dict[str, Any]]:
    """Links or copies the repo's Claude Code sessions into out/claude.

    Args:
      repo: The paper's repository.
      out: The transcripts directory.
      copy: Whether to copy the sessions instead of linking them.

    Returns:
      One index_claude_session() row per session, oldest first, each marked
      with whether it came from a worktree or subdirectory.
    """
    slug = slug_for(repo)
    folders = []
    if CLAUDE_DIR.exists():
        folders = [
            folder for folder in CLAUDE_DIR.glob(f"{slug}*") if folder.is_dir()
        ]
    dest = out / "claude"
    dest.mkdir(parents=True, exist_ok=True)
    rows = []
    for folder in sorted(folders):
        for session in sorted(folder.glob("*.jsonl")):
            link_or_copy(session, dest / session.name, copy)
            info = index_claude_session(session)
            info["worktree"] = folder.name != slug
            rows.append(info)
    rows.sort(key=lambda row: row["first"] or "")
    return rows


def collect_antigravity(
    repo: pathlib.Path, out: pathlib.Path, copy: bool
) -> list[dict[str, str]]:
    """Links or copies the Antigravity artefacts that mention the repo.

    Args:
      repo: The paper's repository.
      out: The transcripts directory; conversations go to out/antigravity.
      copy: Whether to copy the conversations instead of linking them.

    Returns:
      One row per conversation, oldest first: its id, when its artefacts
      last changed, their names, and the first line of its task.md.
    """
    if not ANTIGRAVITY_BRAIN.exists():
        return []
    needle = str(repo)
    dest = out / "antigravity"
    dest.mkdir(parents=True, exist_ok=True)
    rows = []
    for conversation in sorted(ANTIGRAVITY_BRAIN.iterdir()):
        if not conversation.is_dir():
            continue
        markdown_files = list(conversation.glob("*.md"))
        mentioning = [
            path
            for path in markdown_files
            if needle in path.read_text(encoding="utf-8", errors="replace")
        ]
        if not mentioning:
            continue
        _place_conversation(conversation, dest / conversation.name, copy)
        newest = max(path.stat().st_mtime for path in markdown_files)
        modified = datetime.datetime.fromtimestamp(newest)
        rows.append(
            {
                "id": conversation.name,
                "modified": modified.isoformat(timespec="minutes"),
                "artefacts": ", ".join(
                    sorted(path.name for path in markdown_files)
                ),
                "task": _first_task_line(conversation / "task.md"),
            }
        )
    rows.sort(key=lambda row: row["modified"])
    return rows


def _place_conversation(
    conversation: pathlib.Path, target: pathlib.Path, copy: bool
) -> None:
    """Links target to a conversation folder, or copies its artefacts there."""
    if copy:
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(
            conversation,
            target,
            ignore=shutil.ignore_patterns("*.resolved*", "*.metadata.json"),
        )
    else:
        if target.exists() or target.is_symlink():
            target.unlink()
        target.symlink_to(conversation)


def _first_task_line(task: pathlib.Path) -> str:
    """Returns the first non-blank line of task.md, or "" if there is none."""
    if task.exists():
        text = task.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            if line.strip():
                return line.strip()[:120]
    return ""


def _claude_row(row: dict[str, Any]) -> str:
    """Formats one Claude Code session as a table row of the index."""
    worktree = " (subdir or worktree)" if row.get("worktree") else ""
    first = (row["first"] or "")[:16]
    last = (row["last"] or "")[:16]
    prompt = row["first_prompt"].replace("|", "/")
    return (
        f"| `{row['id']}`{worktree} | {first} | {last} | {row['branch'] or ''}"
        f" | {row['user_turns']} | {row['cowriter_mentions']} | {prompt} |"
    )


def write_index(
    out: pathlib.Path,
    repo: pathlib.Path,
    claude_rows: Sequence[dict[str, Any]],
    antigravity_rows: Sequence[dict[str, str]],
) -> None:
    """Writes out/index.md, the table of every session found.

    Args:
      out: The transcripts directory.
      repo: The paper's repository.
      claude_rows: The rows collect_claude() returned.
      antigravity_rows: The rows collect_antigravity() returned.
    """
    collected = datetime.datetime.now().isoformat(timespec="minutes")
    lines = [
        f"# Transcripts for {repo}",
        "",
        f"Collected {collected} by scripts/collect_transcripts.py.",
        "",
    ]
    lines += _claude_section(claude_rows)
    lines += _antigravity_section(antigravity_rows)
    lines += [
        "",
        "Full Antigravity conversations are binary under"
        " ~/.gemini/antigravity/conversations/ and are not parsed.",
        "",
    ]
    (out / "index.md").write_text("\n".join(lines), encoding="utf-8")


def _claude_section(rows: Sequence[dict[str, Any]]) -> list[str]:
    """Returns the lines of the index's Claude Code table."""
    lines = [
        "## Claude Code",
        "",
        "| session | first | last | branch | user turns | co-writer mentions"
        " | first prompt |",
        "|---|---|---|---|---|---|---|",
    ]
    lines += [_claude_row(row) for row in rows]
    if not rows:
        lines.append(
            "| — | | | | | | no sessions found under ~/.claude/projects for"
            " this path |"
        )
    return lines


def _antigravity_section(rows: Sequence[dict[str, str]]) -> list[str]:
    """Returns the lines of the index's Antigravity table."""
    lines = [
        "",
        "## Antigravity (brain artefacts mentioning this repo)",
        "",
        "| conversation | modified | artefacts | task |",
        "|---|---|---|---|",
    ]
    for row in rows:
        task = row["task"].replace("|", "/")
        lines.append(
            f"| `{row['id']}` | {row['modified']} | {row['artefacts']}"
            f" | {task} |"
        )
    if not rows:
        lines.append(
            "| — | | | none found; Antigravity sessions are recorded by the"
            " session note in .co-writer/log/ |"
        )
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    """Collects and indexes the transcripts of a paper repository.

    Args:
      argv: The arguments after the program name; None reads sys.argv.

    Returns:
      The exit status, 0.
    """
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--repo", help="repo root (default: cwd)")
    parser.add_argument(
        "--copy", action="store_true", help="copy files instead of symlinking"
    )
    args = parser.parse_args(argv)

    if args.repo:
        repo = pathlib.Path(args.repo).expanduser().resolve()
    else:
        repo = pathlib.Path.cwd().resolve()
    out = repo / OUT
    out.mkdir(parents=True, exist_ok=True)

    claude_rows = collect_claude(repo, out, args.copy)
    antigravity_rows = collect_antigravity(repo, out, args.copy)
    write_index(out, repo, claude_rows, antigravity_rows)

    print(
        f"claude sessions: {len(claude_rows)}   antigravity conversations:"
        f" {len(antigravity_rows)}"
    )
    print(f"index: {out / 'index.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
