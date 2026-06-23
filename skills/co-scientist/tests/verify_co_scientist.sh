#!/bin/bash
# ==============================================================================
# Co-Scientist Skill — Post-Run Verification Script
#
# Run this in the working directory after a Full-Project co-scientist run to
# verify the skill operated correctly.
#
# Usage: bash verify_co_scientist.sh [working_dir]
#   working_dir: optional, defaults to current directory.
#
# Note: this checks artifacts of a FULL PROJECT run. Quick/Derivation-mode runs
# legitimately produce fewer artifacts and are not the target of this script.
# ==============================================================================

set -uo pipefail

WORKDIR="${1:-.}"
CKPT="${WORKDIR}/checkpoints"
ERRORS=0
WARNINGS=0

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
pass() { echo -e "${GREEN}PASS${NC}: $1"; }
fail() { echo -e "${RED}FAIL${NC}: $1"; ERRORS=$((ERRORS + 1)); }
warn() { echo -e "${YELLOW}WARN${NC}: $1"; WARNINGS=$((WARNINGS + 1)); }

# Count files (under WORKDIR) whose CONTENT matches an extended-regex pattern.
# Uses -E (so | alternation works) and wc -l (so the result is always an integer).
count_content_matches() { # $1 = ERE pattern, $2 = dir
    grep -rlIE "$1" "$2" 2>/dev/null | wc -l | tr -d ' '
}

echo "========================================"
echo "Co-Scientist Skill Verification"
echo "Working directory: ${WORKDIR}"
echo "========================================"
echo ""

# ---------------------------------------------------------------------------
# Initialization & workspace
# ---------------------------------------------------------------------------
echo "--- Initialization ---"
[ -d "${CKPT}" ]            && pass "checkpoints/ directory exists" || fail "checkpoints/ not created"
[ -d "${WORKDIR}/figures" ] && pass "figures/ directory exists"     || fail "figures/ not created"
[ -d "${WORKDIR}/scripts" ] && pass "scripts/ directory exists"     || warn "scripts/ not found (OK if no scripts were needed)"
[ -f "${CKPT}/checkpoint_000_project_init.md" ] && pass "checkpoint_000_project_init.md exists" || fail "checkpoint_000_project_init.md not found — workspace not initialized"
[ -f "${CKPT}/manifest.json" ] && pass "run manifest (manifest.json) exists" || warn "checkpoints/manifest.json not found — run may not be resumable"
echo ""

# ---------------------------------------------------------------------------
# Checkpointing
# ---------------------------------------------------------------------------
echo "--- Checkpointing ---"
CHECKPOINT_COUNT=$(find "${CKPT}" -name "checkpoint_*.md" 2>/dev/null | wc -l | tr -d ' ')
if [ "${CHECKPOINT_COUNT:-0}" -ge 4 ]; then
    pass "Found ${CHECKPOINT_COUNT} checkpoint files (>=4 expected)"
else
    fail "Expected >=4 checkpoint files, found ${CHECKPOINT_COUNT:-0}"
fi

TEMPLATE_ISSUES=0
for f in "${CKPT}"/checkpoint_*.md; do
    [ -f "$f" ] || continue
    # The assumptions ledger is a table, not a standard checkpoint — skip it.
    [ "$(basename "$f")" = "checkpoint_assumptions.md" ] && continue
    grep -q "## Summary" "$f" 2>/dev/null || { warn "$(basename "$f") missing '## Summary'"; TEMPLATE_ISSUES=$((TEMPLATE_ISSUES + 1)); }
    grep -q "## Content" "$f" 2>/dev/null || { warn "$(basename "$f") missing '## Content'"; TEMPLATE_ISSUES=$((TEMPLATE_ISSUES + 1)); }
done
[ "$TEMPLATE_ISSUES" -eq 0 ] && [ "${CHECKPOINT_COUNT:-0}" -gt 0 ] && pass "All checkpoints follow template format"
echo ""

# ---------------------------------------------------------------------------
# Mathematical derivation quality
# ---------------------------------------------------------------------------
echo "--- Mathematical Derivation Quality ---"
# Step-skipping language: -E so the | alternation is honored (the old script
# omitted -E, so | was literal and this check NEVER fired).
SKIP_PATTERNS="it can be shown|after simplification|trivially follows|it is easy to see|straightforward to show|clearly we have"
SKIP_HITS=$(count_content_matches "$SKIP_PATTERNS" "${CKPT}")
if [ "${SKIP_HITS:-0}" -gt 0 ]; then
    fail "Step-skipping language found in ${SKIP_HITS} checkpoint file(s):"
    grep -rlIE "$SKIP_PATTERNS" "${CKPT}" 2>/dev/null | while read -r f; do echo "       - $(basename "$f")"; done
else
    pass "No step-skipping language detected in checkpoints"
fi

# Equation blocks in derivation checkpoints. Pattern uses SINGLE backslashes in a
# single-quoted string so grep -E matches real LaTeX (\begin, \[) — the old
# four-backslash pattern matched two literal backslashes and never fired.
DERIVATION_FILES=$(find "${CKPT}" \( -name "*derivation*" -o -name "*math*" \) 2>/dev/null)
if [ -n "$DERIVATION_FILES" ]; then
    while IFS= read -r f; do
        [ -n "$f" ] || continue
        EQ_COUNT=$(grep -cE '^[[:space:]]*(\*\*Step [0-9]|\\begin\{(equation|align)|\$\$|\\\[)' "$f" 2>/dev/null)
        if [ "${EQ_COUNT:-0}" -ge 5 ]; then
            pass "$(basename "$f") has ${EQ_COUNT} equation blocks (>=5)"
        else
            warn "$(basename "$f") has ${EQ_COUNT:-0} equation blocks (expected >=5)"
        fi
    done <<< "$DERIVATION_FILES"
