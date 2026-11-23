#!/usr/bin/env bash
# ==============================================================================
# science-skills installer — the one script. Clone the repo, run this, done.
#
#   bash scripts/install.sh              # install / refresh everything
#   bash scripts/install.sh --skill cite-check  # one skill and its MCP
#   bash scripts/install.sh --skill cite-check --skill co-writer  # selected skills
#   bash scripts/install.sh --voice-profile /path/or/git-url [--voice-branch BR]
#                                        # link or clone a private co-writer voice repo
#   bash scripts/install.sh --uninstall --skill cite-check  # remove one skill
#   bash scripts/install.sh --uninstall  # remove what this script created
#   bash scripts/install.sh --dry-run    # show what would change, touch nothing
#   bash scripts/install.sh --skip-mcp   # skills only, no MCP toolbox
#   bash scripts/install.sh --skip-keys  # do not ask for registry API keys
#   bash scripts/install.sh --uninstall --purge-keys   # …and forget stored keys
#
# Step 1 registers every skill in skills/ with each harness found on this
# machine. With --skill, only the named skills are changed; dependencies
# referenced by their instructions are not installed automatically.
#
# A selective Codex operation converts an owned collection link into individual
# skill links while preserving already installed siblings. A default all-skill
# install restores recursive collection discovery.
#
# Targets:
#
#   Claude Code  -> per-skill symlinks in  ~/.claude/skills/<name>
#                   (no directory-registry exists; rerun to pick up new skills)
#   Antigravity  -> per-skill symlinks in ~/.gemini/config/skills/<name>
#                   (rerun to pick up new skills)
#   OpenAI Codex -> one symlink  ~/.agents/skills/science-skills -> skills/
#                   (scanned recursively — new skills appear with no rerun)
#
# Step 2 runs the selected skills' mcp/setup_mcp.sh scripts (all by default),
# which build each skill's Python
# venv and registers its MCP server with each harness. This needs the network
# and takes a minute; --skip-mcp leaves it out. A toolbox that talks to
# registries (cite-check) asks for its API keys here — input is not echoed,
# secrets go to the OS keychain or a 0600 file, never into a harness config,
# and Enter skips a key so that source stays disabled. With no terminal the
# questions are skipped; --skip-keys skips them explicitly. Enter or change
# keys later with:  bash skills/cite-check/mcp/setup_mcp.sh --keys
#
# Step 3 configures co-writer's private voice profile (when co-writer is
# installed): links a local voice repo or clones a private git repo into
# ~/.co-writer/profile/ (with --voice-profile / --voice-branch or an
# interactive prompt), or initializes a clean v0.0.0 starter profile that
# grows from edits. Existing profiles are left untouched on refresh/uninstall.
#
# Step 4 checks the command-line tools the skills run: uv (code-style formats,
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
# (default ~/.gemini/config), CODEX_HOME (default ~/.codex),
# AGENTS_SKILLS_DIR (default ~/.agents/skills, where Codex finds user skills),
# CO_WRITER_HOME (default ~/.co-writer) and CO_WRITER_PROFILE_DIR.
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
VOICE_PROFILE=""
VOICE_BRANCH=""
SELECTED_SKILLS=()
while [ "$#" -gt 0 ]; do
    arg="$1"
    shift
    case "$arg" in
        --uninstall)  MODE=uninstall ;;
        --dry-run)    DRY_RUN=1 ;;
        --skip-mcp)   SKIP_MCP=1 ;;
        --skip-keys)  SKIP_KEYS=1 ;;
        --purge-keys) PURGE_KEYS=1 ;;
        --voice-profile)
            if [ "$#" -eq 0 ] || [ -z "$1" ] || [[ "$1" == --* ]]; then
                echo "--voice-profile requires a local directory or git URL" >&2
                exit 1
            fi
            VOICE_PROFILE="$1"
            shift ;;
        --voice-profile=*)
            VOICE_PROFILE="${arg#--voice-profile=}"
            if [ -z "$VOICE_PROFILE" ]; then
                echo "--voice-profile requires a local directory or git URL" >&2
                exit 1
            fi ;;
        --voice-branch)
            if [ "$#" -eq 0 ] || [ -z "$1" ] || [[ "$1" == --* ]]; then
                echo "--voice-branch requires a branch name" >&2
                exit 1
            fi
            VOICE_BRANCH="$1"
            shift ;;
        --voice-branch=*)
            VOICE_BRANCH="${arg#--voice-branch=}"
            if [ -z "$VOICE_BRANCH" ]; then
                echo "--voice-branch requires a branch name" >&2
                exit 1
            fi ;;
        --skill)
            if [ "$#" -eq 0 ] || [ -z "$1" ] || [[ "$1" == --* ]]; then
                echo "--skill requires a skill name" >&2
                exit 1
            fi
            SELECTED_SKILLS+=("$1")
            shift ;;
        --skill=*)
            if [ -z "${arg#--skill=}" ]; then
                echo "--skill requires a skill name" >&2
                exit 1
            fi
            SELECTED_SKILLS+=("${arg#--skill=}") ;;
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

