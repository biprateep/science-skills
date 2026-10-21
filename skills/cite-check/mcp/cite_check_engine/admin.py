"""Tool liveness and credential-management orchestration."""

import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
from cite_check_engine import config as _engine_config
from cite_check_engine import credentials as _engine_credentials
from cite_check_engine import registry_clients as _engine_registry_clients
from cite_check_engine import transport as _engine_transport


def _ads_test(token: str) -> dict:
    """Live check of a token against ADS (one tiny query, not cached)."""
    url = f"{_engine_registry_clients._ADS}/search/query?{urllib.parse.urlencode({'q': 'bibcode:2016A&A...594A..13P', 'fl': 'bibcode', 'rows': 1})}"
    try:
        status, _ = _engine_transport._http(url, headers={"Authorization": f"Bearer {token}"}, cache=False, timeout=20)
    except RuntimeError as exc:
        return {"ok": None, "detail": f"could not reach ADS ({exc}); stored untested"}
    if status == 200:
        return {"ok": True, "detail": "ADS accepted the token"}
    if status == 401:
        return {"ok": False, "detail": "ADS rejected the token (HTTP 401)"}
    return {"ok": None, "detail": f"ADS answered HTTP {status}; stored untested"}

def _semanticscholar_test(token: str) -> dict[str, Any]:
    """Check API authorization without logging secrets or response bodies."""
    try:
        status, _ = _engine_transport._http(
            "https://api.semanticscholar.org/graph/v1/paper/search?"
            "query=science&limit=1&fields=title",
            headers={"x-api-key": token},
            cache=False,
            timeout=20,
        )
    except RuntimeError:
        return {"ok": None, "detail": "Service unavailable; stored untested."}
    if status == 200:
        return {"ok": True, "detail": "Semantic Scholar accepted the key."}
    if status in {401, 403}:
        return {"ok": False, "detail": "Semantic Scholar rejected the key."}
    return {"ok": None, "detail": f"HTTP {status}; stored untested."}

def key_store(name: str, value: str, test: bool = True) -> dict:
    if name not in _engine_credentials.KEYS:
        return {"stored": False, "error": f"unknown key {name!r}; one of {list(_engine_credentials.KEYS)}"}
    spec, value = _engine_credentials.KEYS[name], (value or "").strip()
    if not value:
        return {"stored": False, "error": "empty value — nothing stored"}
    if spec["secret"] and re.search(r"[\s\"']", value):
        return {"stored": False, "error": "a token cannot contain whitespace or quotes — check the paste"}
    if name == "mailto" and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", value):
        return {"stored": False, "error": "that does not look like an e-mail address"}
    tested = None
    if name == "semanticscholar" and test:
        tested = _semanticscholar_test(value)
        if tested["ok"] is False:
            return dict(stored=False, error=tested["detail"], tested=tested)
    if name in ("ads", "github") and test:
        tested = _ads_test(value) if name == "ads" else _github_test(value)
        if tested["ok"] is False:
            return {"stored": False, "error": tested["detail"], "tested": tested}
    if spec["secret"]:
        backend = _engine_credentials._keyring_backend() if os.environ.get("CITE_CHECK_KEYRING", "auto").lower() == "auto" else None
        if backend and _engine_credentials._keyring_set(name, value):
            _engine_credentials._file_delete(name)
        else:
            _engine_credentials._file_set(name, value)
            backend = "file"
    else:
        cfg = _engine_credentials._config_read()
        cfg[name] = value
        _engine_credentials._config_write(cfg)
        backend = "config"
    _engine_credentials._key_cache["values"].pop(name, None)
    return {"stored": True, "backend": backend, "masked": _engine_credentials._mask(value) if spec["secret"] else value,
            "tested": tested, "where": _engine_credentials._file_key_path(name) if backend == "file" else
            (os.path.join(_engine_credentials._config_dir(), "config.json") if backend == "config" else backend)}

def _github_test(token: str) -> dict:
    """Live check of a token against GitHub (rate_limit costs no quota)."""
    try:
        status, body = _engine_registry_clients._gh_api("/rate_limit", token=token)
    except RuntimeError as exc:
        return {"ok": None, "detail": f"could not reach GitHub ({exc}); stored untested"}
    if status == 200:
        try:
            limit = json.loads(body)["resources"]["core"]["limit"]
        except (ValueError, KeyError, TypeError):
            limit = "?"
        return {"ok": True, "detail": f"GitHub accepted the token ({limit} requests/hour)"}
    if status == 401:
        return {"ok": False, "detail": "GitHub rejected the token (HTTP 401)"}
    return {"ok": None, "detail": f"GitHub answered HTTP {status}; stored untested"}

