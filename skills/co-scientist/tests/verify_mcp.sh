#!/usr/bin/env bash
# ==============================================================================
# Smoke-test the co-scientist MCP toolbox (CLI mode — no MCP client needed).
#
#   bash tests/verify_mcp.sh [--network]
#
# --network additionally exercises resolve_citation against live registries.
# Uses mcp/.venv if present, else system python3 (needs sympy).
# ==============================================================================
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER="$HERE/../mcp/server.py"
PY="$HERE/../mcp/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
W="$(mktemp -d)"
trap 'rm -rf "$W"' EXIT

PASS=0; FAIL=0
check() {  # check <name> <expected_exit> <cmd...>
    local name="$1" expected="$2"; shift 2
    "$@" >/dev/null 2>&1
    local got=$?
    if [ "$got" -eq "$expected" ]; then
        echo "PASS  $name"; PASS=$((PASS+1))
    else
        echo "FAIL  $name (exit $got, expected $expected)"; FAIL=$((FAIL+1))
    fi
}

check "ping" 0 "$PY" "$SERVER" call ping '{}'

check "verify: correct chain passes" 0 "$PY" "$SERVER" call verify_derivation '{
  "symbols": {"x": "real", "k": "positive"},
  "steps": [
    {"label": "1->2", "cls": "S", "lhs": "(x+1)**2", "rhs": "x**2 + 2*x + 1"},
    {"label": "2->3", "cls": "A", "lhs": "integrate(x*exp(-k*x), (x, 0, oo))", "rhs": "1/k**2"},
    {"label": "3", "cls": "U", "note": "convergence"}
  ]}'

check "verify: wrong step fails" 1 "$PY" "$SERVER" call verify_derivation '{
  "symbols": {"x": "real"},
  "steps": [{"label": "1->2", "cls": "S", "lhs": "(x+1)**2", "rhs": "x**2 + 2*x + 2"}]}'

check "verify: bad class rejected" 1 "$PY" "$SERVER" call verify_derivation '{
  "steps": [{"label": "1", "cls": "X", "lhs": "1", "rhs": "1"}]}'

check "manifest: init" 0 "$PY" "$SERVER" call manifest_init \
  "{\"workdir\": \"$W\", \"run_id\": \"t\", \"goal\": \"g\"}"
check "manifest: init idempotent" 0 "$PY" "$SERVER" call manifest_init \
  "{\"workdir\": \"$W\", \"run_id\": \"t2\", \"goal\": \"g2\"}"
check "manifest: append checkpoint" 0 "$PY" "$SERVER" call manifest_append \
  "{\"workdir\": \"$W\", \"section\": \"checkpoints\", \"entry\": {\"descriptor\": \"deriv\", \"phase\": \"derivation\"}}"
check "manifest: verified needs evidence" 1 "$PY" "$SERVER" call manifest_update_checkpoint \
  "{\"workdir\": \"$W\", \"checkpoint_id\": \"000\", \"verified\": true}"
check "manifest: bad scalar field rejected" 1 "$PY" "$SERVER" call manifest_set \
  "{\"workdir\": \"$W\", \"fields\": {\"next_id\": 99}}"

cp "$HERE/../resources/paper_template.tex" "$W/report.tex"
check "compile: blocked by unverified checkpoint" 1 "$PY" "$SERVER" call compile_report \
  "{\"workdir\": \"$W\"}"
check "manifest: mark verified with evidence" 0 "$PY" "$SERVER" call manifest_update_checkpoint \
  "{\"workdir\": \"$W\", \"checkpoint_id\": \"000\", \"verified\": true, \"evidence\": \"verify_derivation 2/2 PASS seed 12345\"}"
if command -v pdflatex >/dev/null 2>&1; then
    check "compile: succeeds once verified" 0 "$PY" "$SERVER" call compile_report \
      "{\"workdir\": \"$W\"}"
else
    echo "SKIP  compile: succeeds once verified (no pdflatex)"
fi

printf '\\documentclass{article}\\usepackage{graphicx}\\begin{document}\\includegraphics{nope}\\end{document}\n' > "$W/fig.tex"
check "figures: missing target detected" 1 "$PY" "$SERVER" call validate_figures \
  "{\"tex_path\": \"$W/fig.tex\"}"

if [ "${1:-}" = "--network" ]; then
    check "citation: real arXiv id resolves" 0 "$PY" "$SERVER" call resolve_citation \
      '{"identifier": "arXiv:1706.03762"}'
    check "citation: real DOI resolves" 0 "$PY" "$SERVER" call resolve_citation \
      '{"identifier": "10.1103/PhysRev.47.777"}'
    check "citation: fake id rejected" 1 "$PY" "$SERVER" call resolve_citation \
      '{"identifier": "2599.99999"}'
else
    echo "SKIP  citation checks (pass --network to enable)"
fi

echo ""
echo "$PASS passed, $FAIL failed"
exit $((FAIL > 0))
