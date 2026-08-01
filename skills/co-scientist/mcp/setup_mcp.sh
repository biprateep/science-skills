#!/usr/bin/env bash
# ==============================================================================
# co-scientist MCP toolbox — one-shot, idempotent setup for every harness.
#
#   bash setup_mcp.sh
#
# 1. Creates mcp/.venv and installs requirements (uv if available, else pip).
# 2. Smoke-tests the server in CLI mode.
# 3. Registers the server in every harness found on this machine:
#      Claude Code      -> `claude mcp add --scope user`
#      OpenAI Codex     -> ~/.codex/config.toml   ([mcp_servers.co_scientist])
#      Google Antigravity -> mcp_config.json      ("mcpServers"."co-scientist")
#    Existing registrations and unrelated config entries are left untouched.
#
# Newly registered MCP servers load at the NEXT session start of each harness.
# Until then the identical checks are available via CLI mode:
#   mcp/.venv/bin/python mcp/server.py call <tool> '<json-args>'
# ==============================================================================
set -euo pipefail

MCP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$MCP_DIR/.venv"
PY="$VENV/bin/python"
SERVER="$MCP_DIR/server.py"

echo "== co-scientist MCP setup =="

# --- 1. venv + dependencies ---------------------------------------------------
if [ ! -x "$PY" ]; then
    if command -v uv >/dev/null 2>&1; then
        uv venv -q "$VENV"
    else
        python3 -m venv "$VENV"
    fi
    echo "  venv: created $VENV"
else
    echo "  venv: exists"
fi
if command -v uv >/dev/null 2>&1; then
    uv pip install -q --python "$PY" -r "$MCP_DIR/requirements.txt"
else
    "$PY" -m pip install -q --upgrade pip
    "$PY" -m pip install -q -r "$MCP_DIR/requirements.txt"
fi
echo "  deps: installed"

# --- 2. smoke test ------------------------------------------------------------
if "$PY" "$SERVER" call ping '{}' >/dev/null 2>&1; then
    echo "  smoke: server responds (CLI mode)"
else
    echo "  smoke: FAILED — server.py cannot run; aborting before registration" >&2
    "$PY" "$SERVER" call ping '{}' || true
    exit 1
fi

# --- 3a. Claude Code ----------------------------------------------------------
if command -v claude >/dev/null 2>&1; then
    if claude mcp get co-scientist >/dev/null 2>&1; then
        echo "  claude-code: already registered"
    else
        claude mcp add --scope user co-scientist -- "$PY" "$SERVER" >/dev/null
        echo "  claude-code: registered (user scope)"
    fi
else
    echo "  claude-code: not found — skipped"
fi

# --- 3b. OpenAI Codex ---------------------------------------------------------
CODEX_CFG="$HOME/.codex/config.toml"
if command -v codex >/dev/null 2>&1 || [ -f "$CODEX_CFG" ]; then
    mkdir -p "$HOME/.codex" && touch "$CODEX_CFG"
    if grep -Eq '^\[mcp_servers\.co[_-]scientist\]' "$CODEX_CFG"; then
        echo "  codex: already registered"
    else
        # A new [table] appended at EOF is valid TOML regardless of what precedes it.
        printf '\n[mcp_servers.co_scientist]\ncommand = "%s"\nargs = ["%s"]\n' \
            "$PY" "$SERVER" >> "$CODEX_CFG"
        echo "  codex: registered in $CODEX_CFG"
    fi
else
    echo "  codex: not found — skipped"
fi

# --- 3c. Google Antigravity ---------------------------------------------------
AG_DONE=0
for AG_CFG in "$HOME/.gemini/antigravity/mcp_config.json" "$HOME/.antigravity/mcp_config.json"; do
    [ -f "$AG_CFG" ] || continue
    "$PY" - "$AG_CFG" "$PY" "$SERVER" <<'PYEOF'
import json, sys
cfg_path, py, srv = sys.argv[1], sys.argv[2], sys.argv[3]
with open(cfg_path) as fh:
    cfg = json.load(fh)
servers = cfg.setdefault("mcpServers", {})
if "co-scientist" in servers:
    print(f"  antigravity: already registered ({cfg_path})")
else:
    servers["co-scientist"] = {"command": py, "args": [srv]}
    with open(cfg_path, "w") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")
    print(f"  antigravity: registered in {cfg_path}")
PYEOF
    AG_DONE=1
    break
done
[ "$AG_DONE" = 1 ] || echo "  antigravity: no mcp_config.json found — skipped (add via its MCP settings UI once, then rerun)"

echo ""
echo "Done. Newly registered servers appear at the NEXT session start."
echo "For the current session, call tools via CLI:"
echo "  $PY $SERVER call ping '{}'"