def ping() -> dict:
    """Liveness and capability check: token, PDF extractor, cache location."""
    info = {"ok": True, "server": "cite-check", "version": _engine_config.VERSION, "python": sys.version.split()[0],
            "ads_token": bool(_engine_credentials._ads_token()), "ads_token_source": _engine_credentials.key_value("ads")[1],
            "github_token": bool(_engine_credentials._github_token()), "github_token_source": _engine_credentials.key_value("github")[1],
            "keyring": _engine_credentials._keyring_backend() or "file", "config_dir": _engine_credentials._config_dir(),
            "pdftotext": bool(shutil.which("pdftotext")), "cache_dir": _engine_config.CACHE_DIR, "mailto": _engine_credentials._mailto() or None}
    if _engine_credentials._key_cache.get("warnings"):
        info["key_warnings"] = sorted(set(_engine_credentials._key_cache["warnings"]))
    try:
        import pypdf
        info["pypdf"] = pypdf.__version__
    except ImportError:
        info["pypdf"] = None
    try:
        import yaml
        info["pyyaml"] = yaml.__version__
    except ImportError:
        info["pyyaml"] = None
        info["yaml_warning"] = "PyYAML missing — GitHub repositories' CITATION.cff files are not read"
    try:
        import importlib.metadata as md
        info["mcp"] = md.version("mcp")
    except Exception:
        info["mcp"] = None
    if not info["ads_token"]:
        info["note"] = ("no ADS token — ADS search/export disabled (others active). Get one at "
                        "https://ui.adsabs.harvard.edu/user/settings/token and store it with "
                        "`bash mcp/setup_mcp.sh --keys` (or export ADS_API_TOKEN)")
    if not info["pdftotext"] and not info["pypdf"]:
        info["warning"] = "no PDF text extractor — full-text support checks limited to arXiv HTML and abstracts"
    return info

def _run_keys(argv):
    """server.py keys names | backend | fields <name> | list [--json] | set <name> [--no-test]
    (value on stdin) | test <name> | delete <name>|--all. Plain text for shell use."""
    sub = argv[0] if argv else "list"
    if sub == "names":
        print("\n".join(_engine_credentials.KEYS))
    elif sub == "backend":
        print(_engine_credentials._keyring_backend() or f"file ({os.path.join(_engine_credentials._config_dir(), 'keys')}, mode 0600)")
    elif sub == "fields" and len(argv) > 1 and argv[1] in _engine_credentials.KEYS:
        st = next(k for k in _engine_credentials.key_status() if k["name"] == argv[1])
        # unit separator: bash `read` keeps empty fields only for a non-blank IFS
        print("\x1f".join([st["label"], st["source"] if st["configured"] else "none", st["masked"] or "",
                           st["url"] or "", st["enables"], "1" if st["secret"] else "0"]))
    elif sub == "list":
        rows = _engine_credentials.key_status()
        if "--json" in argv:
            print(json.dumps(rows, indent=2, ensure_ascii=False))
        else:
            for k in rows:
                state = f"{k['source']} ({k['masked']})" if k["configured"] else "not configured"
                print(f"{k['name']:8s} {k['label']}: {state}")
            for w in sorted(set(_engine_credentials._key_cache.get("warnings", []))):
                print(f"WARNING: {w}")
    elif sub == "set" and len(argv) > 1:
        value = sys.stdin.read().strip()
        r = key_store(argv[1], value, test="--no-test" not in argv)
        if not r["stored"]:
            sys.exit(f"not stored: {r['error']}")
        line = f"stored in {r['backend']}" + (f" at {r['where']}" if r["backend"] in ("file", "config") else "")
        if r.get("tested"):
            line += f"; {r['tested']['detail']}"
        print(line)
    elif (sub == "test" and len(argv) > 1
          and argv[1] in ("ads", "github", "semanticscholar")):
        tok = _engine_credentials.key_value(argv[1])[0]
        if not tok:
            sys.exit(f"no {argv[1]} token configured")
        testers = {"ads": _ads_test, "github": _github_test,
                   "semanticscholar": _semanticscholar_test}
        r = testers[argv[1]](tok)
        print(r["detail"])
        sys.exit(0 if r["ok"] else 1)
    elif sub == "delete" and len(argv) > 1:
        names = list(_engine_credentials.KEYS) if argv[1] == "--all" else [argv[1]]
        for n in names:
            r = _engine_credentials.key_delete(n)
            print(f"{n}: " + (f"removed from {', '.join(r['removed_from'])}" if r["deleted"] else r.get("error") or "nothing stored"))
    else:
        sys.exit(
            "usage: server.py keys names|backend|fields <name>|list [--json]|"
            "set <name> [--no-test]|test ads|github|semanticscholar|"
            "delete <name>|--all")
