#!/usr/bin/env bash
# ==============================================================================
# cite-check MCP toolbox — one-shot, idempotent setup for every harness.
#
#   bash setup_mcp.sh              # create the venv, ask for API keys, register
#   bash setup_mcp.sh --keys       # only (re)enter API keys
#   bash setup_mcp.sh --skip-keys  # install without asking for keys
#   bash setup_mcp.sh --uninstall  # deregister everywhere and drop the venv
#   bash setup_mcp.sh --uninstall --purge-keys   # …and forget stored keys
#   bash setup_mcp.sh --dry-run    # show what would change, touch nothing
#
# Normally you do not run this by hand: scripts/install.sh calls it for you.
#
# 1. Creates mcp/.venv and installs requirements (uv if available, else pip).
# 2. Smoke-tests the server in CLI mode.
# 2b. Asks for each registry API key (NASA ADS token; a contact e-mail for
#     the Crossref/OpenAlex polite pools). Input is not echoed. The secret goes
#     into the OS keychain (macOS Keychain / Linux Secret Service) when one is
#     available, else into a 0600 file under ~/.config/cite-check/keys/. It is
#     never written to a harness config, passed on a command line, or logged.
#     Press Enter to skip a key: that source is simply left disabled, and the
#     other registries keep working. No terminal (CI, an agent's shell) → the
#     questions are skipped automatically; run --keys later from a terminal.
# 3. Registers the server in every harness found on this machine:
#      Claude Code        -> `claude mcp add --scope user`
#      OpenAI Codex       -> ~/.codex/config.toml   ([mcp_servers.cite_check])
#      Google Antigravity -> mcp_config.json        ("mcpServers"."cite-check")
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
KEYS_ONLY=0
SKIP_KEYS=0
PURGE_KEYS=0
for arg in ${@+"$@"}; do   # ${@+...} keeps `set -u` quiet on bash 3.2 (macOS)
    case "$arg" in
        --uninstall)  MODE=uninstall ;;
        --dry-run)    DRY_RUN=1 ;;
        --keys)       KEYS_ONLY=1 ;;
        --skip-keys)  SKIP_KEYS=1 ;;
        --purge-keys) PURGE_KEYS=1 ;;
        -h|--help)    sed -n '2,36p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
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

# ==============================================================================
# API keys — prompted here, stored by server.py (`keys` subcommand), which
# picks the keychain when there is one and a 0600 file otherwise. The value
# travels to python on stdin, never on argv (argv shows up in `ps`).
# ==============================================================================
ask() {  # ask <read-options...> — from the terminal when there is one, else stdin
    if { : </dev/tty; } 2>/dev/null; then read "$@" </dev/tty; else read "$@"; fi
}

configure_keys() {
    local py names name label status masked url enables secret value
    py="$(host_python)" || { echo "  keys: no python3 to store them — skipped"; return; }
    names="$("$py" "$SERVER" keys names 2>/dev/null)" || { echo "  keys: server not runnable — skipped"; return; }
    if [ "$DRY_RUN" = 1 ]; then
        for name in $names; do
            IFS=$'\x1f' read -r label status masked url enables secret <<< "$("$py" "$SERVER" keys fields "$name")"
            if [ "$status" = none ]; then echo "  [dry-run] would ask for: $label"
            else echo "  [dry-run] $label: configured ($status)"; fi
        done
        return
    fi
    if [ "$KEYS_ONLY" = 0 ] && [ ! -t 0 ]; then
        echo "  keys: no terminal — not asked. From a terminal, run:  bash $0 --keys"
        return
    fi
    echo "  keys: stored in $("$py" "$SERVER" keys backend); Enter skips a source"
    for name in $names; do
        IFS=$'\x1f' read -r label status masked url enables secret <<< "$("$py" "$SERVER" keys fields "$name")"
        if [ "$status" != none ]; then
            echo "  * $label — configured ($status${masked:+, $masked})"
            printf '    Enter keeps it, or paste a new one: '
        else
            echo "  * $label — enables $enables"
            [ -n "$url" ] && echo "    get one at $url"
            printf '    paste it (Enter to skip): '
        fi
        if [ "$secret" = 1 ]; then ask -r -s value || value=""; echo
        else ask -r value || value=""; fi
        if [ -z "$value" ]; then
            [ "$status" = none ] && echo "    skipped — this source stays off; add it later with: bash $0 --keys"
            continue
        fi
        if printf '%s' "$value" | "$py" "$SERVER" keys set "$name" 2>&1 | sed 's/^/    /'; then :; else
            echo "    (source stays as it was)"
        fi
        value=""
    done
}

