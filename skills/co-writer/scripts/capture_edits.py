#!/usr/bin/env python3
"""Turn co-writer's session log plus the author's edits into a corrections file.

    python capture_edits.py [--repo DIR] [--threshold 0.5] [--recompute]

co-writer appends one entry per rewrite to <repo>/.co-writer/log/*.md (the
format is specified in SKILL.md, "Session log"). Each entry records what was
*delivered*. The paper's .tex file, as the author later committed it, records
what was *accepted*. This script joins the two:

  for every logged output paragraph, find the paragraph in the target file
  that best matches it, and write the word-level diff delivered -> accepted
  together with a normalized edit distance to <repo>/.co-writer/corrections.md.

corrections.md is the training signal for the voice profile: recurring edits
become Never entries, regraded rules, or new specimens (SKILL.md,
"Maintenance"). The summary printed at the end shows mean distance per slot
and per profile version -- a later profile version is better if and only if
the author edits less.

Idempotent: entries already present in corrections.md are skipped unless
--recompute is given. Standard library only.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

LOG_DIR = ".co-writer/log"
OUT_FILE = ".co-writer/corrections.md"
WORD_RE = re.compile(r"\S+")


# ---------------------------------------------------------------------------
# log parsing
# ---------------------------------------------------------------------------

def find_repo(start: Path) -> Path | None:
    for p in [start, *start.parents]:
        if (p / ".co-writer").is_dir():
            return p
    return None


def parse_entry(path: Path) -> dict | None:
    text = path.read_text(encoding="utf-8", errors="replace")
    m = re.match(r"---\s*\n(.*?)\n---\s*\n", text, flags=re.DOTALL)
    if not m:
        return None
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    body = text[m.end():]
    sections = {}
    for name, content in re.findall(r"^##\s+(\w+)\s*\n(.*?)(?=^##\s+\w+\s*$|\Z)", body, flags=re.DOTALL | re.M):
        sections[name.lower()] = content.strip()
    meta.setdefault("id", path.stem)
    meta["_path"] = path
    meta["input"] = sections.get("input", "")
    meta["output"] = sections.get("output", "")
    meta["note"] = sections.get("note", "")
    return meta


def paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def words(text: str) -> list[str]:
    return WORD_RE.findall(text)


# ---------------------------------------------------------------------------
# matching and diffing
# ---------------------------------------------------------------------------

def edit_distance(a: list[str], b: list[str]) -> float:
    """Normalized word-level edit distance from SequenceMatcher opcodes."""
    if not a and not b:
        return 0.0
    sm = SequenceMatcher(None, a, b, autojunk=False)
    edits = sum(max(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal")
    return round(edits / max(len(a), len(b)), 3)


def word_diff(a: list[str], b: list[str]) -> str:
    """Inline diff in wdiff style: [-deleted-] {+inserted+}."""
    sm = SequenceMatcher(None, a, b, autojunk=False)
    out = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            out.append(" ".join(a[i1:i2]))
        elif tag == "delete":
            out.append("[-" + " ".join(a[i1:i2]) + "-]")
        elif tag == "insert":
            out.append("{+" + " ".join(b[j1:j2]) + "+}")
        else:
            out.append("[-" + " ".join(a[i1:i2]) + "-] {+" + " ".join(b[j1:j2]) + "+}")
    return " ".join(out)


def best_match(target: list[str], candidates: list[list[str]]) -> tuple[int, float]:
    best_i, best_r = -1, 0.0
    for i, cand in enumerate(candidates):
        sm = SequenceMatcher(None, target, cand, autojunk=False)
        if sm.real_quick_ratio() < best_r or sm.quick_ratio() < best_r:
            continue
        r = sm.ratio()
        if r > best_r:
            best_i, best_r = i, r
    return best_i, best_r


def capture(entry: dict, repo: Path, threshold: float) -> dict:
    rel = entry.get("file")
    result = {"id": entry["id"], "meta": entry, "paragraphs": [], "status": "ok"}
    if not rel:
        result["status"] = "no file: field -- nothing to compare against"
        return result
    target = repo / rel
    if not target.exists():
        result["status"] = f"file not found: {rel}"
        return result
    file_paras = [words(p) for p in paragraphs(target.read_text(encoding="utf-8", errors="replace"))]
    for out_para in paragraphs(entry["output"]):
        a = words(out_para)
        i, ratio = best_match(a, file_paras)
        if i == -1 or ratio < threshold:
            result["paragraphs"].append({"delivered": a, "accepted": None, "distance": 1.0, "ratio": ratio})
        else:
            b = file_paras[i]
            result["paragraphs"].append({"delivered": a, "accepted": b, "distance": edit_distance(a, b), "ratio": ratio})
    return result


# ---------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------

def render(result: dict) -> str:
    m = result["meta"]
    head = f"## {result['id']} · {m.get('slot', '?')} · {m.get('register', '?')} · profile {m.get('profile_version', '?')} · {m.get('agent', '?')}"
    lines = [head, f"file: {m.get('file', '-')} · date: {m.get('date', '-')}"]
    if result["status"] != "ok":
        lines.append(f"status: {result['status']}")
        return "\n".join(lines) + "\n"
    paras = result["paragraphs"]
    matched = sum(1 for p in paras if p["accepted"] is not None)
    mean = round(sum(p["distance"] for p in paras) / len(paras), 3) if paras else None
    lines.append(f"paragraphs matched: {matched}/{len(paras)} · mean distance: {mean}")
    if m.get("note"):
        lines.append(f"note: {m['note']}")
    for n, p in enumerate(paras, 1):
        if p["accepted"] is None:
            lines.append(f"\n### ¶{n} — not found in file (best ratio {p['ratio']:.2f}); replaced or removed, distance 1.0")
            lines.append("delivered: " + " ".join(p["delivered"]))
        elif p["distance"] == 0.0:
            lines.append(f"\n### ¶{n} — accepted verbatim")
        else:
            lines.append(f"\n### ¶{n} — distance {p['distance']}")
            lines.append(word_diff(p["delivered"], p["accepted"]))
    return "\n".join(lines) + "\n"


def recurring_tokens(results: list[dict], k: int = 12) -> tuple[list, list]:
    """Most frequently deleted / inserted words across all captured edits."""
    removed, added = Counter(), Counter()
    for r in results:
        for p in r["paragraphs"]:
            if p["accepted"] is None:
                continue
            sm = SequenceMatcher(None, p["delivered"], p["accepted"], autojunk=False)
            for tag, i1, i2, j1, j2 in sm.get_opcodes():
                if tag in ("delete", "replace"):
                    removed.update(w.strip(".,;:()").lower() for w in p["delivered"][i1:i2])
                if tag in ("insert", "replace"):
                    added.update(w.strip(".,;:()").lower() for w in p["accepted"][j1:j2])
    return removed.most_common(k), added.most_common(k)


def summary(results: list[dict]) -> str:
    by_slot, by_ver = defaultdict(list), defaultdict(list)
    for r in results:
        if r["status"] != "ok" or not r["paragraphs"]:
            continue
        d = sum(p["distance"] for p in r["paragraphs"]) / len(r["paragraphs"])
        by_slot[r["meta"].get("slot", "?")].append(d)
        by_ver[r["meta"].get("profile_version", "?")].append(d)
    out = ["\nmean edit distance (0 = accepted verbatim, 1 = replaced)"]
    out.append("  by profile version:")
    for v in sorted(by_ver):
        ds = by_ver[v]
        out.append(f"    {v:<10} n={len(ds):<3} mean={sum(ds)/len(ds):.3f}")
    out.append("  by slot:")
    for s in sorted(by_slot):
        ds = by_slot[s]
        out.append(f"    {s:<14} n={len(ds):<3} mean={sum(ds)/len(ds):.3f}")
    rem, add = recurring_tokens(results)
    if rem:
        out.append("  most often removed: " + ", ".join(f"{w}({c})" for w, c in rem))
    if add:
        out.append("  most often added:   " + ", ".join(f"{w}({c})" for w, c in add))
    return "\n".join(out)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", help="repo root (default: nearest ancestor of cwd containing .co-writer/)")
    ap.add_argument("--threshold", type=float, default=0.5, help="min match ratio to pair a delivered paragraph with one in the file")
    ap.add_argument("--recompute", action="store_true", help="rebuild corrections.md from scratch")
    args = ap.parse_args(argv)

    repo = Path(args.repo).expanduser().resolve() if args.repo else find_repo(Path.cwd().resolve())
    if repo is None or not (repo / LOG_DIR).is_dir():
        print("no .co-writer/log/ found; nothing to capture", file=sys.stderr)
        return 2

    entries = [e for e in (parse_entry(p) for p in sorted((repo / LOG_DIR).glob("*.md"))) if e]
    out_path = repo / OUT_FILE
    existing = out_path.read_text(encoding="utf-8") if out_path.exists() and not args.recompute else ""
    done = set(re.findall(r"^## (\S+) ·", existing, flags=re.M))

    results = [capture(e, repo, args.threshold) for e in entries]
    new = [r for r in results if r["id"] not in done]

    header = "# co-writer corrections\n\nGenerated by scripts/capture_edits.py. delivered -> accepted, word-level: [-removed-] {+added+}.\n\n"
    text = existing if existing else header
    text += "".join(render(r) + "\n" for r in new)
    out_path.write_text(text, encoding="utf-8")

    print(f"{len(entries)} log entries, {len(new)} new, written to {out_path.relative_to(repo)}")
    for r in new:
        if r["status"] != "ok":
            print(f"  {r['id']}: {r['status']}")
    print(summary(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
