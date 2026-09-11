#!/usr/bin/env bash
# ==============================================================================
# science-skills uninstaller — undo everything scripts/install.sh created.
#
#   bash scripts/uninstall.sh            # remove skills and MCP toolboxes
#   bash scripts/uninstall.sh --dry-run  # show what would go, touch nothing
#   bash scripts/uninstall.sh --skip-mcp # unregister skills, keep the toolboxes
#   bash scripts/uninstall.sh --purge-keys   # also forget stored registry API keys
#
# Removes, from every harness found on this machine:
#   - the Claude Code symlinks in ~/.claude/skills/<name>
#   - this repo's directory entry in ~/.gemini/config/skills.json
#   - each skill's MCP server registration (Claude Code, Codex, Antigravity)
#     and its mcp/.venv (stored API keys are kept unless --purge-keys)
#
# Skills, MCP servers and config entries that did not come from this repo are
# left alone. The repo itself is never touched — delete the clone by hand
# afterwards if you want it gone.
#
# This is exactly `scripts/install.sh --uninstall`; it exists as its own script
# so it can be found without reading the installer's --help.
# ==============================================================================
set -euo pipefail

for arg in ${@+"$@"}; do
    case "$arg" in
        # Answer --help here: forwarding it would print the installer's header,
        # which describes installing.
        -h|--help) sed -n '2,22p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    esac
done

exec bash "$(dirname "${BASH_SOURCE[0]}")/install.sh" --uninstall ${@+"$@"}
