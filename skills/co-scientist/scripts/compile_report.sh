#!/usr/bin/env bash
# Compile through the same verification/citation/figure gates as the MCP tool.
# Run from the report directory: compile_report.sh [report_basename].
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$HERE/../mcp/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
ARGS="$("$PY" -c 'import json, os, sys; print(json.dumps({"workdir": os.getcwd(), "name": sys.argv[1]}))' "${1:-report}")"
exec "$PY" "$HERE/../mcp/server.py" call compile_report "$ARGS"
