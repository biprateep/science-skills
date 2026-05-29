#!/bin/bash

# Compile a LaTeX report into a PDF safely
# Usage: ./compile_report.sh <filename_without_extension>

if [ -z "$1" ]; then
    echo "Usage: $0 <filename_without_extension>"
    exit 1
fi

FILE=$1

if [ ! -f "${FILE}.tex" ]; then
    echo "Error: ${FILE}.tex not found!"
    exit 1
fi

echo "Compiling ${FILE}.tex..."

# Run pdflatex (with interaction mode batchmode to avoid hanging)
pdflatex -interaction=nonstopmode "${FILE}.tex"

# Check if compiling succeeded
if [ $? -ne 0 ]; then
    echo "pdflatex encountered errors. Check ${FILE}.log for details."
fi

# Run bibtex if .bib file is used and cited
if [ -f "${FILE}.bib" ]; then
    bibtex "${FILE}"
    pdflatex -interaction=nonstopmode "${FILE}.tex"
    pdflatex -interaction=nonstopmode "${FILE}.tex"
fi

echo "Compilation process finished."
if [ -f "${FILE}.pdf" ]; then
    echo "Successfully generated ${FILE}.pdf"
else
    echo "Failed to generate ${FILE}.pdf"
fi