else
    warn "No derivation checkpoint files found to check equation count"
fi

# Independent verification scripts (sympy / numeric checks).
VERIF=$(find "${WORKDIR}/scripts" -name "check_*.py" 2>/dev/null | wc -l | tr -d ' ')
if [ "${VERIF:-0}" -ge 1 ]; then
    pass "Found ${VERIF} derivation-verification script(s) (check_*.py)"
else
    warn "No verification scripts (check_*.py) — derivations may be unverified"
fi
echo ""

# ---------------------------------------------------------------------------
# Rigor extras: red-team, novelty, assumptions ledger, reproducibility, confidence
# ---------------------------------------------------------------------------
echo "--- Rigor & Honesty ---"
[ -n "$(find "${CKPT}" -iname '*redteam*' -o -iname '*red_team*' -o -iname '*review*' 2>/dev/null)" ] \
    && pass "Red-team / review checkpoint present" || warn "No red-team/review checkpoint found"
[ "$(count_content_matches 'novelty verdict|prior art|already (been )?(done|shown|proven)' "${CKPT}")" -gt 0 ] \
    && pass "Novelty verdict / prior-art discussion present" || warn "No explicit novelty verdict found"
[ -f "${CKPT}/checkpoint_assumptions.md" ] \
    && pass "Assumptions & limitations ledger present" || warn "No assumptions ledger (checkpoint_assumptions.md)"
[ "$(count_content_matches 'Confidence' "${CKPT}")" -gt 0 ] \
    && pass "Confidence tags present in checkpoints" || warn "No confidence tags found"
# Optional Elo tournament (informational only — not run on every project).
if [ -n "$(find "${CKPT}" -iname '*tournament*' 2>/dev/null)" ] || grep -q '"tournament"' "${CKPT}/manifest.json" 2>/dev/null; then
    pass "Optional Elo tournament artifacts present"
else
    echo "INFO: no tournament artifacts (optional add-on — only when requested)"
fi
# Reproducibility: scripts that use randomness should set a seed.
RNG=$(grep -rlIE 'random|np\.random|default_rng|sample' "${WORKDIR}/scripts" 2>/dev/null | wc -l | tr -d ' ')
SEEDED=$(grep -rlIE 'seed|default_rng\(' "${WORKDIR}/scripts" 2>/dev/null | wc -l | tr -d ' ')
if [ "${RNG:-0}" -eq 0 ]; then
    pass "No stochastic scripts requiring a seed"
elif [ "${SEEDED:-0}" -ge "${RNG:-0}" ]; then
    pass "All stochastic scripts set a seed"
else
    warn "Some stochastic scripts may not set an RNG seed (${SEEDED}/${RNG} seeded)"
fi
echo ""

# ---------------------------------------------------------------------------
# Visualizations
# ---------------------------------------------------------------------------
echo "--- Visualizations ---"
FIG_COUNT=$(find "${WORKDIR}/figures" \( -name "*.png" -o -name "*.pdf" -o -name "*.svg" \) 2>/dev/null | wc -l | tr -d ' ')
[ "${FIG_COUNT:-0}" -ge 1 ] && pass "Found ${FIG_COUNT} figure file(s)" || warn "No figures generated (OK if none clarified a result)"
VIZ_SCRIPTS=$(find "${WORKDIR}/scripts" -name "viz_*.py" 2>/dev/null | wc -l | tr -d ' ')
[ "${VIZ_SCRIPTS:-0}" -ge 1 ] && pass "Found ${VIZ_SCRIPTS} visualization script(s)" || warn "No visualization scripts (viz_*.py)"
FIG_REFS=$(count_content_matches 'fig_|\.png|\.pdf|includegraphics' "${CKPT}")
[ "${FIG_REFS:-0}" -gt 0 ] && pass "Figures referenced in ${FIG_REFS} checkpoint(s)" || warn "No figure references in checkpoints"
echo ""

# ---------------------------------------------------------------------------
# Report quality
# ---------------------------------------------------------------------------
echo "--- Report Quality ---"
# Prefer report.tex in the working dir (the skill copies the template there).
TEX_FILE="${WORKDIR}/report.tex"
[ -f "$TEX_FILE" ] || TEX_FILE=$(find "${WORKDIR}" -maxdepth 2 -name "*.tex" -not -path "*/\.*" 2>/dev/null | head -1)
if [ -n "${TEX_FILE:-}" ] && [ -f "$TEX_FILE" ]; then
    grep -q "includegraphics" "$TEX_FILE" 2>/dev/null && pass "Report includes \\includegraphics" || warn "Report has no \\includegraphics"
    grep -qi "Assumptions and Limitations" "$TEX_FILE" 2>/dev/null && pass "Report has an Assumptions and Limitations section" || warn "Report missing Assumptions and Limitations section"
    PDF_FILE="${TEX_FILE%.tex}.pdf"
    [ -f "$PDF_FILE" ] && pass "PDF compiled: $(basename "$PDF_FILE")" || warn "PDF not found — report may not have compiled"
else
    warn "No .tex report found (OK for non-report runs)"
fi
echo ""

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo "========================================"
echo -e "Results: ${RED}${ERRORS} errors${NC}, ${YELLOW}${WARNINGS} warnings${NC}"
echo "========================================"
if [ "$ERRORS" -eq 0 ]; then
    echo -e "${GREEN}All critical checks passed!${NC}"
else
    echo -e "${RED}${ERRORS} critical issue(s) found. Review above.${NC}"
fi
exit "$ERRORS"
