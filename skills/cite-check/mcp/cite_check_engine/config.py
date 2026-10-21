"""Process configuration and shared runtime state; no service imports."""

import os
import threading


VERSION = "0.10.0"

CACHE_DIR = os.environ.get("CITE_CHECK_CACHE") or os.path.join(
    os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "cite-check")

META_TTL = int(os.environ.get("CITE_CHECK_TTL_DAYS", "14")) * 86400   # registry metadata

NEG_TTL = 86400                                                       # cached 404s

PROJECT_DIR = ".cite-check"                                           # per-manuscript state

MAX_PDF_BYTES = 40 * 1024 * 1024

_HOST_INTERVAL = {
    "export.arxiv.org": 3.0, "arxiv.org": 1.0, "api.crossref.org": 0.15,
    "api.openalex.org": 0.15, "api.adsabs.harvard.edu": 0.25,
    "inspirehep.net": 0.5, "api.datacite.org": 0.25, "api.github.com": 0.25,
    "raw.githubusercontent.com": 0.1,
    "api.semanticscholar.org": 1.0, "eutils.ncbi.nlm.nih.gov": 0.35,
    "dblp.org": 1.0,
}

_host_last: dict = {}

_host_lock = threading.Lock()

EVIDENCE_POLICY = "exact-span-v1"

TEXT_EXTRACTION_VERSION = "text-v1"

ENTRYPOINT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "server.py")
