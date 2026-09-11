#!/usr/bin/env python3
"""Gather the chat transcripts behind a paper into <repo>/.co-writer/transcripts/.

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
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude" / "projects"
AG_BRAIN = Path.home() / ".gemini" / "antigravity" / "brain"
OUT = ".co-writer/transcripts"


def slug_for(repo: Path) -> str:
    return "-" + str(repo).strip("/").replace("/", "-")


def first_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                return block.get("text", "")
    return ""


def index_claude_session(path: Path) -> dict:
    info = {"id": path.stem, "first": None, "last": None, "branch": None, "user_turns": 0,
            "first_prompt": "", "cowriter_mentions": 0, "bytes": path.stat().st_size}
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            info["cowriter_mentions"] += line.count("co-writer")
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = d.get("timestamp")
            if ts:
                info["first"] = info["first"] or ts
                info["last"] = ts
            if d.get("type") == "user":
                info["branch"] = info["branch"] or d.get("gitBranch")
                text = first_text(d.get("message", {}).get("content"))
                if text and not text.startswith("<"):  # skip tool results / system-shaped turns
                    info["user_turns"] += 1
                    if not info["first_prompt"]:
                        info["first_prompt"] = re.sub(r"\s+", " ", text)[:120]
    return info


def link_or_copy(src: Path, dst: Path, copy: bool) -> None:
    if dst.exists() or dst.is_symlink():
        if copy and dst.stat().st_mtime >= src.stat().st_mtime:
            return
        dst.unlink()
    if copy:
        shutil.copy2(src, dst)
    else:
        dst.symlink_to(src)


def collect_claude(repo: Path, out: Path, copy: bool) -> list[dict]:
    slug = slug_for(repo)
    dirs = [d for d in CLAUDE_DIR.glob(slug + "*") if d.is_dir()] if CLAUDE_DIR.exists() else []
    dest = out / "claude"
    dest.mkdir(parents=True, exist_ok=True)
    rows = []
    for d in sorted(dirs):
        for f in sorted(d.glob("*.jsonl")):
            link_or_copy(f, dest / f.name, copy)
            info = index_claude_session(f)
            info["worktree"] = d.name != slug
            rows.append(info)
    rows.sort(key=lambda r: r["first"] or "")
    return rows


def collect_antigravity(repo: Path, out: Path, copy: bool) -> list[dict]:
    if not AG_BRAIN.exists():
        return []
    needle = str(repo)
    dest = out / "antigravity"
    dest.mkdir(parents=True, exist_ok=True)
    rows = []
    for conv in sorted(AG_BRAIN.iterdir()):
        if not conv.is_dir():
            continue
        mds = [p for p in conv.glob("*.md")]
        hit = [p for p in mds if needle in p.read_text(encoding="utf-8", errors="replace")]
        if not hit:
            continue
        target = dest / conv.name
        if copy:
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(conv, target, ignore=shutil.ignore_patterns("*.resolved*", "*.metadata.json"))
        else:
            if target.exists() or target.is_symlink():
                target.unlink()
            target.symlink_to(conv)
        task = conv / "task.md"
        first_line = ""
        if task.exists():
            for line in task.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.strip():
                    first_line = line.strip()[:120]
                    break
        mtime = datetime.fromtimestamp(max(p.stat().st_mtime for p in mds)).isoformat(timespec="minutes")
        rows.append({"id": conv.name, "modified": mtime, "artefacts": ", ".join(sorted(p.name for p in mds)),
                     "task": first_line})
    rows.sort(key=lambda r: r["modified"])
    return rows


def write_index(out: Path, repo: Path, claude_rows: list[dict], ag_rows: list[dict]) -> None:
    lines = [f"# Transcripts for {repo}", "",
             f"Collected {datetime.now().isoformat(timespec='minutes')} by scripts/collect_transcripts.py.", ""]
    lines += ["## Claude Code", "",
              "| session | first | last | branch | user turns | co-writer mentions | first prompt |",
              "|---|---|---|---|---|---|---|"]
    for r in claude_rows:
        wt = " (subdir or worktree)" if r.get("worktree") else ""
        lines.append(f"| `{r['id']}`{wt} | {(r['first'] or '')[:16]} | {(r['last'] or '')[:16]} | {r['branch'] or ''} | "
                     f"{r['user_turns']} | {r['cowriter_mentions']} | {r['first_prompt'].replace('|', '/')} |")
    if not claude_rows:
        lines.append("| — | | | | | | no sessions found under ~/.claude/projects for this path |")
    lines += ["", "## Antigravity (brain artefacts mentioning this repo)", "",
              "| conversation | modified | artefacts | task |", "|---|---|---|---|"]
    for r in ag_rows:
        lines.append(f"| `{r['id']}` | {r['modified']} | {r['artefacts']} | {r['task'].replace('|', '/')} |")
    if not ag_rows:
        lines.append("| — | | | none found; Antigravity sessions are recorded by the session note in .co-writer/log/ |")
    lines += ["", "Full Antigravity conversations are binary under ~/.gemini/antigravity/conversations/ and are not parsed.", ""]
    (out / "index.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", help="repo root (default: cwd)")
    ap.add_argument("--copy", action="store_true", help="copy files instead of symlinking")
    args = ap.parse_args(argv)

    repo = Path(args.repo).expanduser().resolve() if args.repo else Path.cwd().resolve()
    out = repo / OUT
    out.mkdir(parents=True, exist_ok=True)

    claude_rows = collect_claude(repo, out, args.copy)
    ag_rows = collect_antigravity(repo, out, args.copy)
    write_index(out, repo, claude_rows, ag_rows)

    print(f"claude sessions: {len(claude_rows)}   antigravity conversations: {len(ag_rows)}")
    print(f"index: {out / 'index.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
