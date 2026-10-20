#!/usr/bin/env bash
# ==============================================================================
# co-scientist MCP toolbox — one-shot, idempotent setup for every harness.
#
#   bash setup_mcp.sh              # create the venv and register the server
#   bash setup_mcp.sh --uninstall  # deregister everywhere and drop the venv
#   bash setup_mcp.sh --dry-run    # show what would change, touch nothing
#
# Normally you do not run this by hand: scripts/install.sh calls it for you.
#
# 1. Creates mcp/.venv and installs requirements (uv if available, else pip).
# 2. Smoke-tests the server in CLI mode.
# 3. Registers the server in every harness found on this machine:
#      Claude Code        -> user-scope mcpServers in ~/.claude.json
#      OpenAI Codex       -> ~/.codex/config.toml   ([mcp_servers.co-scientist])
#      Google Antigravity -> mcp_config.json        ("mcpServers"."co-scientist")
#    Owned registrations refresh; unrelated entries are left untouched.
#
# Newly registered MCP servers load at the NEXT session start of each harness.
# Until then the identical checks are available via CLI mode:
#   mcp/.venv/bin/python mcp/server.py call <tool> '<json-args>'
#
# Override: GEMINI_CONFIG_DIR (default ~/.gemini/config) to target a custom
# Antigravity install.
# ==============================================================================
set -euo pipefail

MCP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$MCP_DIR/.venv"
PY="$VENV/bin/python"
SERVER="$MCP_DIR/server.py"

MODE=install
DRY_RUN=0
for arg in ${@+"$@"}; do   # ${@+...} keeps `set -u` quiet on bash 3.2 (macOS)
    case "$arg" in
        --uninstall) MODE=uninstall ;;
        --dry-run)   DRY_RUN=1 ;;
        --skip-keys|--purge-keys) ;;   # passed through by scripts/install.sh; this toolbox has no API keys
        --keys)      echo "co-scientist's toolbox needs no API keys."; exit 0 ;;
        -h|--help)   sed -n '2,26p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $arg (try --help)" >&2; exit 1 ;;
    esac
done

run() {  # execute, or just narrate under --dry-run
    if [ "$DRY_RUN" = 1 ]; then echo "    [dry-run] $*"; else "$@"; fi
}

# JSON edits need *a* python; during uninstall the venv may already be gone.
host_python() {
    if [ -x "$PY" ]; then echo "$PY"
    elif command -v python3 >/dev/null 2>&1; then command -v python3
    else return 1; fi
}

echo "== co-scientist MCP $MODE =="

# ==============================================================================
# 1. venv + dependencies  (install only)
# ==============================================================================
if [ "$MODE" = install ]; then
    if [ ! -x "$PY" ]; then
        if [ "$DRY_RUN" = 1 ]; then
            echo "  [dry-run] would create venv $VENV and install requirements"
        elif command -v uv >/dev/null 2>&1; then
            uv venv -q "$VENV"
            echo "  venv: created $VENV"
        else
            python3 -m venv "$VENV"
            echo "  venv: created $VENV"
        fi
    else
        echo "  venv: exists"
    fi

    if [ "$DRY_RUN" = 0 ]; then
        if command -v uv >/dev/null 2>&1; then
            uv pip install -q --python "$PY" -r "$MCP_DIR/requirements.txt"
        else
            "$PY" -m pip install -q --upgrade pip
            "$PY" -m pip install -q -r "$MCP_DIR/requirements.txt"
        fi
        echo "  deps: installed"
    fi

    # --- 2. smoke test --------------------------------------------------------
    if [ "$DRY_RUN" = 1 ]; then
        echo "  [dry-run] would smoke-test the server"
    elif "$PY" "$SERVER" call ping '{}' >/dev/null 2>&1; then
        echo "  smoke: server responds (CLI mode)"
    else
        echo "  smoke: FAILED — server.py cannot run; aborting before registration" >&2
        "$PY" "$SERVER" call ping '{}' || true
        exit 1
    fi
fi

# ==============================================================================
# 3. Client configurations — parsed, ownership-checked, atomic transactions.
# ==============================================================================
CONFIG_HELPER="$MCP_DIR/../../../scripts/install_config.py"
CONFIG_PY="$(host_python)"
CONFIG_FAILED=0
register_client() {
    local client="$1" config="$2"
    local options=()
    if [ "$DRY_RUN" = 1 ] && [ "$client" = codex ] \
            && ! "$CONFIG_PY" -c 'import tomlkit' >/dev/null 2>&1; then
        echo "  [dry-run] would install tomlkit, then validate owned Codex registration"
        return
    fi
    [ "$DRY_RUN" = 1 ] && options+=(--dry-run)
    if ! "$CONFIG_PY" "$CONFIG_HELPER" mcp --client "$client" \
            --config "$config" --name "co-scientist" --python "$PY" \
            --server "$SERVER" --mode "$MODE" ${options+"${options[@]}"}; then
        CONFIG_FAILED=1
    fi
}

# Read the user scope directly; `claude mcp get` can select a project/local
# entry with the same name and cannot establish ownership of the user entry.
if [ -n "${CLAUDE_CONFIG_DIR:-}" ]; then
    CLAUDE_USER_CFG="$CLAUDE_CONFIG_DIR/.claude.json"
else
    CLAUDE_USER_CFG="$HOME/.claude.json"
fi
if command -v claude >/dev/null 2>&1 || [ -f "$CLAUDE_USER_CFG" ]; then
    register_client claude "$CLAUDE_USER_CFG"
fi
CODEX_CFG="${CODEX_HOME:-$HOME/.codex}/config.toml"
if command -v codex >/dev/null 2>&1 || [ -f "$CODEX_CFG" ]; then
    register_client codex "$CODEX_CFG"
fi
AG_DIR="${GEMINI_CONFIG_DIR:-$HOME/.gemini/config}"
if [ -d "$AG_DIR" ] || command -v agy >/dev/null 2>&1 \
        || command -v antigravity >/dev/null 2>&1; then
    register_client antigravity "$AG_DIR/mcp_config.json"
fi
if [ "$CONFIG_FAILED" = 1 ]; then
    echo "MCP configuration conflicts remain; venv retained. See above." >&2
    exit 1
fi

# ==============================================================================
# 4. venv teardown  (uninstall only — after the configs stop pointing at it)
# ==============================================================================
if [ "$MODE" = uninstall ]; then
    if [ -d "$VENV" ]; then
        run rm -rf "$VENV"
        [ "$DRY_RUN" = 1 ] || echo "  venv: removed $VENV"
    else
        echo "  venv: nothing to remove"
    fi
fi

echo ""
if [ "$DRY_RUN" = 1 ]; then
    echo "Dry run — nothing was changed."
elif [ "$MODE" = uninstall ]; then
    echo "MCP toolbox removed. Restart each harness to drop the tools."
else
    echo "Done. Newly registered servers appear at the NEXT session start."
    echo "For the current session, call tools via CLI:"
    echo "  $PY $SERVER call ping '{}'"
fi
