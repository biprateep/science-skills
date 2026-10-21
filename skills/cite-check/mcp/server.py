#!/usr/bin/env python3
"""Public CLI/MCP entrypoint for the modular citation integrity engine."""

import pathlib
import sys

# Script, symlink and importlib entrypoints use the adjacent package.
_PACKAGE_ROOT = pathlib.Path(__file__).resolve().parent
_loaded = sys.modules.get("cite_check_engine")
if _loaded is not None:
    _origin = getattr(_loaded, "__file__", None)
    if (
        not _origin
        or pathlib.Path(_origin).resolve().parent
        != _PACKAGE_ROOT / "cite_check_engine"
    ):
        raise ImportError(
            "a different cite_check_engine checkout is already imported"
        )
if str(_PACKAGE_ROOT) not in sys.path[:1]:
    sys.path.insert(0, str(_PACKAGE_ROOT))
# These imports must follow the resolved-checkout bootstrap.
from cite_check_engine import api  # noqa: E402
from cite_check_engine import config  # noqa: E402
from cite_check_engine import manuscripts  # noqa: E402
from cite_check_engine import models  # noqa: E402

VERSION = config.VERSION
TOOLS = api.TOOLS
register_input = api.TOOLS["register_input"]
ping = api.TOOLS["ping"]
resolve_citation = api.TOOLS["resolve_citation"]
search_citation = api.TOOLS["search_citation"]
fetch_bibtex = api.TOOLS["fetch_bibtex"]
bib_add = api.TOOLS["bib_add"]
verify_bib = api.TOOLS["verify_bib"]
lint_bib = api.TOOLS["lint_bib"]
extract_cites = api.TOOLS["extract_cites"]
register_claims = api.TOOLS["register_claims"]
fetch_text = api.TOOLS["fetch_text"]
find_passages = api.TOOLS["find_passages"]
record_support = api.TOOLS["record_support"]
ledger_read = api.TOOLS["ledger_read"]
audit = api.TOOLS["audit"]
correction_report = api.TOOLS["correction_report"]
verification_job = api.TOOLS["verification_job"]
VerificationBudget = models.VerificationBudget
ClaimPriority = models.ClaimPriority
InputCitation = models.InputCitation
AtomicClaim = models.AtomicClaim
ProposedCorrection = models.ProposedCorrection
BibliographyItem = models.BibliographyItem


if __name__ == "__main__":
    if sys.argv[1:] == ["_extract-pdf"]:
        manuscripts._input_pdf_worker()  # noqa: SLF001
    elif len(sys.argv) > 1:
        api._run_cli(sys.argv[1:])  # noqa: SLF001
    else:
        api._run_mcp_server()  # noqa: SLF001