if [ "${#SELECTED_SKILLS[@]}" -gt 0 ]; then
    validated=()
    for selected in "${SELECTED_SKILLS[@]}"; do
        found=0
        for name in "${SKILLS[@]}"; do
            [ "$selected" = "$name" ] && found=1
        done
        if [ "$found" = 0 ]; then
            echo "unknown skill: $selected (available: ${SKILLS[*]})" >&2
            exit 1
        fi
        duplicate=0
        for name in ${validated+"${validated[@]}"}; do
            [ "$selected" = "$name" ] && duplicate=1
        done
        [ "$duplicate" = 1 ] || validated+=("$selected")
    done
    SELECTED_SKILLS=("${validated[@]}")
    SKILLS=("${validated[@]}")
fi

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
    for selected in ${SELECTED_SKILLS+"${SELECTED_SKILLS[@]}"}; do
        options+=(--skill "$selected")
    done
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
# Co-Writer voice profile — lives outside science-skills in ~/.co-writer/profile
# ==============================================================================
COWRITER_SELECTED=0
for name in "${SKILLS[@]}"; do
    [ "$name" = "co-writer" ] && COWRITER_SELECTED=1
done
COWRITER_SCRIPT="$SKILLS_DIR/co-writer/scripts/cowriter.py"
VOICE_FAILED=0

is_git_url() {
    case "$1" in
        git@*:*|http://*|https://*|ssh://*|git://*|file://*|*.git) return 0 ;;
        *) return 1 ;;
    esac
}

expand_tilde() {
    case "$1" in
        "~")   printf '%s' "$HOME" ;;
        "~/"*) printf '%s/%s' "$HOME" "${1#~/}" ;;
        *)     printf '%s' "$1" ;;
    esac
}

ask_tty() {
    if { : </dev/tty; } 2>/dev/null; then read "$@" </dev/tty; else read "$@"; fi
}

