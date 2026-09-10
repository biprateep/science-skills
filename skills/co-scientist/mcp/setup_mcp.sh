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
#      Claude Code        -> `claude mcp add --scope user`
#      OpenAI Codex       -> ~/.codex/config.toml   ([mcp_servers.co_scientist])
#      Google Antigravity -> mcp_config.json        ("mcpServers"."co-scientist")
#    Existing registrations and unrelated config entries are left untouched.
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
# 3a. Claude Code
# ==============================================================================
if command -v claude >/dev/null 2>&1; then
    if [ "$MODE" = install ]; then
        if claude mcp get co-scientist >/dev/null 2>&1; then
            echo "  claude-code: already registered"
        else
            run claude mcp add --scope user co-scientist -- "$PY" "$SERVER"
            [ "$DRY_RUN" = 1 ] || echo "  claude-code: registered (user scope)"
        fi
    else
        if claude mcp get co-scientist >/dev/null 2>&1; then
            run claude mcp remove --scope user co-scientist
            [ "$DRY_RUN" = 1 ] || echo "  claude-code: deregistered"
        else
            echo "  claude-code: not registered"
        fi
    fi
else
    echo "  claude-code: not found — skipped"
fi

# ==============================================================================
# 3b. OpenAI Codex
# ==============================================================================
CODEX_CFG="$HOME/.codex/config.toml"
if command -v codex >/dev/null 2>&1 || [ -f "$CODEX_CFG" ]; then
    if [ "$MODE" = install ]; then
        [ -f "$CODEX_CFG" ] || run mkdir -p "$HOME/.codex"
        [ -f "$CODEX_CFG" ] || run touch "$CODEX_CFG"
        if [ -f "$CODEX_CFG" ] && grep -Eq '^\[mcp_servers\.co[_-]scientist\]' "$CODEX_CFG"; then
            echo "  codex: already registered"
        elif [ "$DRY_RUN" = 1 ]; then
            echo "  [dry-run] would add [mcp_servers.co_scientist] to $CODEX_CFG"
        else
            # A new [table] appended at EOF is valid TOML regardless of what precedes it.
            printf '\n[mcp_servers.co_scientist]\ncommand = "%s"\nargs = ["%s"]\n' \
                "$PY" "$SERVER" >> "$CODEX_CFG"
            echo "  codex: registered in $CODEX_CFG"
        fi
    elif [ ! -f "$CODEX_CFG" ] || ! grep -Eq '^\[mcp_servers\.co[_-]scientist\]' "$CODEX_CFG"; then
        echo "  codex: not registered"
    elif [ "$DRY_RUN" = 1 ]; then
        echo "  [dry-run] would remove [mcp_servers.co_scientist] from $CODEX_CFG"
    else
        # Drop our table and its keys, up to the next table header or EOF.
        awk '
            /^\[mcp_servers\.co[_-]scientist\]/ { drop = 1; next }
            drop && /^\[/                       { drop = 0 }
            !drop                               { print }
        ' "$CODEX_CFG" > "$CODEX_CFG.tmp" && mv "$CODEX_CFG.tmp" "$CODEX_CFG"
        echo "  codex: deregistered from $CODEX_CFG"
    fi
else
    echo "  codex: not found — skipped"
fi

# ==============================================================================
# 3c. Google Antigravity
# ==============================================================================
# Antigravity has moved this file between releases, so try every known home and
# take the first that exists. An empty file counts: the installer creates one.
AG_CFG=""
for cand in "${GEMINI_CONFIG_DIR:-$HOME/.gemini/config}/mcp_config.json" \
            "$HOME/.gemini/antigravity/mcp_config.json" \
            "$HOME/.antigravity/mcp_config.json"; do
    if [ -f "$cand" ]; then AG_CFG="$cand"; break; fi
done

if [ -z "$AG_CFG" ]; then
    echo "  antigravity: no mcp_config.json found — skipped (add via its MCP settings UI once, then rerun)"
elif [ "$DRY_RUN" = 1 ]; then
    echo "  [dry-run] would $MODE 'co-scientist' in $AG_CFG"
elif ! AG_PY="$(host_python)"; then
    echo "  antigravity: no python3 available to edit $AG_CFG — skipped" >&2
else
    "$AG_PY" - "$AG_CFG" "$PY" "$SERVER" "$MODE" <<'PYEOF'
import json, os, sys
cfg_path, py, srv, mode = sys.argv[1:5]
# A freshly created mcp_config.json is zero bytes; json.load would choke on it.
raw = open(cfg_path).read().strip()
if raw:
    try:
        cfg = json.loads(raw)
    except ValueError as exc:
        sys.exit(f"  antigravity: {cfg_path} is not valid JSON ({exc}); fix it, then rerun")
else:
    cfg = {}
if not isinstance(cfg, dict):
    sys.exit(f"  antigravity: {cfg_path} must contain a JSON object; leaving it alone")

servers = cfg.setdefault("mcpServers", {})
if mode == "install":
    if "co-scientist" in servers:
        print(f"  antigravity: already registered ({cfg_path})")
        raise SystemExit
    servers["co-scientist"] = {"command": py, "args": [srv]}
    verb = "registered in"
else:
    if "co-scientist" not in servers:
        print(f"  antigravity: not registered ({cfg_path})")
        raise SystemExit
    del servers["co-scientist"]
    verb = "deregistered from"

with open(cfg_path, "w") as fh:
    json.dump(cfg, fh, indent=2)
    fh.write("\n")
print(f"  antigravity: {verb} {cfg_path}")
PYEOF
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
