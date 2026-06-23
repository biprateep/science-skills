#!/bin/bash
# ==============================================================================
# Compile a LaTeX report into a PDF, safely and with honest failure detection.
#
# Usage: bash compile_report.sh [filename_without_extension]
#   filename defaults to "report".
#
# Run this FROM the working directory that contains <filename>.tex and figures/
# (copy resources/paper_template.tex there as report.tex first — see
# references/protocols/reporting.md). Do not compile the bundled template
# in place.
# ==============================================================================

set -uo pipefail   # NOT -e: pdflatex's nonzero exits in nonstopmode are expected.

FILE="${1:-report}"          # default basename
FILE="${FILE%.tex}"          # tolerate a passed-in .tex extension

if [ ! -f "${FILE}.tex" ]; then
    echo "Error: ${FILE}.tex not found in $(pwd)." >&2
    echo "Copy resources/paper_template.tex here as ${FILE}.tex and retry." >&2
    exit 1
fi

# Remove any stale PDF so the final existence check can't pass on an old build.
rm -f "${FILE}.pdf"

echo "Compiling ${FILE}.tex ..."
pdflatex -interaction=nonstopmode "${FILE}.tex" >/dev/null 2>&1 || true

# Run bibtex ONLY when both a .bib exists AND an active \bibliography{...} is
# present (an uncommented line, ignoring % comments).
if [ -f "${FILE}.bib" ] && grep -Eq '^[^%]*\\bibliography\{' "${FILE}.tex"; then
    echo "Bibliography detected — running bibtex ..."
    bibtex "${FILE}" >/dev/null 2>&1 || true
    pdflatex -interaction=nonstopmode "${FILE}.tex" >/dev/null 2>&1 || true
    pdflatex -interaction=nonstopmode "${FILE}.tex" >/dev/null 2>&1 || true
elif [ -f "${FILE}.bib" ]; then
    echo "Note: ${FILE}.bib exists but no active \\bibliography{...} in ${FILE}.tex — skipping bibtex."
fi

# Honest error reporting: trust the .log, not the exit code.
if grep -q '^!' "${FILE}.log" 2>/dev/null; then
    echo ""
    echo "LaTeX reported errors (see ${FILE}.log):"
    grep -A2 '^!' "${FILE}.log" | head -n 40
fi

echo ""
if [ -f "${FILE}.pdf" ]; then
    echo "Successfully generated ${FILE}.pdf"
    exit 0
else
    echo "Failed to generate ${FILE}.pdf — check ${FILE}.log."
    exit 1
fi
