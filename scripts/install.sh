#!/usr/bin/env bash
# ==============================================================================
# science-skills installer — the one script. Clone the repo, run this, done.
#
#   bash scripts/install.sh              # install / refresh everything
#   bash scripts/install.sh --uninstall  # remove what this script created
#   bash scripts/install.sh --dry-run    # show what would change, touch nothing
#   bash scripts/install.sh --skip-mcp   # skills only, no MCP toolbox
#
# Step 1 registers every skill in skills/ with each harness found on this
# machine:
#
#   Claude Code  -> per-skill symlinks in  ~/.claude/skills/<name>
#                   (no directory-registry exists; rerun to pick up new skills)
#   Antigravity  -> one directory entry in ~/.gemini/config/skills.json
#                   (scans skills/ — new skills appear with no rerun)
#
# Step 2 runs every skills/*/mcp/setup_mcp.sh, which builds that skill's Python
# venv and registers its MCP server with each harness. This needs the network
# and takes a minute; --skip-mcp leaves it out.
#
# No skill file is copied: both harnesses read the repo working tree, so a
# `git pull` publishes skill edits immediately. Unrelated links and config
# entries are left untouched.
#
# Overrides: CLAUDE_CONFIG_DIR (default ~/.claude), GEMINI_CONFIG_DIR
# (default ~/.gemini/config). Set either to a path to target a custom install.
# ==============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILLS_DIR="$REPO_ROOT/skills"

CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
AG_DIR="${GEMINI_CONFIG_DIR:-$HOME/.gemini/config}"

MODE=install
DRY_RUN=0
SKIP_MCP=0
for arg in ${@+"$@"}; do   # ${@+...} keeps `set -u` quiet on bash 3.2 (macOS)
    case "$arg" in
        --uninstall) MODE=uninstall ;;
        --dry-run)   DRY_RUN=1 ;;
        --skip-mcp)  SKIP_MCP=1 ;;
        -h|--help)   sed -n '2,27p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $arg (try --help)" >&2; exit 1 ;;
    esac
done

run() {  # execute, or just narrate under --dry-run
    if [ "$DRY_RUN" = 1 ]; then echo "    [dry-run] $*"; else "$@"; fi
}
# Past tense for a real run, conditional for a dry run: "linked" vs "would link".
said() { if [ "$DRY_RUN" = 1 ]; then echo "would $2"; else echo "$1"; fi; }