configure_voice_profile() {
    local store="${CO_WRITER_HOME:-$HOME/.co-writer}"
    local target="${CO_WRITER_PROFILE_DIR:-$store/profile}"
    local source="$VOICE_PROFILE"
    local branch="$VOICE_BRANCH"

    echo ""
    echo "-- Co-Writer voice profile"
    if [ "$MODE" = uninstall ]; then
        echo "    kept at $target (personal voice data is never deleted on uninstall)"
        return
    fi

    if [ -z "$source" ] && [ -f "$target/voice-profile.md" ]; then
        if [ -L "$target" ]; then
            echo "    configured: $target -> $(readlink "$target")"
        else
            echo "    configured: $target"
        fi
        python3 "$COWRITER_SCRIPT" profile | grep -E '^(version|voice-profile):' | sed 's/^/    /' || true
        echo "    (to switch repos: bash scripts/install.sh --voice-profile <dir|git-url>)"
        return
    fi

    if [ "$DRY_RUN" = 1 ]; then
        if [ -n "$source" ]; then
            if is_git_url "$source"; then
                echo "    [dry-run] would clone $source${branch:+ (branch $branch)} to $target"
            else
                echo "    [dry-run] would link $target -> $(expand_tilde "$source")"
            fi
        else
            echo "    [dry-run] would initialize starter voice profile (v0.0.0) at $target"
            echo "    [dry-run] (or prompt interactively for a local path / private git repo URL)"
        fi
        return
    fi

    if [ -z "$source" ] && [ -t 0 ]; then
        echo "    Personal voice profiles live outside this repo at: $target"
        echo "    Press Enter to start with a blank v0.0.0 starter profile (learns from your edits),"
        printf '    or enter a local path / private git repo URL: '
        ask_tty -r source || source=""
        if [ -n "$source" ] && is_git_url "$source" && [ -z "$branch" ]; then
            printf '    branch (Enter for repo default): '
            ask_tty -r branch || branch=""
        fi
    fi

    if [ -z "$source" ]; then
        if python3 "$COWRITER_SCRIPT" init | sed 's/^/    /'; then
            echo "    location: $target"
            echo "    Connect a private voice repo later with:"
            echo "      bash scripts/install.sh --voice-profile <path-or-git-url>"
            echo "    or: python3 $COWRITER_SCRIPT init --link <local-voice-repo>"
        else
            VOICE_FAILED=1
        fi
        return
    fi

    if is_git_url "$source"; then
        if [ -e "$target" ] || [ -L "$target" ]; then
            echo "    error: $target already exists; move or remove it before cloning $source" >&2
            VOICE_FAILED=1
            return
        fi
        mkdir -p "$(dirname "$target")"
        local clone_args=(clone)
        [ -n "$branch" ] && clone_args+=(--branch "$branch")
        clone_args+=("$source" "$target")
        if git "${clone_args[@]}"; then
            echo "    cloned: $source -> $target"
            python3 "$COWRITER_SCRIPT" profile | grep -E '^(version|voice-profile):' | sed 's/^/    /' || true
        else
            VOICE_FAILED=1
        fi
    else
        source="$(expand_tilde "$source")"
        if [ -n "${CO_WRITER_PROFILE_DIR:-}" ]; then
            echo "    CO_WRITER_PROFILE_DIR is set to $CO_WRITER_PROFILE_DIR; linking default $store/profile"
        fi
        if python3 "$COWRITER_SCRIPT" init --link "$source" | sed 's/^/    /'; then
            python3 "$COWRITER_SCRIPT" profile | grep -E '^(version|voice-profile):' | sed 's/^/    /' || true
        else
            VOICE_FAILED=1
        fi
    fi
}

if [ "$COWRITER_SELECTED" = 1 ] && [ -f "$COWRITER_SCRIPT" ]; then
    configure_voice_profile
elif [ -n "$VOICE_PROFILE" ] && [ "$MODE" = install ]; then
    echo ""
    echo "-- Co-Writer voice profile"
    echo "    skipped: co-writer is not among the selected skills (${SKILLS[*]})"
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
    if [ "${#SELECTED_SKILLS[@]}" -gt 0 ]; then
        printf 'To refresh this selection: git pull && bash scripts/install.sh'
        for selected in "${SELECTED_SKILLS[@]}"; do printf ' --skill %q' "$selected"; done
        echo
        echo "Referenced collaborator skills are separate selections; install them when their capabilities are needed."
    else
        echo "To update this machine later:  git pull && bash scripts/install.sh"
        echo "(new skills get linked into Claude Code and Antigravity; Codex finds them automatically)."
    fi
    echo "Registry API keys (cite-check) can be entered or changed any time with:"
    echo "  bash skills/cite-check/mcp/setup_mcp.sh --keys"
    if [ "$COWRITER_SELECTED" = 1 ] && [ -f "$COWRITER_SCRIPT" ]; then
        echo "Co-Writer voice profile lives at ${CO_WRITER_PROFILE_DIR:-${CO_WRITER_HOME:-$HOME/.co-writer}/profile}:"
        echo "  python3 skills/co-writer/scripts/cowriter.py profile"
    fi
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

if [ "$VOICE_FAILED" = 1 ]; then
    echo "Co-Writer voice profile setup did not finish; see above." >&2
    exit 1
fi

if [ "$LINK_FAILED" = 1 ]; then
    echo "Some skill links conflicted with another installation; see above." >&2
    exit 1
fi