echo "== cite-check MCP $MODE =="

if [ "$KEYS_ONLY" = 1 ]; then
    configure_keys
    echo ""
    "$(host_python)" "$SERVER" keys list 2>/dev/null | sed 's/^/  /'
    exit 0
fi

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

    # --- 2b. API keys ---------------------------------------------------------
    if [ "$SKIP_KEYS" = 1 ]; then
        echo "  keys: skipped (--skip-keys); add them later with: bash $0 --keys"
    else
        configure_keys
    fi
fi

# ==============================================================================
# 3a. Claude Code
# ==============================================================================
if command -v claude >/dev/null 2>&1; then
    if [ "$MODE" = install ]; then
        if claude mcp get cite-check >/dev/null 2>&1; then
            echo "  claude-code: already registered"
        else
            run claude mcp add --scope user cite-check -- "$PY" "$SERVER"
            [ "$DRY_RUN" = 1 ] || echo "  claude-code: registered (user scope)"
        fi
    else
        if claude mcp get cite-check >/dev/null 2>&1; then
            run claude mcp remove --scope user cite-check
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
        if [ -f "$CODEX_CFG" ] && grep -Eq '^\[mcp_servers\.cite[_-]check\]' "$CODEX_CFG"; then
            echo "  codex: already registered"
        elif [ "$DRY_RUN" = 1 ]; then
            echo "  [dry-run] would add [mcp_servers.cite_check] to $CODEX_CFG"
        else
            # A new [table] appended at EOF is valid TOML regardless of what precedes it.
            printf '\n[mcp_servers.cite_check]\ncommand = "%s"\nargs = ["%s"]\n' \
                "$PY" "$SERVER" >> "$CODEX_CFG"
            echo "  codex: registered in $CODEX_CFG"
        fi
    elif [ ! -f "$CODEX_CFG" ] || ! grep -Eq '^\[mcp_servers\.cite[_-]check\]' "$CODEX_CFG"; then
        echo "  codex: not registered"
    elif [ "$DRY_RUN" = 1 ]; then
        echo "  [dry-run] would remove [mcp_servers.cite_check] from $CODEX_CFG"
    else
        # Drop our table and its keys, up to the next table header or EOF.
        awk '
            /^\[mcp_servers\.cite[_-]check\]/ { drop = 1; next }
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
    echo "  [dry-run] would $MODE 'cite-check' in $AG_CFG"
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
    if "cite-check" in servers:
        print(f"  antigravity: already registered ({cfg_path})")
        raise SystemExit
    servers["cite-check"] = {"command": py, "args": [srv]}
    verb = "registered in"
else:
    if "cite-check" not in servers:
        print(f"  antigravity: not registered ({cfg_path})")
        raise SystemExit
    del servers["cite-check"]
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
    if [ "$PURGE_KEYS" = 1 ]; then
        if [ "$DRY_RUN" = 1 ]; then echo "  [dry-run] would forget stored API keys"
        elif KP="$(host_python)"; then "$KP" "$SERVER" keys delete --all | sed 's/^/  keys: /'
        else echo "  keys: no python3 to remove them — left in place"; fi
    else
        echo "  keys: kept (pass --purge-keys to forget them)"
    fi
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
    echo "API keys:"
    "$PY" "$SERVER" keys list 2>/dev/null | sed 's/^/  /'
    echo "  (change them any time: bash $MCP_DIR/setup_mcp.sh --keys)"
fi