# --- discover installable skills ----------------------------------------------
# A directory is a skill only if it has SKILL.md; drafts are skipped, not failed.
SKILLS=()
SKIPPED=()
for d in "$SKILLS_DIR"/*/; do
    [ -d "$d" ] || continue
    name="$(basename "$d")"
    if [ -f "$d/SKILL.md" ]; then SKILLS+=("$name"); else SKIPPED+=("$name"); fi
done

if [ "$MODE" = install ] && [ "${#SKILLS[@]}" -eq 0 ]; then
    echo "error: no skills with a SKILL.md found under $SKILLS_DIR" >&2
    exit 1
fi

echo "== science-skills $MODE =="
echo "  repo:   $REPO_ROOT"
if [ "${#SKILLS[@]}" -gt 0 ]; then echo "  skills: ${SKILLS[*]}"; fi
if [ "${#SKIPPED[@]}" -gt 0 ]; then
    echo "  skipped (no SKILL.md): ${SKIPPED[*]}"
fi

# --- helper: is $1 a symlink pointing into this repo? -------------------------
# Plain `readlink` (not -f) is used deliberately: BSD/macOS readlink has no -f.
# Our own links are always absolute, so one level of resolution is enough.
owned_by_repo() {
    [ -L "$1" ] || return 1
    case "$(readlink "$1")" in "$SKILLS_DIR"/*) return 0 ;; *) return 1 ;; esac
}

# ==============================================================================
# Claude Code — per-skill symlinks
# ==============================================================================
echo ""
echo "-- Claude Code"
if [ -d "$CLAUDE_DIR" ] || command -v claude >/dev/null 2>&1; then
    TARGET="$CLAUDE_DIR/skills"
    [ -d "$TARGET" ] || run mkdir -p "$TARGET"

    if [ "$MODE" = install ]; then
        for name in "${SKILLS[@]}"; do
            link="$TARGET/$name"
            if [ -e "$link" ] && ! [ -L "$link" ]; then
                echo "    $name: SKIPPED — a real directory already exists at $link" >&2
                continue
            fi
            if [ "$(readlink "$link" 2>/dev/null)" = "$SKILLS_DIR/$name" ]; then
                echo "    $name: already linked"
            else
                run ln -sfn "$SKILLS_DIR/$name" "$link"
                echo "    $name: $(said linked link)"
            fi
        done
    fi

    # Prune links this script owns that no longer correspond to a live skill
    # (skill renamed or deleted upstream), plus ours left dangling by a repo move.
    if [ -d "$TARGET" ]; then
        for link in "$TARGET"/*; do
            [ -L "$link" ] || continue
            name="$(basename "$link")"
            stale=0
            if [ "$MODE" = uninstall ]; then
                if owned_by_repo "$link"; then stale=1; fi
            else
                if owned_by_repo "$link"; then
                    case " ${SKILLS[*]} " in *" $name "*) ;; *) stale=1 ;; esac
                elif [ ! -e "$link" ]; then
                    # dangling: only ours if it shares a name with one of our skills
                    case " ${SKILLS[*]} " in *" $name "*) stale=1 ;; esac
                fi
            fi
            if [ "$stale" = 1 ]; then
                run rm -f "$link"
                echo "    $name: $(said removed remove)"
            fi
        done
    fi
else
    echo "    not found — skipped (no $CLAUDE_DIR, no 'claude' on PATH)"
fi

# ==============================================================================
# Antigravity — one directory entry in skills.json
# ==============================================================================
echo ""
echo "-- Antigravity"
if [ -d "$AG_DIR" ] || [ -d "$HOME/.gemini" ] || command -v antigravity >/dev/null 2>&1; then
    [ -d "$AG_DIR" ] || run mkdir -p "$AG_DIR"
    CFG="$AG_DIR/skills.json"

    # Per-skill symlinks under the global root would double-register every skill
    # now that skills.json scans the directory. Remove only links we own.
    if [ -d "$AG_DIR/skills" ]; then
        for link in "$AG_DIR/skills"/*; do
            owned_by_repo "$link" || continue
            run rm -f "$link"
            echo "    $(basename "$link"): $(said removed remove) redundant symlink (superseded by skills.json)"
        done
        # tidy up only if we emptied it; never under --dry-run
        [ "$DRY_RUN" = 1 ] || rmdir "$AG_DIR/skills" 2>/dev/null || true
    fi

    # Python owns the writing whenever it exists — it escapes the path correctly
    # and merges without disturbing neighbouring keys. The heredoc below is only
    # a fallback for a bare machine with no python3 at all.
    if [ "$DRY_RUN" = 1 ]; then
        echo "    [dry-run] would $MODE entry '$SKILLS_DIR' in $CFG"
    elif command -v python3 >/dev/null 2>&1; then
        python3 - "$CFG" "$SKILLS_DIR" "$MODE" <<'PYEOF'
import json, os, sys
cfg_path, skills_dir, mode = sys.argv[1], sys.argv[2], sys.argv[3]
if os.path.exists(cfg_path):
    try:
        with open(cfg_path) as fh:
            cfg = json.load(fh)
    except (json.JSONDecodeError, ValueError) as exc:
        sys.exit(f"    ERROR: {cfg_path} is not valid JSON ({exc}); fix or move it, then rerun")
elif mode == "install":
    cfg = {}
else:
    print(f"    nothing to remove ({cfg_path} does not exist)")
    raise SystemExit
if not isinstance(cfg, dict):
    sys.exit(f"    ERROR: {cfg_path} must contain a JSON object; leaving it alone")

entries = cfg.get("entries") or []
def same(entry):
    path = entry.get("path", "") if isinstance(entry, dict) else ""
    return os.path.normpath(os.path.expanduser(path)) == os.path.normpath(skills_dir)

if mode == "install":
    if any(same(e) for e in entries):
        print(f"    already registered in {cfg_path}")
        raise SystemExit
    entries.append({"path": skills_dir})
    verb = "registered"
else:
    kept = [e for e in entries if not same(e)]
    if len(kept) == len(entries):
        print(f"    no entry for this repo in {cfg_path}")
        raise SystemExit
    entries, verb = kept, "unregistered"

cfg["entries"] = entries
with open(cfg_path, "w") as fh:
    json.dump(cfg, fh, indent=2)
    fh.write("\n")
print(f"    {verb} {skills_dir} in {cfg_path}")
PYEOF
    elif [ "$MODE" = install ] && [ ! -f "$CFG" ]; then
        cat > "$CFG" <<EOF
{
  "entries": [
    { "path": "$SKILLS_DIR" }
  ]
}
EOF
        echo "    registered $SKILLS_DIR in $CFG"
    elif [ ! -f "$CFG" ]; then
        echo "    nothing to remove ($CFG does not exist)"
    else
        echo "    ERROR: $CFG exists and python3 is unavailable to merge it." >&2
        echo "           Add this entry by hand:  { \"path\": \"$SKILLS_DIR\" }" >&2
    fi
else
    echo "    not found — skipped (no $AG_DIR, no 'antigravity' on PATH)"
fi

# ==============================================================================
# MCP toolboxes — each skill that ships one sets it up itself
# ==============================================================================
# A skill's tools are part of the skill: installing one without the other leaves
# it half-working, so this runs by default. The sub-scripts take the same flags
# and are just as idempotent, so a rerun is cheap.
MCP_SCRIPTS=()
for name in "${SKILLS[@]}"; do
    setup="$SKILLS_DIR/$name/mcp/setup_mcp.sh"
    [ -f "$setup" ] && MCP_SCRIPTS+=("$setup")
done

MCP_FAILED=()
if [ "${#MCP_SCRIPTS[@]}" -gt 0 ] && [ "$SKIP_MCP" = 1 ]; then
    echo ""
    echo "-- MCP toolboxes"
    echo "    skipped (--skip-mcp); run them later with:"
    for setup in "${MCP_SCRIPTS[@]}"; do echo "      bash ${setup#$REPO_ROOT/}"; done
elif [ "${#MCP_SCRIPTS[@]}" -gt 0 ]; then
    MCP_ARGS=()
    [ "$MODE" = uninstall ] && MCP_ARGS+=(--uninstall)
    [ "$DRY_RUN" = 1 ] && MCP_ARGS+=(--dry-run)
    echo ""
    echo "-- MCP toolboxes"
    for setup in "${MCP_SCRIPTS[@]}"; do
        # A toolbox that fails to build (no network, no python) must not take the
        # skill links down with it — report it at the end and keep going.
        if ! bash "$setup" ${MCP_ARGS+"${MCP_ARGS[@]}"}; then
            MCP_FAILED+=("${setup#$REPO_ROOT/}")
            echo "    ^ FAILED — skills are still installed; see above" >&2
        fi
    done
fi

# ==============================================================================
echo ""
if [ "$MODE" = uninstall ]; then
    echo "Uninstalled. Restart each harness to drop the skills from its menu."
else
    echo "Done. Skills load at the NEXT session start of each harness."
    echo "New skills added to skills/ later: Antigravity picks them up automatically;"
    echo "rerun this script to link them into Claude Code."
fi
if [ "${#MCP_FAILED[@]}" -gt 0 ]; then
    echo ""
    echo "But these MCP toolboxes did not finish:" >&2
    for f in "${MCP_FAILED[@]}"; do echo "  bash $f" >&2; done
    echo "Fix the error above and rerun that script (or this one)." >&2
    exit 1
fi
