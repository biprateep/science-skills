#!/usr/bin/env bash
# ==============================================================================
# science-skills installer — the one script. Clone the repo, run this, done.
#
#   bash scripts/install.sh              # install / refresh everything
#   bash scripts/install.sh --uninstall  # remove what this script created
#   bash scripts/install.sh --dry-run    # show what would change, touch nothing
#   bash scripts/install.sh --skip-mcp   # skills only, no MCP toolbox
#   bash scripts/install.sh --skip-keys  # do not ask for registry API keys
#   bash scripts/install.sh --uninstall --purge-keys   # …and forget stored keys
#
# Step 1 registers every skill in skills/ with each harness found on this
# machine:
#
#   Claude Code  -> per-skill symlinks in  ~/.claude/skills/<name>
#                   (no directory-registry exists; rerun to pick up new skills)
#   Antigravity  -> per-skill symlinks in ~/.gemini/config/skills/<name>
#                   (rerun to pick up new skills)
#   OpenAI Codex -> one symlink  ~/.agents/skills/science-skills -> skills/
#                   (scanned recursively — new skills appear with no rerun)
#
# Step 2 runs every skills/*/mcp/setup_mcp.sh, which builds that skill's Python
# venv and registers its MCP server with each harness. This needs the network
# and takes a minute; --skip-mcp leaves it out. A toolbox that talks to
# registries (cite-check) asks for its API keys here — input is not echoed,
# secrets go to the OS keychain or a 0600 file, never into a harness config,
# and Enter skips a key so that source stays disabled. With no terminal the
# questions are skipped; --skip-keys skips them explicitly. Enter or change
# keys later with:  bash skills/cite-check/mcp/setup_mcp.sh --keys
#
# Step 3 checks the command-line tools the skills run: uv (code-style formats,
# lints and type-checks through it, and the toolboxes build faster with it)
# and python3. A missing one is reported with how to install it; this script
# installs neither.
#
# No skill file is copied: every harness reads the repo working tree, so a
# `git pull` publishes skill edits immediately. Unrelated links and config
# entries are left untouched.
#
# To update a machine: `git pull`, then rerun this script. It links skills
# that are new since the last run, removes links to skills renamed or deleted
# upstream, reinstalls each toolbox's requirements and repeats the tool check.
#
# Overrides: CLAUDE_CONFIG_DIR (default ~/.claude), GEMINI_CONFIG_DIR
# (default ~/.gemini/config), CODEX_HOME (default ~/.codex) and
# AGENTS_SKILLS_DIR (default ~/.agents/skills, where Codex finds user skills).
# Set any of them to a path to target a custom install.
# ==============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILLS_DIR="$REPO_ROOT/skills"

CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
AG_DIR="${GEMINI_CONFIG_DIR:-$HOME/.gemini/config}"
CODEX_DIR="${CODEX_HOME:-$HOME/.codex}"
AGENTS_DIR="${AGENTS_SKILLS_DIR:-$HOME/.agents/skills}"
CODEX_FOUND=0

MODE=install
DRY_RUN=0
SKIP_MCP=0
SKIP_KEYS=0
PURGE_KEYS=0
for arg in ${@+"$@"}; do   # ${@+...} keeps `set -u` quiet on bash 3.2 (macOS)
    case "$arg" in
        --uninstall)  MODE=uninstall ;;
        --dry-run)    DRY_RUN=1 ;;
        --skip-mcp)   SKIP_MCP=1 ;;
        --skip-keys)  SKIP_KEYS=1 ;;
        --purge-keys) PURGE_KEYS=1 ;;
        # The header runs from line 2 to the line before `set -euo pipefail`.
        -h|--help)    sed -n '2,/^set -euo pipefail$/p' "${BASH_SOURCE[0]}" \
                          | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
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

# Skill links are ownership-checked by the same transaction helper as MCPs.
CONFIG_HELPER="$REPO_ROOT/scripts/install_config.py"
LINK_FAILED=0
link_skills() {
    local target="$1"
    shift
    local options=()
    [ "$DRY_RUN" = 1 ] && options+=(--dry-run)
    if ! python3 "$CONFIG_HELPER" links --source "$SKILLS_DIR" \
            --target "$target" --mode "$MODE" \
            ${options+"${options[@]}"} "$@"; then
        LINK_FAILED=1
    fi
}

echo ""
echo "-- Claude Code"
if [ -d "$CLAUDE_DIR" ] || command -v claude >/dev/null 2>&1; then
    link_skills "$CLAUDE_DIR/skills"
else
    echo "    not found — skipped"
fi

echo ""
echo "-- Antigravity"
if [ -d "$AG_DIR" ] || [ -d "$HOME/.gemini" ] \
        || command -v antigravity >/dev/null 2>&1 \
        || command -v agy >/dev/null 2>&1; then
    link_skills "$AG_DIR/skills" --legacy-registry "$AG_DIR/skills.json"
