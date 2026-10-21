"""Static public tool registry and CLI/MCP adapters."""

import json
import sys
from cite_check_engine import acquisition as _engine_acquisition
from cite_check_engine import admin as _engine_admin
from cite_check_engine import audit as _engine_audit
from cite_check_engine import bibliography as _engine_bibliography
from cite_check_engine import discovery as _engine_discovery
from cite_check_engine import evidence as _engine_evidence
from cite_check_engine import jobs as _engine_jobs
from cite_check_engine import manuscripts as _engine_manuscripts
from cite_check_engine import reporting as _engine_reporting
from cite_check_engine import resolution as _engine_resolution


TOOLS = {
    "register_input": _engine_manuscripts.register_input,
    "ping": _engine_admin.ping,
    "resolve_citation": _engine_resolution.resolve_citation,
    "search_citation": _engine_discovery.search_citation,
    "fetch_bibtex": _engine_bibliography.fetch_bibtex,
    "bib_add": _engine_bibliography.bib_add,
    "verify_bib": _engine_bibliography.verify_bib,
    "lint_bib": _engine_bibliography.lint_bib,
    "extract_cites": _engine_manuscripts.extract_cites,
    "register_claims": _engine_evidence.register_claims,
    "fetch_text": _engine_acquisition.fetch_text,
    "find_passages": _engine_acquisition.find_passages,
    "record_support": _engine_evidence.record_support,
    "ledger_read": _engine_evidence.ledger_read,
    "audit": _engine_audit.audit,
    "correction_report": _engine_reporting.correction_report,
    "verification_job": _engine_jobs.verification_job,
}

def _run_mcp_server():
    try:
        from mcp.server import MCPServer as ServerClass          # mcp >= 2.0
    except ImportError:
        try:
            from mcp.server.fastmcp import FastMCP as ServerClass  # mcp 1.x
        except ImportError:
            sys.exit("The `mcp` package is not installed. Run mcp/setup_mcp.sh, or use "
                     "CLI mode: server.py call <tool> '<json>'")
    app = ServerClass("cite-check")
    for fn in TOOLS.values():
        app.tool()(fn)
    app.run()

def _run_cli(argv):
    if argv and argv[0] == "keys":
        return _engine_admin._run_keys(argv[1:])
    if not argv or argv[0] in ("-h", "--help") or argv[0] != "call":
        names = "\n  ".join(TOOLS)
        sys.exit(f"usage: server.py                      (MCP stdio server)\n"
                 f"       server.py call <tool> '<json-args>'\n"
                 "       server.py keys list|set <name>|delete <name>|"
                 "test ads|github|semanticscholar   (API keys)\n\n"
                 f"tools:\n  {names}")
    if len(argv) < 2 or argv[1] not in TOOLS:
        sys.exit(f"unknown tool {argv[1] if len(argv) > 1 else '(none)'!r} — one of: {', '.join(TOOLS)}")
    try:
        kwargs = json.loads(argv[2]) if len(argv) > 2 else {}
    except json.JSONDecodeError as exc:
        sys.exit(f"invalid JSON args: {exc}")
    result = TOOLS[argv[1]](**kwargs)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if isinstance(result, dict) and (result.get("error") or result.get("ok") is False
                                     or result.get("resolved") is False or result.get("recorded") is False
                                     or (argv[1] == "fetch_bibtex" and not result.get("bibtex"))):
        sys.exit(1)
