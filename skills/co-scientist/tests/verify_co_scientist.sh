#!/bin/bash
# ==============================================================================
# Co-Scientist Skill — Post-Run Verification Script
#
# Run this in the working directory after a co-scientist session to verify
# that the skill operated correctly.
#
# Usage: bash tests/verify_co_scientist.sh [working_dir]
#   working_dir: optional, defaults to current directory
# ==============================================================================

set -euo pipefail

WORKDIR="${1:-.}"
ERRORS=0
WARNINGS=0

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

pass() { echo -e "${GREEN}PASS${NC}: $1"; }
fail() { echo -e "${RED}FAIL${NC}: $1"; ERRORS=$((ERRORS + 1)); }
warn() { echo -e "${YELLOW}WARN${NC}: $1"; WARNINGS=$((WARNINGS + 1)); }

echo "========================================"
echo "Co-Scientist Skill Verification"
echo "Working directory: ${WORKDIR}"
echo "========================================"
echo ""

# ---------------------------------------------------------------------------
# Flaw #1: Activation — check workspace was initialized
# ---------------------------------------------------------------------------
echo "--- Flaw #1: Activation ---"

if [ -d "${WORKDIR}/checkpoints" ]; then
    pass "checkpoints/ directory exists"
else
    fail "checkpoints/ directory not created"
fi

if [ -d "${WORKDIR}/figures" ]; then
    pass "figures/ directory exists"
else
    fail "figures/ directory not created"
fi

if [ -d "${WORKDIR}/scripts" ] || ls "${WORKDIR}"/scripts/viz_*.py >/dev/null 2>&1; then
    pass "scripts/ directory exists"
else
    warn "scripts/ directory not found (may be OK if no viz scripts needed)"
fi

if [ -f "${WORKDIR}/checkpoints/checkpoint_000_project_init.md" ]; then
    pass "checkpoint_000_project_init.md exists"
else
    fail "checkpoint_000_project_init.md not found — workspace not initialized"
fi

echo ""

# ---------------------------------------------------------------------------
# Flaw #3: Checkpointing
# ---------------------------------------------------------------------------
echo "--- Flaw #3: Checkpointing ---"

CHECKPOINT_COUNT=$(find "${WORKDIR}/checkpoints" -name "checkpoint_*.md" 2>/dev/null | wc -l)
if [ "$CHECKPOINT_COUNT" -ge 4 ]; then
    pass "Found ${CHECKPOINT_COUNT} checkpoint files (≥4 expected)"
else
    fail "Expected ≥4 checkpoint files, found ${CHECKPOINT_COUNT}"
fi

# Check checkpoint template compliance
TEMPLATE_ISSUES=0
for f in "${WORKDIR}"/checkpoints/checkpoint_*.md; do
    [ -f "$f" ] || continue
    if ! grep -q "## Summary" "$f" 2>/dev/null; then
        warn "$(basename "$f") missing '## Summary' section"
        TEMPLATE_ISSUES=$((TEMPLATE_ISSUES + 1))
    fi
    if ! grep -q "## Content" "$f" 2>/dev/null; then
        warn "$(basename "$f") missing '## Content' section"
        TEMPLATE_ISSUES=$((TEMPLATE_ISSUES + 1))
    fi
done

if [ "$TEMPLATE_ISSUES" -eq 0 ] && [ "$CHECKPOINT_COUNT" -gt 0 ]; then
    pass "All checkpoints follow template format"
fi

echo ""

# ---------------------------------------------------------------------------
# Flaw #2: Math derivation quality
# ---------------------------------------------------------------------------
echo "--- Flaw #2: Mathematical Derivation Quality ---"

# Look for step-skipping anti-patterns
SKIP_PATTERNS="it can be shown|after simplification|trivially follows|it is easy to see|straightforward to show|clearly we have"
SKIP_HITS=$(grep -rlic "${SKIP_PATTERNS}" "${WORKDIR}/checkpoints/" 2>/dev/null || echo "0")
if [ "$SKIP_HITS" -gt 0 ]; then
    fail "Found step-skipping language in ${SKIP_HITS} checkpoint file(s):"
    grep -rlin "${SKIP_PATTERNS}" "${WORKDIR}/checkpoints/" 2>/dev/null | while read -r f; do
        echo "       - $(basename "$f")"
    done
else
    pass "No step-skipping language detected in checkpoints"
fi

# Check for numbered equations (look for patterns like (1), Eq. 1, Step 1)
DERIVATION_FILES=$(find "${WORKDIR}/checkpoints" -name "*derivation*" -o -name "*math*" 2>/dev/null)
if [ -n "$DERIVATION_FILES" ]; then
    for f in $DERIVATION_FILES; do
        EQ_COUNT=$(grep -cE '^\s*(\*\*Step [0-9]|\\\\begin\{equation|\\\\begin\{align|\$\$|\\\[)' "$f" 2>/dev/null || echo "0")
        if [ "$EQ_COUNT" -ge 5 ]; then
            pass "$(basename "$f") has ${EQ_COUNT} equation blocks (≥5 expected)"
        else
            warn "$(basename "$f") has ${EQ_COUNT} equation blocks (expected ≥5)"
        fi
    done
else
    warn "No derivation checkpoint files found to check equation count"
fi

echo ""

# ---------------------------------------------------------------------------
# Flaw #5: Visualizations
# ---------------------------------------------------------------------------
echo "--- Flaw #5: Visualizations ---"

FIG_COUNT=$(find "${WORKDIR}/figures" -name "*.png" -o -name "*.pdf" -o -name "*.svg" 2>/dev/null | wc -l)
if [ "$FIG_COUNT" -ge 1 ]; then
    pass "Found ${FIG_COUNT} figure file(s) in figures/"
else
    fail "No figures generated in figures/"
fi

VIZ_SCRIPTS=$(find "${WORKDIR}/scripts" -name "viz_*.py" 2>/dev/null | wc -l)
if [ "$VIZ_SCRIPTS" -ge 1 ]; then
    pass "Found ${VIZ_SCRIPTS} visualization script(s) in scripts/"
else
    warn "No visualization scripts (viz_*.py) found in scripts/"
fi

# Check if figures are referenced inline in checkpoints (not in a separate section)
FIG_REFS_IN_CHECKPOINTS=$(grep -rlc "fig_\|\.png\|\.pdf\|includegraphics" "${WORKDIR}/checkpoints/" 2>/dev/null || echo "0")
if [ "$FIG_REFS_IN_CHECKPOINTS" -gt 0 ]; then
    pass "Figures are referenced in ${FIG_REFS_IN_CHECKPOINTS} checkpoint file(s)"
else
    warn "No figure references found in checkpoint files"
fi

echo ""

# ---------------------------------------------------------------------------
# Report quality
# ---------------------------------------------------------------------------
echo "--- Report Quality ---"

TEX_FILE=$(find "${WORKDIR}" -name "*.tex" -not -path "*/\.*" 2>/dev/null | head -1)
if [ -n "$TEX_FILE" ]; then
    if grep -q "includegraphics" "$TEX_FILE" 2>/dev/null; then
        pass "LaTeX report includes \\includegraphics"
    else
        warn "LaTeX report has no \\includegraphics — figures may be missing"
    fi

    PDF_FILE="${TEX_FILE%.tex}.pdf"
    if [ -f "$PDF_FILE" ]; then
        pass "PDF report compiled successfully: $(basename "$PDF_FILE")"
    else
        warn "PDF not found — report may not have been compiled"
    fi
else
    warn "No .tex file found in working directory"
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