else
    echo "    not found — skipped"
fi

echo ""
echo "-- OpenAI Codex"
if [ -d "$CODEX_DIR" ] || command -v codex >/dev/null 2>&1; then
    CODEX_FOUND=1
    link_skills "$AGENTS_DIR" --collection
else
    echo "    not found — skipped"
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
    if [ "$MODE" = uninstall ]; then hint=" --uninstall"; else hint=""; fi
    echo "    skipped (--skip-mcp); run them later with:"
    for setup in "${MCP_SCRIPTS[@]}"; do echo "      bash ${setup#$REPO_ROOT/}$hint"; done
elif [ "${#MCP_SCRIPTS[@]}" -gt 0 ]; then
    MCP_ARGS=()
    [ "$MODE" = uninstall ] && MCP_ARGS+=(--uninstall)
    [ "$DRY_RUN" = 1 ] && MCP_ARGS+=(--dry-run)
    [ "$SKIP_KEYS" = 1 ] && MCP_ARGS+=(--skip-keys)
    [ "$PURGE_KEYS" = 1 ] && MCP_ARGS+=(--purge-keys)
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
# Tools the skills run — checked, never installed
# ==============================================================================
# code-style formats, lints and type-checks through uv (uvx ruff, uv run mypy),
# and its checker needs Python 3.10+. Without them the skills still load and
# their rules still apply; only the checks cannot run. So a missing tool is
# reported, here and in the summary, and does not fail the install.
MISSING_TOOLS=()
if [ "$MODE" = install ]; then
    echo ""
    echo "-- Tools"
    if command -v uv >/dev/null 2>&1; then
        echo "    uv: $(uv --version 2>/dev/null || echo found)"
    else
        echo "    uv: NOT FOUND — code-style runs ruff and mypy through it. Install with"
        echo "        curl -LsSf https://astral.sh/uv/install.sh | sh"
        echo "      (other ways: https://docs.astral.sh/uv/getting-started/installation/)"
        MISSING_TOOLS+=(uv)
    fi
    if command -v python3 >/dev/null 2>&1; then
        py_version="$(python3 -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null || echo unknown)"
        if python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
            echo "    python3: $py_version"
        else
            echo "    python3: $py_version — older than 3.10, which code-style's checker needs"
            echo "      (inside a uv project, 'uv run' supplies its own Python)"
        fi
    else
        echo "    python3: NOT FOUND — the skills' scripts need Python 3.10+"
        MISSING_TOOLS+=(python3)
    fi
    # Codex runs shell commands in a sandbox that, by default, has no network
    # and cannot write uv's cache, so every uv call (and every registry call
    # made outside the MCP toolboxes) stops for approval. Widening the sandbox
    # is the user's decision; this only says how.
    CODEX_CFG="$CODEX_DIR/config.toml"
    if [ "$CODEX_FOUND" = 1 ] && command -v uv >/dev/null 2>&1 \
            && ! grep -qs "$(uv cache dir 2>/dev/null)" "$CODEX_CFG"; then
        echo "    codex sandbox: uv cannot write its cache there, so Codex will ask before"
        echo "      each uv command. To let uv run inside the sandbox, see README.md,"
        echo "      \"Codex sandbox\"."
    fi
fi

# ==============================================================================
echo ""
if [ "$DRY_RUN" = 1 ]; then
    echo "Dry run — nothing was changed. Rerun without --dry-run to $MODE."
elif [ "$MODE" = uninstall ]; then
    echo "Uninstalled. Restart each harness to drop the skills from its menu."
    echo "The repo itself is untouched — delete this clone by hand if you want it gone."
else
    echo "Done. Skills load at the NEXT session start of each harness."
    echo "To update this machine later:  git pull && bash scripts/install.sh"
    echo "(new skills get linked into Claude Code and Antigravity; Codex finds them automatically)."
    echo "Registry API keys (cite-check) can be entered or changed any time with:"
    echo "  bash skills/cite-check/mcp/setup_mcp.sh --keys"
fi
if [ "${#MISSING_TOOLS[@]}" -gt 0 ]; then
    echo ""
    echo "Missing tools (see '-- Tools' above): ${MISSING_TOOLS[*]}"
fi
if [ "${#MCP_FAILED[@]}" -gt 0 ]; then
    echo ""
    echo "But these MCP toolboxes did not finish:" >&2
    for f in "${MCP_FAILED[@]}"; do echo "  bash $f" >&2; done
    echo "Fix the error above and rerun that script (or this one)." >&2
    exit 1
fi

if [ "$LINK_FAILED" = 1 ]; then
    echo "Some skill links conflicted with another installation; see above." >&2
    exit 1
fi
