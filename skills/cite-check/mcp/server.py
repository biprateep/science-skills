#!/usr/bin/env python3
"""cite-check MCP toolbox — citation existence, provenance and claim-support checks.

Dual interface, same code paths:

  python3 server.py                          # MCP stdio server (needs `mcp` pkg)
  python3 server.py call <tool> '<json>'     # CLI mode (no `mcp` pkg needed)

Every verdict the skill relies on is computed here rather than narrated by the
agent: registry lookups, title/author/year comparison, official BibTeX export,
verbatim-quote verification against the cited paper's own text, and the audit
gate. See skills/cite-check/SKILL.md and references/registries.md.
"""

import concurrent.futures
import contextlib
import contextvars
import dataclasses
import functools
import tempfile
from collections import Counter
import difflib
import hashlib
import importlib.metadata
import io
import logging
import html
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
import uuid
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Literal
from collections.abc import Callable

VERSION = "0.9.0"

# ---------------------------------------------------------------------------
# configuration, cache, HTTP
# ---------------------------------------------------------------------------

CACHE_DIR = os.environ.get("CITE_CHECK_CACHE") or os.path.join(
    os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "cite-check")
META_TTL = int(os.environ.get("CITE_CHECK_TTL_DAYS", "14")) * 86400   # registry metadata
NEG_TTL = 86400                                                       # cached 404s
PROJECT_DIR = ".cite-check"                                           # per-manuscript state
MAX_PDF_BYTES = 40 * 1024 * 1024

# Registries publish these as their politeness rules (arXiv: one request per
# three seconds). Batched lookups keep the arXiv wait from dominating.
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


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@contextlib.contextmanager
def _file_lock(path: str):
    """Serialize a file transaction across threads and server processes."""
    lock_path = os.path.abspath(path) + ".lock"
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    with open(lock_path, "a+b") as lock:
        if os.name == "nt":
            import msvcrt
            lock.write(b"0")
            lock.flush()
        else:
            import fcntl
        budget = _request_budget.get()
        lock_timeout = min(120, budget.remaining()) if budget else 120
        deadline = time.monotonic() + lock_timeout
        while True:
            try:
                if os.name == "nt":
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (BlockingIOError, OSError):
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"timed out locking {path}")
                if budget is not None:
                    budget.sleep(min(0.02, budget.remaining() / 2))
                else:
                    time.sleep(0.02)
        try:
            yield
        finally:
            if os.name == "nt":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _atomic_write(path: str, content: str | bytes) -> None:
    """Publish a complete file with a unique same-directory temporary file."""
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=os.path.dirname(path))
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content.encode("utf-8") if isinstance(content, str) else content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _serialized_bibliography(function):
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        path = args[0] if args else kwargs["bib_path"]
        with _file_lock(os.path.realpath(path)):
            return function(*args, **kwargs)
    return wrapped


def _cache_file(kind: str, name: str) -> str:
    d = os.path.join(CACHE_DIR, kind)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name)


# ---------------------------------------------------------------------------
# API keys — OS keychain when there is one, else a 0600 file. Secrets never
# travel through argv (visible in `ps`), harness config files, or logs.
# ---------------------------------------------------------------------------

_SERVICE = "cite-check"
KEYS = {
    "ads": {"label": "NASA ADS API token", "secret": True,
            "env": ("ADS_API_TOKEN", "ADS_DEV_KEY", "ADS_TOKEN"),
            "legacy_files": ("~/.ads/dev_key", "~/.config/cite-check/ads_token"),
            "url": "https://ui.adsabs.harvard.edu/user/settings/token",
            "enables": "ADS search, bibcode resolution and ADS BibTeX export (astronomy/physics)"},
    "mailto": {"label": "contact e-mail for the Crossref/OpenAlex polite pools", "secret": False,
               "env": ("CITE_CHECK_MAILTO",), "legacy_files": (), "url": None,
               "enables": "faster, more reliable Crossref and OpenAlex answers (optional, not a key)"},
    "semanticscholar": {
        "label": "Semantic Scholar API key (optional discovery)",
        "secret": True, "env": ("SEMANTIC_SCHOLAR_API_KEY", "S2_API_KEY"),
        "legacy_files": (),
        "url": "https://www.semanticscholar.org/product/api",
        "enables": "optional Semantic Scholar discovery (not verification)",
    },
    "github": {"label": "GitHub token (read-only, no scopes needed)", "secret": True,
               "env": ("GITHUB_TOKEN", "GH_TOKEN"), "legacy_files": (),
               "url": "https://github.com/settings/personal-access-tokens/new",
               "enables": "GitHub repository checks at 5000 requests/hour instead of 60 (public repositories work without it)"},
}
_key_cache: dict = {"values": {}}


def _config_dir() -> str:
    return os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), _SERVICE)


def _keyring_backend() -> str | None:
    """'macos-keychain' | 'secret-tool' | None, probed once per process.
    CITE_CHECK_KEYRING=file forces the file store; =off disables stored keys."""
    if "backend" in _key_cache:
        return _key_cache["backend"]
    backend = None
    if os.environ.get("CITE_CHECK_KEYRING", "auto").lower() == "auto":
        try:
            if sys.platform == "darwin" and shutil.which("security"):
                backend = "macos-keychain"
            elif shutil.which("secret-tool") and os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
                r = subprocess.run(["secret-tool", "lookup", "service", _SERVICE, "key", "__probe__"],
                                   capture_output=True, text=True, timeout=8)
                if r.returncode in (0, 1) and not r.stderr.strip():   # 1 = not found, no daemon error
                    backend = "secret-tool"
        except (subprocess.TimeoutExpired, OSError):
            backend = None
    _key_cache["backend"] = backend
    return backend


def _keyring_get(name: str) -> str | None:
    b = _keyring_backend()
    try:
        if b == "macos-keychain":
            r = subprocess.run(["security", "find-generic-password", "-s", _SERVICE, "-a", name, "-w"],
                               capture_output=True, text=True, timeout=10)
        elif b == "secret-tool":
            r = subprocess.run(["secret-tool", "lookup", "service", _SERVICE, "key", name],
                               capture_output=True, text=True, timeout=10)
        else:
            return None
        return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None
    except (subprocess.TimeoutExpired, OSError):
        return None


def _keyring_set(name: str, value: str) -> bool:
    b = _keyring_backend()
    try:
        if b == "macos-keychain":   # `security -i` reads the command from stdin: the secret stays off argv
            cmd = f'add-generic-password -U -s "{_SERVICE}" -a "{name}" -l "{_SERVICE} {name}" -w "{value}"\n'
            r = subprocess.run(["security", "-i"], input=cmd, capture_output=True, text=True, timeout=15)
        elif b == "secret-tool":
            r = subprocess.run(["secret-tool", "store", f"--label={_SERVICE} {name}", "service", _SERVICE, "key", name],
                               input=value, capture_output=True, text=True, timeout=15)
        else:
            return False
        return r.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _keyring_delete(name: str) -> bool:
    b = _keyring_backend()
    try:
        if b == "macos-keychain":
            r = subprocess.run(["security", "delete-generic-password", "-s", _SERVICE, "-a", name],
                               capture_output=True, text=True, timeout=10)
        elif b == "secret-tool":
            r = subprocess.run(["secret-tool", "clear", "service", _SERVICE, "key", name],
                               capture_output=True, text=True, timeout=10)
        else:
            return False
        return r.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _file_key_path(name: str) -> str:
    return os.path.join(_config_dir(), "keys", name)


def _file_get(name: str) -> str | None:
    path = _file_key_path(name)
    if not os.path.exists(path):
        return None
    if os.stat(path).st_mode & 0o077:
        _key_cache.setdefault("warnings", []).append(f"{path} is readable by others — run: chmod 600 {path}")
    with open(path) as fh:
        return fh.read().strip() or None


def _file_set(name: str, value: str) -> None:
    path = _file_key_path(name)
    d = os.path.dirname(path)
    os.makedirs(d, mode=0o700, exist_ok=True)
    os.chmod(_config_dir(), 0o700)      # makedirs applies the mode to the leaf only
    os.chmod(d, 0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(value + "\n")
    os.chmod(path, 0o600)


def _config_read() -> dict:
    path = os.path.join(_config_dir(), "config.json")
    if os.path.exists(path):
        try:
            with open(path) as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}
    return {}


def _config_write(cfg: dict) -> None:
    os.makedirs(_config_dir(), mode=0o700, exist_ok=True)
    os.chmod(_config_dir(), 0o700)
    path = os.path.join(_config_dir(), "config.json")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(cfg, fh, indent=2)


def key_value(name: str) -> tuple:
    """(value | None, source) for a configured key: environment first, then
    the keychain, the 0600 file, legacy files; non-secrets from config.json.
    Cached per process — the keychain is a subprocess call."""
    spec = KEYS[name]
    for var in spec["env"]:
        if os.environ.get(var, "").strip():
            return os.environ[var].strip(), f"env:{var}"
    if name in _key_cache["values"]:
        return _key_cache["values"][name]
    value, source = None, "none"
    if os.environ.get("CITE_CHECK_KEYRING", "auto").lower() != "off":
        if spec["secret"]:
            value = _keyring_get(name)
            source = _keyring_backend() or "none"
            if not value:
                value, source = _file_get(name), "file"
            if not value:
                for lf in spec["legacy_files"]:
                    path = os.path.expanduser(lf)
                    if os.path.exists(path):
                        with open(path) as fh:
                            value = fh.read().strip() or None
                        if value:
                            source = f"legacy-file:{lf}"
                            break
        else:
            value, source = _config_read().get(name), "config"
    if not value:
        source = "none"
    _key_cache["values"][name] = (value, source)
    return value, source


def _mask(value: str) -> str:
    return ("…" + value[-4:]) if len(value) >= 8 else "…"


def _ads_test(token: str) -> dict:
    """Live check of a token against ADS (one tiny query, not cached)."""
    url = f"{_ADS}/search/query?{urllib.parse.urlencode({'q': 'bibcode:2016A&A...594A..13P', 'fl': 'bibcode', 'rows': 1})}"
    try:
        status, _ = _http(url, headers={"Authorization": f"Bearer {token}"}, cache=False, timeout=20)
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
        status, _ = _http(
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
    if name not in KEYS:
        return {"stored": False, "error": f"unknown key {name!r}; one of {list(KEYS)}"}
    spec, value = KEYS[name], (value or "").strip()
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
        backend = _keyring_backend() if os.environ.get("CITE_CHECK_KEYRING", "auto").lower() == "auto" else None
        if backend and _keyring_set(name, value):
            _file_delete(name)
        else:
            _file_set(name, value)
            backend = "file"
    else:
        cfg = _config_read()
        cfg[name] = value
        _config_write(cfg)
        backend = "config"
    _key_cache["values"].pop(name, None)
    return {"stored": True, "backend": backend, "masked": _mask(value) if spec["secret"] else value,
            "tested": tested, "where": _file_key_path(name) if backend == "file" else
            (os.path.join(_config_dir(), "config.json") if backend == "config" else backend)}


def _file_delete(name: str) -> bool:
    path = _file_key_path(name)
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


def key_delete(name: str) -> dict:
    if name not in KEYS:
        return {"deleted": False, "error": f"unknown key {name!r}"}
    removed = []
    if KEYS[name]["secret"]:
        if _keyring_delete(name):
            removed.append(_keyring_backend())
        if _file_delete(name):
            removed.append("file")
    else:
        cfg = _config_read()
        if name in cfg:
            del cfg[name]
            _config_write(cfg)
            removed.append("config")
    _key_cache["values"].pop(name, None)
    return {"deleted": bool(removed), "removed_from": removed}


def key_status() -> list:
    out = []
    for name, spec in KEYS.items():
        value, source = key_value(name)
        out.append({"name": name, "label": spec["label"], "secret": spec["secret"], "url": spec["url"],
                    "enables": spec["enables"], "configured": bool(value), "source": source,
                    "masked": (_mask(value) if spec["secret"] else value) if value else None})
    return out


def _mailto() -> str:
    return (key_value("mailto")[0] or "").strip()


def _user_agent() -> str:
    ua = f"cite-check/{VERSION} (+https://github.com/biprateep/science-skills"
    return ua + (f"; mailto:{_mailto()})" if _mailto() else ")")


@dataclasses.dataclass
class VerificationBudget:
    """Per-run admission limits; seconds are a cooperative deadline.

    Known public registry service fees are estimated as zero under the
    documented pricing policy. Actual billed costs are not measured.
    """

    __pydantic_config__ = {"extra": "forbid"}

    max_requests: int = dataclasses.field(default=50, metadata={"strict": True})
    max_searches: int = dataclasses.field(default=10, metadata={"strict": True})
    max_seconds: float = dataclasses.field(
        default=60.0, metadata={"strict": True}
    )
    max_cost_usd: float | None = dataclasses.field(
        default=0.0, metadata={"strict": True}
    )


@dataclasses.dataclass
class ClaimPriority:
    """Caller-assigned scheduling advice for one current support requirement."""

    __pydantic_config__ = {"extra": "forbid"}

    occurrence_id: str
    reason: str
    priority: Literal["high", "normal", "low"] = "high"
    atom_id: str | None = None


class BudgetExhaustedError(RuntimeError):
    """A registry operation was not admitted; this is never absence evidence."""


# This context is per invocation, explicitly copied into existing workers.
# The shared budget object serializes reservations within one job only.
_request_budget: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "citation_request_budget", default=None
)
_PUBLIC_ZERO_FEE_HOSTS = frozenset({
    "api.adsabs.harvard.edu", "api.crossref.org", "api.datacite.org",
    "api.github.com", "api.openalex.org", "export.arxiv.org", "arxiv.org",
    "inspirehep.net", "github.com", "raw.githubusercontent.com",
    "api.semanticscholar.org", "eutils.ncbi.nlm.nih.gov", "dblp.org",
})
_JOB_POLICY = "prioritized-identity-v1"
_PRICING_POLICY = "public-registry-service-fee-zero-v1"


def _validated_budget(
    value: VerificationBudget | dict[str, Any] | None,
) -> dict[str, Any]:
    """Validate CLI input as strictly as the native nested schema."""
    defaults = dataclasses.asdict(VerificationBudget())
    supplied = (
        dataclasses.asdict(value)
        if isinstance(value, VerificationBudget)
        else value
    )
    if supplied is None:
        return defaults
    if not isinstance(supplied, dict) or set(supplied) - set(defaults):
        raise ValueError("budget must contain only documented limits")
    defaults.update(supplied)
    for name in ("max_requests", "max_searches"):
        if type(defaults[name]) is not int or defaults[name] < 0:
            raise ValueError(f"{name} must be a nonnegative integer")
    for name in ("max_seconds", "max_cost_usd"):
        number = defaults[name]
        if number is None and name == "max_cost_usd":
            continue
        if (
            type(number) not in (int, float)
            or not math.isfinite(number)
            or number < 0
        ):
            raise ValueError(f"{name} must be a finite nonnegative number")
    return defaults


class _RequestBudget:
    """Share and durably account admission reservations across workers."""

    def __init__(
        self, limits: dict[str, Any], persist: Callable[[dict[str, Any]], None]
    ) -> None:
        self.limits = limits
        self.persist = persist
        self.started = time.monotonic()
        self.lock = threading.RLock()
        self.requests = 0
        self.searches = 0
        self.http_cache_hits = 0
        self.unknown_price_requests = 0
        self.stopped: str | None = None

    def usage(self) -> dict[str, Any]:
        """Return elapsed time and conservative admitted work counts."""
        with self.lock:
            elapsed = max(0.0, time.monotonic() - self.started)
            return {
                "requests": self.requests,
                "searches": self.searches,
                "http_cache_hits": self.http_cache_hits,
                "elapsed_seconds": elapsed,
                "unknown_price_requests": self.unknown_price_requests,
                "estimated_service_cost_usd": None
                if self.unknown_price_requests
                else 0.0,
                "actual_billed_cost_usd": None,
                "model_tokens": None,
                "model_calls": 0,
                "external_model_cost_usd": None,
                "deadline_exceeded": elapsed > self.limits["max_seconds"],
                "deadline_overshoot_seconds": max(
                    0.0, elapsed - self.limits["max_seconds"]
                ),
                "stop_reason": self.stopped,
            }

    def stop(self, reason: str) -> None:
        self.stopped = self.stopped or reason
        raise BudgetExhaustedError(self.stopped)

    def remaining(self) -> float:
        """Refuse work after any budget denial or cooperative deadline."""
        with self.lock:
            if self.stopped:
                raise BudgetExhaustedError(self.stopped)
            remaining = self.limits["max_seconds"] - (
                time.monotonic() - self.started
            )
            if remaining <= 0:
                self.stop("deadline")
            return remaining

    def sleep(self, seconds: float) -> None:
        """Do not begin throttle/backoff waits exceeding the remaining grant."""
        with self.lock:
            if seconds >= self.remaining():
                self.stop("deadline-before-wait")
        time.sleep(seconds)
        self.remaining()

    def cache_hit(self) -> None:
        """Count HTTP-cache reuse separately from request reservations."""
        with self.lock:
            self.remaining()
            self.http_cache_hits += 1
            self.persist(self.usage())

    def reserve(self, kind: str, url: str | None = None) -> None:
        """Persist an upper-bound reservation before sending any operation."""
        with self.lock:
            self.remaining()
            field = "requests" if kind == "request" else "searches"
            if getattr(self, field) >= self.limits["max_" + field]:
                self.stop(field)
            unknown = False
            if kind == "request":
                parsed = urllib.parse.urlparse(url or "")
                unknown = (
                    parsed.scheme not in {"https", "http"}
                    or parsed.hostname not in _PUBLIC_ZERO_FEE_HOSTS
                )
                if unknown and self.limits["max_cost_usd"] is not None:
                    self.stop("unknown-request-price")
            setattr(self, field, getattr(self, field) + 1)
            self.unknown_price_requests += int(unknown)
            self.persist(self.usage())
            self.remaining()


def _context_map(
    executor: Any, function: Callable[..., Any], values: Any
) -> list[Any]:
    """Propagate invocation-local limits to each existing executor worker."""
    futures = [
        executor.submit(contextvars.copy_context().run, function, value)
        for value in values
    ]
    return [future.result() for future in futures]


def _budget_sleep(seconds: float) -> None:
    budget = _request_budget.get()
    if budget is None:
        time.sleep(seconds)
    else:
        budget.sleep(seconds)


class _BudgetRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Disable implicit redirects so each physical request is admitted here."""

    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        del req, fp, code, msg, headers, newurl
        return None


def _budget_open(request: Any, timeout: float) -> Any:
    """Close redirect bodies and admit each hop immediately before opening."""
    budget = _request_budget.get()
    credential_header = any(name.lower() == "x-api-key"
                            for name, _ in request.header_items())
    if credential_header:
        # Never forward API keys, even to same-origin or downgrade redirects.
        opener = urllib.request.build_opener(_BudgetRedirectHandler())
        if budget is not None:
            budget.reserve("request", request.full_url)
            timeout = min(timeout, budget.remaining())
        return opener.open(request, timeout=timeout)
    if budget is None:
        return urllib.request.urlopen(request, timeout=timeout)
    opener = urllib.request.build_opener(_BudgetRedirectHandler())
    visited: dict[str, int] = {}
    while True:
        budget.reserve("request", request.full_url)
        try:
            return opener.open(
                request, timeout=min(timeout, budget.remaining())
            )
        except urllib.error.HTTPError as error:
            location = error.headers.get("location") or error.headers.get("uri")
            if error.code not in {301, 302, 303, 307, 308} or not location:
                raise
            try:
                target = urllib.parse.urljoin(request.full_url, location)
                if urllib.parse.urlparse(target).scheme not in {
                    "http",
                    "https",
                }:
                    budget.stop("unsupported-redirect-protocol")
                target = urllib.parse.quote(target, safe=":/?#[]@!$&'()*+,;=%")
                visited[target] = visited.get(target, 0) + 1
                if visited[target] > 4 or sum(visited.values()) > 10:
                    raise RuntimeError("redirect limit exceeded")
                response_headers: Any = error.headers
                redirected = (
                    urllib.request.HTTPRedirectHandler().redirect_request(
                        request,
                        error,
                        error.code,
                        error.msg,
                        response_headers,
                        target,
                    )
                )
                if redirected is None:
                    raise RuntimeError("redirect method refused")
                if (
                    urllib.parse.urlparse(target).scheme == "http"
                    and urllib.parse.urlparse(request.full_url).scheme
                    == "https"
                ):
                    budget.stop("insecure-redirect-downgrade")
                if (
                    urllib.parse.urlparse(target).netloc
                    != urllib.parse.urlparse(request.full_url).netloc
                ):
                    for name in ("Authorization", "Cookie"):
                        redirected.remove_header(name)
                request = redirected
            finally:
                error.close()
            # No unbounded drain of a redirect body. Throttle then reserve
            # at the top of the loop, with a fresh remaining-time check.
            _throttle(urllib.parse.urlparse(request.full_url).netloc)


def _budget_read(response: Any) -> bytes:
    """Check cooperative deadline between bounded reads, including errors."""
    budget = _request_budget.get()
    if budget is None:
        return response.read()
    chunks: list[bytes] = []
    while True:
        remaining = budget.remaining()
        stream = response
        socket = None
        for _ in range(3):
            stream = getattr(stream, "fp", None)
            socket = getattr(getattr(stream, "raw", None), "_sock", None)
            if socket is not None or stream is None:
                break
        if socket is not None:
            current = socket.gettimeout()
            socket.settimeout(
                min(current, remaining) if current is not None else remaining
            )
        read = getattr(response, "read1", response.read)
        chunk = read(65536)
        budget.remaining()
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _throttle(host: str) -> None:
    interval = _HOST_INTERVAL.get(host, 0.2)
    budget = _request_budget.get()
    acquired = (
        _host_lock.acquire(timeout=budget.remaining())
        if budget
        else _host_lock.acquire()
    )
    if not acquired:
        budget.stop("deadline-waiting-for-throttle")
    try:
        if budget is not None:
            budget.remaining()
        wait = _host_last.get(host, 0.0) + interval - time.monotonic()
        if wait > 0:
            _budget_sleep(wait)
        _host_last[host] = time.monotonic()
    finally:
        _host_lock.release()


def _http(url: str, method: str = "GET", data: bytes | None = None, headers: dict | None = None,
          timeout: int = 30, cache: bool = True, binary: bool = False, retries: int = 3):
    """Return (status, body). body is str, or bytes when binary=True.

    200 and 404 text responses are cached (404 for one day: a fabricated
    identifier stays fabricated; a freshly minted DOI shows up tomorrow).
    429/5xx are retried with backoff. Network failure raises RuntimeError.
    """
    budget = _request_budget.get()
    if budget is not None:
        budget.remaining()
    hdrs = {"User-Agent": _user_agent(), "Accept": "application/json, text/plain, */*"}
    hdrs.update(headers or {})
    cache_key = hashlib.sha1(
        f"{method} {url} {data.decode('utf-8', 'replace') if data else ''} "
        f"{hdrs.get('Accept', '')}".encode()).hexdigest()
    path = _cache_file("http", cache_key + ".json")
    if cache and not binary and os.path.exists(path):
        try:
            with open(path) as fh:
                hit = json.load(fh)
            ttl = META_TTL if hit["status"] == 200 else NEG_TTL
            if time.time() - hit["at"] < ttl:
                if budget is not None:
                    budget.cache_hit()
                return hit["status"], hit["body"]
        except (OSError, ValueError, KeyError):
            pass
    host = urllib.parse.urlparse(url).netloc
    last_error = None
    for attempt in range(1, retries + 1):
        _throttle(host)
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with _budget_open(req, timeout=timeout) as resp:
                raw = _budget_read(resp)
                status = resp.status
            body = raw if binary else raw.decode("utf-8", errors="replace")
            if cache and not binary and status == 200:
                _atomic_write(path, json.dumps(
                    {"status": status, "body": body, "at": time.time(), "url": url}
                ))
            return status, body
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                try:
                    delay = float(retry_after) if retry_after else 2.0 ** attempt
                except ValueError:
                    delay = 2.0 ** attempt
                exc.close()
                _budget_sleep(min(delay, 30))
                last_error = exc
                continue
            try:
                body = (b"" if binary else _budget_read(exc).decode(
                    "utf-8", errors="replace"
                ))
            finally:
                exc.close()
            if cache and not binary and exc.code == 404:
                _atomic_write(path, json.dumps(
                    {"status": 404, "body": "", "at": time.time(), "url": url}
                ))
            return exc.code, body
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt < retries:
                _budget_sleep(2.0 ** attempt)
                continue
    raise RuntimeError(f"{host}: {type(last_error).__name__}: {last_error}")


def _get_json(url: str, headers: dict | None = None, timeout: int = 30):
    status, body = _http(url, headers=headers, timeout=timeout)
    if status != 200:
        return status, None
    try:
        return status, json.loads(body)
    except ValueError:
        return status, None


def _chunks(seq, n):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


# ---------------------------------------------------------------------------
# text normalisation, similarity, names
# ---------------------------------------------------------------------------

_STOPWORDS = set("""a an and are as at be been but by can could did do does for from had has have
he her his how i if in into is it its may might more most no nor not of on one or our
own same she should so some such than that the their them then there these they this
those through to too under until up upon us use used using very via was we were what when made make makes based
where which while who whom why will with within without would you your also however
here paper show shows shown results result recent new find found given""".split())


def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()


def _strip_latex(s: str) -> str:
    s = re.sub(r"\\[a-zA-Z]+\*?\s*(?:\[[^\]]*\])?", " ", s or "")
    return s.replace("{", "").replace("}", "").replace("$", "").replace("~", " ")


def _norm_title(s: str) -> str:
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    s = _ascii(_strip_latex(s)).lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _title_sim(a: str, b: str) -> float:
    """Normalised title similarity in [0, 1]. Sequence ratio, or token
    containment for titles that merely reorder or extend each other (a
    Crossref title+subtitle against the same title written on one line)."""
    na, nb = _norm_title(a), _norm_title(b)
    if not na or not nb:
        return 0.0
    ratio = difflib.SequenceMatcher(None, na, nb).ratio()
    ta, tb = set(na.split()), set(nb.split())
    lo, hi = min(len(ta), len(tb)), max(len(ta), len(tb))
    if lo >= 4:      # word-order shuffles count; a title that merely contains the other does not
        ratio = max(ratio, 0.97 * (len(ta & tb) / lo) * (lo / hi) ** 0.35)
    return round(ratio, 3)


_PARTICLES = {"da", "de", "del", "della", "der", "di", "du", "la", "le", "van", "von", "den", "ter", "af"}
_COLLAB = re.compile(r"\b(collaboration|consortium|team|group|survey)\b", re.I)


def _surname(name: str) -> str:
    """Comparable surname token: 'Vaswani, Ashish' / 'Ashish Vaswani' / '{Planck
    Collaboration}' / 'van der Waals, J.' all reduce to one lowercase string."""
    name = _ascii(html.unescape(_strip_latex(name or ""))).strip()
    if not name:
        return ""
    if _COLLAB.search(name):
        words = [w for w in re.split(r"\s+", name) if w and not _COLLAB.match(w)
                 and w.lower() not in ("the", "scientific", "and")]
        return re.sub(r"[^a-z]", "", "".join(words).lower())
    if "," in name:
        fam = name.split(",", 1)[0]
    else:
        toks = name.split()
        fam = toks[-1] if toks else ""
        i = len(toks) - 2
        while i >= 0 and toks[i].lower() in _PARTICLES:   # J. D. van der Waals
            fam = toks[i] + fam
            i -= 1
    return re.sub(r"[^a-z]", "", fam.lower())


def _split_bib_authors(field: str) -> list:
    field = (field or "").replace("\n", " ")
    parts = re.split(r"\s+and\s+", field, flags=re.I)
    return [p.strip(" {}") for p in parts if p.strip(" {}")]


def _author_match(a: list, b: list) -> dict:
    """Compare two author lists (any name format). first: first surnames agree;
    any: some surname of a appears in b."""
    sa = [_surname(x) for x in (a or []) if _surname(x)]
    sb = [_surname(x) for x in (b or []) if _surname(x)]
    if not sa or not sb:
        return {"first": None, "any": None}
    return {"first": sa[0] == sb[0] or sa[0] in sb[0] or sb[0] in sa[0],
            "any": bool(set(sa) & set(sb))}


def _content_words(text: str) -> list:
    text = re.sub(r"\u27e8[^\u27e9]*\u27e9", " ", text or "")       # ⟨cite:…⟩ placeholders
    text = _ascii(_strip_latex(html.unescape(text))).lower()
    words = re.findall(r"[a-z][a-z0-9\-]{2,}|\d+(?:\.\d+)?", text)
    out = []
    for w in words:
        if w in _STOPWORDS:
            continue
        out.append(_stem(w))
    return out


def _stem(w: str) -> str:
    for suf in ("ies", "sses", "ing", "ed", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[:-len("ies")] + "y" if suf == "ies" else w[:-len(suf)]
    return w


# ---------------------------------------------------------------------------
# identifiers
# ---------------------------------------------------------------------------

_ARXIV_CORE = r"(?:\d{4}\.\d{4,5}|[a-z\-]+(?:\.[A-Za-z]{2})?/\d{7})"
_ARXIV_RE = re.compile(rf"^{_ARXIV_CORE}(?:v\d+)?$", re.I)
_ARXIV_ANY = re.compile(rf"(?<![\w/]){_ARXIV_CORE}(?:v\d+)?(?!\d)", re.I)
_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.I)
_DOI_ANY = re.compile(r"10\.\d{4,9}/[^\s\"'<>{}]+", re.I)
_BIBCODE_RE = re.compile(r"^\d{4}[A-Za-z0-9&.]{14}[A-Za-z.:]$")
_OPENALEX_RE = re.compile(r"^W\d{4,}$", re.I)
_GITHUB_RE = re.compile(r"^([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/([A-Za-z0-9._-]{1,100})$")
_GITHUB_ANY = re.compile(r"(?<!gist\.)github\.com[/:]([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/([A-Za-z0-9._-]{1,100})", re.I)
_GITHUB_REF = re.compile(r"github\.com/[^/\s]+/[^/\s]+/(?:tree|blob|commit|releases/tag)/([^/\s?#}]+)", re.I)
# first path segments of github.com that are site pages, not repository owners
_GITHUB_RESERVED = {"about", "apps", "collections", "contact", "customer-stories", "enterprise", "events",
                    "explore", "features", "issues", "login", "marketplace", "new", "notifications", "orgs",
                    "organizations", "pricing", "pulls", "search", "security", "settings", "site", "sponsors",
                    "topics", "trending", "users"}


def _strip_arxiv_version(s: str) -> str:
    return re.sub(r"v\d+$", "", s, flags=re.I)


def _classify(raw: str) -> tuple:
    """Map any identifier spelling (bare, prefixed, or URL) to (kind, value).
    kind ∈ arxiv | doi | bibcode | openalex | inspire | github | unknown."""
    s = (raw or "").strip().strip("<>").rstrip(".,;)")
    s = re.sub(r"^(?:https?://)?(?:www\.)?", "", s, flags=re.I)
    m = re.match(r"^(arxiv|doi|bibcode|ads|openalex|inspire|github|gh):\s*(.+)$", s, re.I)
    prefix, s = (m.group(1).lower(), m.group(2).strip()) if m else (None, s)
    url_rules = [
        (r"^arxiv\.org/(?:abs|pdf|html)/(.+?)(?:\.pdf)?/?$", "arxiv"),
        (r"^(?:dx\.)?doi\.org/(.+)$", "doi"),
        (r"^ui\.adsabs\.harvard\.edu/abs/([^/]+)(?:/.*)?$", "bibcode"),
        (r"^(?:api\.)?openalex\.org/(?:works/)?(W\d+)$", "openalex"),
        (r"^inspirehep\.net/(?:literature|api/literature)/(\d+)", "inspire"),
        (r"^(?:git@)?github\.com[/:]([^/\s]+/[^/\s#?]+)", "github"),
    ]
    for pat, kind in url_rules:
        m = re.match(pat, s, re.I)
        if m:
            prefix, s = kind, m.group(1)
            break
    if prefix in ("ads",):
        prefix = "bibcode"
    if prefix == "gh":
        prefix = "github"
    if prefix == "github":
        m = _GITHUB_RE.match(re.sub(r"\.git$", "", s.split("#")[0].split("?")[0].rstrip("/"), flags=re.I))
        if m and m.group(1).lower() not in _GITHUB_RESERVED and m.group(2) not in (".", ".."):
            return "github", f"{m.group(1)}/{m.group(2)}".lower()
        return "unknown", raw
    if prefix == "arxiv" or (prefix is None and _ARXIV_RE.match(s)):
        s = urllib.parse.unquote(s)
        return ("arxiv", _strip_arxiv_version(s)) if _ARXIV_RE.match(s) else ("unknown", raw)
    if prefix == "doi" or (prefix is None and _DOI_RE.match(s)):
        s = urllib.parse.unquote(s).lower()
        m = re.match(r"^10\.48550/arxiv\.(.+)$", s)
        if m and _ARXIV_RE.match(m.group(1)):
            return "arxiv", _strip_arxiv_version(m.group(1))
        return ("doi", s) if _DOI_RE.match(s) else ("unknown", raw)
    if prefix == "bibcode" or (prefix is None and _BIBCODE_RE.match(s)):
        s = urllib.parse.unquote(s)
        return ("bibcode", s) if _BIBCODE_RE.match(s) else ("unknown", raw)
    if prefix == "openalex" or (prefix is None and _OPENALEX_RE.match(s)):
        return ("openalex", s.upper()) if _OPENALEX_RE.match(s) else ("unknown", raw)
    if prefix == "inspire" and s.isdigit():
        return "inspire", s
    return "unknown", raw


def _canonical(rec: dict) -> str:
    """Stable identity for the ledger and caches: DOI first (survives the
    preprint → journal transition), then arXiv, bibcode, OpenAlex, INSPIRE.
    A GitHub repository is always github:owner/repo — its software DOI, when
    it has one, is a field, so the DataCite record of that DOI never
    overwrites the repository's cached record."""
    if rec.get("github"):
        return f"github:{rec['github']}"
    for k, tag in (("doi", "doi"), ("arxiv", "arXiv"), ("bibcode", "bibcode"),
                   ("openalex", "openalex"), ("inspire", "inspire")):
        if rec.get(k):
            return f"{tag}:{rec[k]}"
    return ""


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s)[:120]


def _cache_key(identifier: str) -> str:
    return hashlib.sha256(identifier.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# registry clients — every function returns the same record shape:
#   {registry, title, authors[], year, venue, doi, arxiv, bibcode, openalex,
#    inspire, abstract, type, url, citation_count, pdf_urls[]}
# ---------------------------------------------------------------------------

def _record(**kw) -> dict:
    rec = {"registry": None, "title": "", "authors": [], "year": None, "venue": "",
           "doi": None, "arxiv": None, "bibcode": None, "openalex": None, "inspire": None,
           "github": None, "abstract": "", "type": "", "url": "", "citation_count": None, "pdf_urls": []}
    rec.update({k: v for k, v in kw.items() if v is not None})
    if rec["doi"]:
        rec["doi"] = rec["doi"].lower()
        m = re.match(r"^10\.48550/arxiv\.(.+)$", rec["doi"])
        if m and _ARXIV_RE.match(m.group(1)):          # DataCite's arXiv DOIs: one identity, not two
            rec["arxiv"], rec["doi"] = rec["arxiv"] or _strip_arxiv_version(m.group(1)), None
    if rec["arxiv"]:
        rec["arxiv"] = _strip_arxiv_version(rec["arxiv"])
    if rec["github"]:
        rec["github"] = rec["github"].lower()
    return rec


def _year(v) -> int | None:
    m = re.search(r"(19|20)\d{2}", str(v or ""))
    return int(m.group(0)) if m else None


# --- Additional discovery sources (never authoritative record-cache input) ---

_DISCOVERY_SOURCES = {"semanticscholar", "pubmed", "dblp"}
_S2_SEARCH = "https://api.semanticscholar.org/graph/v1/paper/search"
_PUBMED_API = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
_DBLP_SEARCH = "https://dblp.org/search/publ/api"
_DISCOVERY_LIMIT = 10


def _discovery_json(
    source: str, url: str, headers: dict[str, str] | None = None
) -> dict[str, Any]:
    """Read a public API envelope, preserving errors rather than empty hits."""
    status, payload = _get_json(url, headers=headers)
    if status != 200:
        outcome = (
            "rate-limited"
            if status == 429
            else "authentication-required"
            if status in {401, 403}
            else "unavailable"
        )
        raise RegistryLookupError(source, outcome, status)
    if not isinstance(payload, dict) or payload.get("error"):
        raise RegistryLookupError(source, "malformed-response", status)
    return payload


def _discovery_rows(
    source: str,
    rows: Any,
    total: Any = None,
    sent: Any = None,
) -> list[Any]:
    """Check bounded result counts, distinguishing empty from partial data."""
    if not isinstance(rows, list) or len(rows) > _DISCOVERY_LIMIT:
        raise RegistryLookupError(source, "malformed-response", 200)
    for name, value in (("total", total), ("sent", sent)):
        if value is None:
            continue
        if type(value) is not int and not (
            isinstance(value, str) and re.fullmatch(r"[0-9]+", value)
        ):
            raise RegistryLookupError(source, "malformed-response", 200)
        count = int(value)
        size = min(count, _DISCOVERY_LIMIT) if name == "total" else count
        if count < 0 or size != len(rows):
            raise RegistryLookupError(source, "incomplete-response", 200)
    return rows


def _discovery_string(source: str, value: Any, required: bool = False) -> str:
    """Validate provider strings without converting structured data to text."""
    if value is None and not required:
        return ""
    if not isinstance(value, str) or (required and not value.strip()):
        raise RegistryLookupError(source, "malformed-response", 200)
    return value.strip()


def _discovery_authors(
    source: str, value: Any, name_field: str = "name"
) -> list[str]:
    """Normalize the documented provider author shapes."""
    if value is None:
        return []
    if isinstance(value, (str, dict)) and source == "dblp":
        value = [value]
    if not isinstance(value, list):
        raise RegistryLookupError(source, "malformed-response", 200)
    authors = []
    for row in value:
        name = row.get(name_field) if isinstance(row, dict) else row
        if not isinstance(row, dict) and source != "dblp":
            raise RegistryLookupError(source, "malformed-response", 200)
        authors.append(_discovery_string(source, name, required=True))
    return authors


def _discovery_year(source: str, value: Any) -> int | None:
    """Validate numeric publication years when the provider supplies them."""
    if value is None or value == "":
        return None
    if type(value) is int and 1000 <= value <= 9999:
        return value
    if (
        source == "dblp"
        and isinstance(value, str)
        and re.fullmatch(r"\d{4}", value)
    ):
        return int(value)
    raise RegistryLookupError(source, "malformed-response", 200)


def _discovery_alias(source: str, value: Any, kind: str) -> str:
    """Validate a suggested alias without establishing work identity."""
    text = _discovery_string(source, value, required=True)
    actual, identifier = _classify(text if ":" in text else f"{kind}:{text}")
    if actual not in ({"doi", "arxiv"} if kind == "doi" else {kind}):
        raise RegistryLookupError(source, "malformed-response", 200)
    return f"{actual}:{identifier}"


def _discovery_record(
    source: str,
    native_id: str,
    title: str,
    authors: list[str],
    year: int | None,
    venue: str,
    suggested_ids: list[str],
    publication_type: str = "",
) -> dict[str, Any]:
    """Build an isolated discovery candidate with a fixed-origin source URL."""
    if source == "semanticscholar":
        if not re.fullmatch(r"[0-9a-fA-F]{40}", native_id):
            raise RegistryLookupError(source, "malformed-response", 200)
        native_id = native_id.lower()
        identifier = "semanticscholar:" + native_id
        url = "https://www.semanticscholar.org/paper/" + native_id
    elif source == "pubmed":
        if not re.fullmatch(r"[1-9]\d*", native_id):
            raise RegistryLookupError(source, "malformed-response", 200)
        identifier = "pmid:" + native_id
        url = "https://pubmed.ncbi.nlm.nih.gov/" + native_id + "/"
    else:
        if (
            not re.fullmatch(r"[A-Za-z0-9._/-]+", native_id)
            or "/" not in native_id
            or any(part in {"", ".", ".."} for part in native_id.split("/"))
        ):
            raise RegistryLookupError(source, "malformed-response", 200)
        identifier = "dblp:" + native_id
        url = "https://dblp.org/rec/" + native_id
    return _record(
        registry=source,
        title=title,
        authors=authors,
        year=year,
        venue=venue,
        type=publication_type,
        url=url,
        discovery_only=True,
        discovery_id=identifier,
        suggested_ids=list(dict.fromkeys(suggested_ids)),
        provenance=dict(source=source, record_id=native_id, url=url),
    )


def _discovery_deduplicate(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Collapse identical native rows; reject conflicting same-ID responses."""
    indexed: dict[str, dict[str, Any]] = {}
    for record in records:
        identifier = record["discovery_id"]
        if identifier in indexed and indexed[identifier] != record:
            raise RegistryLookupError(
                record["registry"], "conflicting-native-records", 200
            )
        indexed[identifier] = record
    return list(indexed.values())


def _semanticscholar_search(
    title: str | None = None,
    author: str | None = None,
    words: list[str] | None = None,
    year: int | None = None,
) -> list[dict[str, Any]]:
    """Search a bounded Semantic Scholar page for unverified candidates."""
    source = "semanticscholar"
    query = " ".join(filter(None, [title, author, " ".join(words or [])]))
    params: dict[str, Any] = dict(
        query=_strip_latex(query),
        limit=_DISCOVERY_LIMIT,
        fields="title,authors,year,venue,externalIds",
    )
    if year is not None:
        params["year"] = f"{year - 1}-{year + 1}"
    key = key_value(source)[0]
    if key and re.search(r"[\s\"']", key):
        raise RegistryLookupError(source, "invalid-credential", 0)
    payload = _discovery_json(
        source,
        _S2_SEARCH + "?" + urllib.parse.urlencode(params),
        {"x-api-key": key} if key else None,
    )
    rows = _discovery_rows(source, payload.get("data"), payload.get("total"))
    records = []
    for row in rows:
        if not isinstance(row, dict):
            raise RegistryLookupError(source, "malformed-response", 200)
        external = row.get("externalIds")
        if external is None:
            external = {}
        if not isinstance(external, dict):
            raise RegistryLookupError(source, "malformed-response", 200)
        aliases = [
            _discovery_alias(source, external[name], kind)
            for name, kind in (("DOI", "doi"), ("ArXiv", "arxiv"))
            if name in external and external[name] is not None
        ]
        records.append(
            _discovery_record(
                source,
                _discovery_string(source, row.get("paperId"), True),
                _discovery_string(source, row.get("title"), True),
                _discovery_authors(source, row.get("authors")),
                _discovery_year(source, row.get("year")),
                _discovery_string(source, row.get("venue")),
                aliases,
            )
        )
    return _discovery_deduplicate(records)


def _pubmed_search(
    title: str | None = None,
    author: str | None = None,
    words: list[str] | None = None,
    year: int | None = None,
) -> list[dict[str, Any]]:
    """Search PubMed UIDs and retrieve one bounded batch of summaries."""
    source = "pubmed"
    query = " ".join(filter(None, [title, author, " ".join(words or [])]))
    common = dict(db="pubmed", retmode="json", tool="cite-check")
    if _mailto():
        common["email"] = _mailto()
    params = dict(
        common,
        term=_strip_latex(query),
        retmax=_DISCOVERY_LIMIT,
        sort="relevance",
    )
    if year is not None:
        params.update(
            datetype="pdat", mindate=str(year - 1), maxdate=str(year + 1)
        )
    payload = _discovery_json(
        source, _PUBMED_API + "esearch.fcgi?" + urllib.parse.urlencode(params)
    )
    found = payload.get("esearchresult")
    if (
        not isinstance(found, dict)
        or found.get("ERROR")
        or found.get("errorlist")
        or not isinstance(found.get("idlist"), list)
    ):
        raise RegistryLookupError(source, "malformed-response", 200)
    identifiers = _discovery_rows(source, found["idlist"], found.get("count"))
    if len(identifiers) > _DISCOVERY_LIMIT or any(
        not isinstance(uid, str) or not re.fullmatch(r"[1-9]\d*", uid)
        for uid in identifiers
    ):
        raise RegistryLookupError(source, "malformed-response", 200)
    identifiers = list(dict.fromkeys(identifiers))
    if not identifiers:
        return []
    summary = _discovery_json(
        source,
        _PUBMED_API
        + "esummary.fcgi?"
        + urllib.parse.urlencode(dict(common, id=",".join(identifiers))),
    )
    result = summary.get("result")
    if (
        not isinstance(result, dict)
        or not isinstance(result.get("uids"), list)
        or len(result["uids"]) != len(identifiers)
        or any(not isinstance(uid, str) for uid in result["uids"])
        or set(result["uids"]) != set(identifiers)
    ):
        raise RegistryLookupError(source, "malformed-response", 200)
    records = []
    for identifier in identifiers:
        row = result.get(identifier)
        if (
            not isinstance(row, dict)
            or row.get("uid") != identifier
            or row.get("error")
        ):
            raise RegistryLookupError(source, "malformed-response", 200)
        article_ids = row.get("articleids", [])
        if not isinstance(article_ids, list):
            raise RegistryLookupError(source, "malformed-response", 200)
        aliases = []
        for alias in article_ids:
            if not isinstance(alias, dict):
                raise RegistryLookupError(source, "malformed-response", 200)
            if (
                alias.get("idtype") == "pubmed"
                and alias.get("value") != identifier
            ):
                raise RegistryLookupError(source, "identity-mismatch", 200)
            if alias.get("idtype") == "doi":
                aliases.append(
                    _discovery_alias(source, alias.get("value"), "doi")
                )
        date = _discovery_string(source, row.get("pubdate"))
        match = re.search(r"\b\d{4}\b", date)
        records.append(
            _discovery_record(
                source,
                identifier,
                _discovery_string(source, row.get("title"), True),
                _discovery_authors(source, row.get("authors")),
                int(match.group()) if match else None,
                _discovery_string(
                    source, row.get("fulljournalname") or row.get("source")
                ),
                aliases,
            )
        )
    return _discovery_deduplicate(records)


def _dblp_search(
    title: str | None = None,
    author: str | None = None,
    words: list[str] | None = None,
    year: int | None = None,
) -> list[dict[str, Any]]:
    """Search dblp publications without accepting its BibTeX as an export."""
    source = "dblp"
    query = " ".join(
        filter(
            None,
            [
                title,
                author,
                " ".join(words or []),
                str(year) if year is not None else None,
            ],
        )
    )
    payload = _discovery_json(
        source,
        _DBLP_SEARCH
        + "?"
        + urllib.parse.urlencode(
            dict(q=_strip_latex(query), format="json", h=_DISCOVERY_LIMIT, c=0)
        ),
    )
    result = payload.get("result")
    hits = result.get("hits") if isinstance(result, dict) else None
    if not isinstance(hits, dict):
        raise RegistryLookupError(source, "malformed-response", 200)
    rows = hits.get("hit", [])
    if isinstance(rows, dict):
        rows = [rows]
    rows = _discovery_rows(source, rows, hits.get("@total"), hits.get("@sent"))
    if not rows and "@total" not in hits:
        raise RegistryLookupError(source, "malformed-response", 200)
    records = []
    for hit in rows:
        row = hit.get("info") if isinstance(hit, dict) else None
        if not isinstance(row, dict):
            raise RegistryLookupError(source, "malformed-response", 200)
        authors = row.get("authors")
        if authors is None:
            authors = {}
        if not isinstance(authors, dict):
            raise RegistryLookupError(source, "malformed-response", 200)
        links = row.get("ee")
        if links is None:
            links = []
        if isinstance(links, str):
            links = [links]
        if not isinstance(links, list):
            raise RegistryLookupError(source, "malformed-response", 200)
        aliases = []
        for link in links:
            link = _discovery_string(source, link, True)
            kind, value = _classify(link)
            if kind in {"doi", "arxiv"}:
                aliases.append(f"{kind}:{value}")
        records.append(
            _discovery_record(
                source,
                _discovery_string(source, row.get("key"), True),
                _discovery_string(source, row.get("title"), True),
                _discovery_authors(source, authors.get("author"), "text"),
                _discovery_year(source, row.get("year")),
                _discovery_string(source, row.get("venue")),
                aliases,
                _discovery_string(source, row.get("type")),
            )
        )
    return _discovery_deduplicate(records)


# --- arXiv -------------------------------------------------------------------

_ATOM = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom"}
_ARXIV_API = "https://export.arxiv.org/api/query"


def _arxiv_parse(body: str) -> list:
    out = []
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise RegistryLookupError("arxiv", "malformed-response", 200) from exc
    if root.tag != "{http://www.w3.org/2005/Atom}feed":
        raise RegistryLookupError("arxiv", "malformed-response", 200)
    for e in root.findall("a:entry", _ATOM):
        title = re.sub(r"\s+", " ", e.findtext("a:title", "", _ATOM)).strip()
        eid = e.findtext("a:id", "", _ATOM)
        m = re.fullmatch(r"https?://arxiv\.org/abs/(.+)", eid)
        if (not title or title == "Error" or not m
                or not _ARXIV_RE.fullmatch(m.group(1))):
            raise RegistryLookupError("arxiv", "malformed-response", 200)
        aid = _strip_arxiv_version(m.group(1))
        cat = e.find("x:primary_category", _ATOM)
        out.append(_record(
            registry="arxiv", title=title, arxiv=aid,
            arxiv_api_version=(m.group(1) if re.search(r"v[1-9]\d*$", m.group(1), re.I) else None),
            authors=[a.findtext("a:name", "", _ATOM) for a in e.findall("a:author", _ATOM)],
            year=_year(e.findtext("a:published", "", _ATOM)),
            doi=(e.findtext("x:doi", "", _ATOM) or None),
            venue=(e.findtext("x:journal_ref", "", _ATOM) or "arXiv"),
            abstract=re.sub(r"\s+", " ", e.findtext("a:summary", "", _ATOM)).strip(),
            type="preprint", url=f"https://arxiv.org/abs/{aid}" if aid else eid,
            primary_class=cat.get("term") if cat is not None else None,
            pdf_urls=[f"https://arxiv.org/pdf/{aid}"] if aid else []))
    return out


class RegistryLookupError(RuntimeError):
    """A non-definitive registry outcome; never evidence of absence."""

    def __init__(self, registry: str, outcome: str, status: int = 0):
        self.outcome = outcome
        super().__init__(f"{registry}: {outcome} (HTTP {status})")


def _registry_status(registry: str, status: int) -> bool:
    if status == 404:
        return False
    if status != 200:
        raise RegistryLookupError(
            registry, "rate-limited" if status == 429 else "unavailable", status
        )
    return True


def _arxiv_lookup(ids: list) -> dict:
    found = {}
    for chunk in _chunks(ids, 50):
        status, body = _http(f"{_ARXIV_API}?id_list={','.join(chunk)}&max_results={len(chunk)}")
        if not _registry_status("arxiv", status):
            continue
        for rec in _arxiv_parse(body):
            found[rec["arxiv"].lower()] = rec
            if rec.get("arxiv_api_version"):
                found[rec["arxiv_api_version"].lower()] = rec
    return found


def _arxiv_query(q: str, max_results: int = 10) -> list:
    url = f"{_ARXIV_API}?search_query={urllib.parse.quote(q)}&max_results={max_results}"
    status, body = _http(url)
    return _arxiv_parse(body) if _registry_status("arxiv", status) else []


def _arxiv_search(title=None, author=None, words=None, year=None, max_results=10) -> list:
    parts = []
    if title:
        parts.append('ti:"%s"' % re.sub(r'["\\]', " ", _strip_latex(title)).strip())
    if author:
        parts.append('au:"%s"' % author.replace('"', ""))
    if words and not title:
        parts.append("(" + " OR ".join(f"ti:{w} OR abs:{w}" for w in words[:4]) + ")")
    if year and (author or title):
        parts.append(f"submittedDate:[{year - 1}01010000 TO {year + 1}12312359]")
    return _arxiv_query(" AND ".join(parts), max_results) if parts else []


# --- Crossref / DataCite ------------------------------------------------------

_CROSSREF = "https://api.crossref.org/works"


def _registry_list(
    data: dict, key: str, item_type: type, registry: str,
) -> list:
    """Validate optional registry arrays before converting their contents."""
    value = data.get(key)
    if value is None:
        return []
    if not isinstance(value, list) or any(
        not isinstance(item, item_type) for item in value
    ):
        raise RegistryLookupError(registry, "malformed-response", 200)
    return value


def _registry_strings(data: dict, keys: tuple[str, ...], registry: str) -> None:
    """Reject non-string scalar fields in a registry response."""
    if any(data.get(key) is not None and not isinstance(data[key], str)
           for key in keys):
        raise RegistryLookupError(registry, "malformed-response", 200)


def _cr_record(msg: dict) -> dict:
    """Convert valid Crossref records and classify malformed nested fields."""
    if not isinstance(msg, dict):
        raise RegistryLookupError("crossref", "malformed-response", 200)
    _registry_strings(msg, ("DOI", "abstract", "type", "URL"), "crossref")
    if not _DOI_RE.fullmatch(msg.get("DOI") or ""):
        raise RegistryLookupError("crossref", "malformed-response", 200)
    if msg.get("is-referenced-by-count") is not None and type(
        msg["is-referenced-by-count"]
    ) is not int:
        raise RegistryLookupError("crossref", "malformed-response", 200)
    for key in ("title", "subtitle", "container-title"):
        _registry_list(msg, key, str, "crossref")
    for author in _registry_list(msg, "author", dict, "crossref"):
        _registry_strings(author, ("family", "given", "name"), "crossref")
    for link in _registry_list(msg, "link", dict, "crossref"):
        _registry_strings(link, ("URL", "content-type"), "crossref")
    try:
        return _cr_record_fields(msg)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
        raise RegistryLookupError("crossref", "malformed-response", 200) from exc


def _cr_record_fields(msg: dict) -> dict:
    title = " ".join(msg.get("title") or []).strip()
    sub = " ".join(msg.get("subtitle") or []).strip()
    if sub and _norm_title(sub) not in _norm_title(title):
        title = f"{title}: {sub}"
    authors = []
    for a in msg.get("author") or []:
        if a.get("family"):
            authors.append(f"{a['family']}, {a.get('given', '')}".strip(", "))
        elif a.get("name"):
            authors.append(a["name"])
    year = None
    for k in ("published-print", "published-online", "issued", "created"):
        parts = (msg.get(k) or {}).get("date-parts") or [[None]]
        if parts and parts[0] and parts[0][0]:
            year = int(parts[0][0])
            break
    abstract = re.sub(r"<[^>]+>", " ", msg.get("abstract") or "")
    pdfs = [l["URL"] for l in msg.get("link") or []
            if l.get("content-type") == "application/pdf" and l.get("URL")]
    clean = lambda v: re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", v or ""))).strip()
    return _record(registry="crossref", title=clean(title), authors=authors, year=year,
                   venue=clean((msg.get("container-title") or [""])[0]),
                   doi=msg.get("DOI"), type=msg.get("type", ""),
                   abstract=re.sub(r"\s+", " ", html.unescape(abstract)).strip(),
                   url=f"https://doi.org/{msg.get('DOI')}" if msg.get("DOI") else msg.get("URL", ""),
                   citation_count=msg.get("is-referenced-by-count"), pdf_urls=pdfs)


def _crossref_work(doi: str):
    status, data = _get_json(f"{_CROSSREF}/{urllib.parse.quote(doi, safe='')}")
    if not _registry_status("crossref", status):
        return None
    message = data.get("message") if isinstance(data, dict) else None
    if not isinstance(message, dict) or not message.get("DOI"):
        raise RegistryLookupError("crossref", "malformed-response", status)
    return _cr_record(message)


def _crossref_search(title=None, author=None, words=None, year=None, rows=10) -> list:
    params = {"rows": rows, "select": "DOI,title,subtitle,author,issued,published-print,"
                                      "published-online,created,container-title,type,"
                                      "is-referenced-by-count,abstract,link,URL"}
    biblio = _strip_latex(title) if title else " ".join(words or [])
    if biblio.strip():
        params["query.bibliographic"] = biblio.strip()
    if author:
        params["query.author"] = author
    if year:
        params["filter"] = f"from-pub-date:{year - 1}-01-01,until-pub-date:{year + 1}-12-31"
    if _mailto():
        params["mailto"] = _mailto()
    if "query.bibliographic" not in params and "query.author" not in params:
        return []
    status, data = _get_json(f"{_CROSSREF}?{urllib.parse.urlencode(params)}")
    if status != 200 or not data:
        return []
    return [_cr_record(m) for m in data.get("message", {}).get("items", [])]


def _datacite_doi(doi: str):
    status, data = _get_json(f"https://api.datacite.org/dois/{urllib.parse.quote(doi, safe='')}")
    if not _registry_status("datacite", status):
        return None
    try:
        a = data["data"]["attributes"]
        if not isinstance(a, dict) or not a.get("doi"):
            raise ValueError("missing DOI")
    except (KeyError, TypeError, ValueError) as exc:
        raise RegistryLookupError("datacite", "malformed-response", status) from exc
    _registry_strings(a, ("doi", "publisher", "url"), "datacite")
    if not _DOI_RE.fullmatch(a.get("doi") or ""):
        raise RegistryLookupError("datacite", "malformed-response", status)
    for title in _registry_list(a, "titles", dict, "datacite"):
        _registry_strings(title, ("title",), "datacite")
    for creator in _registry_list(a, "creators", dict, "datacite"):
        _registry_strings(
            creator, ("familyName", "givenName", "name"), "datacite"
        )
    for description in _registry_list(a, "descriptions", dict, "datacite"):
        _registry_strings(description, ("description",), "datacite")
    if a.get("types") is not None and not isinstance(a["types"], dict):
        raise RegistryLookupError("datacite", "malformed-response", status)
    _registry_strings(
        a.get("types") or {}, ("resourceTypeGeneral",), "datacite"
    )
    if a.get("publicationYear") is not None and type(a["publicationYear"]) is not int:
        raise RegistryLookupError("datacite", "malformed-response", status)
    try:
        return _datacite_record_fields(a)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
        raise RegistryLookupError("datacite", "malformed-response", status) from exc


def _datacite_record_fields(a: dict) -> dict:
    authors = []
    for c in a.get("creators") or []:
        if c.get("familyName"):
            authors.append(f"{c['familyName']}, {c.get('givenName', '')}".strip(", "))
        elif c.get("name"):
            authors.append(c["name"])
    desc = next((d.get("description", "") for d in a.get("descriptions") or []), "")
    return _record(registry="datacite", title=(a.get("titles") or [{}])[0].get("title", ""),
                   authors=authors, year=a.get("publicationYear"), venue=a.get("publisher", ""),
                   doi=a.get("doi"), type=(a.get("types") or {}).get("resourceTypeGeneral", ""),
                   abstract=re.sub(r"\s+", " ", desc).strip(), url=a.get("url", ""))


# --- OpenAlex -----------------------------------------------------------------

_OPENALEX = "https://api.openalex.org/works"


def _oa_abstract(inv: dict | None) -> str:
    if not inv:
        return ""
    pos = sorted((p, w) for w, ps in inv.items() for p in ps)
    return " ".join(w for _, w in pos)


def _oa_record(w: dict) -> dict:
    ids = w.get("ids") or {}
    doi = (ids.get("doi") or w.get("doi") or "").replace("https://doi.org/", "") or None
    arxiv = None
    for loc in [w.get("primary_location")] + (w.get("locations") or []):
        for u in ((loc or {}).get("landing_page_url"), (loc or {}).get("pdf_url")):
            m = re.search(r"arxiv\.org/(?:abs|pdf)/(" + _ARXIV_CORE + r")", u or "", re.I)
            if m:
                arxiv = m.group(1)
                break
        if arxiv:
            break
    oa = w.get("best_oa_location") or {}
    return _record(registry="openalex", title=w.get("display_name") or "",
                   authors=[(a.get("author") or {}).get("display_name", "") for a in w.get("authorships") or []],
                   year=w.get("publication_year"),
                   venue=(((w.get("primary_location") or {}).get("source") or {}).get("display_name") or ""),
                   doi=doi, arxiv=arxiv, openalex=(ids.get("openalex") or w.get("id") or "").rsplit("/", 1)[-1] or None,
                   abstract=_oa_abstract(w.get("abstract_inverted_index")), type=w.get("type", ""),
                   url=w.get("id", ""), citation_count=w.get("cited_by_count"),
                   pdf_urls=[oa["pdf_url"]] if oa.get("pdf_url") else [])


def _oa_params(extra: dict) -> str:
    if _mailto():
        extra = dict(extra, mailto=_mailto())
    return urllib.parse.urlencode(extra)


def _openalex_get(ident: str):
    status, data = _get_json(f"{_OPENALEX}/{urllib.parse.quote(ident, safe=':/')}?{_oa_params({})}")
    return _oa_record(data) if status == 200 and data else None


def _openalex_batch_dois(dois: list) -> dict:
    found = {}
    for chunk in _chunks(dois, 40):
        q = _oa_params({"filter": "doi:" + "|".join(chunk), "per-page": 50})
        status, data = _get_json(f"{_OPENALEX}?{q}")
        for w in (data or {}).get("results", []) if status == 200 else []:
            rec = _oa_record(w)
            if rec["doi"]:
                found[rec["doi"]] = rec
    return found


def _openalex_search(title=None, author=None, words=None, year=None, per_page=10) -> list:
    search = _strip_latex(title) if title else " ".join(words or [])
    filters = []
    if year:
        filters.append(f"publication_year:{year - 1}|{year}|{year + 1}")
    if author:
        filters.append(f"raw_author_name.search:{author}")
    if not search.strip() and not author:
        return []
    params = {"per-page": per_page}
    if search.strip():
        params["search"] = search.strip()
    if filters:
        params["filter"] = ",".join(filters)
    status, data = _get_json(f"{_OPENALEX}?{_oa_params(params)}")
    if status != 200 and author:          # filter syntax rejected: retry without it
        params["filter"] = ",".join(f for f in filters if not f.startswith("raw_author"))
        status, data = _get_json(f"{_OPENALEX}?{_oa_params(params)}")
    if status != 200 or not data:
        return []
    return [_oa_record(w) for w in data.get("results", [])]


# --- INSPIRE-HEP --------------------------------------------------------------

_INSPIRE = "https://inspirehep.net/api"
_INSPIRE_FIELDS = ("titles,authors.full_name,dois,arxiv_eprints,publication_info,earliest_date,"
                   "abstracts,control_number,citation_count,document_type,imprints")


def _insp_record(hit: dict) -> dict:
    m = hit.get("metadata") or {}
    pub = (m.get("publication_info") or [{}])[0]
    year = _year(m.get("earliest_date")) or _year(pub.get("year")) or _year((m.get("imprints") or [{}])[0].get("date"))
    return _record(registry="inspire", title=(m.get("titles") or [{}])[0].get("title", ""),
                   authors=[a.get("full_name", "") for a in m.get("authors") or []],
                   year=year, venue=pub.get("journal_title", ""),
                   doi=(m.get("dois") or [{}])[0].get("value"),
                   arxiv=(m.get("arxiv_eprints") or [{}])[0].get("value"),
                   inspire=str(m.get("control_number") or hit.get("id") or "") or None,
                   abstract=(m.get("abstracts") or [{}])[0].get("value", ""),
                   type=",".join(m.get("document_type") or []),
                   url=f"https://inspirehep.net/literature/{m.get('control_number')}" if m.get("control_number") else "",
                   citation_count=m.get("citation_count"))


def _inspire_get(kind: str, value: str):
    path = {"arxiv": "arxiv", "doi": "doi", "inspire": "literature"}[kind]
    status, data = _get_json(f"{_INSPIRE}/{path}/{urllib.parse.quote(value, safe='')}")
    return _insp_record(data) if status == 200 and data and data.get("metadata") else None


def _inspire_search(title=None, author=None, words=None, year=None, size=10) -> list:
    clauses = []
    if title:
        clauses.append('t "%s"' % re.sub(r'["\\]', " ", _strip_latex(title)).strip())
    if author:
        clauses.append(f"a {author}")
    if words and not title:
        clauses.append("(" + " or ".join(f"t {w}" for w in words[:4]) + ")")
    if year and (author or title):
        clauses.append(f"date {year - 1}->{year + 1}")
    if not clauses:
        return []
    q = urllib.parse.urlencode({"q": " and ".join(clauses), "size": size, "fields": _INSPIRE_FIELDS})
    status, data = _get_json(f"{_INSPIRE}/literature?{q}")
    if status != 200 or not data:
        return []
    return [_insp_record(h) for h in data.get("hits", {}).get("hits", [])]


# --- NASA ADS -----------------------------------------------------------------

_ADS = "https://api.adsabs.harvard.edu/v1"
_ADS_FL = "bibcode,title,author,year,doi,identifier,pub,abstract,doctype,citation_count,bibstem,property"


def _ads_token() -> str:
    return key_value("ads")[0] or ""


def _ads_arxiv_id(identifiers: list) -> str | None:
    for v in identifiers or []:
        m = re.match(r"^arxiv:(" + _ARXIV_CORE + r")$", str(v).strip(), re.I)
        if m:
            return m.group(1)
    return None


def _ads_record(doc: dict) -> dict:
    return _record(registry="ads", title=(doc.get("title") or [""])[0], authors=doc.get("author") or [],
                   year=_year(doc.get("year")), venue=doc.get("pub", ""),
                   doi=(doc.get("doi") or [None])[0], arxiv=_ads_arxiv_id(doc.get("identifier")),
                   bibcode=doc.get("bibcode"), abstract=doc.get("abstract", ""),
                   type=doc.get("doctype", ""), citation_count=doc.get("citation_count"),
                   url=f"https://ui.adsabs.harvard.edu/abs/{doc.get('bibcode')}/abstract")


def _ads_query(q: str, rows: int = 10) -> list:
    tok = _ads_token()
    if not tok:
        return []
    url = f"{_ADS}/search/query?{urllib.parse.urlencode({'q': q, 'fl': _ADS_FL, 'rows': rows})}"
    status, data = _get_json(url, headers={"Authorization": f"Bearer {tok}"})
    if status == 401:
        raise RuntimeError("ADS rejected the API token (HTTP 401) — check ADS_API_TOKEN / ~/.ads/dev_key")
    if status != 200 or not data:
        return []
    return [_ads_record(d) for d in data.get("response", {}).get("docs", [])]


def _ads_lookup(kind: str, values: list) -> dict:
    """Batch lookup by arXiv id / DOI / bibcode. Returns {value.lower(): record}."""
    found = {}
    if not values or not _ads_token():
        return found
    for chunk in _chunks(values, 25):
        if kind == "bibcode":
            q = "bibcode:(" + " OR ".join(f'"{v}"' for v in chunk) + ")"
        elif kind == "arxiv":
            q = "identifier:(" + " OR ".join(f'"arXiv:{v}"' for v in chunk) + ")"
        else:
            q = "doi:(" + " OR ".join(f'"{v}"' for v in chunk) + ")"
        for rec in _ads_query(q, rows=len(chunk) * 2):
            for key in (rec["bibcode"], rec["doi"], rec["arxiv"]):
                if key:
                    found[key.lower()] = rec
    return found


def _ads_search(title=None, author=None, words=None, year=None, rows=12) -> list:
    parts = []
    if author:
        parts.append('first_author:"%s"' % author.replace('"', ""))
    if year:
        parts.append(f"year:{year - 1}-{year + 1}")
    if title:
        parts.append('title:"%s"' % re.sub(r'["\\]', " ", _strip_latex(title)).strip())
    elif words:
        parts.append("(" + " OR ".join(f"abs:{w}" for w in words[:5]) + ")")
    if not parts or (not title and not author):
        return []
    return _ads_query(" ".join(parts), rows=rows)


def _ads_export(bibcodes: list, journal_format: int = 2, max_author: int = 10,
                key_format: str | None = None) -> dict:
    """Official ADS BibTeX export. Returns {bibcode: bibtex_entry}."""
    tok = _ads_token()
    if not tok or not bibcodes:
        return {}
    payload = {"bibcode": list(bibcodes), "journalformat": int(journal_format),
               "maxauthor": int(max_author), "authorcutoff": max(int(max_author), 1) + 190}
    if key_format:
        payload["keyformat"] = key_format
    status, body = _http(f"{_ADS}/export/bibtex", method="POST", data=json.dumps(payload).encode(),
                         headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
                         cache=False)
    if status != 200:
        return {}
    try:
        text = json.loads(body).get("export", "")
    except ValueError:
        return {}
    out = {}
    for entry in _parse_bib(text)["entries"]:
        m = re.search(r"adsurl\s*=\s*\{[^}]*/abs/([^}/]+)", entry["raw"])
        bib = m.group(1) if m else entry["key"]
        out[bib] = entry["raw"]
    return out


# --- GitHub (software) ---------------------------------------------------------
# A public repository is a citable work of its own. Its record comes from the
# GitHub REST API; what its authors declare about citing it comes from their
# CITATION.cff (or CITATION.bib) and README. Nothing here is inferred: a
# software DOI is adopted only when CITATION.cff declares it or the Zenodo
# record behind a README badge names this repository.

_GITHUB_API = "https://api.github.com"
_GITHUB_RAW = "https://raw.githubusercontent.com"
_ZENODO_DOI = re.compile(r"^10\.5281/zenodo\.\d+$")


def _github_token() -> str:
    return (key_value("github")[0] or "").strip()


def _gh_api(path: str, accept: str | None = None, token: str | None = None) -> tuple:
    """(status, body) from the GitHub REST API. A spent rate limit raises
    instead of reading as "not found"."""
    hdrs = {"Accept": accept or "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    tok = token if token is not None else _github_token()
    if tok:
        hdrs["Authorization"] = f"Bearer {tok}"
    status, body = _http(_GITHUB_API + path, headers=hdrs, cache=token is None)
    if status in (403, 429) and "rate limit" in (body or "").lower():
        raise RuntimeError("GitHub API rate limit reached (60 requests/hour without a token) — store a "
                           "token with `bash mcp/setup_mcp.sh --keys` or export GITHUB_TOKEN, or retry later")
    return status, body


def _github_test(token: str) -> dict:
    """Live check of a token against GitHub (rate_limit costs no quota)."""
    try:
        status, body = _gh_api("/rate_limit", token=token)
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


def _gh_json(path: str, accept: str | None = None):
    status, body = _gh_api(path, accept)
    if status != 200:
        return status, None
    try:
        return status, json.loads(body)
    except ValueError:
        return status, None


def _cff_people(people) -> list:
    """CITATION.cff authors → [(name, is_entity)]; persons as 'Family, Given'."""
    out = []
    for p in people or []:
        if not isinstance(p, dict):
            continue
        fam = " ".join(str(p[k]).strip() for k in ("name-particle", "family-names") if p.get(k))
        if fam:
            given = " ".join(str(p[k]).strip() for k in ("given-names", "name-suffix") if p.get(k))
            out.append((f"{fam}, {given}" if given else fam, False))
        elif p.get("name"):
            out.append((str(p["name"]).strip(), True))
    return out


def _cff_ids(block: dict) -> dict:
    """DOI / arXiv id a CFF block declares: doi, identifiers[], url."""
    ids = {}
    vals = [block.get("doi")] + [i.get("value") for i in block.get("identifiers") or [] if isinstance(i, dict)]
    vals += [block.get("url")]
    for v in vals:
        if not v:
            continue
        k, val = _classify(str(v))
        if k in ("doi", "arxiv"):
            ids.setdefault(k, val)
    return ids


def _cff_load(text: str) -> tuple:
    try:
        import yaml
    except ImportError:
        return None, "PyYAML is missing, so CITATION.cff was not read — re-run mcp/setup_mcp.sh"
    try:
        d = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return None, f"CITATION.cff is not valid YAML ({type(exc).__name__})"
    return (d, None) if isinstance(d, dict) else (None, "CITATION.cff has no top-level mapping")


def _readme_ids(body: str) -> list:
    """DOIs and arXiv ids a README links or mentions, in order, deduplicated."""
    t = html.unescape(body or "")
    found = []
    for m in _DOI_ANY.finditer(t):
        raw = re.sub(r"(?:/status|/badge)?\.(?:svg|png|jpe?g)$", "", m.group(0).split("?")[0].rstrip(".,;)]"), flags=re.I)
        k, v = _classify(raw)
        if k in ("doi", "arxiv"):
            found.append(("doi:" if k == "doi" else "arXiv:") + v)
    for m in re.finditer(r"(?:arxiv\.org/(?:abs|pdf|html)/|arxiv:\s*)(" + _ARXIV_CORE + r")", t, re.I):
        found.append("arXiv:" + _strip_arxiv_version(m.group(1)))
    return list(dict.fromkeys(found))[:12]


def _zenodo_names_repo(doi: str, full_name: str) -> bool:
    """Is this Zenodo DOI a software archive of this repository? (the
    GitHub–Zenodo integration records the repository as a related URL)."""
    status, data = _get_json(f"https://api.datacite.org/dois/{urllib.parse.quote(doi, safe='')}")
    if status != 200 or not data:
        return False
    a = data.get("data", {}).get("attributes", {})
    if (a.get("types") or {}).get("resourceTypeGeneral") != "Software":
        return False
    want = f"github.com/{full_name}".lower()
    urls = [r.get("relatedIdentifier", "") for r in a.get("relatedIdentifiers") or []] + [a.get("url") or ""]
    return any(re.search(re.escape(want) + r"(?:\.git)?(?:[/#?]|$)", (u or "").lower()) for u in urls)


def _github_get(full: str, ref: str | None = None):
    """Repository record for owner/repo, or None when GitHub has no public
    repository there. Follows renames; reports private repositories."""
    status, r = _gh_json(f"/repos/{full}")
    if status in (404, 451) or (status == 200 and not r):
        return None
    if status != 200:
        raise RuntimeError(f"api.github.com: HTTP {status}")
    if r.get("private"):
        return {"error": f"github:{full} is a private repository — only public repositories can be cited",
                "final": True}
    full_name, owner = r["full_name"], r.get("owner") or {}
    info = {"full_name": full_name, "html_url": r.get("html_url"), "description": r.get("description") or "",
            "owner": owner.get("login"), "owner_type": owner.get("type"), "owner_name": None,
            "archived": bool(r.get("archived")), "fork": bool(r.get("fork")),
            "parent": (r.get("parent") or {}).get("full_name"), "stars": r.get("stargazers_count"),
            "license": (r.get("license") or {}).get("spdx_id"), "default_branch": r.get("default_branch"),
            "created": (r.get("created_at") or "")[:10], "pushed": (r.get("pushed_at") or "")[:10],
            "homepage": r.get("homepage") or None, "topics": r.get("topics") or [],
            "moved_from": full if full_name.lower() != full.lower() else None,
            "citation_file": None, "cff": None, "preferred_citation": None, "readme_ids": [],
            "software_doi_source": None, "notes": []}
    if ref:
        info["description"] = ""  # repository settings are not historical evidence
    title, authors, year, doi, abstract = r.get("name"), [], None, None, info["description"]

    status, text = _http(f"{_GITHUB_RAW}/{full_name}/{ref or 'HEAD'}/CITATION.cff")
    if status == 200 and text.strip():
        info["citation_file"] = "CITATION.cff"
        cff, problem = _cff_load(text)
        if problem:
            info["notes"].append(problem)
        if cff:
            people = _cff_people(cff.get("authors"))
            ids = _cff_ids(cff)
            info["cff"] = {"title": str(cff.get("title") or "").strip() or None, "authors": people,
                           "version": str(cff["version"]) if cff.get("version") is not None else None,
                           "date_released": str(cff.get("date-released") or "")[:10] or None,
                           "doi": ids.get("doi"), "url": cff.get("repository-code") or cff.get("url"),
                           "message": str(cff.get("message") or "").strip()[:300] or None}
            title = info["cff"]["title"] or title
            authors = [n for n, _ in people]
            year = _year(info["cff"]["date_released"])
            abstract = str(cff.get("abstract") or "").strip() or abstract
            if ids.get("doi"):
                doi, info["software_doi_source"] = ids["doi"], "CITATION.cff"
            pc = cff.get("preferred-citation")
            if isinstance(pc, dict):
                info["preferred_citation"] = {
                    "title": str(pc.get("title") or "").strip(), "authors": [n for n, _ in _cff_people(pc.get("authors"))][:6],
                    "year": _year(pc.get("year") or pc.get("date-published")), "type": pc.get("type"),
                    "ids": _cff_ids(pc), "source": "CITATION.cff preferred-citation"}
    if not info["preferred_citation"]:
        status, text = _http(f"{_GITHUB_RAW}/{full_name}/{ref or 'HEAD'}/CITATION.bib")
        entries = _parse_bib(text)["entries"] if status == 200 else []
        if entries:
            e = entries[0]
            info["citation_file"] = info["citation_file"] or "CITATION.bib"
            info["preferred_citation"] = {
                "title": re.sub(r"[{}]", "", e["fields"].get("title", "")).strip(),
                "authors": _split_bib_authors(e["fields"].get("author", ""))[:6],
                "year": _year(e["fields"].get("year")), "type": e["type"], "ids": _entry_ids(e),
                "source": "CITATION.bib"}

    query = "?" + urllib.parse.urlencode({"ref": ref}) if ref else ""
    status, readme = _gh_api(f"/repos/{full_name}/readme{query}", accept="application/vnd.github.html+json")
    if status == 200:
        info["readme_ids"] = _readme_ids(readme)
    if not doi:
        for rid in info["readme_ids"]:
            d = rid[4:] if rid.startswith("doi:") else ""
            if _ZENODO_DOI.match(d) and _zenodo_names_repo(d, full_name):
                doi, info["software_doi_source"] = d, "Zenodo archive linked from the README"
                break
    if not authors:
        u_status, u = _gh_json(f"/users/{info['owner']}") if info["owner"] else (0, None)
        info["owner_name"] = (u or {}).get("name") or None
        authors = [info["owner_name"] or info["owner"]] if info["owner"] else []
    if info["archived"]:
        info["notes"].append("archived: the repository is read-only and no longer maintained")
    if info["fork"]:
        info["notes"].append(f"fork of {info['parent'] or 'another repository'} — cite the upstream "
                             "unless this fork is the work being cited")
    if info["moved_from"]:
        info["notes"].append(f"moved: {info['moved_from']} now redirects to {full_name} — update the URL")
    pc = info["preferred_citation"]
    if pc and pc.get("title"):
        target = next(iter(pc["ids"].values()), None)
        info["notes"].append(f"the authors ask that '{pc['title'][:90]}' be cited ({pc['source']})"
                             + (f" — add it too: bib_add(identifier='{target}')" if target else ""))
    return _record(registry="github", title=title or full_name, authors=authors, year=year, venue="GitHub",
                   doi=doi, github=full_name, abstract=abstract, type="software", url=info["html_url"],
                   citation_count=r.get("stargazers_count"), repo=info)


def _github_ref(full: str, ref: str) -> dict:
    """Does `ref` (tag, branch or commit; 'v' prefix tolerated) exist in the
    repository? found, the ref as it exists, its commit sha and date."""
    ref = (ref or "").strip()
    bare = re.sub(r"^v(?=\d)", "", ref, flags=re.I)
    for cand in dict.fromkeys([ref, bare, "v" + bare]):
        params = urllib.parse.urlencode({"sha": cand, "per_page": 1})
        status, data = _gh_json(f"/repos/{full}/commits?{params}")
        if status not in (200, 404, 422):
            raise RegistryLookupError("github", "unavailable", status)
        if status == 200 and isinstance(data, list) and data:
            c = data[0]
            return {"found": True, "ref": cand, "sha": c["sha"],
                    "date": ((c.get("commit") or {}).get("committer") or {}).get("date", "")[:10]}
    return {"found": False, "ref": ref}


def _gh_search_record(it: dict) -> dict:
    owner = it.get("owner") or {}
    return _record(registry="github", title=it.get("name", ""), authors=[owner.get("login")] if owner.get("login") else [],
                   venue="GitHub", github=it.get("full_name"), abstract=it.get("description") or "",
                   type="software", url=it.get("html_url", ""), citation_count=it.get("stargazers_count"),
                   repo={"full_name": it.get("full_name"), "description": it.get("description") or "",
                         "archived": bool(it.get("archived")), "fork": bool(it.get("fork")), "partial": True})


def _github_search(title=None, author=None, words=None, year=None, per_page=10) -> list:
    """Repository search by name/description — opt-in (registries=["github"])."""
    q = title or " ".join(words or [])
    if not q:
        return []
    params = urllib.parse.urlencode({"q": f"{q} in:name,description", "per_page": per_page})
    status, data = _gh_json(f"/search/repositories?{params}")
    if status != 200 or not data:
        return []
    return [_gh_search_record(it) for it in data.get("items") or []]


def _bib_escape(s: str) -> str:
    s = re.sub(r"[{}]", "", str(s or ""))
    return re.sub(r"(?<!\\)([_%#$])", r"\\\1", s)


def _github_pin(full: str, repo: dict, version: str | None) -> dict | None:
    """The state an entry cites: the requested tag / branch / commit, else the
    latest release, else the default branch's current commit. None when the
    requested version does not exist."""
    if not version:
        status, rel = _gh_json(f"/repos/{full}/releases/latest")
        if status == 200 and rel and rel.get("tag_name"):
            return {"version": rel["tag_name"], "note": None,
                    "year": (rel.get("published_at") or rel.get("created_at") or "")[:4]}
    ref = _github_ref(full, version or repo.get("default_branch") or "HEAD")
    if not ref["found"]:
        return None
    commit = f"Commit {ref['sha']} ({ref['date']})"
    if version and not re.match(r"^[0-9a-f]{7,40}$", ref["ref"]):
        return {"version": ref["ref"], "note": commit, "year": ref["date"][:4]}
    return {"version": None, "note": commit, "year": ref["date"][:4]}


def _github_bibtex(rec: dict) -> tuple:
    """(bibtex, source) for a repository with no registry export: laid out
    field for field from the authors' CITATION.cff (source citation-cff), else
    from the GitHub record with the cited version — rec["pin"], else the
    latest release, else the default branch's commit — pinned (source
    github). Never from model memory."""
    repo = rec.get("repo") or {}
    full = repo.get("full_name") or rec["github"]
    if repo.get("partial"):
        full_rec = _github_get(full)
        if not full_rec or full_rec.get("error"):
            return None, "github"
        rec, repo = dict(full_rec, pin=rec.get("pin")), full_rec["repo"]
    cff, version = repo.get("cff"), rec.get("pin")
    frozen_pin = None
    if rec.get("pinned_sha"):
        requested = rec.get("requested_version") or rec["pinned_sha"]
        date = rec.get("pinned_date") or ""
        frozen_pin = {
            "version": None if requested == rec["pinned_sha"] else requested,
            "note": f"Commit {rec['pinned_sha']} ({date})",
            "year": date[:4],
        }
    fields = []
    if cff and cff.get("title") and cff.get("authors"):
        source = "citation-cff"
        pin = frozen_pin or (_github_pin(full, repo, version) if version else None)
        if version and not pin:
            return None, source
        fields += [("author", " and ".join(("{%s}" % _bib_escape(n)) if ent else _bib_escape(n)
                                           for n, ent in cff["authors"])),
                   ("title", "{%s}" % _bib_escape(cff["title"]))]
        if pin:
            fields += [("version", _bib_escape(pin["version"] or "")), ("note", pin["note"])]
        elif cff.get("version"):
            fields.append(("version", _bib_escape(cff["version"])))
        if cff.get("doi"):
            fields.append(("doi", cff["doi"]))
        fields.append(("url", cff.get("url") or repo.get("html_url")))
        year = pin["year"] if pin else (cff.get("date_released") or "")[:4]
        fields.append(("year", year) if year else ("note", f"Accessed {_today()}"))
    else:
        source = "github"
        pin = frozen_pin or _github_pin(full, repo, version)
        if not pin:
            return None, source
        owner = repo.get("owner_name") or repo.get("owner") or full.split("/")[0]
        entity = repo.get("owner_type") == "Organization" or not repo.get("owner_name")
        fields += [("author", ("{%s}" % _bib_escape(owner)) if entity else _bib_escape(owner)),
                   ("title", "{%s}" % _bib_escape(full.split("/")[1])),
                   ("version", _bib_escape(pin["version"] or "")), ("note", pin["note"])]
        if rec.get("doi"):
            fields.append(("doi", rec["doi"]))
        fields += [("publisher", "GitHub"), ("url", repo.get("html_url") or f"https://github.com/{full}"),
                   ("year", pin["year"])]
    if rec.get("pinned_sha"):
        fields = [(key, value) for key, value in fields if key != "url"]
        fields.append(("url", f"https://github.com/{full}/tree/{rec['pinned_sha']}"))
    body = ",\n".join(f"  {k} = {{{v}}}" for k, v in fields if v)
    return f"@software{{{_slug(full.replace('/', '_'))},\n{body}\n}}", source


# ---------------------------------------------------------------------------
# resolve — identifier → bibliographic record from the registry that owns it
# ---------------------------------------------------------------------------

_AUTHORITY = {"ads": 5, "crossref": 4, "datacite": 4, "inspire": 3, "github": 2, "openalex": 2, "arxiv": 1}
_ID_KEYS = ("doi", "arxiv", "bibcode", "openalex", "inspire", "github")


def _record_cache_put(rec: dict) -> None:
    if rec.get("discovery_only"):
        return  # Never promote discovery metadata into authoritative caches.
    cid = _canonical(rec)
    if cid and (rec.get("repo") or {}).get("partial") and _record_cache_get(cid):
        return              # a search hit must not replace the repository's full record
    if cid:
        _atomic_write(_cache_file("records", _cache_key(cid) + ".json"), json.dumps(rec))


def _record_cache_get(cid: str, max_age: float | None = None) -> dict | None:
    path = _cache_file("records", _cache_key(cid) + ".json")
    if os.path.exists(path) and (max_age is None or time.time() - os.path.getmtime(path) < max_age):
        with open(path) as fh:
            return json.load(fh)
    return None


def _alias_put(kind: str, value: str, cid: str) -> None:
    _atomic_write(
        _cache_file("records", "alias_" + _cache_key(f"{kind}_{value}") + ".json"),
        json.dumps({"id": cid})
    )


def _alias_get(kind: str, value: str) -> str | None:
    path = _cache_file("records", "alias_" + _cache_key(f"{kind}_{value}") + ".json")
    if os.path.exists(path):
        with open(path) as fh:
            return json.load(fh).get("id")
    return None


def _merge_records(base: dict, extra: dict) -> dict:
    """Fill what `base` lacks from `extra`; base keeps its title and authors."""
    out = dict(base)
    for k in _ID_KEYS + ("venue", "year", "abstract", "citation_count", "type", "url"):
        if not out.get(k) and extra.get(k):
            out[k] = extra[k]
    if not out.get("title") and extra.get("title"):
        out["title"], out["authors"] = extra["title"], extra.get("authors", [])
    if len(extra.get("abstract") or "") > len(out.get("abstract") or "") + 200:
        out["abstract"] = extra["abstract"]
    out["pdf_urls"] = list(dict.fromkeys((out.get("pdf_urls") or []) + (extra.get("pdf_urls") or [])))
    regs = set(out.get("registries") or [out["registry"]]) | set(extra.get("registries") or [extra["registry"]])
    out["registries"] = sorted(regs, key=lambda r: -_AUTHORITY.get(r, 0))
    return out


def _public(rec: dict, raw: str, kind: str) -> dict:
    out = _public_core(rec, raw, kind)
    if rec.get("repo"):
        out["repo"] = rec["repo"]
    return out


def _public_core(rec: dict, raw: str, kind: str) -> dict:
    return {"resolved": True, "input": raw, "kind": kind, "id": _canonical(rec),
            "ids": {k: rec[k] for k in _ID_KEYS if rec.get(k)},
            "title": rec.get("title", ""), "authors": (rec.get("authors") or [])[:12],
            "n_authors": len(rec.get("authors") or []), "year": rec.get("year"),
            "venue": rec.get("venue", ""), "type": rec.get("type", ""),
            "registries": rec.get("registries") or [rec.get("registry")],
            "url": rec.get("url", ""), "has_abstract": bool(rec.get("abstract"))}


def _resolve_many(identifiers: list) -> list:
    """Batched resolution of mixed identifiers; results in input order.
    arXiv ids go out in one id_list call, DOIs/OpenAlex/INSPIRE in a small
    thread pool, and ADS (when a token exists) enriches everything in one
    batch so records gain bibcodes and DOI↔arXiv cross-links."""
    kinds = [_classify(i) for i in identifiers]
    arxiv_ids = sorted({v for k, v in kinds if k == "arxiv"})
    dois = sorted({v for k, v in kinds if k == "doi"})
    bibcodes = sorted({v for k, v in kinds if k == "bibcode"})
    others = sorted({(k, v) for k, v in kinds if k in ("openalex", "inspire")})
    repos = sorted({v for k, v in kinds if k == "github"})

    try:
        arxiv_found = _arxiv_lookup(arxiv_ids) if arxiv_ids else {}
    except RuntimeError as exc:
        arxiv_found = {identifier.lower(): {
            "error": str(exc), "outcome": getattr(exc, "outcome", "unavailable")
        } for identifier in arxiv_ids}

    def by_doi(identifier):
        errors = []
        for lookup in (_crossref_work, _datacite_doi):
            try:
                record = lookup(identifier)
                if record:
                    return identifier, record
            except RuntimeError as exc:
                errors.append(exc)
        if errors:
            return identifier, {
                "error": "; ".join(str(error) for error in errors),
                "outcome": getattr(errors[0], "outcome", "unavailable"),
            }
        return identifier, None

    def by_other(kv):
        k, v = kv
        try:
            return kv, (_openalex_get(v) if k == "openalex" else _inspire_get("inspire", v))
        except RuntimeError as exc:
            return kv, {"error": str(exc)}

    def by_repo(v):
        try:
            return v, _github_get(v)
        except RuntimeError as exc:
            return v, {"error": str(exc)}

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        doi_found = dict(_context_map(ex, by_doi, dois))
        other_found = dict(_context_map(ex, by_other, others))
        repo_found = dict(_context_map(ex, by_repo, repos))

    ads, ads_error = {}, None
    if _ads_token():
        try:
            ads.update(_ads_lookup("arxiv", arxiv_ids))
            ads.update(_ads_lookup("doi", dois))
            ads.update(_ads_lookup("bibcode", bibcodes))
        except RuntimeError as exc:
            ads_error = str(exc)

    results = []
    for raw, (kind, value) in zip(identifiers, kinds):
        rec, reason = None, None
        if kind == "arxiv":
            rec = arxiv_found.get(value.lower())
            reason = "arXiv API returned no entry for this id"
        elif kind == "doi":
            rec = doi_found.get(value)
            reason = "DOI is not registered at Crossref or DataCite"
        elif kind == "bibcode":
            rec = ads.get(value.lower())
            reason = ads_error or ("bibcode not found in ADS" if _ads_token() else
                                   "bibcode lookup needs an ADS API token (ADS_API_TOKEN or ~/.ads/dev_key)")
        elif kind in ("openalex", "inspire"):
            rec = other_found.get((kind, value))
            reason = f"{kind} returned no record for {value}"
        elif kind == "github":
            rec = repo_found.get(value)
            reason = (f"no public GitHub repository at github.com/{value} (deleted, private, or renamed "
                      "without a redirect)")
        else:
            reason = ("unrecognized identifier — expected an arXiv id, DOI (10.*), ADS bibcode, "
                      "OpenAlex Wnnn, inspire:nnn, or a GitHub repository (github.com/owner/repo)")
        failed = False
        outcome = rec.get("outcome") if isinstance(rec, dict) else "not-found"
        if isinstance(rec, dict) and rec.get("error"):
            reason, rec, failed = rec["error"], None, not rec.get("final")
        if not rec:
            results.append(dict({"resolved": False, "input": raw, "kind": kind, "reason": reason},
                                **({"lookup_error": True, "outcome": outcome or "unavailable"}
                                   if failed else {"outcome": "not-found"})))
            continue
        rec = dict(rec)
        rec.setdefault("registries", [rec["registry"]])
        for key in ((rec.get("arxiv"), rec.get("doi"), rec.get("bibcode")) if kind != "github" else ()):
            hit = ads.get((key or "").lower())
            if hit and hit is not rec:
                rec = _merge_records(rec, hit)
                break
        _record_cache_put(rec)
        _alias_put(kind, value, _canonical(rec))
        public_record = rec
        if kind == "arxiv" and re.search(_ARXIV_CORE + r"v\d+", raw, re.I):
            try:
                public_record = _with_pin(rec, raw, None)
            except (RuntimeError, ValueError) as exc:
                result = {"resolved": False, "input": raw, "kind": kind,
                          "reason": str(exc), "outcome": "not-found"}
                if isinstance(exc, RuntimeError):
                    result.update(lookup_error=True, outcome=getattr(
                        exc, "outcome", "unavailable"
                    ))
                results.append(result)
                continue
        pub = _public(public_record, raw, kind)
        if public_record.get("arxiv_version"):
            pub["requested_version"] = public_record["arxiv_version"]
        m = _GITHUB_REF.search(raw) if kind == "github" else None
        if m:
            try:
                pub["ref"] = _github_ref(rec["repo"]["full_name"], urllib.parse.unquote(m.group(1)))
            except RuntimeError as exc:
                pub["ref"] = {"found": None, "ref": m.group(1), "error": str(exc)}
        results.append(pub)
    return results


def resolve_citation(identifier: str | list[str]) -> dict:
    """Resolve an identifier (or a list of them) to real bibliographic metadata.

    Accepts arXiv ids, DOIs, ADS bibcodes, OpenAlex W-ids, inspire:nnn, in bare,
    prefixed or URL form, and public GitHub repositories (github.com/owner/repo,
    github:owner/repo, git@github.com:owner/repo.git). resolved=false with a
    reason when the registry has no such record. A resolved result is
    existence only — verify_bib / search compare titles, authors and years to
    catch real ids attached to the wrong paper. A repository result carries
    `repo`: archived / fork / moved flags, its CITATION.cff, the paper its
    authors ask to be cited (`preferred_citation`), its software DOI, the
    identifiers its README mentions, and `ref` when the URL names a tag,
    branch or commit (checked to exist).
    """
    many = isinstance(identifier, list)
    if not isinstance(identifier, (str, list)):
        return {"resolved": False, "error": "identifier must be a string or list of strings"}
    idents = identifier if many else [identifier]
    if not idents or any(not isinstance(item, str) or not item.strip() for item in idents):
        return {"resolved": False, "error": "provide at least one nonempty identifier string"}
    try:
        res = _resolve_many(idents)
    except RuntimeError as exc:
        return {"error": f"registry lookup failed ({exc}) — retry, or mark the citation UNVERIFIED"}
    if many:
        return {"results": res, "resolved": all(r.get("resolved") for r in res), "n": len(res)}
    return res[0]


def _full_record(identifier) -> dict | None:
    """The internal record (with abstract and pdf urls) for an identifier —
    from the local record cache when it was resolved within the TTL (no
    network), else resolved now."""
    kind, value = _classify(str(identifier))
    cid = _alias_get(kind, value) if kind != "unknown" else None
    rec = _record_cache_get(cid, META_TTL) if cid else None
    if rec:
        return rec
    r = resolve_citation(identifier)
    if not r.get("resolved"):
        return None
    return _record_cache_get(r["id"])


# ---------------------------------------------------------------------------
# search — a description of a paper → ranked real candidates
# ---------------------------------------------------------------------------

_HINT_RE = re.compile(r"^([A-Za-z][A-Za-z'\-\s]*?)[_:\-]?((?:19|20)\d{2}|\d{2})([A-Za-z0-9_\-]*)$")


def _parse_hint(hint: str) -> dict:
    """Rough cite key → {surname, initial, year, word}. Understands Vaswani2017,
    vaswani2017attention, Vaswani17, Vaswani_2017, Smith2019a, LiW25, JSmith05,
    VanDerWaals1910, planck2016cosmological. Identifiers pass through as `id`."""
    h = (hint or "").strip().strip("{}")
    if not h:
        return {}
    if _classify(h)[0] != "unknown":
        return {"id": h}
    s = _ascii(h).replace("{", "").replace("}", "")
    m = _HINT_RE.match(s)
    if not m:
        sur = re.sub(r"[^A-Za-z\-\s']", " ", s).strip()
        return {"surname": sur or None}
    raw_surname, ytxt, suffix = m.groups()
    if len(ytxt) == 4:
        year = int(ytxt)
    else:
        yy, cur = int(ytxt), datetime.now().year
        year = 2000 + yy if 2000 + yy <= cur + 2 else 1900 + yy
    sur, initial = raw_surname.strip(" _:-"), None
    m2 = re.match(r"^([A-Z][a-z\-']+)([A-Z])$", sur)          # LiW25
    m3 = re.match(r"^([A-Z])([A-Z][a-z\-']+)$", sur)          # JSmith05
    if m2:
        sur, initial = m2.groups()
    elif m3:
        initial, sur = m3.groups()
    sur = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", sur).strip()   # VanDerWaals → Van Der Waals
    word = None
    if suffix:
        w = re.sub(r"[^A-Za-z]", "", suffix)
        if len(w) >= 3:
            word = w.lower()
    return {"surname": sur or None, "initial": initial, "year": year, "word": word}


def _identity_keys(rec: dict) -> list:
    keys = []
    if rec.get("arxiv"):
        keys.append("arxiv:" + rec["arxiv"].lower())
    if rec.get("doi"):
        keys.append("doi:" + rec["doi"].lower())
    if rec.get("bibcode"):
        keys.append("bibcode:" + rec["bibcode"])
    if rec.get("github"):
        keys.append("github:" + rec["github"])
        return keys          # repositories share names freely; only the full name identifies one
    t = _norm_title(rec.get("title", ""))
    fa = _surname(rec["authors"][0]) if rec.get("authors") else ""
    if t and fa:
        keys.append(f"work:{t}:{fa}")
    return keys


def _merge_candidates(records: list) -> list:
    """Collapse the same work reported by several registries into one
    candidate. Records must arrive most-authoritative first."""
    merged, index = [], {}
    for rec in records:
        keys = _identity_keys(rec)
        hit = next((index[k] for k in keys if k in index), None)
        if hit is None:
            rec = dict(rec)
            rec["registries"] = [rec["registry"]]
            hit = len(merged)
            merged.append(rec)
        else:
            merged[hit] = _merge_records(merged[hit], rec)
        for k in keys + _identity_keys(merged[hit]):
            index.setdefault(k, hit)
    return merged


def _given_initial(name: str) -> str:
    name = _ascii(_strip_latex(name or "")).strip()
    if "," in name:
        given = name.split(",", 1)[1].strip()
    else:
        toks = name.split()
        given = " ".join(toks[:-1]) if len(toks) > 1 else ""
    return given[:1].lower()


def _score_candidate(c: dict, title, author, initial, year, words) -> dict:
    s, d = 0.0, {}
    if title:
        d["title_similarity"] = _title_sim(title, c.get("title", ""))
        s += 100 * d["title_similarity"]
    if words:
        want = set(words)
        in_title = set(_content_words(c.get("title", "")))
        in_abs = set(_content_words((c.get("abstract") or "")[:1500]))
        ov_t = len(want & in_title) / len(want)
        ov_a = len(want & in_abs) / len(want)
        s += 40 * ov_t + 12 * ov_a
        d["context_overlap"] = round(max(ov_t, ov_a), 2)
    if author:
        am = _author_match([author], c.get("authors") or [])
        d["first_author_match"] = am["first"]
        s += 30 if am["first"] else (12 if am["any"] else -10)
        if initial and c.get("authors"):
            gi = _given_initial(c["authors"][0])
            if gi and gi != initial.lower():
                s -= 8
                d["initial_mismatch"] = True
    if year and c.get("year"):
        delta = abs(int(year) - int(c["year"]))
        d["year_delta"] = delta
        s += 15 if delta == 0 else (8 if delta == 1 else -15)
    s += 4 * (len(c.get("registries") or []) - 1)
    if c.get("doi") or c.get("bibcode"):
        s += 3
    if c.get("citation_count"):
        s += min(5.0, math.log10(c["citation_count"] + 1))
    d["score"] = round(s, 1)
    return d


def _confidence(d: dict, title, author, year) -> str:
    sim, fam, yd = d.get("title_similarity"), d.get("first_author_match"), d.get("year_delta")
    year_ok = yd is not None and yd <= 1
    if sim is not None:
        if sim >= 0.9 and (fam or year_ok or (not author and not year)):
            return "high"
        return "medium" if sim >= 0.75 else "low"
    if fam and year_ok:
        return "medium"
    return "low"


def search_citation(
    query: str | None = None,
    title: str | None = None,
    author: str | None = None,
    year: int | None = None,
    hint: str | None = None,
    context: str | None = None,
    registries: list[str] | None = None,
    max_results: int = 8,
) -> dict[str, Any]:
    """Find real papers matching a description; returns ranked candidates.

    Give as much as you know: `title` (best), `author` (first-author surname),
    `year`, a rough cite key as `hint` ("Vaswani2017", "planck2016cosmological"),
    and/or the sentence being written as `context`. `query` is free text, or a
    bare identifier or GitHub URL (then this is just a resolve). Software:
    registries=["github"] searches repository names and descriptions (opt-in;
    the default registries are the bibliographic ones). Candidates are ranked by
    cite-check's own title/author/year/context scoring — registry ranking is
    not trusted. Opt in to semanticscholar, pubmed, or dblp for additional
    discovery. Their native IDs are locators only: independently resolve a
    suggested_id, compare metadata, then obtain an official export and assess
    support. Discovery metadata never enters authoritative record caches.
    No search candidate establishes citation identity or claim support.
    """
    supported = {
        "ads",
        "arxiv",
        "crossref",
        "openalex",
        "inspire",
        "github",
    } | _DISCOVERY_SOURCES
    if (
        type(max_results) is not int
        or not 1 <= max_results <= 100
        or year is not None
        and (type(year) is not int or not 1000 <= year <= 9999)
        or any(
            value is not None
            and (not isinstance(value, str) or len(value) > 10000)
            for value in (query, title, author, hint, context)
        )
        or registries is not None
        and (
            not isinstance(registries, list)
            or not registries
            or any(
                not isinstance(name, str) or name not in supported
                for name in registries
            )
        )
    ):
        return {
            "error": "Invalid search arguments or unknown registry selector.",
            "candidates": [],
            "n_candidates": 0,
            "errors": {},
        }
    h = _parse_hint(hint) if hint else {}
    direct = h.get("id") or (
        query if query and _classify(query)[0] != "unknown" else None
    )
    if direct:
        r = resolve_citation(direct)
        r["confidence"] = "high" if r.get("resolved") else "none"
        return {
            "direct": True,
            "query": direct,
            "candidates": [r] if r.get("resolved") else [],
            "n_candidates": 1 if r.get("resolved") else 0,
            "errors": {} if r.get("resolved") else {"resolve": r.get("reason")},
        }
    if query and not title:
        title = query
    author = author or h.get("surname")
    year = int(year) if year else h.get("year")
    initial = h.get("initial")
    words = [h["word"]] if h.get("word") else []
    if context:
        words += [w for w in _content_words(context) if len(w) >= 4][:8]
    words = list(dict.fromkeys(words))
    if not (title or author or words):
        return {
            "error": "give a title/query, author+year hint, or sentence context"
        }

    enabled = list(
        dict.fromkeys(
            registries
            if registries is not None
            else ["ads", "arxiv", "crossref", "openalex", "inspire"]
        )
    )
    if not _ads_token():
        enabled = [r for r in enabled if r != "ads"]
    fns = {
        "ads": _ads_search,
        "arxiv": _arxiv_search,
        "crossref": _crossref_search,
        "openalex": _openalex_search,
        "inspire": _inspire_search,
        "github": _github_search,
        "semanticscholar": _semanticscholar_search,
        "pubmed": _pubmed_search,
        "dblp": _dblp_search,
    }
    kwargs = dict(title=title, author=author, words=words or None, year=year)

    def run(name):
        try:
            budget = _request_budget.get()
            if budget is not None:
                budget.reserve("search")
            return name, fns[name](**kwargs), None
        except Exception as exc:  # one registry down must not sink the search
            return name, [], f"{type(exc).__name__}: {exc}"

    records, errors = [], {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        for name, recs, err in _context_map(
            ex, run, [r for r in enabled if r in fns]
        ):
            records += recs
            if err:
                errors[name] = err
    records.sort(key=lambda r: -_AUTHORITY.get(r["registry"], 0))
    scored = []
    discoveries = [record for record in records if record.get("discovery_only")]
    established = [
        record for record in records if not record.get("discovery_only")
    ]
    for c in _merge_candidates(established):
        d = _score_candidate(c, title, author, initial, year, words)
        d["confidence"] = _confidence(d, title, author, year)
        pub = _public(c, "", "search")
        for k in ("resolved", "input", "kind"):
            pub.pop(k, None)
        scored.append(dict(pub, **d))
        _record_cache_put(c)  # fetch_bibtex / fetch_text reuse it by id
    for candidate in discoveries:
        details = _score_candidate(
            candidate, title, author, initial, year, words
        )
        details["confidence"] = _confidence(details, title, author, year)
        aliases = candidate["suggested_ids"]
        scored.append(
            dict(
                id=candidate["discovery_id"],
                ids={},
                title=candidate["title"],
                authors=candidate["authors"][:12],
                n_authors=len(candidate["authors"]),
                year=candidate["year"],
                venue=candidate["venue"],
                type=candidate["type"],
                registries=[candidate["registry"]],
                url=candidate["url"],
                has_abstract=False,
                discovery_only=True,
                verification_status="unverified",
                suggested_ids=aliases,
                provenance=candidate["provenance"],
                next_action=(
                    "Resolve a suggested_id independently, compare its "
                    "metadata with this candidate, then obtain an official "
                    "export and assess claim support."
                    if aliases
                    else "No official identifier is supplied. Search official "
                    "registries; establish identity before export or support."
                ),
                **details,
            )
        )
    scored.sort(key=lambda x: -x["score"])
    return {
        "query": {
            "title": title,
            "author": author,
            "initial": initial,
            "year": year,
            "words": words,
            "hint": hint,
        },
        "registries": enabled,
        "errors": errors,
        "n_candidates": len(scored),
        "candidates": scored[:max_results],
        "note": (
            "Ranked by cite-check scoring; confirm the candidate through "
            "independent identity checks and official export. Discovery-only "
            "rows require resolving suggested_ids and comparing metadata; "
            "their native id is not an export identifier. "
            "Search never verifies support."
        ),
    }


# ---------------------------------------------------------------------------
# BibTeX — parsing, official export, insertion with provenance, verification
# ---------------------------------------------------------------------------

_PROV_RE = re.compile(r"cite-check:\s*(.*)", re.S)


def _find_close(text: str, open_idx: int) -> int:
    """Index of the '}' or ')' closing the group opened at open_idx, else -1.
    Braces nest; a paren-delimited entry closes at the first ')' at depth 0."""
    paren = text[open_idx] == "("
    depth = 0
    for i in range(open_idx, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if not paren and depth == 0:
                return i
        elif paren and ch == ")" and depth == 0:
            return i
    return -1


_FIELD_START = re.compile(r"\s*([A-Za-z0-9_\-:.+/]+)\s*=\s*")
_BARE = re.compile(r"[^,#\s}]+")


def _parse_fields(body: str) -> dict:
    """`name = value, …` after the key. Values may be {…} (nested), "…",
    bare tokens/macros, and `#`-concatenations. Outer delimiters are removed."""
    fields, i, n = {}, 0, len(body)
    while i < n:
        m = _FIELD_START.match(body, i)
        if not m:
            if body[i:].strip().strip(",").strip():
                raise ValueError("malformed bibliography field")
            break
        name, i, parts = m.group(1).lower(), m.end(), []
        while True:
            while i < n and body[i].isspace():
                i += 1
            if i >= n:
                raise ValueError("missing bibliography field value")
            if body[i] == "{":
                j = _find_close(body, i)
                if j < 0:
                    raise ValueError("unterminated bibliography field")
                parts.append(body[i + 1:j])
                i = j + 1
            elif body[i] == '"':
                j, depth = i + 1, 0
                while j < n:
                    if body[j] == "{":
                        depth += 1
                    elif body[j] == "}":
                        depth -= 1
                    elif body[j] == '"' and depth == 0:
                        break
                    j += 1
                if j >= n:
                    raise ValueError("unterminated quoted bibliography field")
                parts.append(body[i + 1:j])
                i = j + 1
            else:
                m2 = _BARE.match(body, i)
                if not m2:
                    raise ValueError("missing bibliography field value")
                parts.append(m2.group(0))
                i = m2.end()
            while i < n and body[i].isspace():
                i += 1
            if i < n and body[i] == "#":
                i += 1
                continue
            break
        fields[name] = re.sub(r"\s+", " ", "".join(parts)).strip()
        if i < n and body[i] != ",":
            raise ValueError("missing comma between bibliography fields")
        i += 1
    return fields


def _parse_prov(s: str) -> dict:
    out = {}
    for part in re.split(r";\s*", s):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip().strip('"')
    return out


def _next_bib_entry(text: str, start: int) -> int:
    """Find an entry marker outside percent comments between entries."""
    while start < len(text):
        marker = re.search(r"[%@]", text[start:])
        if marker is None:
            return -1
        position = start + marker.start()
        if text[position] == "@":
            return position
        newline = text.find("\n", position)
        if newline < 0:
            return -1
        start = newline + 1
    return -1


def _parse_bib(text: str) -> dict:
    """Entries with raw text and span, plus @comment/@string/@preamble blocks.
    A `@comment{cite-check: …}` directly before an entry becomes its provenance."""
    entries, comments, keys, errors = [], [], {}, []
    i, last_prov, last_prov_end = 0, None, -1
    head = re.compile(r"@\s*([A-Za-z]+)\s*([{(])")
    while True:
        at = _next_bib_entry(text, i)
        if at < 0:
            break
        m = head.match(text, at)
        if not m:
            errors.append(f"malformed entry at character {at}")
            i = at + 1
            continue
        etype, open_idx = m.group(1).lower(), m.end() - 1
        close = _find_close(text, open_idx)
        if close < 0:
            errors.append(f"unterminated entry at character {at}")
            break
        body, raw = text[open_idx + 1:close], text[at:close + 1]
        if etype in ("comment", "string", "preamble"):
            pm = _PROV_RE.search(body) if etype == "comment" else None
            comments.append({"type": etype, "start": at, "end": close + 1, "raw": raw,
                             "cite_check": pm.group(1).strip() if pm else None})
            if pm:
                last_prov, last_prov_end = pm.group(1).strip(), close + 1
            i = close + 1
            continue
        km = re.match(r"\s*([^,\s]+)\s*,", body)
        key = km.group(1) if km else ""
        try:
            if not km:
                raise ValueError("missing entry key or comma")
            fields = _parse_fields(body[km.end():])
        except ValueError as exc:
            errors.append(f"{key or at}: {exc}")
            i = close + 1
            continue
        if key in keys:
            errors.append(f"duplicate bibliography key: {key}")
        prov = _parse_prov(last_prov) if last_prov and not text[last_prov_end:at].strip() else None
        last_prov = None
        entry = {"type": etype, "key": key, "fields": fields, "raw": raw,
                 "start": at, "end": close + 1, "provenance": prov}
        entries.append(entry)
        keys.setdefault(key, entry)
        i = close + 1
    return {"entries": entries, "comments": comments, "keys": keys,
            "errors": errors, "complete": not errors}


def _entry_ids(entry: dict) -> dict:
    """Identifiers an entry carries: doi / arxiv / bibcode, from wherever
    authors and export tools put them (doi, eprint, url, adsurl, note, eid…)."""
    f, ids = entry["fields"], {}
    for src in (f.get("doi", ""), f.get("url", ""), f.get("note", "")):
        m = _DOI_ANY.search(src)
        if m:
            k, v = _classify(m.group(0))
            if k in ("doi", "arxiv"):
                ids.setdefault(k, v)
    ep = f.get("eprint", "").strip()
    if ep and _classify(ep)[0] == "arxiv":
        ids["arxiv"] = _classify(ep)[1]
    if "arxiv" not in ids:
        blob = " ".join(f.get(k, "") for k in ("url", "adsurl", "note", "howpublished", "eid", "journal", "eprint"))
        m = re.search(r"(?:arxiv:|arxiv\.org/(?:abs|pdf|html)/)\s*(" + _ARXIV_CORE + r")", blob, re.I)
        if m:
            ids["arxiv"] = _strip_arxiv_version(m.group(1))
    bc = f.get("bibcode", "").strip()
    m = re.search(r"/abs/([^/\s}]+)", f.get("adsurl", ""))
    if m:
        bc = urllib.parse.unquote(m.group(1))
    if bc and _BIBCODE_RE.match(bc):
        ids["bibcode"] = bc
    srcs = ["url", "howpublished", "repository", "code"]          # the entry's locator, not a "code at…" remark
    if entry["type"] in _SOFTWARE_TYPES:
        srcs.append("note")
    for k in srcs:
        m = _GITHUB_ANY.search(f.get(k, ""))
        if m:
            kind, val = _classify("github.com/" + m.group(1) + "/" + m.group(2))
            if kind == "github":
                ids["github"] = val
                break
    return ids


_SOFTWARE_TYPES = {"software", "softwareversion", "softwaremodule", "codefragment", "misc", "online",
                   "electronic", "www", "manual", "unpublished"}


def _entry_ref(entry: dict) -> str | None:
    """The version a repository entry cites: its version field, or the
    tag / branch / commit in its GitHub URL."""
    f = entry["fields"]
    if f.get("version", "").strip():
        return re.sub(r"[{}]", "", f["version"]).strip()
    for k in ("url", "howpublished", "repository", "note"):
        m = _GITHUB_REF.search(f.get(k, ""))
        if m:
            return urllib.parse.unquote(m.group(1))
    return None


_DEFAULT_PREFER = ["ads", "crossref", "datacite", "inspire", "arxiv", "github"]
_MACRO_CLASSES = re.compile(r"\\documentclass(?:\[[^\]]*\])?\{(?:aastex\w*|aasjournal\w*|mnras|emulateapj|apj\w*|aa)\}")


def _journal_format_for(tex_path: str | None) -> int:
    """ADS journal macros (\\apj, \\mnras) compile only where the class defines
    them; everywhere else ask ADS for journal abbreviations instead."""
    if not tex_path or not os.path.exists(tex_path):
        return 2
    with open(tex_path, errors="replace") as fh:
        return 1 if _MACRO_CLASSES.search(fh.read(6000)) else 2


def _official_bibtex(rec: dict, prefer=None, journal_format: int = 2, max_author: int = 10) -> dict:
    """BibTeX from a registry's own export, in `prefer` order. Never
    synthesised — the one exception is a GitHub repository with no DOI
    export, laid out field for field by _github_bibtex from its authors'
    CITATION.cff or its GitHub record."""
    tried = []
    order = prefer or _DEFAULT_PREFER
    if rec.get("arxiv_version"):
        order = ["arxiv"]
    if rec.get("github") and rec.get("pin"):
        order = ["github"]          # a DOI export would cite the latest version, not the one asked for
    for src in order:
        bib, label = None, src
        try:
            if src == "ads":
                if not _ads_token():
                    tried.append("ads: no API token")
                    continue
                bibcode = rec.get("bibcode")
                if not bibcode:
                    for kind, val in (("doi", rec.get("doi")), ("arxiv", rec.get("arxiv"))):
                        hit = _ads_lookup(kind, [val]).get(val.lower()) if val else None
                        if hit:
                            bibcode = rec["bibcode"] = hit["bibcode"]
                            break
                if not bibcode:
                    tried.append("ads: record not indexed")
                    continue
                bib = _ads_export([bibcode], journal_format, max_author).get(bibcode)
            elif src == "crossref" and rec.get("doi"):
                status, body = _http(f"{_CROSSREF}/{urllib.parse.quote(rec['doi'], safe='')}"
                                     "/transform/application/x-bibtex")
                bib = body if status == 200 and body.lstrip().startswith("@") else None
            elif src == "datacite" and rec.get("doi"):
                status, body = _http(f"https://api.datacite.org/dois/{urllib.parse.quote(rec['doi'], safe='')}",
                                     headers={"Accept": "application/x-bibtex"})
                bib = body if status == 200 and body.lstrip().startswith("@") else None
            elif src == "inspire":
                for kind, val in (("arxiv", rec.get("arxiv")), ("doi", rec.get("doi")), ("inspire", rec.get("inspire"))):
                    if not val:
                        continue
                    path = {"arxiv": "arxiv", "doi": "doi", "inspire": "literature"}[kind]
                    status, body = _http(f"{_INSPIRE}/{path}/{urllib.parse.quote(val, safe='')}?format=bibtex")
                    if status == 200 and body.lstrip().startswith("@"):
                        bib = body
                        break
            elif src == "arxiv" and rec.get("arxiv"):
                status, body = _http(f"https://arxiv.org/bibtex/{rec.get('arxiv_version') or rec['arxiv']}")
                bib = body if status == 200 and body.lstrip().startswith("@") else None
            elif src == "github" and rec.get("github"):
                bib, label = _github_bibtex(rec)
            else:
                continue
        except RuntimeError as exc:
            tried.append(f"{src}: {exc}")
            continue
        if not bib:
            tried.append(f"{src}: version '{rec['pin']}' is not a tag, branch or commit of {rec['github']}"
                         if src == "github" and rec.get("pin") else f"{src}: no export")
            continue
        parsed = _parse_bib(bib)["entries"]
        if not parsed:
            tried.append(f"{src}: unparsable export")
            continue
        entry = parsed[0]
        if rec.get("arxiv_version") and _entry_arxiv_version(entry) != rec["arxiv_version"]:
            tried.append(
                f"{src}: official export omits the requested version "
                f"{rec['arxiv_version']} — refusing to drop the pin"
            )
            continue
        sim = _title_sim(rec.get("title", ""), entry["fields"].get("title", ""))
        if rec.get("title") and entry["fields"].get("title") and sim < 0.6 and not (
                rec.get("github") and _names_repo(entry["fields"]["title"], rec["github"])):
            tried.append(f"{src}: export title mismatch ({sim})")
            continue
        return {"bibtex": _sanitize_bibtex(entry, rec), "source": label, "title_similarity": sim, "tried": tried}
    return {"bibtex": None, "source": None, "tried": tried}


_MONTHS = {"jan": "jan", "january": "jan", "feb": "feb", "february": "feb", "mar": "mar", "march": "mar",
           "apr": "apr", "april": "apr", "may": "may", "jun": "jun", "june": "jun", "jul": "jul", "july": "jul",
           "aug": "aug", "august": "aug", "sep": "sep", "sept": "sep", "september": "sep", "oct": "oct",
           "october": "oct", "nov": "nov", "november": "nov", "dec": "dec", "december": "dec"}


def _sanitize_bibtex(entry: dict, rec: dict) -> str:
    """Encoding repairs on a registry export, then a canonical layout. Crossref
    ships HTML entities and tags, line-wrapped values, month=Sept, and drops
    collaboration authors ('author = { and Ade, …}'); the missing name is put
    back from the same registry's JSON record. No content is invented."""
    fields = {}
    for k, v in entry["fields"].items():
        v = html.unescape(re.sub(r"<[^>]+>", "", v))
        v = re.sub(r"(?<!\\)&", r"\\&", v)
        fields[k] = re.sub(r"\s+", " ", v).strip()
    author = fields.get("author", "")
    if rec.get("authors") and (not author or re.match(r"^\s*and\b", author, re.I)):
        first = re.sub(r"[{}]", "", rec["authors"][0])
        fields["author"] = ("{%s}" % first) + (" " + author.strip() if author.strip() else "")
    if fields.get("month"):
        m = _MONTHS.get(re.sub(r"[^a-z]", "", fields["month"].lower()))
        if m:
            fields["month"] = m
        else:
            fields.pop("month")
    width = max(len(k) for k in fields) if fields else 0
    lines = [f"@{entry['type'].upper()}{{{entry['key']},"]
    for k, v in fields.items():
        val = v if k == "month" else "{" + v + "}"
        lines.append(f"{k:>{width + 6}} = {val},")
    lines[-1] = lines[-1].rstrip(",")
    return "\n".join(lines) + "\n}"


def _rewrite_key(bibtex: str, key: str) -> str:
    return re.sub(r"^(\s*@\w+\s*[{(]\s*)[^,\s]*(\s*,)", lambda m: m.group(1) + key + m.group(2), bibtex, count=1)


def _prov_comment(rec: dict, source: str) -> str:
    title = re.sub(r"[{}@\n\"]", " ", rec.get("title", ""))[:100].strip()
    pin = f"; version={rec['pin']}" if rec.get("github") and rec.get("pin") else ""
    if rec.get("pinned_sha"):
        pin += f"; commit={rec['pinned_sha']}"
    body = f'cite-check: source={source}; id={_canonical(rec)}{pin}; fetched={_today()}; title="{title}"'
    return "@comment{" + body.replace("@", "(at)") + "}"


def _default_key(rec: dict, existing: set) -> str:
    fam = re.sub(r"[^a-z]", "", _surname(rec["authors"][0]) if rec.get("authors") else "") or "anon"
    base = f"{fam.capitalize()}{rec.get('year') or ''}"
    key, n = base, 0
    while key in existing:
        n += 1
        key = base + ("abcdefghijklmnopqrstuvwxyz"[n - 1] if n <= 26 else str(n))
    return key


def _with_pin(rec: dict, identifier: str, version: str | None) -> dict:
    """Fetch software metadata at an immutable commit; retain arXiv version."""
    if rec.get("arxiv"):
        match = re.search(_ARXIV_CORE + r"v\d+", str(identifier), re.I)
        requested = version or (match.group(0) if match else None)
        if requested:
            if re.fullmatch(r"v[1-9]\d*", requested, re.I):
                requested = rec["arxiv"] + requested
            if (not re.fullmatch(_ARXIV_CORE + r"v[1-9]\d*", requested, re.I)
                    or _strip_arxiv_version(requested).lower() != rec["arxiv"].lower()):
                raise ValueError("arXiv version must name the work and a positive vN suffix")
            found = _arxiv_lookup([requested])
            historical = found.get(requested.lower())
            if historical is None:
                if found:
                    raise RegistryLookupError("arxiv", "malformed-response", 200)
                raise ValueError(f"arXiv version does not exist: {requested}")
            actual = historical.get("arxiv_api_version")
            if not actual or actual.lower() != requested.lower():
                raise RegistryLookupError("arxiv", "malformed-response", 200)
            pinned = dict(historical, arxiv_version=actual)
            # Work aliases remain stable; title/abstract/authors are historical.
            for key in _ID_KEYS:
                if not pinned.get(key) and rec.get(key):
                    pinned[key] = rec[key]
            return pinned
    if not rec.get("github"):
        return rec
    match = _GITHUB_REF.search(str(identifier or ""))
    requested = version or (urllib.parse.unquote(match.group(1)) if match else None)
    repo = rec.get("repo") or {}
    full = repo.get("full_name") or rec["github"]
    ref = _github_ref(full, requested or repo.get("default_branch") or "HEAD")
    if not ref.get("found"):
        raise ValueError(f"repository version does not exist: {requested}")
    pinned = _github_get(full, ref=ref["sha"])
    if not pinned or pinned.get("error"):
        raise RuntimeError("cannot fetch pinned repository metadata")
    return dict(pinned, pin=requested or ref["sha"], pinned_sha=ref["sha"],
                pinned_date=ref.get("date"),
                requested_version=requested or ref["sha"])


def _text_identity(rec: dict) -> str:
    version = rec.get("pinned_sha") or rec.get("arxiv_version")
    return _canonical(rec) + ("@" + version if version else "")


def fetch_bibtex(identifier: str, key: str | None = None, prefer: list[str] | None = None,
                 journal_format: int | None = None, tex_path: str | None = None,
                 max_author: int = 10, version: str | None = None) -> dict:
    """Official BibTeX for one identifier, from ADS / Crossref / DataCite /
    INSPIRE / arXiv (first that has it, in `prefer` order); a GitHub repository
    with no DOI export gets an @software entry laid out from its CITATION.cff
    (source citation-cff) or its GitHub record with the release or commit
    pinned (source github). `version` (or a /tree/<ref> URL) pins the tag,
    branch or commit that was used; it must exist. `key` renames the entry. journal_format (ADS): 1 macros, 2 abbreviations, 3 full names —
    auto-detected from tex_path's documentclass when omitted. bibtex=null means
    no registry exports one: do not hand-write it.
    """
    rec = _full_record(identifier)
    if rec is None:
        r = resolve_citation(identifier)
        return {"bibtex": None, "resolved": False, "reason": r.get("reason") or r.get("error")}
    try:
        rec = _with_pin(rec, identifier, version)
    except (RuntimeError, ValueError) as exc:
        return {"bibtex": None, "resolved": False, "reason": str(exc),
                "lookup_error": isinstance(exc, RuntimeError)}
    jf = int(journal_format) if journal_format else _journal_format_for(tex_path)
    got = _official_bibtex(rec, prefer, jf, max_author)
    if not got["bibtex"]:
        return {"bibtex": None, "resolved": True, "id": _canonical(rec), "tried": got["tried"],
                "reason": ("no registry offers a BibTeX export for this record — do not hand-write "
                           "one; cite a version that has a DOI or arXiv id, or record the gap")}
    bib = _rewrite_key(got["bibtex"], key) if key else got["bibtex"]
    return dict({"bibtex": bib, "key": _parse_bib(bib)["entries"][0]["key"], "source": got["source"],
                 "id": _canonical(rec), "ids": {k: rec[k] for k in _ID_KEYS if rec.get(k)},
                 "title": rec["title"], "provenance": _prov_comment(rec, got["source"]), "tried": got["tried"]},
                **_repo_advice(rec))


def _repo_advice(rec: dict) -> dict:
    """For a repository: what its record says the writer should know."""
    repo = rec.get("repo") or {}
    out = {}
    if repo.get("notes"):
        out["repo_notes"] = repo["notes"]
    pc = repo.get("preferred_citation")
    if pc and pc.get("ids"):
        out["preferred_citation"] = next(iter(pc["ids"].values()))
    elif repo.get("readme_ids"):
        out["readme_ids"] = repo["readme_ids"]
        out.setdefault("repo_notes", []).append(
            "no CITATION file; the README links these identifiers — if one is the paper the authors ask "
            "to be cited, resolve and add it too")
    return out


@dataclasses.dataclass
class BibliographyItem:
    """An official bibliography request with an optional citation key and pin."""

    identifier: str
    key: str | None = None
    version: str | None = None


@_serialized_bibliography
def bib_add(bib_path: str, items: list[BibliographyItem | str], prefer: list[str] | None = None, journal_format: int | None = None,
            tex_path: str | None = None, replace: bool = False, max_author: int = 10) -> dict:
    """Add official entries to a .bib. items: [{"identifier": …, "key": …}] (key
    optional → Surname2017; "version" pins a GitHub repository's tag, branch
    or commit). Each entry is written with a provenance comment.
    Duplicates (same DOI/arXiv/bibcode already present) are reported, not
    added; an existing key is left alone unless replace=true, which swaps a
    hand-written entry for the official one under the same key.
    """
    bib_path = os.path.realpath(bib_path)
    text = ""
    if os.path.exists(bib_path):
        with open(bib_path, errors="replace") as fh:
            text = fh.read()
    if isinstance(items, (str, dict)):
        items = [items]
    if not isinstance(items, list) or not items:
        return {"ok": False, "error": "items must be a nonempty list", "results": []}
    items = [dataclasses.asdict(item) if isinstance(item, BibliographyItem) else item
             for item in items]
    parsed = _parse_bib(text)
    if not parsed["complete"]:
        return {"ok": False, "error": "; ".join(parsed["errors"]), "results": []}
    requested = set()
    for item in items:
        if not isinstance(item, (str, dict)):
            return {"ok": False, "error": "items must be identifiers or objects", "results": []}
        if isinstance(item, dict):
            identifier = item.get("identifier") or item.get("id")
            if not isinstance(identifier, str) or not identifier.strip():
                return {"ok": False, "error": "each item needs an identifier string", "results": []}
            if item.get("version") is not None and not isinstance(item["version"], str):
                return {"ok": False, "error": "version must be a string", "results": []}
        elif not item.strip():
            return {"ok": False, "error": "empty identifier", "results": []}
        key = item.get("key") if isinstance(item, dict) else None
        if key is not None:
            if not isinstance(key, str) or not key or re.search(r"[\s,{}()=]", key):
                return {"ok": False, "error": "invalid bibliography key", "results": []}
            if key in requested:
                return {"ok": False, "error": f"duplicate key in batch: {key}", "results": []}
            requested.add(key)
    by_id = {}
    for e in parsed["entries"]:
        ids = _entry_ids(e)
        if any(ids.get(k) for k in ("doi", "arxiv", "bibcode")):
            ids.pop("github", None)       # a paper that links its code is not the code
        for k, v in ids.items():
            by_id.setdefault(f"{k}:{v.lower()}", e["key"])
    jf = int(journal_format) if journal_format else _journal_format_for(tex_path)
    results, additions, replacements = [], [], {}
    taken = set(parsed["keys"])
    for item in items:
        if isinstance(item, str):
            item = {"identifier": item}
        ident, want = item.get("identifier") or item.get("id"), item.get("key")
        rec = _full_record(ident) if ident else None
        if rec is None:
            results.append({"identifier": ident, "key": want, "status": "unresolved"})
            continue
        try:
            rec = _with_pin(rec, ident, item.get("version"))
        except (RuntimeError, ValueError) as exc:
            results.append({"identifier": ident, "key": want,
                            "status": "unresolved", "note": str(exc)})
            continue
        dup = next((by_id[f"{k}:{rec[k].lower()}"] for k in ("doi", "arxiv", "bibcode", "github")
                    if rec.get(k) and f"{k}:{rec[k].lower()}" in by_id), None)
        if dup and dup != want and not replace:
            results.append({"identifier": ident, "key": want, "status": "duplicate", "existing_key": dup,
                            "note": f"already in the .bib as {dup} — cite that key"})
            continue
        key = want or dup or _default_key(rec, taken)
        if key in taken and key not in parsed["keys"]:
            results.append({"identifier": ident, "key": key, "status": "key-conflict",
                            "note": "key already reserved by this batch"})
            continue
        if key in parsed["keys"] and not replace:
            have = _entry_ids(parsed["keys"][key])
            same = any(have.get(k) and rec.get(k) and have[k].lower() == rec[k].lower() for k in ("doi", "arxiv", "bibcode", "github"))
            results.append({"identifier": ident, "key": key, "status": "exists" if same else "key-conflict",
                            "note": None if same else f"key {key} already holds a different work; pick another key or replace=true"})
            continue
        got = _official_bibtex(rec, prefer, jf, max_author)
        if not got["bibtex"]:
            results.append({"identifier": ident, "key": key, "status": "no-official-bibtex", "tried": got["tried"]})
            continue
        block = _prov_comment(rec, got["source"]) + "\n" + _rewrite_key(got["bibtex"], key).strip() + "\n"
        status = "replaced" if key in parsed["keys"] else "added"
        (replacements.__setitem__(key, block) if status == "replaced" else additions.append((key, block)))
        taken.add(key)
        for k in ("doi", "arxiv", "bibcode", "github"):
            if rec.get(k):
                by_id[f"{k}:{rec[k].lower()}"] = key
        results.append(dict({"identifier": ident, "key": key, "status": status, "source": got["source"],
                             "id": _canonical(rec), "title": rec["title"]}, **_repo_advice(rec)))
    accepted = {"added", "replaced", "exists", "duplicate"}
    if any(result["status"] not in accepted for result in results):
        for result in results:
            if result["status"] in {"added", "replaced"}:
                result["status"] = "aborted"
        return {"bib": bib_path, "ok": False, "results": results,
                "error": "batch validation failed; bibliography unchanged"}
    if replacements or additions:
        new = text
        for e in sorted(parsed["entries"], key=lambda e: -e["start"]):
            if e["key"] not in replacements:
                continue
            start = e["start"]
            prev = [c for c in parsed["comments"] if c["cite_check"] and c["end"] <= start
                    and not text[c["end"]:start].strip()]
            if prev:
                start = prev[-1]["start"]
            new = new[:start] + replacements[e["key"]] + new[e["end"]:]
        if additions:
            new = new.rstrip("\n") + ("\n\n" if new.strip() else "") + "\n".join(b for _, b in additions)
        _atomic_write(bib_path, new)
    return {"bib": bib_path, "results": results,
            "ok": all(r["status"] in ("added", "replaced", "exists", "duplicate") for r in results)}


_OK_STATUS = {"VERIFIED", "FOUND"}



def _entry_arxiv_version(entry: dict) -> str | None:
    """Return a version named in the entry's identifier-bearing fields."""
    fields = entry["fields"]
    for key in ("eprint", "arxiv", "url", "doi"):
        match = re.search(_ARXIV_CORE + r"v\d+", fields.get(key, ""), re.I)
        if match:
            return match.group(0)
    return None


def _compare_arxiv_version(entry: dict, pub: dict, version: str) -> dict:
    """Compare against the exact arXiv edition, never the latest metadata."""
    record = dict(pub["ids"])
    record.setdefault("arxiv", _entry_ids(entry).get("arxiv"))
    try:
        historical = _with_pin(record, "arxiv:" + version, version)
    except (RuntimeError, ValueError) as exc:
        return {
            "key": entry["key"],
            "status": "UNRESOLVED" if isinstance(exc, RuntimeError) else "NOT_FOUND",
            "via": "arxiv:" + version, "id": pub["id"], "ids": pub["ids"],
            "notes": [str(exc)], "provenance": entry["provenance"],
        }
    result = _compare(
        entry, _public(historical, "arxiv:" + version, "arxiv"),
        "arxiv:" + version,
    )
    result["arxiv_version"] = historical["arxiv_version"]
    return result

def _compare(entry: dict, pub: dict, via: str) -> dict:
    """Entry fields vs the registry record: the actual existence test."""
    f = entry["fields"]
    title, authors, year = f.get("title", ""), _split_bib_authors(f.get("author", "")), _year(f.get("year"))
    sim = _title_sim(title, pub["title"]) if title else None
    am = _author_match(authors, pub["authors"])
    yd = abs(year - pub["year"]) if year and pub.get("year") else None
    notes = []
    if sim is None:
        status = "PROBABLE"
        notes.append("entry has no title — the identifier resolves but nothing can be compared")
    elif sim >= 0.9:
        status = "VERIFIED"
        if am["first"] is False:
            status = "PROBABLE"
            notes.append(f"first author differs: bib '{authors[0]}' vs registry '{pub['authors'][0]}'")
        if yd is not None and yd > 2:
            status = "PROBABLE"
            notes.append(f"year differs by {yd} (bib {year}, registry {pub['year']})")
    elif sim >= 0.75:
        status = "PROBABLE" if am["first"] else "MISMATCH"
        notes.append(f"title similarity only {sim}: registry has '{pub['title'][:90]}'")
    else:
        status = "MISMATCH"
        notes.append(f"identifier resolves to a different paper: '{pub['title'][:90]}' (similarity {sim})")
    return {"key": entry["key"], "status": status, "via": via, "id": pub["id"], "ids": pub["ids"],
            "title_similarity": sim, "first_author_match": am["first"], "year_bib": year,
            "year_registry": pub.get("year"), "registry_title": pub["title"], "notes": notes,
            "provenance": entry["provenance"]}


def _names_repo(title: str, full: str) -> bool:
    """Does the title name the repository as a whole word run ('corner.py:
    Scatterplot matrices…' names dfm/corner.py)?"""
    name = _norm_title(full.split("/")[-1])
    return len(name) >= 3 and f" {name} " in f" {_norm_title(title)} "


def _compare_repo(entry: dict, pub: dict) -> dict:
    """Entry fields vs the GitHub repository its URL points at. The title must
    be the repository's own (CITATION.cff title, name, name and description,
    or a title that names it); an entry titled as the paper the repository
    asks to be cited is FOUND — that paper is what the entry should be. A
    cited version must exist as a tag, branch or commit."""
    requested = _entry_ref(entry)
    if requested:
        try:
            raw = _github_get(pub["ids"]["github"])
            if not raw or raw.get("error"):
                raise RuntimeError("repository unavailable")
            pinned = _with_pin(raw, pub["id"], requested)
            pub = _public(pinned, pub["id"], "github")
        except (RuntimeError, ValueError) as exc:
            return {"key": entry["key"], "status": "UNRESOLVED",
                    "via": pub["id"], "id": pub["id"], "ids": pub["ids"],
                    "notes": [f"cited version could not be checked: {exc}"],
                    "provenance": entry["provenance"]}
    f, repo = entry["fields"], pub.get("repo") or {}
    full = repo.get("full_name") or pub["ids"]["github"]
    title, authors, year = f.get("title", ""), _split_bib_authors(f.get("author", "")), _year(f.get("year"))
    name, desc = full.split("/")[1], repo.get("description") or ""
    own = [t for t in (pub["title"], name, full, desc, f"{name}: {desc}", f"{pub['title']}: {desc}") if t]
    sim = max(_title_sim(title, t) for t in own) if title else None
    people = list(pub.get("authors") or []) + [x for x in (repo.get("owner_name"), repo.get("owner")) if x]
    am = _author_match(authors, people)
    out = {"key": entry["key"], "via": f"github:{pub['ids']['github']}", "id": pub["id"], "ids": pub["ids"],
           "title_similarity": sim, "first_author_match": am["first"], "year_bib": year,
           "year_registry": pub.get("year"), "registry_title": pub["title"],
           "notes": list(repo.get("notes") or []), "provenance": entry["provenance"]}
    if sim is None:
        out["status"] = "PROBABLE"
        out["notes"].append("entry has no title — the repository exists but nothing can be compared")
    elif sim >= 0.9:
        out["status"] = "VERIFIED"
    else:
        paper = _repo_paper_match(title, repo)
        if paper:
            return dict(out, status=paper["status"], id=paper.get("id", out["id"]), ids=paper.get("ids", out["ids"]),
                        title_similarity=paper["similarity"], registry_title=paper["title"],
                        notes=[paper["note"]] + out["notes"])
        if _names_repo(title, full):
            out["status"] = "VERIFIED"
            out["notes"].append(f"title names the repository; its own title is '{pub['title'][:80]}'")
        elif sim >= 0.75:
            out["status"] = "PROBABLE"
            out["notes"].append(f"title similarity only {sim}: the repository is '{full}' — '{desc[:80]}'")
        else:
            out["status"] = "MISMATCH"
            out["notes"] = [f"the URL points at a different work: github.com/{full} — '{desc[:80]}' "
                                f"(similarity {sim})"]
            return out
    if am["first"] is False and am["any"] is False:
        out["status"] = "PROBABLE"
        out["notes"].append(f"authors differ: bib '{authors[0]}' vs repository '{people[0]}'")
    ref = _entry_ref(entry)
    if ref:
        try:
            out["ref"] = _github_ref(full, ref)
        except RuntimeError as exc:
            out["ref"] = {"found": None, "ref": ref}
            out["notes"].append(f"cited version '{ref}' not checked: {exc}")
        if out["ref"]["found"] is False:
            out["status"] = "PROBABLE"
            out["notes"].append(f"cited version '{ref}' is not a tag, branch or commit of {full}")
    return out


def _repo_paper_match(title: str, repo: dict) -> dict | None:
    """Is an entry pointing at a repository really the paper that repository
    asks to be cited (CITATION.cff / CITATION.bib) or links from its README?"""
    pc = repo.get("preferred_citation") or {}
    declared = [("doi:" if k == "doi" else "arXiv:") + v for k, v in (pc.get("ids") or {}).items()]
    candidates = list(dict.fromkeys(declared + list(repo.get("readme_ids") or [])[:6]))
    try:
        resolved = _resolve_many(candidates) if candidates else []
    except RuntimeError:
        resolved = []
    for r in resolved:
        if r.get("resolved"):
            s = _title_sim(title, r["title"])
            if s >= 0.9:
                where = pc.get("source") if r["input"] in declared else "linked from the README"
                return {"status": "FOUND", "id": r["id"], "ids": r["ids"], "similarity": s, "title": r["title"],
                        "note": f"entry is the paper '{r['title'][:80]}' ({where}), not the repository — replace "
                                f"it with the official entry: bib_add(items=[{{'identifier': '{r['id']}', "
                                "'key': …}], replace=true)"}
    if pc.get("title") and _title_sim(title, pc["title"]) >= 0.9:
        return {"status": "PROBABLE", "similarity": _title_sim(title, pc["title"]), "title": pc["title"],
                "note": f"entry is the paper the repository asks to be cited ({pc.get('source')}), which declares "
                        f"no DOI or arXiv id — find it with search_citation(title='{pc['title'][:80]}')"}
    return None


def _search_entry(entry: dict) -> dict:
    f = entry["fields"]
    title, authors, year = f.get("title", ""), _split_bib_authors(f.get("author", "")), _year(f.get("year"))
    base = {"key": entry["key"], "via": "search", "provenance": entry["provenance"], "year_bib": year}
    if not title:
        return dict(base, status="UNRESOLVED", notes=["no identifier and no title — nothing to look up"])
    s = search_citation(title=title, author=_surname(authors[0]) if authors else None, year=year, max_results=3)
    cands = s.get("candidates") or []
    if cands and cands[0]["confidence"] == "high":
        c = cands[0]
        return dict(base, status="FOUND", id=c["id"], ids=c["ids"], title_similarity=c.get("title_similarity"),
                    first_author_match=c.get("first_author_match"), year_registry=c.get("year"),
                    registry_title=c["title"],
                    notes=["entry carries no identifier; matched by search — replace it with the official "
                           f"entry: bib_add(items=[{{'identifier': '{c['id']}', 'key': '{entry['key']}'}}], replace=true)"])
    if cands and cands[0]["confidence"] == "medium":
        c = cands[0]
        return dict(base, status="PROBABLE", id=c["id"], ids=c["ids"], title_similarity=c.get("title_similarity"),
                    first_author_match=c.get("first_author_match"), year_registry=c.get("year"),
                    registry_title=c["title"],
                    notes=[f"closest registry match: '{c['title'][:90]}' ({c['id']}, similarity "
                           f"{c.get('title_similarity')}) — confirm by eye, then bib_add(replace=true)"])
    closest = f"; closest: '{cands[0]['title'][:70]}' ({cands[0].get('title_similarity')})" if cands else ""
    return dict(base, status="UNRESOLVED", notes=[f"no registry match for title '{title[:90]}'{closest}"])


_LINT_MAX_BYTES = 4 * 1024 * 1024
_LINT_MAX_ENTRIES = 2000
_LINT_CREATOR = ("author", "editor", "organization", "institution")
_LINT_DATE = ("year", "date")
_LINT_RULES = {
    "article": [
        ("title",),
        _LINT_CREATOR,
        _LINT_DATE,
        ("journal", "journaltitle"),
    ],
    "book": [("title",), _LINT_CREATOR, _LINT_DATE, ("publisher",)],
    "collection": [("title",), _LINT_CREATOR, _LINT_DATE, ("publisher",)],
    "inbook": [("title",), _LINT_CREATOR, _LINT_DATE, ("booktitle",)],
    "incollection": [("title",), _LINT_CREATOR, _LINT_DATE, ("booktitle",)],
    "inproceedings": [("title",), _LINT_CREATOR, _LINT_DATE, ("booktitle",)],
    "conference": [("title",), _LINT_CREATOR, _LINT_DATE, ("booktitle",)],
    "proceedings": [("title",), _LINT_DATE],
    "report": [
        ("title",),
        _LINT_CREATOR,
        _LINT_DATE,
        ("institution", "organization"),
    ],
    "techreport": [
        ("title",),
        _LINT_CREATOR,
        _LINT_DATE,
        ("institution", "organization"),
    ],
    "thesis": [
        ("title",),
        _LINT_CREATOR,
        _LINT_DATE,
        ("institution", "school"),
    ],
    "phdthesis": [
        ("title",),
        _LINT_CREATOR,
        _LINT_DATE,
        ("institution", "school"),
    ],
    "mastersthesis": [
        ("title",),
        _LINT_CREATOR,
        _LINT_DATE,
        ("institution", "school"),
    ],
    **{
        kind: [("title",), ("url", "doi", "repository", "howpublished")]
        for kind in (
            "software",
            "softwareversion",
            "softwaremodule",
            "codefragment",
            "dataset",
            "online",
            "electronic",
            "www",
        )
    },
    **{kind: [] for kind in ("misc", "manual", "unpublished", "xdata", "set")},
}


def _lint_deferred_fields(entry: dict[str, Any]) -> set[str]:
    """Identify unexpanded top-level field expressions in parsed input."""
    raw = entry["raw"]
    body = raw[raw.index(",") + 1 : -1] if "," in raw else ""
    deferred: set[str] = set()
    position = 0
    while match := _FIELD_START.match(body, position):
        name, position = match.group(1).lower(), match.end()
        while position < len(body):
            while position < len(body) and body[position].isspace():
                position += 1
            start = position
            if body[position] == "{":
                position = _find_close(body, position) + 1
            elif body[position] == '"':
                position += 1
                depth = 0
                while position < len(body):
                    character = body[position]
                    if character == "{":
                        depth += 1
                    elif character == "}":
                        depth -= 1
                    elif character == '"' and depth == 0:
                        position += 1
                        break
                    position += 1
            else:
                token = _BARE.match(body, position)
                if token is None:
                    break  # The parser rejects this before linting.
                position = token.end()
                if not token.group().isdigit():
                    deferred.add(name)
            if re.search(r"\\[A-Za-z]+", body[start:position]):
                deferred.add(name)
            while position < len(body) and body[position].isspace():
                position += 1
            if position < len(body) and body[position] == "#":
                deferred.add(name)
                position += 1
                continue
            break
        position += 1  # Comma already validated by the parser.
    return deferred


def _lint_entry_ids(entry: dict[str, Any]) -> dict[str, str]:
    """Read literal work locators, excluding free-text notes and macros."""
    deferred = _lint_deferred_fields(entry)
    fields = {
        name: value
        for name, value in entry["fields"].items()
        if name not in deferred and name != "note"
    }
    return _entry_ids(dict(entry, fields=fields))


def _lint_year(value: str, field: str) -> int | None:
    """Extract a supported literal year, deferring legitimate date statuses."""
    if value.lower() in {"forthcoming", "in press", "n.d.", "undated"}:
        return None
    pattern = (
        r"\d{4}(?:-\d{2}(?:-\d{2})?)?(?:[?~%]|/"
        r"(?:\d{4}(?:-\d{2}(?:-\d{2})?)?|\.\.))?"
    )
    if re.fullmatch(pattern if field == "date" else r"\d{4}", value):
        return int(value[:4])
    raise ValueError("not a supported literal year/date")


def _lint_local_issues(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Return conservative style advice, without resolving inherited data."""
    fields = entry["fields"]
    deferred = _lint_deferred_fields(entry)
    issues: list[dict[str, Any]] = []

    def add(code: str, field: str, message: str, action: str) -> None:
        issues.append(
            dict(code=code, field=field, message=message, action=action)
        )

    kind = entry["type"]
    if kind not in _LINT_RULES:
        add(
            "unknown-entry-type",
            "entrytype",
            f"No metadata rules are defined for @{kind}.",
            "Check that the selected bibliography style supports this type.",
        )
    inherited = bool(fields.get("crossref") or fields.get("xdata"))
    if inherited:
        add(
            "inheritance-not-expanded",
            "crossref" if fields.get("crossref") else "xdata",
            "Inherited fields have not been expanded.",
            "Check the resolved bibliography with its intended processor.",
        )
    relevant = {
        "title",
        "year",
        "date",
        "author",
        "editor",
        "organization",
        "institution",
        "school",
        "journal",
        "journaltitle",
        "booktitle",
        "publisher",
        "doi",
        "url",
        "repository",
        "code",
        "howpublished",
        "eprint",
        "bibcode",
        "adsurl",
        "eid",
        "note",
    }
    for field in sorted(deferred & relevant):
        add(
            "field-macro-unexpanded",
            field,
            "A macro or concatenation prevents a literal metadata check.",
            "Check the expanded value with the intended bibliography style.",
        )
    preprint = bool(_lint_entry_ids(entry).get("arxiv"))
    if not inherited:
        for alternatives in _LINT_RULES.get(kind, []):
            if preprint and alternatives[0] == "journal":
                continue
            if not any(fields.get(name) for name in alternatives):
                add(
                    "missing-field",
                    alternatives[0],
                    "No value for " + " or ".join(alternatives) + ".",
                    "Check the official export and style requirements; "
                    "do not invent missing metadata.",
                )
    if kind not in {"xdata", "set"}:
        for field in _LINT_DATE:
            value = fields.get(field)
            if not value or field in deferred:
                continue
            try:
                year = _lint_year(value, field)
            except ValueError:
                add(
                    "invalid-year",
                    field,
                    f"The literal {field} is outside supported date syntax.",
                    "Check the official export and date syntax for the style.",
                )
                continue
            if year and year > int(_today()[:4]):
                add(
                    "future-year",
                    field,
                    "The date is in the future; forthcoming work may be valid.",
                    "Confirm the release date in the source export.",
                )
    return issues


def _lint_record_valid(record: Any) -> bool:
    """Check provider shape before using it as comparison input."""
    return (
        isinstance(record, dict)
        and record.get("resolved") is True
        and isinstance(record.get("id"), str)
        and bool(record["id"])
        and _classify(record["id"])[0] != "unknown"
        and isinstance(record.get("registries", []), list)
        and all(
            isinstance(registry, str)
            for registry in record.get("registries", [])
        )
        and isinstance(record.get("ids"), dict)
        and all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in record["ids"].items()
        )
        and isinstance(record.get("title"), str)
        and isinstance(record.get("authors"), list)
        and all(isinstance(author, str) for author in record["authors"])
        and (record.get("year") is None or type(record["year"]) is int)
        and isinstance(record.get("venue", ""), str)
        and isinstance(record.get("type", ""), str)
    )


def _lint_compare_entries(
    entries: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Compare own-ID metadata without title searches or file changes."""
    plans: dict[str, list[str]] = {}
    outcomes: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for entry in entries:
        if entry["type"] in {"xdata", "set"}:
            outcomes.append(
                dict(key=entry["key"], status="not-applicable", identifiers=[])
            )
            continue
        ids = _lint_entry_ids(entry)
        # Incidental code links in paper citations do not identify the paper.
        if any(name in ids for name in ("doi", "arxiv", "bibcode")):
            ids.pop("github", None)
        pinned = _entry_arxiv_version(entry) or (
            ids.get("github") and _entry_ref(entry)
        )
        identifiers = [f"{name}:{value}" for name, value in ids.items()]
        status = (
            "pinned-version-skipped"
            if pinned
            else "pending"
            if identifiers
            else "no-identifier"
        )
        if status == "pending":
            plans[entry["key"]] = identifiers
        outcomes.append(
            dict(key=entry["key"], status=status, identifiers=identifiers)
        )
    requested = list(
        dict.fromkeys(value for values in plans.values() for value in values)
    )
    try:
        rows = _resolve_many(requested) if requested else []
    except (RuntimeError, OSError, ValueError):
        rows = []
    records = {}
    if isinstance(rows, list):
        for row in rows:
            if (
                isinstance(row, dict)
                and isinstance(row.get("input"), str)
                and row["input"] in requested
            ):
                # Duplicate responses are ambiguous, not independent evidence.
                key = row["input"]
                records[key] = None if key in records else row
    for entry, outcome in zip(entries, outcomes):
        if outcome["status"] == "not-applicable":
            continue
        code = "registry-comparison-unavailable"
        message = "No usable own-identifier registry comparison is available."
        if outcome["status"] == "pinned-version-skipped":
            code = "registry-version-unchecked"
            message = "Pinned versions are not compared with latest metadata."
        elif outcome["status"] == "pending":
            outcome["status"] = "unavailable"
            confirmed = None
            for identifier in plans[entry["key"]]:
                record = records.get(identifier)
                if not isinstance(record, dict) or not _lint_record_valid(
                    record
                ):
                    continue
                aliases = {_classify(record["id"])} | {
                    _classify(f"{name}:{value}")
                    for name, value in record["ids"].items()
                }
                if _classify(identifier) not in aliases:
                    outcome["status"] = "identity-unconfirmed"
                    continue
                # Deferred expressions cannot establish metadata identity.
                deferred = _lint_deferred_fields(entry)
                if deferred & {"title", "author", "year", "date"}:
                    outcome["status"] = "identity-unconfirmed"
                    continue
                comparison_entry = entry
                if not entry["fields"].get("year"):
                    date = entry["fields"].get("date", "")
                    try:
                        date_year = _lint_year(date, "date") if date else None
                    except ValueError:
                        date_year = None
                    if date_year:
                        comparison_entry = dict(
                            entry,
                            fields=dict(entry["fields"], year=str(date_year)),
                        )
                comparison = _compare(comparison_entry, record, identifier)
                if comparison["status"] == "VERIFIED":
                    confirmed = record
                    break
                outcome["status"] = "identity-unconfirmed"
            if confirmed is not None:
                outcome["status"] = "compared"
                outcome["resolved_id"] = confirmed["id"]
                fields = entry["fields"]
                year = _year(fields.get("year") or fields.get("date"))
                if year and confirmed.get("year") and year != confirmed["year"]:
                    issues.append(
                        dict(
                            key=entry["key"],
                            field="year",
                            code="registry-year-difference",
                            message="The same-work registry record has a "
                            "different year; print dates may differ.",
                            action="Review the intended version and official "
                            "export before changing the date.",
                            evidence=dict(
                                id=confirmed["id"], year=confirmed["year"]
                            ),
                        )
                    )
                ids = _lint_entry_ids(entry)
                if (
                    ids.get("arxiv")
                    and not ids.get("doi")
                    and confirmed["ids"].get("doi")
                    and confirmed.get("venue")
                    and (
                        confirmed.get("type")
                        in {
                            "journal-article",
                            "article",
                            "proceedings-article",
                            "conference-paper",
                            "book-chapter",
                        }
                        or "arxiv" in (confirmed.get("registries") or [])
                    )
                    and not re.search(
                        r"arxiv|preprint", confirmed["venue"], re.I
                    )
                ):
                    issues.append(
                        dict(
                            key=entry["key"],
                            field="entrytype",
                            code="preprint-publication-review",
                            message="The own-ID record explicitly links this "
                            "preprint to a DOI and publication venue.",
                            action="Review whether the preprint or published "
                            "version is intended; retain intentional versions.",
                            evidence=dict(
                                id=confirmed["id"],
                                ids=confirmed["ids"],
                                venue=confirmed["venue"],
                            ),
                        )
                    )
                continue
            if outcome["status"] == "identity-unconfirmed":
                code = "registry-identity-unconfirmed"
                message = (
                    "Metadata or identifier aliases do not confirm "
                    "that this is the same work."
                )
        issues.append(
            dict(
                key=entry["key"],
                field="identifier",
                code=code,
                message=message,
                action="Resolve the intended "
                "work and inspect its official export manually.",
            )
        )
    return dict(
        requested=True,
        identifiers_requested=requested,
        identifier_count=len(requested),
        comparable_entries=sum(
            row["status"] != "not-applicable" for row in outcomes
        ),
        compared_entries=sum(row["status"] == "compared" for row in outcomes),
        outcomes=outcomes,
    ), issues


def lint_bib(
    bib_path: str,
    keys: list[str] | None = None,
    verify: bool = False,
) -> dict[str, Any]:
    """Advise on bibliography metadata, independently of citation readiness.

    Args:
        bib_path: UTF-8 bibliography file, at most 4 MiB and 2000 entries.
        keys: Optional entry keys to inspect; omitted means every entry.
        verify: Compare own-ID registry metadata using normal resolver caches.
            Counts describe identifiers, not HTTP requests. Default is offline.

    Returns:
        Advisory issues with exact entry byte/character spans. ``ok`` and
        ``input_complete`` concern input processing, never existence, official
        provenance, support, or submission readiness. No file is modified.
    """
    report: dict[str, Any] = dict(
        ok=False,
        input_complete=False,
        advisory_only=True,
        submission_ready=False,
        advisory_clean=False,
        comparison_complete=False if verify else None,
        input_sha256=None,
        entries=[],
        issues=[],
        comparison=dict(
            requested=verify,
            identifiers_requested=[],
            identifier_count=0,
            compared_entries=0,
            outcomes=[],
        ),
    )
    if (
        not isinstance(bib_path, str)
        or not bib_path
        or type(verify) is not bool
        or keys is not None
        and (
            not isinstance(keys, list)
            or any(not isinstance(key, str) or not key.strip() for key in keys)
        )
    ):
        return dict(report, error="Invalid path, keys, or verify argument.")
    path = os.path.abspath(os.path.expanduser(bib_path))
    try:
        if not os.path.isfile(path):
            raise ValueError("Bibliography must be a regular file.")
        with open(path, "rb") as stream:
            raw = stream.read(_LINT_MAX_BYTES + 1)
        if len(raw) > _LINT_MAX_BYTES:
            raise ValueError("Bibliography exceeds the 4 MiB input limit.")
        source = raw.decode("utf-8")
        report["input_sha256"] = hashlib.sha256(raw).hexdigest()
        parsed = _parse_bib(source)
        if not parsed["complete"]:
            return dict(
                report,
                error="Bibliography parsing is incomplete.",
                parse_errors=parsed["errors"],
            )
        entries = parsed["entries"]
        if len(entries) > _LINT_MAX_ENTRIES:
            raise ValueError("Bibliography exceeds the 2000 entry limit.")
        missing = sorted(set(keys or []) - set(parsed["keys"]))
        if missing:
            return dict(
                report,
                error="Requested bibliography keys are absent.",
                missing_keys=missing,
            )
        selected = set(keys) if keys is not None else None
        locations = {}
        previous = byte_position = 0
        line = 1
        for entry in entries:
            start, end = entry["start"], entry["end"]
            gap = source[previous:start]
            byte_position += len(gap.encode("utf-8"))
            line += gap.count("\n")
            size = len(entry["raw"].encode("utf-8"))
            locations[entry["key"]] = dict(
                scope="entry",
                file=path,
                line=line,
                end_line=line + entry["raw"].count("\n"),
                start=start,
                end=end,
                byte_start=byte_position,
                byte_end=byte_position + size,
            )
            previous, byte_position = end, byte_position + size
            line += entry["raw"].count("\n")
        entries = [
            entry
            for entry in entries
            if selected is None or entry["key"] in selected
        ]
        issues = [
            dict(issue, key=entry["key"])
            for entry in entries
            for issue in _lint_local_issues(entry)
        ]
        if verify:
            comparison, comparison_issues = _lint_compare_entries(entries)
            report["comparison"] = comparison
            report["comparison_complete"] = (
                comparison["compared_entries"]
                == comparison["comparable_entries"]
            )
            issues.extend(comparison_issues)
        else:
            report["comparison"]["outcomes"] = [
                dict(key=entry["key"], status="not-requested", identifiers=[])
                for entry in entries
            ]
        with open(path, "rb") as stream:
            current = stream.read(_LINT_MAX_BYTES + 1)
        if current != raw:
            raise ValueError("Bibliography snapshot is stale; rerun lint.")
    except (OSError, ValueError, UnicodeError) as exc:
        return dict(
            report,
            error=str(exc),
            comparison_complete=False if verify else None,
        )
    report["issues"] = [
        dict(issue, severity="advisory", location=locations[issue["key"]])
        for issue in issues
    ]
    report["entries"] = [
        dict(
            key=entry["key"],
            type=entry["type"],
            issue_count=sum(issue["key"] == entry["key"] for issue in issues),
        )
        for entry in entries
    ]
    report.update(
        ok=True,
        input_complete=True,
        advisory_clean=not issues
        and (not verify or report["comparison_complete"]),
    )
    return report


def verify_bib(bib_path: str, keys: list[str] | None = None, tex_path: str | None = None,
               search_unresolved: bool = True) -> dict:
    """Existence check of every entry (or `keys`): resolve the entry's own
    DOI / arXiv id / bibcode — or, for software, the GitHub repository in its
    url / howpublished / repository field — and compare title, first author
    and year with the registry record (a repository entry's cited version
    must exist as a tag, branch or commit). Entries without any identifier
    are searched by title, author and year. Statuses: VERIFIED, FOUND (by search — replace with the
    official entry), PROBABLE (look), MISMATCH (real id, different paper),
    NOT_FOUND, UNRESOLVED (no identifier, or the lookup failed). ok=true only
    when every entry is VERIFIED or FOUND.
    """
    bib_path = os.path.abspath(bib_path)
    if not os.path.exists(bib_path):
        return {"error": f"{bib_path} not found"}
    with open(bib_path, errors="replace") as fh:
        parsed = _parse_bib(fh.read())
    if not parsed["complete"]:
        return {"ok": False, "complete": False, "error": "; ".join(parsed["errors"]),
                "entries": [], "n": 0, "parse_errors": parsed["errors"]}
    wanted = set(keys) if keys else None
    entries = [e for e in parsed["entries"] if wanted is None or e["key"] in wanted]
    missing_keys = sorted(wanted - set(parsed["keys"])) if wanted else []
    plan = []
    for e in entries:
        ids = _entry_ids(e)
        order = [(k, ids[k]) for k in ("doi", "arxiv") if ids.get(k)]
        if ids.get("bibcode") and _ads_token():
            order.append(("bibcode", ids["bibcode"]))
        prov_id = (e["provenance"] or {}).get("id", "")
        if prov_id.startswith("github:") and _classify(prov_id)[0] == "github":
            ids["github"] = _classify(prov_id)[1]      # bib_add filed it as the repository (e.g. its DataCite export)
            order.insert(0, ("github", ids["github"]))
        elif ids.get("github"):
            order.append(("github", ids["github"]))
        plan.append((e, order))
    all_ids = list(dict.fromkeys(f"{k}:{v}" for _, order in plan for k, v in order))
    try:
        resolved = dict(zip(all_ids, _resolve_many(all_ids))) if all_ids else {}
    except RuntimeError as exc:
        return {"error": f"registry lookup failed ({exc})"}
    out, to_search = [], []
    for e, order in plan:
        result, bad = None, []
        for k, v in order:
            r = resolved.get(f"{k}:{v}")
            if r and r.get("resolved"):
                version = _entry_arxiv_version(e)
                if version and k != "github":
                    result = _compare_arxiv_version(e, r, version)
                else:
                    result = _compare_repo(e, r) if k == "github" else _compare(e, r, f"{k}:{v}")
                break
            bad.append(f"{k}:{v} — {(r or {}).get('reason', 'no result')}")
        if result and result["status"] == "MISMATCH" and result["via"].startswith("github:") and search_unresolved:
            found = _search_entry(e)
            if found["status"] in ("FOUND", "PROBABLE") and e["type"] not in _SOFTWARE_TYPES:
                # an article whose url is its code: the paper is what is cited
                found["notes"].insert(0, f"its GitHub URL points at {result['ids']['github']}, which is not this work")
                result = found
            elif found["status"] in ("FOUND", "PROBABLE"):
                # a software entry with the wrong repository is the real-DOI-wrong-title case: still a failure
                result["notes"].append(f"a registry record with this title exists ({found['id']}) — fix the URL, "
                                       f"or bib_add(items=[{{'identifier': '{found['id']}', 'key': '{e['key']}'}}], replace=true)")
        if result:
            result["notes"] += [f"stale identifier in entry: {b}" for b in bad]
            out.append(result)
        elif order:
            failed = any((resolved.get(f"{k}:{v}") or {}).get("lookup_error") for k, v in order)
            out.append({"key": e["key"], "status": "UNRESOLVED" if failed else "NOT_FOUND", "via": None,
                        "notes": bad + (["the lookup itself failed — retry before calling this a fabrication"]
                                        if failed else []), "provenance": e["provenance"]})
        else:
            to_search.append(e)
    if to_search and search_unresolved:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
            out += list(_context_map(ex, _search_entry, to_search))
    else:
        out += [{"key": e["key"], "status": "UNRESOLVED", "via": None, "provenance": e["provenance"],
                 "notes": ["no identifier; search skipped"]} for e in to_search]
    pos = {e["key"]: i for i, e in enumerate(entries)}
    out.sort(key=lambda r: pos.get(r["key"], 10 ** 9))
    counts = Counter(r["status"] for r in out)
    report = {"ok": all(r["status"] in _OK_STATUS for r in out) and not missing_keys,
              "bib": bib_path, "n": len(out), "counts": dict(counts), "missing_keys": missing_keys,
              "ads": bool(_ads_token()), "checked": _now_iso(), "entries": out}
    _write_project(os.path.dirname(bib_path), "verify.json", report)
    return report


# ---------------------------------------------------------------------------
# Manuscript inputs: explicit markers, review mappings and PDF page snapshots
# ---------------------------------------------------------------------------

_INPUT_POLICY = "manuscript-input-v1"
_INPUT_MAX_BYTES = 20 * 1024 * 1024
_INPUT_MAX_PAGES = 500
_INPUT_MAX_TEXT = 2 * 1024 * 1024
_INPUT_PDF_TIMEOUT = 30.0
_INPUT_KEY = re.compile(r"[\w][\w:./+\-]*", re.UNICODE)


@dataclasses.dataclass
class InputCitation:
    """Explicit review mapping into an exact source-text snapshot."""

    __pydantic_config__ = {"extra": "forbid"}
    start: int = dataclasses.field(metadata={"strict": True})
    end: int = dataclasses.field(metadata={"strict": True})
    key: str
    marker: str
    page: int | None = dataclasses.field(
        default=None, metadata={"strict": True}
    )


def _input_format(path: str) -> str:
    """Select only supported manuscript formats from their extensions."""
    extension = os.path.splitext(path)[1].lower()
    formats = {
        ".tex": "latex",
        ".ltx": "latex",
        ".latex": "latex",
        ".md": "markdown",
        ".markdown": "markdown",
        ".txt": "text",
        ".pdf": "pdf",
        "": "latex",
    }
    if extension not in formats:
        raise ValueError("unsupported manuscript format")
    return formats[extension]


def _input_manifest_path(path: str) -> str:
    """Keep review mappings separate for each main manuscript."""
    identifier = hashlib.sha256(os.path.abspath(path).encode()).hexdigest()
    return os.path.join(
        os.path.dirname(os.path.abspath(path)),
        PROJECT_DIR,
        "input-" + identifier + ".json",
    )


def _input_pdf_backend() -> dict[str, Any]:
    """Identify the extractor independently of manuscript contents."""
    try:
        version = importlib.metadata.version("pypdf")
    except importlib.metadata.PackageNotFoundError:
        version = None
    return {
        "name": "pypdf",
        "version": version,
        "policy": _INPUT_POLICY,
        "options": {"strict": True, "mode": "plain"},
    }


def _input_pdf_worker() -> None:
    """Extract bounded page text in a separate, time-limited process."""
    pypdf = importlib.import_module("pypdf")

    logging.getLogger("pypdf").setLevel(logging.CRITICAL)
    raw = sys.stdin.buffer.read(_INPUT_MAX_BYTES + 1)
    if len(raw) > _INPUT_MAX_BYTES:
        raise ValueError("PDF exceeds the 20 MiB input limit")
    reader = pypdf.PdfReader(io.BytesIO(raw), strict=True)
    if reader.is_encrypted:
        raise ValueError("encrypted PDF cannot establish extraction scope")
    count = len(reader.pages)
    if not 0 < count <= _INPUT_MAX_PAGES:
        raise ValueError("PDF must have between 1 and 500 pages")
    pages, size = [], 0
    for number, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ""
        size += len(text.encode("utf-8"))
        if size > _INPUT_MAX_TEXT:
            raise ValueError("PDF exceeds the 2 MiB extracted-text limit")
        pages.append({"page": number, "text": text})
    print(
        json.dumps(
            {"pages": pages, "extractor": _input_pdf_backend()},
            ensure_ascii=False,
        )
    )


def _input_pdf_extract(raw: bytes) -> dict[str, Any]:
    """Isolate PDF decoding with a deadline; never silently fall back to OCR."""
    budget = _request_budget.get()
    timeout = (
        min(_INPUT_PDF_TIMEOUT, budget.remaining())
        if budget
        else _INPUT_PDF_TIMEOUT
    )
    try:
        completed = subprocess.run(
            [sys.executable, os.path.abspath(__file__), "_extract-pdf"],
            input=raw,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise ValueError(
            "PDF extraction timed out; scope is unknown"
        ) from error
    if budget:
        budget.remaining()
    if completed.returncode:
        raise ValueError(
            "PDF extraction failed (missing pypdf, encrypted, "
            "malformed or oversized PDF); scope is unknown"
        )
    if len(completed.stdout) > _INPUT_MAX_TEXT * 6 + 100000:
        raise ValueError("PDF extractor output exceeds its bound")
    try:
        result = json.loads(completed.stdout)
    except (ValueError, UnicodeError) as error:
        raise ValueError("invalid PDF extractor output") from error
    return result


def _input_snapshot(path: str) -> dict[str, Any]:
    """Read one original byte snapshot and its format-specific text views."""
    kind = _input_format(path)
    if kind == "latex":
        raise ValueError("explicit mappings apply to Markdown, text or PDF")
    if not os.path.isfile(path):
        raise ValueError("manuscript must be a regular file")
    with open(path, "rb") as source:
        raw = source.read(_INPUT_MAX_BYTES + 1)
    if len(raw) > _INPUT_MAX_BYTES:
        raise ValueError("manuscript exceeds the 20 MiB input limit")
    if kind == "pdf":
        data = _input_pdf_extract(raw)
        if (
            not isinstance(data, dict)
            or set(data) != {"pages", "extractor"}
            or not isinstance(data["pages"], list)
            or not 0 < len(data["pages"]) <= _INPUT_MAX_PAGES
            or data["extractor"] != _input_pdf_backend()
        ):
            raise ValueError("malformed or inconsistent PDF extraction")
        pages = data["pages"]
        for number, page in enumerate(pages, 1):
            if (
                not isinstance(page, dict)
                or set(page) != {"page", "text"}
                or type(page["page"]) is not int
                or page["page"] != number
                or not isinstance(page["text"], str)
            ):
                raise ValueError("malformed PDF page extraction")
        if sum(len(page["text"].encode()) for page in pages) > _INPUT_MAX_TEXT:
            raise ValueError("PDF exceeds the extracted-text limit")
        if not any(page["text"].strip() for page in pages):
            raise ValueError(
                "PDF has no extractable text; scan/OCR scope is unknown"
            )
        extractor = data["extractor"]
    else:
        pages = [{"page": None, "text": raw.decode("utf-8")}]
        if not pages[0]["text"].strip():
            raise ValueError("empty manuscript; citation scope is unknown")
        extractor = {"name": "utf-8", "policy": _INPUT_POLICY}
    fingerprint = {
        "format": kind,
        "extractor": extractor,
        "pages": [
            hashlib.sha256(page["text"].encode()).hexdigest() for page in pages
        ],
    }
    return {
        "input_format": kind,
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "pages": pages,
        "fingerprint": fingerprint,
    }


def _input_blank(value: str) -> str:
    """Mask excluded syntax without changing character offsets or newlines."""
    return "".join("\n" if character == "\n" else " " for character in value)


def _input_mask(text: str, kind: str, *, math: bool = True) -> str:
    """Exclude Markdown code/comments/link syntax and URLs from markers."""
    if kind == "markdown":
        lines = text.splitlines(keepends=True)
        fence, width = None, 0
        masked = []
        for line in lines:
            match = re.match(r" {0,3}(`{3,}|~{3,})", line)
            if fence:
                masked.append(_input_blank(line))
                if (
                    match
                    and match[1][0] == fence
                    and len(match[1]) >= width
                    and not line[match.end() :].strip()
                ):
                    fence = None
            elif match:
                fence, width = match[1][0], len(match[1])
                masked.append(_input_blank(line))
            elif line.startswith("    ") or line.startswith("\t"):
                masked.append(_input_blank(line))
            else:
                masked.append(line)
        text = "".join(masked)
        text = re.sub(
            r"<!--.*?(?:-->|\Z)",
            lambda match: _input_blank(match[0]),
            text,
            flags=re.S,
        )
        if math:
            text = re.sub(
                r"(?<!\\)(`+)(?!`)(.*?)\1(?!`)",
                lambda match: _input_blank(match[0]),
                text,
                flags=re.S,
            )
        text = re.sub(
            r"\[[^\]\n]*\]\([^\n)]*\)",
            lambda match: (
                match[0][: match[0].index("]") + 1]
                + _input_blank(match[0][match[0].index("]") + 1 :])
            ),
            text,
        )
        # Front matter is metadata, not manuscript prose. The caller passes
        # the authoritative bibliography explicitly to audit/job tools.
        text = re.sub(
            r"\A---\s*\r?\n.*?\r?\n(?:---|\.\.\.)[^\n]*(?:\n|\Z)",
            lambda match: _input_blank(match[0]),
            text,
            flags=re.S,
        )
    text = re.sub(
        r"(?:https?://|mailto:)[^\s<>]+",
        lambda match: _input_blank(match[0]),
        text,
    )
    return (
        _TEX_MATH.sub(lambda match: _input_blank(match[0]), text)
        if math
        else text
    )


def _input_references(text: str, kind: str) -> tuple[str, list[dict[str, Any]]]:
    """Retain printed references as raw, unverified manuscript records."""
    records = []
    visible = _input_mask(text, kind, math=False)
    native_keys = {
        key
        for marker in _input_native_markers(_input_mask(text, kind))[0]
        for key in marker["keys"]
    }
    heading = re.search(
        r"(?im)^[ \t]*(?:#{1,6}[ \t]+)?"
        r"(?:References|Bibliography)[ \t]*:?[ \t]*\r?$",
        visible,
    )
    spans: list[tuple[int, int, str | None]] = []
    if kind == "markdown":
        metadata = re.match(
            r"\A---[^\n]*\r?\n(.*?)\r?\n(?:---|\.\.\.)[^\n]*(?:\n|\Z)",
            text,
            re.S,
        )
        if metadata and re.search(
            r"(?im)^[ \t]*[\"']?references[\"']?[ \t]*:", metadata[1]
        ):
            spans.append((metadata.start(), metadata.end(), None))
    if heading:
        spans.append((heading.start(), len(text), None))
    for match in re.finditer(
        r"(?m)^[ \t]{0,3}\[(@?[\w][\w:./+\-]*)\]:[^\n]*(?:\n(?:[ \t]+[^\n]*))*",
        visible,
    ):
        # Ordinary Markdown link definitions contain only a URL/title;
        # citation-looking definitions remain explicit unverified metadata.
        body = text[match.start() : match.end()].split("]:", 1)[1].strip()
        if match[1].lstrip("@") not in native_keys and re.fullmatch(
            r"<?https?://[^\s>]+>?(?:\s+[\"'].+[\"'])?", body
        ):
            continue
        if not any(start <= match.start() < end for start, end, _ in spans):
            spans.append((match.start(), match.end(), match[1].lstrip("@")))
    chars = list(text)
    for start, end, key in spans:
        records.append(
            {
                "key": key,
                "raw": text[start:end],
                "start": start,
                "end": end,
                "kind": "printed-reference-block",
                "line": text.count("\n", 0, start) + 1,
            }
        )
        chars[start:end] = _input_blank(text[start:end])
    return "".join(chars), records


def _input_native_markers(
    text: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Parse explicit Pandoc-style keys, retaining uncertain marker syntax."""
    markers, diagnostics, occupied = [], [], []
    for match in re.finditer(r"(?<!\\)\[([^\[\]\n]*)\]", text):
        body = match[1]
        keys = re.findall(r"(?<![\w\\])@([\w][\w:./+\-]*)", body)
        if "@" in body and (not keys or body.rstrip().endswith(";")):
            diagnostics.append(
                {
                    "code": "malformed-citation-marker",
                    "message": "Malformed explicit citation marker",
                    "start": match.start(),
                    "end": match.end(),
                }
            )
            occupied.append((match.start(), match.end()))
        elif keys:
            if "@" in re.sub(r"(?<![\w\\])@[\w][\w:./+\-]*", "", body):
                diagnostics.append(
                    {
                        "code": "malformed-citation-marker",
                        "message": "Ambiguous explicit citation marker",
                        "start": match.start(),
                        "end": match.end(),
                    }
                )
            else:
                markers.append(
                    {"start": match.start(), "end": match.end(), "keys": keys}
                )
            occupied.append((match.start(), match.end()))
        elif re.fullmatch(r"\s*\d+(?:\s*[,;\-–]\s*\d+)*\s*", body):
            diagnostics.append(
                {
                    "code": "unsupported-citation-syntax",
                    "message": (
                        "Numeric marker needs an explicit review mapping"
                    ),
                    "start": match.start(),
                    "end": match.end(),
                }
            )
    for match in re.finditer(
        r"\[\s*\d+(?:[ ,;–-]\d+)*(?=[^\]\n]*(?:\n|\Z))", text
    ):
        if (
            "]"
            not in text[
                match.end() : text.find("\n", match.end())
                if "\n" in text[match.end() :]
                else len(text)
            ]
        ):
            diagnostics.append(
                {
                    "code": "malformed-citation-marker",
                    "message": "Unclosed numeric citation marker",
                    "start": match.start(),
                    "end": match.end(),
                }
            )
    remainder = list(text)
    for start, end in occupied:
        remainder[start:end] = _input_blank(text[start:end])
    remaining = "".join(remainder)
    for match in re.finditer(r"(?<![\w\\@])@([\w][\w:./+\-]*)", remaining):
        # Unclosed bracket syntax is never silently reinterpreted as a
        # complete narrative citation.
        before = remaining[
            max(0, remaining.rfind("\n", 0, match.start())) : match.start()
        ]
        if before.count("[") > before.count("]"):
            diagnostics.append(
                {
                    "code": "malformed-citation-marker",
                    "message": "Unclosed citation cluster",
                    "start": match.start(),
                    "end": match.end(),
                }
            )
        else:
            key = match[1].rstrip(".:/")
            markers.append(
                {
                    "start": match.start(),
                    "end": match.start() + 1 + len(key),
                    "keys": [key],
                }
            )
    for match in re.finditer(
        r"[\[(][^()\[\]\n]*(?:18|19|20)\d{2}[a-z]?"
        r"[^()\[\]\n]*(?:[\])]|(?=\n|\Z))",
        remaining,
    ):
        diagnostics.append(
            {
                "code": "unsupported-citation-syntax",
                "message": (
                    "Author-year marker needs an explicit review mapping"
                ),
                "start": match.start(),
                "end": match.end(),
            }
        )
    return sorted(markers, key=lambda item: item["start"]), diagnostics


def _input_validate_mappings(
    snapshot: dict[str, Any], values: Any
) -> list[dict[str, Any]]:
    """Validate exact, nonoverlapping review bindings."""
    if not isinstance(values, list) or len(values) > 2000:
        raise ValueError("citations must be a list of at most 2000 mappings")
    pages = {page["page"]: page["text"] for page in snapshot["pages"]}
    result: list[dict[str, Any]] = []
    visible_pages = {
        page: _input_mask(
            _input_references(text, snapshot["input_format"])[0],
            snapshot["input_format"],
        )
        for page, text in pages.items()
    }
    native_pages = {
        page: _input_native_markers(text)[0]
        for page, text in visible_pages.items()
    }
    for item in values:
        value = (
            dataclasses.asdict(item)
            if isinstance(item, InputCitation)
            else item
        )
        if (
            not isinstance(value, dict)
            or not {"start", "end", "key", "marker"} <= set(value)
            or set(value) - {"start", "end", "key", "marker", "page"}
        ):
            raise ValueError(
                "mapping requires start, end, key and exact marker"
            )
        value = dict(value)
        value.setdefault("page", None)
        start, end, page = value["start"], value["end"], value["page"]
        if (
            type(start) is not int
            or type(end) is not int
            or (page is not None and type(page) is not int)
            or page not in pages
            or not 0 <= start < end <= len(pages[page])
            or not isinstance(value["marker"], str)
            or pages[page][start:end] != value["marker"]
            or not isinstance(value["key"], str)
            or _INPUT_KEY.fullmatch(value["key"]) is None
        ):
            raise ValueError(
                "mapping does not match exact current page/text offsets"
            )
        visible = visible_pages[page]
        if visible[start:end] != pages[page][start:end]:
            raise ValueError(
                "mapping overlaps excluded code, math, comments or URL syntax"
            )
        native = native_pages[page]
        if any(
            start < marker["end"] and end > marker["start"] for marker in native
        ):
            raise ValueError(
                "explicit native citations do not need review mappings"
            )
        for previous in result:
            if previous["page"] != page:
                continue
            if start < previous["end"] and end > previous["start"]:
                if (start, end) != (
                    previous["start"],
                    previous["end"],
                ) or value["key"] == previous["key"]:
                    raise ValueError(
                        "overlapping or duplicate citation mappings"
                    )
        result.append(value)
    return sorted(
        result,
        key=lambda value: (
            value["page"] or 0,
            value["start"],
            value["end"],
            value["key"],
        ),
    )


def _input_manifest_safe(path: str, manuscript: str) -> None:
    """Protect original inputs and ledger before creating a mapping lock."""
    if os.path.islink(os.path.dirname(path)):
        raise ValueError("input manifest directory is a symlink")
    inputs = [
        manuscript,
        os.path.join(os.path.dirname(manuscript), PROJECT_DIR, "ledger.json"),
    ]
    for output in (path, path + ".lock"):
        if (
            os.path.islink(output)
            or os.path.exists(output)
            and os.stat(output).st_nlink > 1
        ):
            raise ValueError("input manifest or lock is a symlink or hardlink")
        for source in inputs:
            if (
                os.path.realpath(output) == os.path.realpath(source)
                or os.path.exists(output)
                and os.path.exists(source)
                and os.path.samefile(output, source)
            ):
                raise ValueError("input manifest or lock aliases an input")


def register_input(
    tex_path: str, citations: list[InputCitation], reason: str
) -> dict[str, Any]:
    """Bind explicit review mappings to unchanged Markdown/text/PDF snapshots.

    Args:
        tex_path: Manuscript path; the legacy parameter name is retained.
        citations: Exact offset/key/marker mappings, with a page for PDFs.
        reason: Substantive explanation of the caller's interpretation.

    Returns:
        The saved manifest location. Mappings never establish identity or
        completeness and always remain review-only when nonempty.
    """
    try:
        if (
            not isinstance(tex_path, str)
            or not tex_path
            or not isinstance(reason, str)
            or len(reason.strip()) < 15
        ):
            raise ValueError(
                "give a manuscript path and substantive mapping reason"
            )
        path = os.path.abspath(tex_path)
        snapshot = _input_snapshot(path)
        mappings = _input_validate_mappings(snapshot, citations)
        manifest = _input_manifest_path(path)
        _input_manifest_safe(manifest, path)
        with _file_lock(manifest):
            if _audit_file_digest(path) != snapshot["raw_sha256"]:
                raise ValueError(
                    "manuscript changed while mapping; extract again"
                )
            _input_manifest_safe(manifest, path)
            value = {
                "schema_version": 1,
                "path": path,
                "raw_sha256": snapshot["raw_sha256"],
                "fingerprint": snapshot["fingerprint"],
                "citations": mappings,
                "reason": reason.strip(),
                "policy": _INPUT_POLICY,
            }
            serialized = json.dumps(value, ensure_ascii=False, indent=2)
            if len(serialized.encode("utf-8")) > 1024 * 1024:
                raise ValueError("input mapping manifest exceeds 1 MiB")
            _atomic_write(manifest, serialized)
        return {
            "ok": True,
            "registered": True,
            "manifest_path": manifest,
            "n_mappings": len(mappings),
            "review_only": True,
        }
    except (OSError, ValueError, RuntimeError) as error:
        return {"ok": False, "registered": False, "error": str(error)}


def _input_mappings(
    path: str, snapshot: dict[str, Any]
) -> tuple[list[dict[str, Any]], str | None]:
    """Read mappings bound to the exact bytes and extraction policy."""
    manifest = _input_manifest_path(path)
    _input_manifest_safe(manifest, path)
    if not os.path.exists(manifest):
        return [], None
    with open(manifest, "rb") as source:
        raw = source.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError("input manifest exceeds its size limit")
    value = json.loads(raw)
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "schema_version",
            "path",
            "raw_sha256",
            "fingerprint",
            "citations",
            "reason",
            "policy",
        }
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or value["path"] != path
        or value["raw_sha256"] != snapshot["raw_sha256"]
        or value["fingerprint"] != snapshot["fingerprint"]
        or value["policy"] != _INPUT_POLICY
        or not isinstance(value["reason"], str)
        or len(value["reason"].strip()) < 15
    ):
        raise ValueError(
            "input mapping is stale or malformed; register_input again"
        )
    return _input_validate_mappings(
        snapshot, value["citations"]
    ), hashlib.sha256(raw).hexdigest()

# ---------------------------------------------------------------------------
# LaTeX — every citation instance with the sentence that makes the claim
# ---------------------------------------------------------------------------

_CITE_CMD = re.compile(
    r"\\(?P<cmd>[Cc]ite[a-zA-Z]*|[Pp]arencites?|[Tt]extcites?|[Aa]utocites?|"
    r"[Ff]oot(?:full)?cites?(?:text)?|[Ss]martcites?|[Ss]upercites?|[Ff]ullcite|nocite)\*?(?![a-zA-Z])")
_CITE_EXCLUDE = {"citetext", "citestyle", "citeindextype", "citename", "citeauthoryear", "citenumfont"}
_ABBREV = ("e.g", "i.e", "et al", "cf", "vs", "viz", "ca", "approx", "resp", "Fig", "Figs", "Eq", "Eqs",
           "Sec", "Secs", "Sect", "Ref", "Refs", "Tab", "Tabs", "Dr", "Prof", "Mr", "Ms", "Mrs", "No", "Nos",
           "Vol", "vol", "pp", "p", "Phys", "Rev", "Astrophys", "Astron", "Ann", "Proc", "J", "Ser", "Lett",
           "Suppl", "Chap", "Ch", "St", "Univ", "Inc", "Ltd", "approx", "min", "max")
_CITE_TOKEN = re.compile(r"\u27e8cite#(\d+)\u27e9")
_TEX_MATH = re.compile(
    r"\\begin\{(?P<math_env>(?:equation|align|gather|multline|eqnarray|"
    r"displaymath|flalign|alignat)\*?)\}.*?\\end\{(?P=math_env)\}"
    r"|\\\[.*?\\\]|\$\$.*?\$\$|\\\(.*?\\\)"
    r"|(?<!\\)\$(?!\$)(?:\\.|[^$\\])*\$",
    re.S,
)


def _strip_tex_comments(text: str) -> str:
    """Blank comments while preserving source character offsets and lines."""
    def blank(match: re.Match) -> str:
        return "".join("\n" if char == "\n" else " " for char in match[0])

    text = re.sub(r"(?<!\\)%[^\n]*", blank, text)
    text = re.sub(
        r"\\begin\{comment\}.*?\\end\{comment\}", blank, text, flags=re.S
    )
    return re.sub(r"\\iffalse.*?\\fi", blank, text, flags=re.S)


def _braced(text: str, i: int) -> tuple:
    """text[i] == '{' → (inner, index after the matching '}')."""
    j = _find_close(text, i)
    return (text[i + 1:j], j + 1) if j > 0 else ("", i + 1)


def _tex_file_arguments(text: str, commands: tuple[str, ...]) -> list[str]:
    """Read literal filenames, failing on malformed or dynamic declarations."""
    arguments = []
    pattern = r"\\(" + "|".join(re.escape(cmd) for cmd in commands) + r")\b"
    for match in re.finditer(pattern, text):
        index = match.end()
        while index < len(text) and text[index].isspace():
            index += 1
        if index < len(text) and text[index] == "[":
            closing = text.find("]", index + 1)
            if closing < 0:
                raise ValueError(f"unterminated options for \\{match[1]}")
            index = closing + 1
            while index < len(text) and text[index].isspace():
                index += 1
        if index < len(text) and text[index] == "{":
            closing = _find_close(text, index)
            if closing < 0:
                raise ValueError(f"unterminated filename for \\{match[1]}")
            argument = text[index + 1:closing].strip()
        elif match[1] == "input":
            filename = re.match(r"[^\\{}\s]+", text[index:])
            argument = filename[0] if filename else ""
        else:
            argument = ""
        if not argument or re.search(r"[\\{}#$]", argument):
            raise ValueError(
                f"missing, malformed or dynamic filename for \\{match[1]}"
            )
        arguments.append(argument)
    return arguments


def _gather_tex(main_path: str, seen: set | None = None,
                root: str | None = None,
                snapshots: dict[str, str] | None = None) -> list:
    """[(path, comment-stripped text)] for the main file and every
    \\input / \\include / \\subfile it pulls in."""
    seen = seen if seen is not None else set()
    main_path = os.path.abspath(main_path)
    root = root if root is not None else os.path.dirname(main_path)
    if main_path in seen:
        return []
    if not os.path.isfile(main_path):
        raise ValueError(f"missing included TeX file: {main_path}")
    seen.add(main_path)
    with open(main_path, encoding="utf-8", newline="") as fh:
        original = fh.read()
    if snapshots is not None:
        snapshots[main_path] = original
    text = _strip_tex_comments(original)
    files = [(main_path, text)]
    for argument in _tex_file_arguments(text, ("input", "include", "subfile")):
        cand = os.path.join(root, argument)
        if not os.path.splitext(cand)[1]:
            cand += ".tex"
        files += _gather_tex(cand, seen, root, snapshots)
    return files


def _cite_instances(text: str):
    """Yield (cmd, keys, start, end) for each citation command; \\cites-style
    commands carry several ([pre][post]{keys}) groups."""
    n = len(text)
    for m in _CITE_CMD.finditer(text):
        cmd = m.group("cmd")
        if cmd.lower() in _CITE_EXCLUDE:
            continue
        i, keys, groups = m.end(), [], 0
        while True:
            j = i
            while j < n and text[j].isspace():
                j += 1
            while j < n and text[j] == "[":
                k = text.find("]", j)
                if k < 0:
                    break
                j = k + 1
                while j < n and text[j].isspace():
                    j += 1
            if j < n and text[j] == "{":
                inner, i = _braced(text, j)
                keys += [k.strip() for k in inner.split(",") if k.strip()]
                groups += 1
                if cmd.lower().endswith("cites"):
                    continue
            break
        if groups:
            yield cmd, keys, m.start(), i


def _replace_cmd_arg(text: str, cmd: str, fn) -> str:
    """\\cmd[opt]{arg} → fn(arg), brace-aware, for every occurrence."""
    pat = re.compile(r"\\" + cmd + r"\*?\s*(?:\[[^\]]*\])?\s*\{")
    out, i = [], 0
    while True:
        m = pat.search(text, i)
        if not m:
            out.append(text[i:])
            return "".join(out)
        inner, end = _braced(text, m.end() - 1)
        out.append(text[i:m.start()])
        out.append(fn(inner))
        i = end


def _clean_tex(t: str) -> str:
    """LaTeX → readable prose, preserving citations and mathematical content."""
    math = []
    t = _TEX_MATH.sub(
        lambda match: (
            math.append(re.sub(r"\s+", " ", match[0])),
            f"\u27e8m{len(math) - 1}\u27e9"
        )[1],
        t,
    )
    t = re.sub(r"\\(?:includegraphics|label|vspace|hspace|bibliographystyle|bibliography|addbibresource|"
               r"graphicspath|usepackage|documentclass|setlength|newcommand|renewcommand|def|input|include|"
               r"subfile|affiliation|affil|author|email|correspondingauthor|orcid|keywords|received|revised|accepted|"
               r"submitjournal|shorttitle|shortauthors|thanks|date)\*?(?:\[[^\]]*\])?(?:\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})?",
               " ", t)
    t = _replace_cmd_arg(t, "footnote", lambda a: f" (footnote: {a.strip()}) ")
    t = _replace_cmd_arg(t, "href", lambda a: "")          # url part
    for cmd in ("section", "subsection", "subsubsection", "paragraph", "chapter", "title"):
        t = _replace_cmd_arg(t, cmd, lambda a: f"\n\n{a.strip()}.\n\n")
    for cmd in ("emph", "textbf", "textit", "texttt", "textsc", "textrm", "textsf", "text", "mbox", "underline",
                "url", "caption", "textsuperscript", "textsubscript", "textcolor", "abstract", "quote"):
        t = _replace_cmd_arg(t, cmd, lambda a: a)
    t = re.sub(r"\\(?:ref|eqref|cref|Cref|autoref|pageref|citetext|nameref)\*?\{[^}]*\}", "[ref]", t)
    t = re.sub(r"\\(?:begin|end)\{[^}]*\}(?:\[[^\]]*\])?(?:\{[^{}]*\})*", "\n", t)
    t = re.sub(r"\\item\b", "\n- ", t)
    for a, b in (("\\ldots", "..."), ("\\dots", "..."), ("\\%", "%"), ("\\&", "&"), ("\\_", "_"), ("\\#", "#"),
                 ("\\$", "$"), ("~", " "), ("---", " -- "), ("``", '"'), ("''", '"'), ("\\,", " "), ("\\ ", " ")):
        t = t.replace(a, b)
    t = re.sub(r"\\[a-zA-Z]+\*?(?![a-zA-Z])", " ", t)
    t = re.sub(r"[{}]", "", t)
    t = re.sub(r"\u27e8m(\d+)\u27e9", lambda m: math[int(m.group(1))], t)
    t = re.sub(r"[ \t]+", " ", t)
    return t


def _split_sentences(paragraph: str) -> list:
    prot = paragraph
    for ab in _ABBREV:
        prot = re.sub(r"\b" + re.escape(ab) + r"\.", ab.replace(".", "<DOT>") + "<DOT>", prot)
    prot = re.sub(r"\b([A-Z])\.", r"\1<DOT>", prot)              # initials
    prot = re.sub(r"(\d)\.(\d)", r"\1<DOT>\2", prot)              # decimals
    prot = _TEX_MATH.sub(
        lambda match: match[0].replace(".", "<DOT>"), prot
    )
    parts = re.split(r"(?<=[.!?])\s+(?=[\"'(\[\u27e8$A-Z0-9\\])", prot)
    return [p.replace("<DOT>", ".").strip() for p in parts if p.strip()]


def _extract_tex_cites(tex_path: str) -> dict:
    """Every citation instance in a LaTeX document (following \\input /
    \\include), each with the sentence making the claim (`claim`, with
    ⟨cite:key⟩ marking where the citation sits), one sentence of context each
    side, file and line. Also reports the cite keys, declared .bib files and
    documentclass. \\nocite instances are flagged nocite=true.
    """
    tex_path = os.path.abspath(tex_path)
    if not os.path.exists(tex_path):
        return {"error": f"{tex_path} not found"}
    source_snapshots = {}
    try:
        files = _gather_tex(tex_path, snapshots=source_snapshots)
    except (OSError, ValueError) as exc:
        return {"ok": False, "complete": False, "error": str(exc)}
    cites, bib_files, docclass = [], [], None
    inline_bibliography = []
    sentences = []
    for path, text in files:
        for env in re.finditer(
            r"\\begin\{thebibliography\}(?:\{[^}]*\})?"
            r"(.*?)\\end\{thebibliography\}", text, re.S
        ):
            items = list(
                re.finditer(r"\\bibitem(?:\[[^\]]*\])?\{([^}]+)\}", env[1])
            )
            parsed_items = {item.start() for item in items}
            if (
                not items
                or any(token.start() not in parsed_items
                       for token in re.finditer(r"\\bibitem\b", env[1]))
                or any(_INPUT_KEY.fullmatch(item[1]) is None for item in items)
            ):
                return {
                    "ok": False,
                    "complete": False,
                    "scope_complete": False,
                    "error": "malformed or unsupported inline "
                             "bibliography item",
                }
            for index, item in enumerate(items):
                start = env.start(1) + item.start()
                end = env.start(1) + (
                    items[index + 1].start()
                    if index + 1 < len(items)
                    else len(env[1])
                )
                raw = source_snapshots[path]
                inline_bibliography.append({
                    "key": item[1], "raw": raw[start:end], "file": path,
                    "line": raw.count("\n", 0, start) + 1,
                    "start": start, "end": end,
                    "kind": "inline-bibliography-entry",
                    "source_byte_start": len(raw[:start].encode("utf-8")),
                    "source_byte_end": len(raw[:end].encode("utf-8")),
                })
        text = re.sub(
            r"\\begin\{thebibliography\}.*?\\end\{thebibliography\}",
            lambda match: _input_blank(match[0]),
            text,
            flags=re.S,
        )
        if re.search(r"\\(?:bibitem|begin\{thebibliography\})", text):
            return {
                "ok": False,
                "complete": False,
                "error": "malformed inline bibliography",
            }
        m = re.search(r"\\documentclass(?:\[[^\]]*\])?\{([^}]+)\}", text)
        if m and not docclass:
            docclass = m.group(1)
        try:
            declarations = _tex_file_arguments(
                text, ("bibliography", "addbibresource")
            )
        except ValueError as exc:
            return {"ok": False, "complete": False, "error": f"{path}: {exc}"}
        for declaration in declarations:
            for b in declaration.split(","):
                b = b.strip()
                if b:
                    p = os.path.join(os.path.dirname(tex_path), b)
                    bib_files.append(p if p.endswith(".bib") else p + ".bib")
        instances = list(_cite_instances(text))
        parsed_starts = {instance[2] for instance in instances}
        for command in _CITE_CMD.finditer(text):
            if (command.group("cmd").lower() not in _CITE_EXCLUDE
                    and command.start() not in parsed_starts):
                return {"ok": False, "complete": False,
                        "error": f"malformed citation in {path}"}
        if any(not item[1] for item in instances):
            return {"ok": False, "complete": False,
                    "error": f"empty or malformed citation in {path}"}
        tokens, out, last = {}, [], 0
        for n, (cmd, keys, s, e) in enumerate(instances):
            out.append(text[last:s])
            out.append(f" \u27e8cite#{n}\u27e9 ")
            last = e
            tokens[n] = {
                "cmd": cmd, "keys": keys, "line": text.count("\n", 0, s) + 1,
                "source_start": s, "source_end": e, "source_index": n,
            }
        out.append(text[last:])
        joined = "".join(out)
        m = re.search(r"\\begin\{document\}", joined)
        document = joined[m.end():] if m else joined
        prose = _clean_tex(document)
        if Counter(_CITE_TOKEN.findall(document)) != Counter(
            _CITE_TOKEN.findall(prose)
        ):
            return {
                "ok": False, "complete": False,
                "error": f"citation lost in unsupported TeX structure in {path}",
            }

        def render(s):
            s = _CITE_TOKEN.sub(lambda mm: "\u27e8cite:" + ",".join(tokens[int(mm.group(1))]["keys"]) + "\u27e9", s)
            return re.sub(r"\u27e9 (?=[,.;:)\]])", "\u27e9", s)

        sents = []
        for para in re.split(r"\n\s*\n", prose):
            sents.extend(_split_sentences(re.sub(r"\s+", " ", para).strip()))
        source_text = source_snapshots[path]
        for si, sent in enumerate(sents):
            matches = list(_CITE_TOKEN.finditer(sent))
            if not matches:
                continue
            claim = render(sent)
            context = " ".join(
                render(value) for value in sents[max(0, si - 1):si + 2]
            )
            anchors = [tokens[int(match[1])] for match in matches]
            location_id = _atomic_digest(
                [tex_path, path, anchors[0]["source_index"]]
            )
            sentence_id = _atomic_digest(
                [tex_path, path, anchors, claim, context]
            )
            sentence = {
                "sentence_id": sentence_id, "location_id": location_id,
                "file": path, "tex_path": tex_path,
                "claim": claim, "context": context,
                "citation_ids": [], "offset_unit": "unicode-codepoint",
            }
            for tm in matches:
                t = tokens[int(tm.group(1))]
                marker = "⟨cite:" + ",".join(t["keys"]) + "⟩"
                marker_start = len(render(sent[:tm.start()]))
                marker_end = marker_start + len(marker)
                for key_index, key in enumerate(t["keys"]):
                    occurrence_id = _atomic_digest(
                        [sentence_id, t["source_index"], key_index, key]
                    )
                    sentence["citation_ids"].append(occurrence_id)
                    cites.append({
                        "key": key, "cmd": t["cmd"], "file": path,
                        "tex_path": tex_path,
                        "line": t["line"], "claim": claim, "context": context,
                        "nocite": t["cmd"].lower() == "nocite" or key == "*",
                        "occurrence_id": occurrence_id,
                        "sentence_id": sentence_id,
                        "location_id": location_id,
                        "marker_start": marker_start, "marker_end": marker_end,
                        "source_start": t["source_start"],
                        "source_end": t["source_end"],
                        "source_byte_start": len(
                            source_text[:t["source_start"]].encode("utf-8")
                        ),
                        "source_byte_end": len(
                            source_text[:t["source_end"]].encode("utf-8")
                        ),
                        "source_command": source_text[
                            t["source_start"]:t["source_end"]
                        ],
                    })
            sentences.append(sentence)
    keys = sorted({c["key"] for c in cites if c["key"] != "*"})
    by_key = {}
    for i, c in enumerate(cites):
        by_key.setdefault(c["key"], []).append(i)
    return {
        "input_format": "latex",
        "scope_complete": len({item["key"] for item in inline_bibliography})
        == len(inline_bibliography),
        "review_only": bool(inline_bibliography),
        "inline_bibliography": inline_bibliography,
        "diagnostics": [
            {
                "code": "inline-bibliography-unverified",
                "message": "Printed inline references require migration "
                           "to verified official exports",
                **item,
            }
            for item in inline_bibliography
        ],
        "complete": True,
        "main": tex_path,
        "files": [p for p, _ in files],
        "documentclass": docclass,
        "bib_files": list(dict.fromkeys(bib_files)),
        "n_instances": len(cites),
        "n_keys": len(keys),
        "keys": keys,
        "cites": cites,
        "by_key": by_key,
        "sentences": sentences,
        "source_digests": {
            path: hashlib.sha256(raw.encode("utf-8")).hexdigest()
            for path, raw in source_snapshots.items()
        },
    }



def _input_render(value: str, tokens: dict[int, dict[str, Any]]) -> str:
    """Render internal occurrence tokens without altering claim semantics."""
    value = _CITE_TOKEN.sub(
        lambda token: "⟨cite:" + ",".join(tokens[int(token[1])]["keys"]) + "⟩",
        value,
    )
    return re.sub(r"⟩ (?=[,.;:)\]])", "⟩", value)

def extract_cites(tex_path: str) -> dict[str, Any]:
    """Extract exact citation occurrences from TeX, Markdown, text, or PDF.

    PDF and explicit review mappings never establish complete strict scope.
    Original text offsets are Unicode codepoints; PDF offsets are page-local.

    Args:
        tex_path: Main manuscript path; legacy parameter name is retained.

    Returns:
        Observed citations, exact source locations, extraction diagnostics
        and explicit completeness and review-only flags.
    """
    try:
        path = os.path.abspath(tex_path)
        if _input_format(path) == "latex":
            return _extract_tex_cites(path)
        snapshot = _input_snapshot(path)
        mappings, manifest_digest = _input_mappings(path, snapshot)
        kind = snapshot["input_format"]
        if any(_CITE_TOKEN.search(page["text"]) for page in snapshot["pages"]):
            raise ValueError("reserved internal citation token in manuscript")
        fingerprint = snapshot["fingerprint"]
        cites, sentences, diagnostics = [], [], []
        views: list[str] = []
        inline_bibliography = []
        for page in snapshot["pages"]:
            raw, number = page["text"], page["page"]
            body, references = _input_references(raw, kind)
            for item in references:
                item.update(
                    file=path,
                    page=number,
                    offset_unit="extracted-page-unicode-codepoint"
                    if number
                    else "unicode-codepoint",
                    source_byte_start=None
                    if number
                    else len(raw[: item["start"]].encode("utf-8")),
                    source_byte_end=None
                    if number
                    else len(raw[: item["end"]].encode("utf-8")),
                )
                inline_bibliography.append(item)
                diagnostics.append(
                    {
                        "code": "printed-reference-unverified",
                        "message": (
                            "Printed references require migration to "
                            "verified official exports"
                        ),
                        **item,
                    }
                )
            visible = _input_mask(body, kind, math=False)
            detection = _input_mask(body, kind)
            markers, issues = _input_native_markers(detection)
            manual = [item for item in mappings if item.get("page") == number]
            for item in manual:
                existing = next(
                    (
                        marker
                        for marker in markers
                        if marker["start"] == item["start"]
                        and marker["end"] == item["end"]
                    ),
                    None,
                )
                if existing:
                    existing["keys"].append(item["key"])
                else:
                    markers.append(
                        {
                            "start": item["start"],
                            "end": item["end"],
                            "keys": [item["key"]],
                        }
                    )
            issues = [
                item
                for item in issues
                if not any(
                    mapping["start"] <= item["start"]
                    and mapping["end"] >= item["end"]
                    for mapping in manual
                )
            ]
            diagnostics.extend(
                {**item, "file": path, "page": number} for item in issues
            )
            markers.sort(key=lambda item: item["start"])
            parts, last, tokens = [], 0, {}
            display_base = sum(value.count("\n") + 1 for value in views)
            if number is not None:
                views.append(f"Page {number}\n" + raw)
            for index, marker in enumerate(markers):
                parts.extend(
                    [visible[last : marker["start"]], f" ⟨cite#{index}⟩ "]
                )
                last = marker["end"]
                tokens[index] = marker
            parts.append(visible[last:])
            prose = "".join(parts)
            sents = []
            for paragraph in re.split(r"\n\s*\n", prose):
                sents.extend(
                    _split_sentences(re.sub(r"\s+", " ", paragraph).strip())
                )

            render = functools.partial(_input_render, tokens=tokens)

            for index, sent in enumerate(sents):
                matches = list(_CITE_TOKEN.finditer(sent))
                if not matches:
                    continue
                claim = render(sent)
                context = " ".join(
                    render(value)
                    for value in sents[max(0, index - 1) : index + 2]
                )
                anchors = [tokens[int(match[1])] for match in matches]
                location = _atomic_digest([path, number, anchors[0]["start"]])
                identity = _atomic_digest(
                    [
                        path,
                        number,
                        anchors,
                        claim,
                        context,
                        snapshot["raw_sha256"],
                        fingerprint,
                        manifest_digest,
                    ]
                )
                sentence = {
                    "sentence_id": identity,
                    "location_id": location,
                    "file": path,
                    "tex_path": path,
                    "claim": claim,
                    "context": context,
                    "citation_ids": [],
                    "offset_unit": "unicode-codepoint",
                    "page": number,
                }
                for match in matches:
                    marker = tokens[int(match[1])]
                    marker_start = len(render(sent[: match.start()]))
                    for key_index, key in enumerate(marker["keys"]):
                        occurrence = _atomic_digest(
                            [identity, int(match[1]), key_index, key]
                        )
                        sentence["citation_ids"].append(occurrence)
                        start, end = marker["start"], marker["end"]
                        page_line = raw.count("\n", 0, start) + 1
                        cites.append(
                            {
                                "key": key,
                                "cmd": "input-cite",
                                "file": path,
                                "tex_path": path,
                                "line": page_line
                                + display_base
                                + (1 if number else 0),
                                "page_line": page_line,
                                "page": number,
                                "claim": claim,
                                "context": context,
                                "nocite": False,
                                "occurrence_id": occurrence,
                                "sentence_id": identity,
                                "location_id": location,
                                "marker_start": marker_start,
                                "marker_end": marker_start
                                + len(
                                    "⟨cite:" + ",".join(marker["keys"]) + "⟩"
                                ),
                                "source_start": start,
                                "source_end": end,
                                "source_command": raw[start:end],
                                "source_byte_start": None
                                if number
                                else len(raw[:start].encode("utf-8")),
                                "source_byte_end": None
                                if number
                                else len(raw[:end].encode("utf-8")),
                                "source_offset_unit": (
                                    "extracted-page-unicode-codepoint"
                                    if number
                                    else "unicode-codepoint"
                                ),
                            }
                        )
                sentences.append(sentence)
        if kind == "pdf":
            diagnostics.append(
                {
                    "code": "pdf-extraction-uncertain",
                    "message": (
                        "PDF layout and citation coverage require manual review"
                    ),
                }
            )
        if mappings:
            diagnostics.append(
                {
                    "code": "manual-input-binding",
                    "message": (
                        "Explicit review mappings do not certify "
                        "citation identity or complete scope"
                    ),
                }
            )
        keys = sorted({cite["key"] for cite in cites})
        by_key = {
            key: [
                index for index, cite in enumerate(cites) if cite["key"] == key
            ]
            for key in keys
        }
        digests = {
            path: snapshot["raw_sha256"],
            _input_manifest_path(path): manifest_digest,
        }
        if any(
            _audit_file_digest(source) != digest
            for source, digest in digests.items()
        ):
            raise ValueError(
                "manuscript or input mappings changed during extraction"
            )
        return {
            "complete": True,
            "main": path,
            "files": [path],
            "documentclass": None,
            "bib_files": [],
            "input_format": kind,
            "scope_complete": not diagnostics,
            "review_only": kind == "pdf"
            or bool(mappings)
            or bool(inline_bibliography),
            "diagnostics": diagnostics,
            "inline_bibliography": inline_bibliography,
            "n_instances": len(cites),
            "n_keys": len(keys),
            "keys": keys,
            "cites": cites,
            "by_key": by_key,
            "sentences": sentences,
            "source_digests": digests,
            "extraction_metadata": fingerprint,
            "source_texts": {path: "\n".join(views)} if kind == "pdf" else {},
        }
    except (OSError, ValueError, RuntimeError) as exc:
        return {
            "ok": False,
            "complete": False,
            "scope_complete": False,
            "error": str(exc),
        }

# ---------------------------------------------------------------------------
# full text — fetch, cache, passage retrieval for the judge
# ---------------------------------------------------------------------------

class _HTMLText(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "header", "footer", "button", "annotation"}
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "tr",
             "figcaption", "blockquote", "table"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def _html_to_text(body: str) -> str:
    p = _HTMLText()
    p.feed(body)
    return "".join(p.parts)


def _tidy_text(t: str) -> str:
    t = t.replace("\r", "").replace("\x0c", "\n")
    t = re.sub(r"(\w)-\n(?=[a-z])", r"\1", t)                 # de-hyphenate line breaks
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    last = None
    for m in re.finditer(r"\n\s*(?:\d+\.?\s*)?(?:References|REFERENCES|Bibliography|BIBLIOGRAPHY)\s*\n", t):
        last = m
    if last and last.start() > 0.6 * len(t):                   # drop the reference list
        t = t[:last.start()]
    return t.strip()


def _pdf_to_text(path: str) -> str:
    if shutil.which("pdftotext"):
        r = subprocess.run(["pdftotext", "-enc", "UTF-8", path, "-"], capture_output=True, timeout=180)
        if r.returncode == 0 and len(r.stdout) > 200:
            return r.stdout.decode("utf-8", "replace")
    try:
        import pypdf
    except ImportError:
        raise RuntimeError("no PDF text extractor: install poppler's pdftotext, or pypdf in mcp/.venv")
    reader = pypdf.PdfReader(path)
    return "\n".join((pg.extract_text() or "") for pg in reader.pages)


def _download_pdf(url: str, dest: str) -> bool:
    try:
        status, data = _http(url, binary=True, timeout=120, headers={"Accept": "application/pdf,*/*"})
    except RuntimeError:
        return False
    if status != 200 or not isinstance(data, bytes) or not data.startswith(b"%PDF") or len(data) > MAX_PDF_BYTES:
        return False
    with open(dest, "wb") as fh:
        fh.write(data)
    return True


def _text_paths(cid: str) -> tuple:
    return _cache_file("text", _cache_key(cid) + ".txt"), _cache_file("text", _cache_key(cid) + ".json")


def _load_text_meta(cid: str) -> dict | None:
    legacy_path, metadata_path = _text_paths(cid)
    try:
        with open(metadata_path, encoding="utf-8") as source:
            meta = json.load(source)
        digest = meta.get("text_sha256")
        path = (os.path.join(os.path.dirname(legacy_path), digest + ".txt")
                if isinstance(digest, str) and re.fullmatch(r"[a-f0-9]{64}", digest)
                else legacy_path)
        with open(path, encoding="utf-8", errors="replace") as source:
            text = source.read()
        if digest and hashlib.sha256(text.encode("utf-8")).hexdigest() != digest:
            return None
        meta["path"] = path
        return meta
    except (OSError, ValueError, TypeError):
        return None


def _obtain_text(rec: dict, cid: str) -> tuple:
    """(text, basis, source) — arXiv HTML, arXiv PDF, an open-access PDF the
    registries point at, else the abstract, else nothing. A GitHub repository
    yields its README with its description and CITATION.cff abstract (basis
    readme)."""
    if rec.get("github"):
        return _github_text(rec)
    if rec.get("doi") and (not rec.get("arxiv") or not rec.get("abstract") or not rec.get("pdf_urls")):
        try:                                            # OpenAlex knows OA copies and abstracts
            oa = _openalex_get("https://doi.org/" + rec["doi"])
        except RuntimeError:
            oa = None
        if oa:
            rec = _merge_records(rec, oa)
            _record_cache_put(rec)
    if rec.get("arxiv"):
        arxiv_id = rec.get("arxiv_version") or rec["arxiv"]
        try:
            status, body = _http(f"https://arxiv.org/html/{arxiv_id}", cache=False, timeout=60)
        except RuntimeError:
            status, body = 0, ""
        if status == 200 and "ltx_document" in body:
            text = _tidy_text(_html_to_text(body))
            if len(text) > 2000:
                return text, "fulltext", "arxiv-html"
        pdf = _cache_file("pdf", _cache_key(cid) + ".pdf")
        if _download_pdf(f"https://arxiv.org/pdf/{arxiv_id}", pdf):
            text = _tidy_text(_pdf_to_text(pdf))
            if len(text) > 2000:
                return text, "fulltext", "arxiv-pdf"
    if rec.get("arxiv_version"):
        return "", "none", f"arxiv:{rec['arxiv_version']} unavailable"
    for url in rec.get("pdf_urls") or []:
        pdf = _cache_file("pdf", _cache_key(cid) + ".pdf")
        if _download_pdf(url, pdf):
            text = _tidy_text(_pdf_to_text(pdf))
            if len(text) > 2000:
                return text, "fulltext", url
    if rec.get("abstract"):
        return rec.get("title", "") + "\n\n" + rec["abstract"], "abstract", ",".join(rec.get("registries") or [rec["registry"]])
    return "", "none", None


def _github_text(rec: dict) -> tuple:
    repo = rec.get("repo") or {}
    full = repo.get("full_name") or rec["github"]
    head = "\n\n".join(x for x in dict.fromkeys([rec.get("title", ""), repo.get("description") or "",
                                                  rec.get("abstract") or ""]) if x)
    query = "?" + urllib.parse.urlencode({"ref": rec["pinned_sha"]}) if rec.get("pinned_sha") else ""
    status, body = _gh_api(f"/repos/{full}/readme{query}", accept="application/vnd.github.html+json")
    readme = _tidy_text(_html_to_text(body)) if status == 200 else ""
    if len(readme) > 200:
        return head + "\n\n" + readme, "readme", f"github-readme:{full}@{rec.get('pinned_sha', 'HEAD')}"
    if head.strip():
        return head, "abstract", f"github:{full}"
    return "", "none", None


def fetch_text(identifier: str, pdf_path: str | None = None, text_path: str | None = None,
               refresh: bool = False, max_chars: int = 0,
               version: str | None = None) -> dict:
    """Get the cited paper's text for support checking and cache it: arXiv
    HTML → arXiv PDF → open-access PDF → abstract only. For paywalled papers
    pass pdf_path (or text_path) to ingest your own copy. Returns basis
    (fulltext | readme | abstract | none), source, chars, the cache path, and
    the abstract; max_chars>0 inlines that much text. A GitHub repository's
    text is its README, description and CITATION.cff abstract (basis readme).
    """
    rec = _full_record(identifier)
    if rec is None:
        r = resolve_citation(identifier)
        return {"error": f"cannot resolve {identifier}: {r.get('reason') or r.get('error')}"}
    try:
        rec = _with_pin(rec, identifier, version)
    except (RuntimeError, ValueError) as exc:
        return {"error": str(exc)}
    cid = _text_identity(rec)
    tp, mp = _text_paths(cid)
    meta = None if (refresh or pdf_path or text_path) else _load_text_meta(cid)
    if meta and meta.get("basis") == "none":
        meta = None
    if meta is None:
        try:
            if text_path or pdf_path:
                src = os.path.abspath(text_path or pdf_path)
                if not os.path.exists(src):
                    return {"error": f"{src} not found"}
                if text_path:
                    with open(src, errors="replace") as fh:
                        text = fh.read()
                else:
                    text = _pdf_to_text(src)
                text, basis, source = _tidy_text(text), "fulltext", f"local:{os.path.basename(src)}"
            else:
                text, basis, source = _obtain_text(rec, cid)
        except RuntimeError as exc:
            return {"error": str(exc)}
        meta = {"id": _canonical(rec), "cache_id": cid,
                "requested_version": rec.get("requested_version") or rec.get("arxiv_version"), "basis": basis, "source": source, "chars": len(text),
                "fetched": _now_iso(), "title": rec.get("title", ""),
                "extraction_version": TEXT_EXTRACTION_VERSION,
                "version": rec.get("pinned_sha") or rec.get("arxiv_version")}
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        snapshot = os.path.join(os.path.dirname(tp), digest + ".txt")
        meta["text_sha256"] = digest
        with _file_lock(tp):
            # Immutable snapshot first; metadata is the single commit point.
            _atomic_write(snapshot, text)
            _atomic_write(mp, json.dumps(meta))
        meta["path"] = snapshot
    out = dict(meta)
    out["abstract"] = ("" if rec.get("arxiv_version") else (rec.get("abstract") or "")[:2500])
    if max_chars and out["basis"] != "none":
        with open(out["path"], encoding="utf-8", errors="replace") as fh:
            out["text"] = fh.read()[:max_chars]
    if out["basis"] == "none":
        out["note"] = "no text obtainable — pass pdf_path= with your copy of the paper, or judge UNVERIFIABLE"
    elif out["basis"] == "abstract":
        out["note"] = ("description only (the repository has no README)" if rec.get("github") else
                       "abstract only (paywalled, no open-access copy found) — pass pdf_path= for a full-text check")
    elif out["basis"] == "readme":
        out["note"] = ("repository README, description and CITATION.cff abstract — the code itself is not read; a "
                       "claim about what the code does that its documentation does not state is UNVERIFIABLE")
    return out


def _sentences(text: str) -> list:
    out = []
    for para in re.split(r"\n\s*\n", text):
        para = re.sub(r"\s+", " ", para).strip()
        if len(para) >= 20:
            out += _split_sentences(para)
    return [s for s in out if len(s) >= 25]


def find_passages(identifier: str, claims: list[str] | str, k: int = 6, window: int = 2,
                  version: str | None = None) -> dict:
    """For each claim, the top-k passages (windows of `window` sentences) of
    the cited paper ranked by content-word and bigram overlap, plus the
    abstract. This is what the judge reads before quoting evidence.
    """
    if (not isinstance(k, int) or isinstance(k, bool) or k < 1
            or not isinstance(window, int) or isinstance(window, bool) or window < 1):
        return {"error": "k and window must be positive integers"}
    if not isinstance(claims, (list, str)) or not claims:
        return {"error": "claims must be a nonempty string or list of strings"}
    if isinstance(claims, str):
        claims = [claims]
    if any(not isinstance(claim, str) or not claim.strip() for claim in claims):
        return {"error": "claims must contain nonempty strings"}
    meta = fetch_text(identifier, version=version)
    if meta.get("error"):
        return meta
    text = ""
    if meta["basis"] != "none":
        with open(meta["path"], errors="replace") as fh:
            text = fh.read()
    sents = _sentences(text)
    base = {"id": meta["id"], "basis": meta["basis"], "source": meta.get("source"),
            "n_sentences": len(sents), "abstract": meta["abstract"]}
    if not sents:
        return dict(base, results=[{"claim": c, "passages": []} for c in claims],
                    note=meta.get("note") or "no sentences to search")
    words = [set(_content_words(s)) for s in sents]
    n = len(sents)
    df = Counter(w for ws in words for w in ws)

    def idf(w):
        return math.log((n + 1) / (df.get(w, 0) + 1)) + 1

    results = []
    for claim in claims:
        cw = _content_words(claim)
        cset, bigrams = set(cw), set(zip(cw, cw[1:]))
        scored = []
        for i in range(n):
            win = set().union(*words[i:i + window])
            s = sum(idf(w) for w in cset if w in win)
            if s and bigrams:
                wtext = " ".join(_content_words(" ".join(sents[i:i + window])))
                s += 2 * sum(1 for a, b in bigrams if f"{a} {b}" in wtext)
            scored.append((s, i))
        scored.sort(reverse=True)
        chosen, used = [], set()
        for s, i in scored:
            if s <= 0 or len(chosen) >= k:
                break
            if any(j in used for j in range(i, i + window)):
                continue
            used.update(range(i, i + window))
            chosen.append({"score": round(s, 2), "at": i, "text": " ".join(sents[i:i + window])})
        results.append({"claim": claim, "passages": chosen})
    return dict(base, results=results)


# ---------------------------------------------------------------------------
# ledger — support verdicts, accepted only with verbatim evidence
# ---------------------------------------------------------------------------

_VERDICTS = ("SUPPORTS", "PARTIAL", "UNSUPPORTED", "CONTRADICTS", "UNVERIFIABLE")


def _project_path(workdir: str, name: str) -> str:
    d = os.path.join(os.path.abspath(workdir), PROJECT_DIR)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name)


def _write_project(workdir: str, name: str, obj) -> str:
    path = _project_path(workdir, name)
    _atomic_write(path, json.dumps(obj, indent=2))
    return path


def _load_ledger(workdir: str) -> dict:
    path = _project_path(workdir, "ledger.json")
    if os.path.exists(path):
        with open(path) as fh:
            return json.load(fh)
    return {"version": 1, "entries": {}}


EVIDENCE_POLICY = "exact-span-v1"
TEXT_EXTRACTION_VERSION = "text-v1"


def _claim_hash(claim: str) -> str:
    # Whitespace is layout; scientific Unicode, case and citation markers are not.
    text = re.sub(r"\s+", " ", claim or "").strip()
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _source_identity(meta: dict, text: str) -> dict:
    """Bind judgments to the actual cached bytes and acquisition policy."""
    return {
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "id": meta.get("id"), "basis": meta.get("basis"),
        "source": meta.get("source"), "version": meta.get("version"),
        "extraction": meta.get("extraction_version", "legacy"),
        "policy": EVIDENCE_POLICY,
    }


def _current_source_identity(identifier: str) -> dict | None:
    meta = _load_text_meta(identifier)
    if meta is None:
        return None
    try:
        with open(meta["path"], encoding="utf-8", errors="replace") as source:
            return _source_identity(meta, source.read())
    except OSError:
        return None


def _quote_characters(text: str) -> tuple[str, list[int]]:
    """Normalize whitespace and typographic ligatures, retaining source offsets."""
    ligatures = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi",
                 "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}
    characters, offsets = [], []
    for offset, character in enumerate(text):
        replacement = " " if character.isspace() else ligatures.get(
            character, character
        )
        for item in replacement:
            if item == " " and (not characters or characters[-1] == " "):
                continue
            characters.append(item)
            offsets.append(offset)
    if characters and characters[-1] == " ":
        characters.pop()
        offsets.pop()
    return "".join(characters), offsets


def _norm_quote(text: str) -> str:
    return _quote_characters(text)[0]


def _locate_quote(text: str, quote: str) -> dict:
    """Certify an exact source span after conservative extraction normalization."""
    normalized, offsets = _quote_characters(text)
    needle = _norm_quote(quote)
    if len(needle) < 15:
        return {"found": False, "match": 0.0, "reason": "quote too short"}
    index = normalized.find(needle)
    while index >= 0:
        start, end = offsets[index], offsets[index + len(needle) - 1] + 1
        # A match cannot start or end partway through an expanded ligature.
        # Re-normalizing the entire source span checks both boundaries.
        if _norm_quote(text[start:end]) == needle:
            return {"found": True, "match": 1.0, "at": start, "end": end,
                    "source_text": text[start:end]}
        index = normalized.find(needle, index + 1)
    return {"found": False, "match": 0.0,
            "reason": "not found verbatim in the source text"}


@dataclasses.dataclass
class AtomicClaim:
    """An exact sentence span and the citation occurrences supporting it.

    Offsets are zero-based Unicode codepoints, with an exclusive end.
    """

    # MCP's Pydantic adapter honors these without adding a CLI dependency.
    __pydantic_config__ = {"extra": "forbid"}

    start: int = dataclasses.field(metadata={"strict": True})
    end: int = dataclasses.field(metadata={"strict": True})
    citation_ids: list[str]
    kind: Literal["cited", "uncited"] = "cited"
    reason: str | None = None


def _atomic_digest(value: object) -> str:
    """Hash exact JSON content without normalizing scientific symbols."""
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _validated_atoms(sentence: dict, cites: list[dict], atoms: list) -> list:
    """Validate a complete partition and preserve all citation attachments.

    Raises:
        ValueError: Offsets, coverage or citation attachments are invalid.
    """
    if not isinstance(atoms, list) or not atoms:
        raise ValueError("atoms must be a nonempty list")
    claim = sentence["claim"]
    occurrences = {cite["occurrence_id"]: cite for cite in cites}
    eligible = {key for key, cite in occurrences.items() if not cite["nocite"]}
    result, attached, position = [], set(), 0
    for item in atoms:
        atom = (
            dataclasses.asdict(item) if isinstance(item, AtomicClaim) else item
        )
        if (
            not isinstance(atom, dict)
            or not {"start", "end", "citation_ids"} <= set(atom)
            or set(atom) - {"start", "end", "citation_ids", "kind", "reason"}
        ):
            raise ValueError("each atom needs start, end and citation_ids")
        kind, reason = atom.get("kind", "cited"), atom.get("reason")
        if kind not in ("cited", "uncited"):
            raise ValueError("atom kind must be cited or uncited")
        if reason is not None and not isinstance(reason, str):
            raise ValueError("reason must be a string")
        if kind == "uncited" and len((reason or "").strip()) < 15:
            raise ValueError(
                "uncited atoms need a scope reason of at least 15 characters"
            )
        start, end, citation_ids = (
            atom["start"],
            atom["end"],
            atom["citation_ids"],
        )
        if (
            type(start) is not int
            or type(end) is not int
            or start != position
            or not start < end <= len(claim)
        ):
            raise ValueError(
                "atoms must partition the complete sentence in order, "
                "without gaps or overlaps; use Unicode codepoint offsets"
            )
        if (
            not isinstance(citation_ids, list)
            or (kind == "cited" and not citation_ids)
            or (kind == "uncited" and citation_ids)
            or any(not isinstance(value, str) for value in citation_ids)
            or len(set(citation_ids)) != len(citation_ids)
            or not set(citation_ids) <= eligible
        ):
            raise ValueError(
                "citation_ids must name distinct cited occurrences"
            )
        for expression in _TEX_MATH.finditer(claim):
            if expression.start() < start < expression.end() or (
                expression.start() < end < expression.end()
            ):
                raise ValueError(
                    "an atom boundary cannot split a math expression"
                )
        for occurrence_id, cite in occurrences.items():
            left, right = cite["marker_start"], cite["marker_end"]
            if start < right and end > left:
                if kind == "uncited":
                    raise ValueError(
                        "uncited atoms cannot contain citation markers"
                    )
                if start > left or end < right:
                    raise ValueError(
                        "an atom boundary cannot split a citation marker"
                    )
                if not cite["nocite"] and occurrence_id not in citation_ids:
                    raise ValueError(
                        "retain the citation attached inside each atom"
                    )
        atom_text = claim[start:end]
        prose = re.sub(r"⟨cite:[^⟩]*⟩", "", atom_text)
        if not any(character.isalnum() for character in prose):
            raise ValueError("each atom must contain assertion text")
        result.append(
            {
                "start": start,
                "end": end,
                "text": atom_text,
                "byte_start": len(claim[:start].encode("utf-8")),
                "byte_end": len(claim[:end].encode("utf-8")),
                "citation_ids": sorted(citation_ids),
                "kind": kind,
                "reason": reason.strip() if reason else None,
            }
        )
        attached.update(citation_ids)
        position = end
    if position != len(claim) or attached != eligible:
        raise ValueError(
            "cover the entire sentence and every citation occurrence"
        )
    return result


def register_claims(
    tex_path: str, sentence_id: str, atoms: list[AtomicClaim]
) -> dict:
    """Register agent-proposed atomic claims without rewriting the sentence.

    The first registration enables atomic mode for this main manuscript:
    register every current cited sentence, using one span for simple claims.
    Uncited spans need kind="uncited", no citation_ids, and a scope reason.
    Changed sentence/context or partition requires registration and judging
    again. All attached atom/occurrence pairs require separate verdicts.

    Args:
        tex_path: Main manuscript path, including its input/include files.
        sentence_id: Current sentence_id returned by extract_cites.
        atoms: A complete ordered partition of the exact extracted sentence.
            Each span attaches to explicit occurrence IDs from that sentence.

    Returns:
        Registration and derived atom IDs, or an error. Offsets certify
        coverage, not semantic atomicity: a judge must review the split and
        source scope using the unchanged original sentence and context.
    """
    workdir = os.path.dirname(os.path.abspath(tex_path))
    with _file_lock(_project_path(workdir, "ledger.json")):
        extracted = extract_cites(tex_path)
        if extracted.get("error"):
            return {"ok": False, "error": extracted["error"]}
        sentence = next(
            (
                item
                for item in extracted["sentences"]
                if item["sentence_id"] == sentence_id
            ),
            None,
        )
        if sentence is None:
            return {
                "ok": False,
                "error": "sentence changed or ID is unknown; extract again",
            }
        cites = [
            cite
            for cite in extracted["cites"]
            if cite["sentence_id"] == sentence_id
        ]
        try:
            normalized = _validated_atoms(sentence, cites, atoms)
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        decomposition_id = _atomic_digest([sentence_id, normalized])
        for index, atom in enumerate(normalized):
            atom["atom_id"] = _atomic_digest([decomposition_id, index])
        registration = dict(
            sentence,
            atoms=normalized,
            decomposition_id=decomposition_id,
            tex_path=os.path.abspath(tex_path),
        )
        ledger = _load_ledger(workdir)
        decompositions = ledger.setdefault("decompositions", {})
        # Discard old judgments on any revision, including changing back to an
        # earlier decomposition. An identical registration is idempotent.
        previous = decompositions.get(sentence_id)
        current_ids = {item["sentence_id"] for item in extracted["sentences"]}
        invalidated = {
            old_id
            for old_id, old in decompositions.items()
            if old.get("tex_path") == os.path.abspath(tex_path)
            and old_id not in current_ids
        }
        if previous != registration:
            invalidated.add(sentence_id)
        if invalidated:
            ledger["entries"] = {
                key: value
                for key, value in ledger["entries"].items()
                if value.get("sentence_id") not in invalidated
            }
        # Keep history keyed by exact sentence identity. Inserting a citation
        # must not overwrite a displaced sentence's atomic obligation.
        decompositions[sentence_id] = registration
        ledger["version"] = 3
        _write_project(workdir, "ledger.json", ledger)
    return {"ok": True, **registration}


def _find_decomposition(cite: dict, ledger: dict) -> dict | None:
    """Require exact registration once this manuscript enters atomic mode."""
    registrations = [
        value
        for value in ledger.get("decompositions", {}).values()
        if value.get("tex_path") == cite["tex_path"]
    ]
    for registration in registrations:
        if registration["sentence_id"] == cite["sentence_id"]:
            return registration
    # A moved and edited assertion cannot be matched reliably by text or
    # source ordinal. Atomic mode requires explicit registration of every
    # current sentence; a single span is valid for a simple assertion.
    return registrations[-1] if registrations else None


def _support_target(
    workdir: str,
    tex_path: str,
    occurrence_id: str,
    atom_id: str | None,
    key: str,
    claim: str,
    context: str | None,
    ledger: dict,
) -> dict:
    """Resolve an exact current occurrence and optional registered atom.

    Raises:
        ValueError: The requested target is stale, ambiguous or incomplete.
    """
    if os.path.realpath(workdir) != os.path.realpath(os.path.dirname(tex_path)):
        raise ValueError("workdir must be the main manuscript directory")
    extracted = extract_cites(tex_path)
    if extracted.get("error"):
        raise ValueError(extracted["error"])
    cite = next(
        (
            item
            for item in extracted["cites"]
            if item["occurrence_id"] == occurrence_id
        ),
        None,
    )
    if (
        cite is None
        or cite["nocite"]
        or cite["key"] != key
        or cite["claim"] != claim
        or cite["context"] != context
    ):
        raise ValueError(
            "use the exact current occurrence, key, claim and context"
        )
    registration = _find_decomposition(cite, ledger)
    target = {
        "occurrence_id": occurrence_id,
        "sentence_id": cite["sentence_id"],
        "location_id": cite["location_id"],
        "file": cite["file"],
        "line": cite["line"],
        "context": cite["context"],
    }
    if registration:
        if registration["sentence_id"] != cite["sentence_id"]:
            raise ValueError(
                "sentence or context changed; register claims again"
            )
        atom = next(
            (
                item
                for item in registration["atoms"]
                if item["atom_id"] == atom_id
            ),
            None,
        )
        if atom is None or occurrence_id not in atom["citation_ids"]:
            raise ValueError(
                "record each registered atom with an attached occurrence"
            )
        target.update(
            atom_id=atom_id,
            atom=atom,
            decomposition_id=registration["decomposition_id"],
        )
    elif atom_id is not None:
        raise ValueError("register claims before recording an atom verdict")
    return target


def _support_requirements(extracted: dict, ledger: dict) -> list[dict]:
    """Expand citation instances only into atoms explicitly attached to them."""
    required = []
    for cite in extracted["cites"]:
        if cite["nocite"]:
            continue
        registration = _find_decomposition(cite, ledger)
        if not registration:
            required.append(cite)
        elif registration["sentence_id"] != cite["sentence_id"]:
            required.append(dict(cite, decomposition_stale=True))
        else:
            for atom in registration["atoms"]:
                if cite["occurrence_id"] in atom["citation_ids"]:
                    required.append(
                        dict(
                            cite,
                            atom_id=atom["atom_id"],
                            atom=atom,
                            decomposition_id=registration["decomposition_id"],
                        )
                    )
    return required


def _support_id(occurrence_id: str, atom_id: str | None = None) -> str:
    """Keep sentence-occurrence and atom-occurrence judgments separate."""
    return f"occurrence:{occurrence_id}|atom:{atom_id or 'sentence'}"


@dataclasses.dataclass
class ProposedCorrection:
    """An unapproved judge-authored recommendation, never an applied edit.

    Attributes:
        action: The recommended operation; replacement wording is allowed
            only for revise-claim and does not carry a new citation identity.
        rationale: Why the original assertion needs attention.
        replacement_text: Optional assertion wording requiring human review
            and a fresh support judgment after application.
    """

    __pydantic_config__ = {"extra": "forbid"}

    action: Literal[
        "revise-claim", "replace-citation", "remove-claim", "obtain-text"
    ]
    rationale: str
    replacement_text: str | None = None


def _validated_correction(
    proposal: ProposedCorrection | dict[str, Any] | None,
    verdict: str,
    occurrence_id: str | None,
    judge: str | None,
    found_quotes: int,
) -> dict[str, Any] | None:
    """Validate a bound draft without certifying its proposed meaning."""
    if proposal is None:
        return None
    value = (
        dataclasses.asdict(proposal)
        if isinstance(proposal, ProposedCorrection)
        else proposal
    )
    if (
        not isinstance(value, dict)
        or not {"action", "rationale"} <= set(value)
        or set(value) - {"action", "rationale", "replacement_text"}
    ):
        raise ValueError("proposed_correction needs action and rationale")
    action = value["action"]
    if not isinstance(action, str) or action not in {
        "revise-claim",
        "replace-citation",
        "remove-claim",
        "obtain-text",
    }:
        raise ValueError("unknown proposed correction action")
    rationale = value["rationale"]
    replacement = value.get("replacement_text")
    if (
        not isinstance(rationale, str)
        or len(rationale.strip()) < 15
        or (
            replacement is not None
            and (not isinstance(replacement, str) or not replacement.strip())
        )
    ):
        raise ValueError("provide a meaningful rationale and nonempty wording")
    if (
        verdict == "SUPPORTS"
        or not occurrence_id
        or not isinstance(judge, str)
        or not judge.strip()
    ):
        raise ValueError(
            "corrections require a non-SUPPORTS verdict, explicit occurrence "
            "and judge identity"
        )
    if replacement is not None:
        if action != "revise-claim" or found_quotes == 0:
            raise ValueError(
                "replacement wording needs revise-claim and source quotations"
            )
        if _CITE_CMD.search(replacement) or "⟨cite:" in replacement:
            raise ValueError(
                "replacement_text is assertion wording only; resolve citation "
                "changes separately"
            )
    return {
        "action": action,
        "rationale": rationale.strip(),
        "replacement_text": replacement,
        "author": judge,
        "approval": "unapproved",
        "replacement_verified": False,
    }


def _correction_action(finding: dict[str, Any]) -> dict[str, str]:
    """Give an honest next step without inventing scientific replacements."""
    kind = finding["type"]
    if kind in {"support-stale", "audit-stale", "report-stale"}:
        action, instruction = (
            "re-judge",
            (
                "Refresh the changed inputs and obtain a new indepe"
                "ndent judgment."
            ),
        )
    elif kind == "decomposition-stale":
        action, instruction = (
            "register-claims",
            (
                "Extract current sentences, register their complete"
                " atomic spans, "
                "then judge each attached occurrence."
            ),
        )
    elif kind == "support-missing":
        action, instruction = (
            "judge-claim",
            (
                "Retrieve this cited work and record an independent support "
                "judgment for this exact assertion and occurrence."
            ),
        )
    elif kind == "support-basis" or finding.get("verdict") == "UNVERIFIABLE":
        action, instruction = (
            "obtain-text",
            (
                "Obtain adequate source text and re-judge; do not i"
                "nfer support "
                "from inaccessible evidence."
            ),
        )
    elif kind == "support":
        action, instruction = (
            "review-assertion",
            (
                "Review the disputed assertion against the evidence"
                ". A human may "
                "revise or remove it, or identify and verify an alt"
                "ernative work; "
                "then extract and judge the changed text again."
            ),
        )
    elif kind in {"existence", "verify-error", "undefined-cite"}:
        action, instruction = (
            "resolve-identity",
            (
                "Resolve the intended work through the citation tools. Retry "
                "failed lookups; obtain any replacement bibliograph"
                "y entry from "
                "an official export, never from invented metadata."
            ),
        )
    elif kind == "provenance":
        action, instruction = (
            "refresh-official-export",
            (
                "Check the intended identity and replace the entry through "
                "bib_add using its official export."
            ),
        )
    elif kind == "uncited-atom":
        action, instruction = (
            "review-scope",
            (
                "Review the declared uncited scope; it has not been externally "
                "verified and must not conceal a cited assertion."
            ),
        )
    elif kind == "uncited-entry":
        action, instruction = (
            "review-unused-entry",
            ("Review whether this unused bibliography entry should remain."),
        )
    elif kind == "policy-configuration":
        action, instruction = (
            "run-required-checks",
            (
                "Enable identity and support checks for submission readiness, "
                "or explicitly use exploratory mode for partial work."
            ),
        )
    else:
        action, instruction = (
            "repair-input",
            (
                "Inspect the reported input problem, repair it explicitly, and "
                "rerun the audit before relying on the result."
            ),
        )
    return {"action": action, "instruction": instruction}


def _correction_evidence(
    judgment: dict[str, Any],
    attributed: bool,
) -> dict[str, Any] | None:
    """Recheck source spans locally instead of trusting stored found flags."""
    metadata = _load_text_meta(judgment.get("source_cache_id", judgment["id"]))
    if metadata is None:
        return None
    try:
        with open(
            metadata["path"], encoding="utf-8", errors="replace"
        ) as source:
            text = source.read()
    except OSError:
        return None
    if _source_identity(metadata, text) != judgment["source_identity"]:
        return None
    quotes = []
    for quote in judgment.get("quotes", []):
        if quote["found"]:
            checked = _locate_quote(text, quote["text"])
            if not checked["found"]:
                return None
            quotes.append(dict(checked, text=quote["text"]))
    return {
        "id": judgment["id"],
        "basis": judgment["basis"],
        "identity": judgment["source_identity"],
        "attribution": "verified" if attributed else "unverified",
        "quotes": quotes,
        "status": "current-source-spans",
    }


def _correction_items(
    report: dict[str, Any],
    extracted: dict[str, Any],
    judgments: dict[str, dict[str, Any]],
    verification: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach findings to exact current occurrences, never truncated text."""
    items = []
    for severity, findings in (
        ("failure", report["failures"]),
        ("warning", report["warnings"]),
    ):
        for finding in findings:
            targets = []
            for cite in extracted.get("cites", []):
                if finding.get("occurrence_id") == cite["occurrence_id"]:
                    targets = [cite]
                    break
                if (
                    not finding.get("occurrence_id")
                    and finding.get("key")
                    and finding["key"] == cite["key"]
                ):
                    targets.append(cite)
            for target in targets or [None]:
                occurrence = target["occurrence_id"] if target else None
                atom_id = finding.get("atom_id")
                judgment = (
                    judgments.get(_support_id(occurrence, atom_id))
                    if occurrence
                    else None
                )
                if finding["type"] in {
                    "support-stale",
                    "decomposition-stale",
                    "audit-stale",
                }:
                    judgment = None
                key = target["key"] if target else finding.get("key")
                location = {
                    "file": target["file"] if target else finding.get("file"),
                    "line": target["line"] if target else finding.get("line"),
                    "kind": "citation-command"
                    if target
                    else "reported-or-unknown",
                    "source_byte_start": target.get("source_byte_start")
                    if target
                    else None,
                    "source_byte_end": target.get("source_byte_end")
                    if target
                    else None,
                }
                if target:
                    location.update(
                        {
                            name: target.get(name)
                            for name in (
                                "page",
                                "page_line",
                                "source_start",
                                "source_end",
                                "source_offset_unit",
                            )
                        }
                    )
                source = None
                proposal = None
                if judgment:
                    source = _correction_evidence(
                        judgment,
                        verification.get(key, {}).get("status") == "VERIFIED"
                        and not extracted.get("review_only", False),
                    )
                    if (
                        source is not None
                        and judgment.get("occurrence_id") == occurrence
                    ):
                        stored = judgment.get("proposed_correction")
                        if stored is not None:
                            proposal = dict(
                                stored,
                                approval="unapproved",
                                replacement_verified=False,
                            )
                sentence: dict[str, Any] = next(
                    (
                        value
                        for value in extracted.get("sentences", [])
                        if value["sentence_id"] == finding.get("sentence_id")
                    ),
                    {},
                )
                item = {
                    "finding_id": _atomic_digest(
                        [
                            severity,
                            finding,
                            occurrence,
                            atom_id,
                        ]
                    ),
                    "severity": severity,
                    "type": finding["type"],
                    "key": key,
                    "occurrence_id": occurrence,
                    "atom_id": atom_id,
                    "sentence_id": target.get("sentence_id")
                    if target
                    else finding.get("sentence_id"),
                    "location": location,
                    "bibliography_locations": report.get(
                        "bibliography_locations", {}
                    ).get(key, []),
                    "claim": target["claim"]
                    if target
                    else finding.get("claim"),
                    "context": target["context"]
                    if target
                    else sentence.get("context"),
                    "assertion": finding.get("atom")
                    or (target["claim"] if target else finding.get("claim")),
                    "detail": finding.get("detail"),
                    "verdict": finding.get("verdict"),
                    "status": finding.get("status"),
                    "next_action": _correction_action(finding),
                    "source_evidence": source,
                    "proposed_correction": proposal,
                    "applied": False,
                }
                items.append(item)
    return items


def _invalidate_corrections(report: dict[str, Any]) -> None:
    """Suppress evidence and wording when the report's inputs are stale."""
    for item in report.get("corrections", []):
        item["source_evidence"] = None
        item["proposed_correction"] = None
        item["evidence_status"] = "suppressed-stale-report"
        item["next_action"] = {
            "action": "refresh-audit",
            "instruction": "Inputs changed. Rerun extraction and audit, then re-judge affected assertions before considering corrections.",
        }


def _corrections_markdown(report: dict[str, Any]) -> str:
    """Render actionable findings while preserving exact quoted strings."""
    policy = report.get("policy")
    if policy not in ("exploratory", "submission-ready"):
        policy = "invalid"
    lines = [
        "# Citation correction report",
        "",
        (
            f"Policy: {policy}; submission ready: "
            f"{report.get('submission_ready', False)}."
        ),
        (
            "Proposals are unapproved drafts, not verified repl"
            "acements. No edits were applied."
        ),
        "",
    ]
    for item in report.get("corrections", []):
        location = item["location"]
        lines += [
            f"## {item['type']} — {item['finding_id'][:12]}",
            "",
            (
                f"Occurrence: {item['occurrence_id'] or 'unknown'}; "
                f"atom: {item['atom_id'] or 'none'}"
            ),
            "",
        ]
        # JSON string blocks preserve whitespace and cannot open raw HTML.
        for label, value in (
            ("Location", location),
            ("Bibliography locations", item["bibliography_locations"]),
            ("Assertion", item["assertion"]),
            ("Original sentence", item["claim"]),
            ("Context", item["context"]),
            ("Finding", item["detail"]),
            ("Evidence", item["source_evidence"]),
            ("Unapproved proposal", item["proposed_correction"]),
        ):
            if value is not None:
                encoded = json.dumps(value, ensure_ascii=False, indent=2)
                fence = "`" * max(
                    3,
                    max(
                        (
                            len(match[0]) + 1
                            for match in re.finditer(r"`+", encoded)
                        ),
                        default=3,
                    ),
                )
                lines += [f"{label}:", f"{fence}json", encoded, fence, ""]
        lines += [item["next_action"]["instruction"], ""]
    return "\n".join(lines) + "\n"


def _corrections_html(report: dict[str, Any], sources: dict[str, str]) -> str:
    """Render escaped findings linked to unchanged source-line text."""
    blocks = [
        '<!doctype html><html lang="en"><head><meta charset="utf-8">',
        (
            '<meta http-equiv="Content-Security-Policy" content'
            "=\"default-src 'none'; style-src 'unsafe-inline'; b"
            "ase-uri 'none'; form-action 'none'\">"
        ),
        "<title>Citation correction report</title>",
        (
            "<style>body{font:16px system-ui;max-width:1100px;m"
            "argin:2em auto;padding:0 1em}pre{white-space:pre-w"
            "rap;overflow-wrap:anywhere;background:#f4f4f4;padd"
            "ing:1em}.finding{border-left:4px solid #a64b00;pad"
            "ding:1em;margin:1em 0}.line{display:block}.marked{"
            "background:#fff1c9}.number{color:#666;display:inli"
            "ne-block;min-width:4em}.badge{font:12px system-ui;"
            "margin-right:1em}a{color:#704000}</style>"
        ),
        "</head><body><h1>Citation correction report</h1>",
        (
            "<p>No edits were applied. Proposed wording is unap"
            "proved and must be independently checked after app"
            "lication.</p>"
        ),
    ]
    indices = {path: index for index, path in enumerate(sources)}
    line_findings: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for item in report.get("corrections", []):
        blocks += [
            f'<section class="finding" id="finding-{item["finding_id"]}">',
            f"<h2>{html.escape(item['type'])}</h2>",
        ]
        locations = [("Manuscript", item["location"])] + [
            ("Bibliography", location)
            for location in item["bibliography_locations"]
        ]
        for label, location in locations:
            path, line = location["file"], location["line"]
            anchor = None
            if (
                path in indices
                and type(line) is int
                and 1 <= line <= len(sources[path].splitlines())
            ):
                anchor = f"source-{indices[path]}-line-{line}"
                line_findings.setdefault((path, line), []).append(item)
            where = html.escape(
                f"{label}: {path or 'unknown location'}:"
                f"{line or 'unknown line'}"
            )
            blocks.append(
                f'<p><a href="#{anchor}">{where}</a></p>'
                if anchor
                else f"<p>{where}</p>"
            )
        for label, value in (
            ("Disputed assertion", item["assertion"]),
            ("Original sentence", item["claim"]),
            ("Context", item["context"]),
            ("Finding", item["detail"]),
            ("Next action", item["next_action"]["instruction"]),
        ):
            if value is not None:
                rendered = (
                    value
                    if isinstance(value, str)
                    else json.dumps(value, ensure_ascii=False, indent=2)
                )
                blocks += [
                    f"<h3>{label}</h3><pre>{html.escape(rendered)}</pre>"
                ]
        proposal = item["proposed_correction"]
        if proposal:
            blocks.append("<h3>Unapproved judge-authored proposal</h3>")
            blocks.append(
                "<pre>"
                + html.escape(
                    json.dumps(proposal, ensure_ascii=False, indent=2)
                )
                + "</pre>"
            )
        evidence = item["source_evidence"]
        if evidence:
            blocks += [
                "<h3>Source evidence</h3>",
                "<p>Bibliographic attribution: "
                + html.escape(evidence["attribution"])
                + "</p>",
            ]
            for quote in evidence["quotes"]:
                blocks.append(
                    "<pre>" + html.escape(quote["source_text"]) + "</pre>"
                )
        blocks += [
            (
                "<details><summary>Exact identifiers and evidence m"
                "etadata</summary><pre>"
            ),
            html.escape(json.dumps(item, ensure_ascii=False, indent=2)),
            "</pre></details></section>",
        ]
    for path, content in sources.items():
        index = indices[path]
        blocks += [f"<h2>{html.escape(path)}</h2><pre>"]
        for number, line in enumerate(content.splitlines(keepends=True), 1):
            findings = line_findings.get((path, number), [])
            css = "line marked" if findings else "line"
            blocks.append(
                f'<span class="{css}" id="source-{index}-line-{number}">'
                f'<span class="number">{number}</span>'
            )
            for item in findings:
                blocks.append(
                    f'<a class="badge" href="#finding-{item["finding_id"]}">'
                    f"{html.escape(item['type'])}</a>"
                )
            blocks.append(
                '<code class="source-text">'
                + html.escape(line)
                + "</code></span>"
            )
        blocks.append("</pre>")
    blocks.append("</body></html>")
    return "".join(blocks)


def _correction_snapshot_current(
    snapshot: dict[str, Any], workdir: str
) -> bool:
    """Check only local bound inputs; rendering never repeats registry calls."""
    return (
        (snapshot.get("input_backend") is None
         or snapshot["input_backend"] == _input_pdf_backend())
        and _audit_file_digest(_project_path(workdir, "ledger.json"))
        == snapshot["ledger"]
        and all(
            _audit_file_digest(path) == digest
            for path, digest in snapshot["files"].items()
        )
        and all(
            _current_source_identity(identifier) == identity
            for identifier, identity in snapshot["sources"].items()
        )
    )


def _correction_preflight(tex_path: str, bib_path: str | None) -> str | None:
    """Reject report-pipeline output aliases before any audit mutation."""
    workdir = os.path.dirname(os.path.abspath(tex_path))
    extracted = extract_cites(tex_path)
    inputs = set(extracted.get("files", [os.path.abspath(tex_path)]))
    bibs = (
        [os.path.abspath(bib_path)]
        if bib_path
        else extracted.get("bib_files", [])
    )
    inputs.update(bibs)
    inputs.update(extracted.get("source_digests", {}))
    directories = {os.path.join(workdir, PROJECT_DIR)}
    directories.update(
        os.path.join(os.path.dirname(bib), PROJECT_DIR) for bib in bibs
    )
    outputs: list[str] = []
    for directory in directories:
        if os.path.islink(directory):
            return "report directory is a symlink"
        outputs.extend(
            os.path.join(directory, name)
            for name in (
                "audit.md",
                "audit.json",
                "verify.json",
                "corrections.json",
                "corrections.md",
                "corrections.html",
                "ledger.json.lock",
            )
        )
    try:
        ledger = _audit_ledger(workdir)
    except (OSError, ValueError):
        ledger = {"entries": {}}
    for judgment in ledger["entries"].values():
        metadata = _load_text_meta(
            judgment.get("source_cache_id", judgment["id"])
        )
        if metadata and metadata.get("path"):
            inputs.add(metadata["path"])
    resolved_inputs = {os.path.realpath(path) for path in inputs}
    for output in outputs:
        if (
            os.path.islink(output)
            or os.path.realpath(output) in resolved_inputs
        ):
            return (
                "report pipeline output aliases a manuscript or bib"
                "liography input"
            )
        for source in inputs:
            if (
                os.path.exists(output)
                and os.path.exists(source)
                and os.path.samefile(output, source)
            ):
                return "report pipeline output is hard-linked to an input"
    return None


def correction_report(
    tex_path: str,
    bib_path: str | None = None,
    policy: Literal["exploratory", "submission-ready"] = "submission-ready",
    annotated: bool = False,
    verify: bool = True,
    require_support: bool = True,
) -> dict[str, Any]:
    """Create corrections from one fresh audit without editing inputs.

    Args:
        tex_path: Main manuscript path.
        bib_path: Optional bibliography override, as in audit.
        policy: The explicit audit policy; strict by default.
        annotated: Also write an escaped static HTML copy of source files.
        verify: Perform registry identity checks.
        require_support: Require recorded support in exploratory mode too.

    Returns:
        Audit results, actionable corrections and written artifact paths.
        Scientific proposals remain unapproved and are never applied.
    """
    workdir = os.path.dirname(os.path.abspath(tex_path))
    destination = os.path.join(workdir, PROJECT_DIR)
    preflight_error = _correction_preflight(tex_path, bib_path)
    if preflight_error:
        return {
            "ok": False,
            "submission_ready": False,
            "report_written": False,
            "error": preflight_error,
            "artifacts": {},
        }
    report = audit(tex_path, bib_path, require_support, verify, policy)
    if "corrections" not in report:
        report["corrections"] = _correction_items(report, {}, {}, {})
    snapshot = report.get("snapshot")
    if snapshot is None:
        paths = [os.path.abspath(tex_path)]
        if bib_path:
            paths.append(os.path.abspath(bib_path))
        snapshot = {
            "files": {path: _audit_file_digest(path) for path in paths},
            "ledger": _audit_file_digest(_project_path(workdir, "ledger.json")),
            "sources": {},
        }
        report["snapshot"] = snapshot
        report["annotation_status"] = "unavailable-incomplete-input"
        annotated = False
    outputs = {
        "json": os.path.join(destination, "corrections.json"),
        "markdown": os.path.join(destination, "corrections.md"),
    }
    if annotated:
        outputs["annotated"] = os.path.join(destination, "corrections.html")
    input_paths = set(snapshot["files"])
    for path in outputs.values():
        if os.path.islink(path) or os.path.realpath(path) in {
            os.path.realpath(value) for value in input_paths
        }:
            return dict(
                report,
                ok=False,
                error="report output aliases an input",
                artifacts={},
                report_written=False,
            )
    sources = {}
    for path in report.get("source_files", []):
        try:
            with open(path, "rb") as source:
                raw = source.read()
            if hashlib.sha256(raw).hexdigest() != snapshot["files"].get(path):
                raise ValueError("source changed during report rendering")
            sources[path] = ((report.get("source_texts") or {}).get(path)
                             if path in (report.get("source_texts") or {})
                             else raw.decode("utf-8"))
        except (OSError, ValueError) as error:
            _invalidate_corrections(report)
            return dict(
                report,
                ok=False,
                submission_ready=False,
                complete=False,
                error=str(error),
                artifacts={},
                report_written=False,
            )
    markdown = _corrections_markdown(report)
    annotated_text = _corrections_html(report, sources) if annotated else None
    report.update(artifacts=outputs, report_written=True)
    with _file_lock(_project_path(workdir, "ledger.json")):
        if _correction_preflight(
            tex_path, bib_path
        ) is not None or not _correction_snapshot_current(snapshot, workdir):
            _invalidate_corrections(report)
            return dict(
                report,
                ok=False,
                submission_ready=False,
                complete=False,
                error="report-stale: inputs changed; rerun",
                artifacts={},
                report_written=False,
            )
        for key in [name for name in outputs if name != "json"] + ["json"]:
            path = outputs[key]
            if key == "json":
                _atomic_write(
                    path, json.dumps(report, ensure_ascii=False, indent=2)
                )
            elif key == "markdown":
                _atomic_write(path, markdown)
            elif annotated_text is not None:
                _atomic_write(path, annotated_text)
    return dict(report, artifacts=outputs, report_written=True)


def record_support(
    workdir: str,
    key: str,
    claim: str,
    verdict: str,
    identifier: str,
    quotes: list[str] | None = None,
    note: str | None = None,
    judge: str | None = None,
    file: str | None = None,
    line: int | None = None,
    context: str | None = None,
    version: str | None = None,
    tex_path: str | None = None,
    occurrence_id: str | None = None,
    atom_id: str | None = None,
    proposed_correction: ProposedCorrection | None = None,
) -> dict:
    """Record a support verdict for one (cite key, claim sentence) pair.

    verdict ∈ SUPPORTS | PARTIAL | UNSUPPORTED | CONTRADICTS | UNVERIFIABLE.
    SUPPORTS / PARTIAL / CONTRADICTS are refused unless at least one `quote`
    is found verbatim in the cited paper's fetched text (fetch_text first).
    PARTIAL / CONTRADICTS / UNSUPPORTED / UNVERIFIABLE need a `note` saying
    what the paper does and does not say; UNVERIFIABLE is refused when full
    text is available. `claim` must be the exact sentence extract_cites gave.
    Pass tex_path and occurrence_id together; atom_id selects a registered
    span while claim/context retain the full original. Atomic mode requires
    an atom_id even for a registered single-span sentence. Legacy calls only
    satisfy unambiguous sentences in manuscripts outside atomic mode.
    proposed_correction optionally records an unapproved independent-judge
    draft for a non-support verdict; it never applies or verifies new wording.
    """
    if bool(tex_path) != bool(occurrence_id) or (atom_id and not occurrence_id):
        return {
            "recorded": False,
            "error": (
                "tex_path and occurrence_id are required together; "
                "atoms need both"
            ),
        }
    target = {}
    if tex_path and occurrence_id:
        tex_path = os.path.abspath(tex_path)
        try:
            target = _support_target(
                workdir,
                tex_path,
                occurrence_id,
                atom_id,
                key,
                claim,
                context,
                _load_ledger(workdir),
            )
        except ValueError as error:
            return {"recorded": False, "error": str(error)}
    if quotes is not None and (
        not isinstance(quotes, list)
        or any(not isinstance(quote, str) for quote in quotes)
    ):
        return {"recorded": False, "error": "quotes must be a list of strings"}
    verdict = (verdict or "").strip().upper()
    if verdict not in _VERDICTS:
        return {
            "recorded": False,
            "error": f"verdict must be one of {list(_VERDICTS)}",
        }
    rec = _full_record(identifier)
    if rec is None:
        return {"recorded": False, "error": f"cannot resolve {identifier}"}
    try:
        rec = _with_pin(rec, identifier, version)
    except (RuntimeError, ValueError) as exc:
        return {"recorded": False, "error": str(exc)}
    cid = _canonical(rec)
    cache_id = _text_identity(rec)
    meta = _load_text_meta(cache_id) or fetch_text(identifier, version=version)
    if meta.get("error"):
        return {"recorded": False, "error": meta["error"]}
    basis = meta["basis"]
    text = ""
    if basis != "none":
        with open(meta["path"], errors="replace") as fh:
            text = fh.read()
    quotes = [q.strip() for q in (quotes or []) if q and q.strip()]
    checks = [dict({"text": q}, **_locate_quote(text, q)) for q in quotes]
    n_found = sum(1 for c in checks if c["found"])
    note = (note or "").strip()
    if verdict in ("SUPPORTS", "PARTIAL", "CONTRADICTS") and n_found == 0:
        return {
            "recorded": False,
            "basis": basis,
            "quotes": checks,
            "error": f"{verdict} needs at least one quote found verbatim in the paper's "
            f"{'text' if basis == 'fulltext' else basis} — quote the paper, not your paraphrase",
        }
    if (
        verdict in ("PARTIAL", "CONTRADICTS", "UNSUPPORTED", "UNVERIFIABLE")
        and len(note) < 15
    ):
        return {
            "recorded": False,
            "error": f"{verdict} needs a note (≥ 15 characters) saying what the paper does and does not say",
        }
    if verdict == "UNVERIFIABLE" and basis == "fulltext":
        return {
            "recorded": False,
            "error": "full text is available — read it and decide (SUPPORTS / PARTIAL / "
            "UNSUPPORTED / CONTRADICTS); UNVERIFIABLE is only for papers whose text could not be obtained",
        }
    try:
        correction = _validated_correction(
            proposed_correction, verdict, occurrence_id, judge, n_found
        )
    except ValueError as error:
        return {"recorded": False, "error": str(error)}
    with _file_lock(_project_path(workdir, "ledger.json")):
        ledger = _load_ledger(workdir)
        # Revalidate inside the transaction: registration may have changed
        # while fetching source text. Never commit against an obsolete split.
        if tex_path and occurrence_id:
            try:
                target = _support_target(
                    workdir, tex_path, occurrence_id, atom_id,
                    key, claim, context, ledger,
                )
            except ValueError as error:
                return {"recorded": False, "error": str(error)}
        lid = (_support_id(occurrence_id, atom_id) if occurrence_id
               else f"{key}|{_claim_hash(claim)}")
        ledger["version"] = 3
        ledger["entries"][lid] = {"context_hash": _claim_hash(context if context is not None else claim),
                                  "source_identity": _source_identity(meta, text),
                                  "source_cache_id": meta.get("cache_id", cid), "key": key, "id": cid, "claim": claim, "verdict": verdict, "basis": basis,
                                  "quotes": checks, "note": note or None, "judge": judge or None,
                                  "file": file, "line": line, "recorded": _now_iso()}
        ledger["entries"][lid].update(target)
        if correction is not None:
            ledger["entries"][lid]["proposed_correction"] = correction
        _write_project(workdir, "ledger.json", ledger)
    return {"recorded": True, "ledger_id": lid, "verdict": verdict, "basis": basis,
            "quotes_found": n_found, "quotes": checks}


def ledger_read(workdir: str) -> dict:
    """Read the support ledger of a manuscript directory."""
    return {"path": _project_path(workdir, "ledger.json"), "ledger": _load_ledger(workdir)}


# ---------------------------------------------------------------------------
# audit — the gate
# ---------------------------------------------------------------------------

_AUDIT_POLICIES = ("exploratory", "submission-ready")


def _coverage_axis(
    states: list[str], unresolved: set[str], verified: set[str]
) -> dict[str, Any]:
    """Count every expected unit, including unresolved outcomes."""
    counts = dict(Counter(states))
    expected = len(states)
    assessed = sum(state not in unresolved for state in states)
    accepted = sum(state in verified for state in states)
    return {
        "expected": expected,
        "assessed": assessed,
        "verified": accepted,
        "counts": counts,
        "complete": assessed == expected,
        "assessment_rate": assessed / expected if expected else None,
        "verification_rate": accepted / expected if expected else None,
    }


def _incomplete_audit(policy: str, error: str) -> dict[str, Any]:
    """Report unknown coverage when extraction cannot establish the inputs."""
    axes: dict[str, dict[str, Any]] = {}
    for name in ("existence", "provenance", "support"):
        axes[name] = {
            "expected": None,
            "assessed": 0,
            "verified": 0,
            "counts": {},
            "complete": False,
            "assessment_rate": None,
            "verification_rate": None,
        }
    axes["provenance"].pop("verified")
    axes["provenance"].pop("verification_rate")
    axes["provenance"].update(
        declared=0,
        declaration_rate=None,
        assurance="declaration-only; export digest not checked",
    )
    axes["support"].update(
        basis_counts={},
        unresolved_decompositions=None,
        atomic_total_known=False,
        unit="unknown support requirements",
    )
    return {
        "ok": False,
        "input_complete": False,
        "complete": False,
        "submission_ready": False,
        "policy": policy,
        "error": error,
        "coverage": axes,
        "failures": [{"type": "input-incomplete", "detail": error}],
        "warnings": [],
    }


def _declared_provenance(entry: dict[str, Any], result: dict[str, Any]) -> str:
    """Check declaration shape and identity, without a digest assurance."""
    if not entry:
        return "UNDEFINED"
    provenance = entry.get("provenance")
    if not provenance:
        return "UNOFFICIAL"
    sources = {
        "ads",
        "crossref",
        "datacite",
        "inspire",
        "arxiv",
        "github",
        "citation-cff",
    }
    identifier = provenance.get("id", "")
    if (
        provenance.get("source") not in sources
        or not isinstance(identifier, str)
        or not identifier.strip()
        or _classify(identifier)[0] == "unknown"
    ):
        return "MALFORMED"
    try:
        datetime.strptime(provenance.get("fetched", ""), "%Y-%m-%d")
    except (TypeError, ValueError):
        return "MALFORMED"
    ids = result.get("ids") or {}
    if not isinstance(ids, dict):
        return "MALFORMED"
    resolved = result.get("id")
    aliases = {str(resolved).lower()} if resolved else set()
    for kind, value in ids.items():
        if value:
            aliases.add(f"{kind}:{value}".lower())
    if aliases and identifier.lower() not in aliases:
        return "MISMATCH"
    return "DECLARED"


def _audit_file_digest(path: str) -> str | None:
    """Return a local input digest, or None when its bytes are unavailable."""
    try:
        with open(path, "rb") as source:
            return hashlib.sha256(source.read()).hexdigest()
    except OSError:
        return None


def _audit_ledger(workdir: str) -> dict[str, Any]:
    """Load ledger structure, rejecting malformed state instead of skipping it.

    Raises:
        ValueError: Ledger entries or registrations are malformed.
        OSError: The ledger cannot be read.
    """
    ledger = _load_ledger(workdir)
    if not isinstance(ledger, dict) or not isinstance(
        ledger.get("entries"), dict
    ):
        raise ValueError("ledger must contain an entries object")
    for entry in ledger["entries"].values():
        if not isinstance(entry, dict) or not {
            "id",
            "key",
            "claim",
            "verdict",
            "basis",
        } <= set(entry):
            raise ValueError("malformed support ledger entry")
        if any(
            not isinstance(entry[name], str)
            for name in ("id", "key", "claim", "verdict", "basis")
        ) or (
            "source_cache_id" in entry
            and not isinstance(entry["source_cache_id"], str)
        ):
            raise ValueError("support ledger identity fields must be strings")
    for entry in ledger["entries"].values():
        quotes = entry.get("quotes", [])
        if not isinstance(quotes, list) or any(
            not isinstance(quote, dict)
            or type(quote.get("found")) is not bool
            or not isinstance(quote.get("text"), str)
            for quote in quotes
        ):
            raise ValueError("malformed stored quotation checks")
        proposal = entry.get("proposed_correction")
        if proposal is not None:
            if (
                not isinstance(proposal, dict)
                or set(proposal)
                != {
                    "action",
                    "rationale",
                    "replacement_text",
                    "author",
                    "approval",
                    "replacement_verified",
                }
                or proposal["approval"] != "unapproved"
                or proposal["replacement_verified"] is not False
                or proposal["author"] != entry.get("judge")
            ):
                raise ValueError("malformed stored correction proposal")
            _validated_correction(
                {
                    name: proposal[name]
                    for name in ("action", "rationale", "replacement_text")
                },
                entry["verdict"],
                entry.get("occurrence_id"),
                entry.get("judge"),
                sum(quote["found"] for quote in quotes),
            )
    decompositions = ledger.get("decompositions", {})
    if not isinstance(decompositions, dict):
        raise ValueError("decompositions must be an object")
    for registration in decompositions.values():
        if (
            not isinstance(registration, dict)
            or not {
                "sentence_id",
                "tex_path",
                "atoms",
                "decomposition_id",
                "file",
                "claim",
            }
            <= set(registration)
            or not isinstance(registration["atoms"], list)
        ):
            raise ValueError("malformed atomic registration")
        if any(
            not isinstance(registration[name], str)
            for name in (
                "sentence_id",
                "tex_path",
                "decomposition_id",
                "file",
                "claim",
            )
        ):
            raise ValueError(
                "atomic registration identity fields must be strings"
            )
        for atom in registration["atoms"]:
            if (
                not isinstance(atom, dict)
                or not {
                    "atom_id",
                    "text",
                    "kind",
                    "citation_ids",
                }
                <= set(atom)
                or not isinstance(atom["citation_ids"], list)
            ):
                raise ValueError("malformed registered atom")
            if (
                any(
                    not isinstance(atom[name], str)
                    for name in ("atom_id", "text", "kind")
                )
                or any(
                    not isinstance(value, str) for value in atom["citation_ids"]
                )
                or (
                    atom["kind"] == "uncited"
                    and not isinstance(atom.get("reason"), str)
                )
            ):
                raise ValueError("malformed registered atom fields")
    return ledger


def _adequate_support_basis(entry: dict[str, Any], verified_id: str | None) -> bool:
    """Accept full text or the primary record of a verified GitHub work."""
    return entry["basis"] == "fulltext" or (
        entry["basis"] == "readme"
        and isinstance(verified_id, str)
        and verified_id.startswith("github:")
        and entry["id"] == verified_id
    )


def _audit_markdown(rep: dict[str, Any], ver: dict[str, Any], coverage: dict[str, Any]) -> str:
    label = (
        "SUBMISSION READY"
        if rep["submission_ready"]
        else "EXPLORATORY PROGRESS"
        if rep["ok"]
        else "NEEDS ATTENTION"
    )
    lines = [
        f"# cite-check audit — {label}",
        "",
        f"- policy: `{rep['policy']}`",
        f"- input complete: {rep['input_complete']}; "
        f"assessment complete: {rep['complete']}",
        f"- submission ready: {rep['submission_ready']}",
        f"- manuscript: `{rep['tex']}`",
        f"- bib: {', '.join('`%s`' % b for b in rep['bibs']) or '(none)'}",
        f"- citation instances: {rep['n_instances']} over {rep['n_keys']} keys",
        f"- existence: {rep['existence_counts']}",
        f"- support: {rep['support_counts']} "
        f"(missing: {rep['support_missing']})",
        f"- checked: {rep['checked']}",
        "",
    ]
    lines += [
        "## Coverage",
        "",
        "| axis | assessed / expected | outcomes |",
        "|---|---|---|",
    ]
    for name, axis in rep["coverage"].items():
        lines.append(
            f"| {name} | {axis['assessed']} / {axis['expected']} | "
            f"{axis['counts']} |"
        )
    lines += [
        "",
        "Assessment includes negative and inaccessible outcomes; "
        "it is not a readiness claim. Provenance is declared, not "
        "digest-verified.",
        "",
    ]
    for title, items in (
        ("Failures", rep["failures"]),
        ("Warnings", rep["warnings"]),
    ):
        lines += [f"## {title} ({len(items)})", ""]
        for it in items:
            where = (
                f" ({os.path.basename(it['file'])}:{it.get('line', '—')})"
                if it.get("file")
                else ""
            )
            lines.append(
                f"- **{it['type']}** `{it.get('key', '')}`{where}: "
                f"{it.get('status') or it.get('verdict') or ''} "
                f"{it.get('detail') or ''}".rstrip()
            )
            if it.get("claim"):
                lines.append(f"  > {it['claim']}")
            if it.get("atom"):
                lines.append(f"  Atom `{it['atom_id']}`: {it['atom']}")
        lines.append("")
    lines += [
        "## Per key",
        "",
        "| key | existence | id | support verdicts |",
        "|---|---|---|---|",
    ]
    for key in sorted(coverage):
        v = ver.get(key, {})
        lines.append(
            f"| `{key}` | {v.get('status', '—')} | "
            f"{v.get('id', '')} | {coverage[key]} |"
        )
    return "\n".join(lines) + "\n"


def audit(
    tex_path: str,
    bib_path: str | None = None,
    require_support: bool = True,
    verify: bool = True,
    policy: Literal["exploratory", "submission-ready"] = "submission-ready",
) -> dict[str, Any]:
    """Audit citation integrity under an explicit completion policy.

    Args:
        tex_path: Main manuscript, including input/include files.
        bib_path: Optional bibliography override.
        require_support: Fail on missing judgments, also in exploratory mode.
            False never weakens submission-ready requirements.
        verify: Run registry verification. False leaves existence unchecked
            and cannot pass the submission-ready policy.
        policy: Exploratory progress or the default submission-ready gate.

    Returns:
        Separate coverage axes and input/assessment completeness. Complete
        means assessed, including negative or inaccessible outcomes; only
        submission_ready certifies the strict policy. Writes audit reports.
    """
    if policy not in _AUDIT_POLICIES:
        return _incomplete_audit(str(policy), "unknown audit policy")
    strict = policy == "submission-ready"
    ex = extract_cites(tex_path)
    if ex.get("error"):
        return _incomplete_audit(policy, ex["error"])
    workdir = os.path.dirname(os.path.abspath(tex_path))
    expected_bibs = list(
        dict.fromkeys(
            [
                os.path.abspath(b)
                for b in ([bib_path] if bib_path else ex["bib_files"])
                if b
            ]
        )
    )
    bibs = [path for path in expected_bibs if os.path.isfile(path)]
    failures: list[dict[str, Any]] = [
        {"type": "missing-bib", "detail": path}
        for path in expected_bibs
        if path not in bibs
    ]
    failures.extend(
        {
            "type": item["code"],
            "detail": item["message"],
            **{
                key: value
                for key, value in item.items()
                if key not in {"code", "message"}
            },
        }
        for item in ex.get("diagnostics", [])
    )
    inline_keys = {
        item["key"]
        for item in ex.get("inline_bibliography", [])
        if item.get("key")
    }
    if any(item.get("key") is None
           for item in ex.get("inline_bibliography", [])):
        inline_keys.update(ex["keys"])
    warnings: list[dict[str, Any]] = []
    if not bibs and (expected_bibs or ex["cites"]):
        failures.append(
            {
                "type": "no-bib",
                "detail": (
                    "no readable .bib — pass bib_path or "
                    "declare \\bibliography{…}"
                ),
            }
        )
    entries: dict[str, tuple[str, dict[str, Any]]] = {}
    bibliography_locations: dict[str, list[dict[str, Any]]] = {}
    bib_snapshots = dict.fromkeys(expected_bibs)
    for b in bibs:
        try:
            with open(b, "rb") as fh:
                raw = fh.read()
            bib_snapshots[b] = hashlib.sha256(raw).hexdigest()
            bib_text = raw.decode("utf-8")
            parsed = _parse_bib(bib_text)
        except (OSError, UnicodeError) as exc:
            failures.append({"type": "unreadable-bib", "detail": str(exc)})
            continue
        for error in parsed["errors"]:
            failures.append({"type": "bib-parse", "detail": f"{b}: {error}"})
        for entry in parsed["entries"]:
            bibliography_locations.setdefault(entry["key"], []).append(
                {
                    "file": b,
                    "line": bib_text.count("\n", 0, entry["start"]) + 1,
                    "kind": "bibliography-entry",
                    "start": entry["start"],
                    "end": entry["end"],
                    "offset_unit": "unicode-codepoint",
                    "source_byte_start": len(
                        bib_text[: entry["start"]].encode("utf-8")
                    ),
                    "source_byte_end": len(
                        bib_text[: entry["end"]].encode("utf-8")
                    ),
                }
            )
            if entry["key"] in entries:
                failures.append(
                    {
                        "type": "duplicate-key",
                        "key": entry["key"],
                        "detail": "key appears in multiple entries",
                    }
                )
            entries.setdefault(entry["key"], (b, entry))
    cite_keys = set(ex["keys"])
    nocite_all = any(c["key"] == "*" for c in ex["cites"])
    if nocite_all:
        cite_keys.update(entries)
    for k in sorted(cite_keys - set(entries) - inline_keys):
        failures.append(
            {
                "type": "undefined-cite",
                "key": k,
                "detail": "cited in the .tex but in no .bib",
            }
        )
    if not nocite_all:
        for k in sorted(set(entries) - cite_keys):
            warnings.append(
                {
                    "type": "uncited-entry",
                    "key": k,
                    "detail": "in the .bib but never cited",
                }
            )
    ver = {}
    bibliography_observation_conflict = False
    if verify:
        for bib in bibs:
            keys_here = [
                key
                for key, (path, _) in entries.items()
                if path == bib and key in cite_keys
            ]
            if not keys_here:
                continue
            if _audit_file_digest(bib) != bib_snapshots[bib]:
                bibliography_observation_conflict = True
            result = verify_bib(bib, keys=keys_here, tex_path=tex_path)
            if _audit_file_digest(bib) != bib_snapshots[bib]:
                bibliography_observation_conflict = True
            if not isinstance(result, dict) or result.get("error"):
                failures.append(
                    {
                        "type": "verify-error",
                        "detail": (
                            result.get("error")
                            if isinstance(result, dict)
                            else "malformed verifier response"
                        ),
                    }
                )
                continue
            rows = result.get("entries", [])
            if not isinstance(rows, list):
                rows = []
            for entry in rows:
                if (
                    isinstance(entry, dict)
                    and isinstance(entry.get("key"), str)
                    and entry["key"] in keys_here
                ):
                    if not isinstance(entry.get("ids", {}), dict):
                        entry = dict(entry, status="UNRESOLVED", ids={})
                    ver[entry["key"]] = entry
    for key in inline_keys:
        ver[key] = {
            "key": key,
            "status": "UNCHECKED",
            "notes": [
                "Printed inline reference has no verified official provenance"
            ],
        }
        bibliography_locations.setdefault(key, []).extend(
            item for item in ex["inline_bibliography"] if item["key"] == key
        )
    unofficial, provenance_states = [], []
    for key in sorted(cite_keys):
        parsed_entry = entries.get(key, (None, {}))[1]
        provenance_state = (
            "UNOFFICIAL"
            if key in inline_keys
            else _declared_provenance(parsed_entry, ver.get(key, {}))
        )
        if provenance_state != "DECLARED":
            unofficial.append(key)
        provenance_states.append(provenance_state)
        if provenance_state != "DECLARED":
            (
                failures
                if strict or provenance_state == "MISMATCH"
                else warnings
            ).append(
                {
                    "type": "provenance",
                    "key": key,
                    "status": provenance_state,
                    "detail": "no declared official-export provenance",
                }
            )
        result = ver.setdefault(
            key,
            {
                "key": key,
                "status": (
                    "UNDEFINED"
                    if not parsed_entry
                    else "UNRESOLVED"
                    if verify
                    else "UNCHECKED"
                ),
            },
        )
        status = result.get("status", "UNRESOLVED")
        if not isinstance(status, str) or status not in {
            "VERIFIED",
            "FOUND",
            "PROBABLE",
            "MISMATCH",
            "NOT_FOUND",
            "UNRESOLVED",
            "UNCHECKED",
            "UNDEFINED",
        }:
            status = "UNRESOLVED"
        if status == "VERIFIED" and (
            not isinstance(result.get("id"), str) or not result["id"].strip()
        ):
            status = "UNRESOLVED"
        result["status"] = status
        if status != "VERIFIED":
            blocking = strict or status in {
                "MISMATCH",
                "NOT_FOUND",
                "UNRESOLVED",
                "UNDEFINED",
            }
            (failures if blocking else warnings).append(
                {
                    "type": "existence",
                    "key": key,
                    "status": status,
                    "detail": "; ".join(result.get("notes") or []),
                }
            )
    if strict and (not verify or not require_support):
        failures.append(
            {
                "type": "policy-configuration",
                "detail": (
                    "submission-ready requires verify=true and "
                    "require_support=true; use exploratory for partial work"
                ),
            }
        )
    try:
        with _file_lock(_project_path(workdir, "ledger.json")):
            ledger_state = _audit_ledger(workdir)
            ledger_digest = _audit_file_digest(
                _project_path(workdir, "ledger.json")
            )
    except (OSError, ValueError) as error:
        return _incomplete_audit(policy, f"cannot audit ledger: {error}")
    ledger = ledger_state["entries"]
    verdicts: Counter[str] = Counter()
    coverage: dict[str, str] = {}
    missing: list[dict[str, Any]] = []
    support_states, support_bases = [], []
    supported_adequately = 0
    current_judgments = {}
    source_snapshots: dict[str, dict[str, Any] | None] = {}
    source_observation_conflict = False
    legacy_counts = Counter(
        (cite["key"], _claim_hash(cite["claim"]))
        for cite in ex["cites"]
        if not cite["nocite"]
    )
    requirements = _support_requirements(ex, ledger_state)
    uncited_atoms = []
    for sentence in ex["sentences"]:
        registration = _find_decomposition(sentence, ledger_state)
        if (
            not registration
            or registration["sentence_id"] != sentence["sentence_id"]
        ):
            continue
        for atom in registration["atoms"]:
            if atom["kind"] == "uncited":
                scope = {
                    "sentence_id": sentence["sentence_id"],
                    "file": sentence["file"],
                    "claim": sentence["claim"],
                    "atom_id": atom["atom_id"],
                    "atom": atom["text"],
                    "reason": atom["reason"],
                    "verified": False,
                }
                uncited_atoms.append(scope)
                warnings.append(
                    dict(
                        scope,
                        type="uncited-atom",
                        detail=(
                            "declared uncited scope; not verified: "
                            + atom["reason"]
                        ),
                    )
                )
    for c in requirements:
        loc = {
            "key": c["key"],
            "file": c["file"],
            "line": c["line"],
            "claim": c["claim"][:240],
            "occurrence_id": c["occurrence_id"],
        }
        if c.get("atom_id"):
            loc.update(atom_id=c["atom_id"], atom=c["atom"]["text"])
        if c.get("decomposition_stale"):
            support_states.append("DECOMPOSITION_STALE")
            failures.append(
                dict(
                    loc,
                    type="decomposition-stale",
                    detail=(
                        "atomic mode requires a current sentence registration; "
                        "register claims and re-judge"
                    ),
                )
            )
            coverage[c["key"]] = coverage.get(c["key"], "") + " STALE"
            continue
        judgment = ledger.get(_support_id(c["occurrence_id"], c.get("atom_id")))
        if (
            judgment is None
            and not c.get("atom_id")
            and legacy_counts[(c["key"], _claim_hash(c["claim"]))] == 1
        ):
            legacy = ledger.get(f"{c['key']}|{_claim_hash(c['claim'])}")
            # A legacy judgment is safe only when it maps to one occurrence
            # and any supplied historical source location still matches.
            if (
                legacy
                and (legacy.get("file") in (None, c["file"]))
                and (legacy.get("line") in (None, c["line"]))
            ):
                judgment = legacy
        if not judgment:
            support_states.append("MISSING")
            missing.append(c)
            coverage[c["key"]] = coverage.get(c["key"], "") + " MISSING"
            continue
        vid = (ver.get(c["key"]) or {}).get("id")
        if vid and judgment["id"] != vid:
            support_states.append("STALE")
            failures.append(
                dict(
                    loc,
                    type="support-stale",
                    verdict=judgment["verdict"],
                    detail=(
                        f"verdict was judged against {judgment['id']} "
                        f"but entry resolves to {vid} — re-judge"
                    ),
                )
            )
            coverage[c["key"]] = coverage.get(c["key"], "") + " STALE"
            continue
        source_cache_id = judgment.get("source_cache_id", judgment["id"])
        current_source = _current_source_identity(source_cache_id)
        if (
            source_cache_id in source_snapshots
            and source_snapshots[source_cache_id] != current_source
        ):
            source_observation_conflict = True
        source_snapshots.setdefault(source_cache_id, current_source)
        entry = entries.get(c["key"], (None, {}))[1]
        expected_ref = _entry_ref(entry) if entry else None
        expected_version = ((ver.get(c["key"]) or {}).get("ref") or {}).get(
            "sha"
        )
        source_version = (judgment.get("source_identity") or {}).get("version")
        if expected_ref and not expected_version:
            expected_version = expected_ref
        arxiv_version = _entry_arxiv_version(entry) if entry else None
        if arxiv_version:
            expected_version = arxiv_version
        if (
            judgment.get("decomposition_id") != c.get("decomposition_id")
            or (c.get("atom_id") and judgment.get("atom") != c["atom"])
            or not judgment.get("source_identity")
            or (expected_version and source_version != expected_version)
            or judgment["source_identity"] != current_source
            or judgment.get("context_hash") != _claim_hash(c["context"])
        ):
            support_states.append("STALE")
            failures.append(
                dict(
                    loc,
                    type="support-stale",
                    verdict=judgment["verdict"],
                    detail=(
                        "source, context or evidence policy changed; re-judge"
                    ),
                )
            )
            coverage[c["key"]] = coverage.get(c["key"], "") + " STALE"
            continue
        if judgment.get("verdict") not in _VERDICTS:
            support_states.append("INVALID")
            failures.append(dict(loc, type="support-invalid"))
            continue
        current_judgments[_support_id(c["occurrence_id"], c.get("atom_id"))] = (
            judgment
        )
        verdict = judgment["verdict"]
        support_states.append(
            "INACCESSIBLE" if verdict == "UNVERIFIABLE" else verdict
        )
        support_bases.append(judgment["basis"])
        verdicts[verdict] += 1
        adequate = _adequate_support_basis(
            judgment,
            vid if ver.get(c["key"], {}).get("status") == "VERIFIED" else None,
        )
        supported_adequately += verdict == "SUPPORTS" and adequate
        coverage[c["key"]] = (
            coverage.get(c["key"], "") + f" {verdict}({judgment['basis']})"
        )
        if verdict in ("UNSUPPORTED", "CONTRADICTS"):
            failures.append(
                dict(
                    loc,
                    type="support",
                    verdict=verdict,
                    detail=judgment.get("note"),
                )
            )
        elif verdict in ("PARTIAL", "UNVERIFIABLE"):
            (failures if strict else warnings).append(
                dict(
                    loc,
                    type="support",
                    verdict=verdict,
                    detail=judgment.get("note"),
                )
            )
        elif not adequate:
            (failures if strict else warnings).append(
                dict(
                    loc,
                    type="support-basis",
                    verdict=verdict,
                    detail=(
                        f"limited evidence basis: {judgment['basis']}; "
                        "obtain full text or a verified repository's record"
                    ),
                )
            )
    for c in missing:
        (failures if strict or require_support else warnings).append(
            {
                "type": "support-missing",
                "key": c["key"],
                "file": c["file"],
                "line": c["line"],
                "claim": c["claim"][:240],
                "occurrence_id": c["occurrence_id"],
                "atom_id": c.get("atom_id"),
                "atom": (c.get("atom") or {}).get("text"),
                "detail": (
                    "no support verdict recorded for this atom/occurrence"
                ),
            }
        )
    for k in cite_keys:
        coverage.setdefault(k, "")
    input_complete = (
        ex.get("scope_complete", True)
        and not ex.get("review_only", False)
        and not any(
            item["type"]
            in {
                "missing-bib",
                "unreadable-bib",
                "no-bib",
                "bib-parse",
                "duplicate-key",
                "undefined-cite",
            }
            for item in failures
        )
    )
    existence_axis = _coverage_axis(
        [result["status"] for result in ver.values()],
        {"UNCHECKED", "UNRESOLVED", "UNDEFINED"},
        {"VERIFIED"},
    )
    provenance_axis = _coverage_axis(
        provenance_states,
        {"UNDEFINED"},
        {"DECLARED"},
    )
    provenance_axis["declared"] = provenance_axis.pop("verified")
    provenance_axis["declaration_rate"] = provenance_axis.pop(
        "verification_rate"
    )
    provenance_axis["assurance"] = "declaration-only; export digest not checked"
    support_axis = _coverage_axis(
        support_states,
        {"MISSING", "STALE", "DECOMPOSITION_STALE", "INVALID"},
        set(),
    )
    support_axis["verified"] = supported_adequately
    support_axis["verification_rate"] = (
        supported_adequately / len(requirements) if requirements else None
    )
    support_axis["basis_counts"] = dict(Counter(support_bases))
    support_axis["unresolved_decompositions"] = sum(
        bool(item.get("decomposition_stale")) for item in requirements
    )
    support_axis["atomic_total_known"] = not support_axis[
        "unresolved_decompositions"
    ]
    support_axis["unit"] = (
        "current atom/occurrence judgments, or unresolved occurrence "
        "placeholders where decomposition is stale"
    )
    axes = {
        "existence": existence_axis,
        "provenance": provenance_axis,
        "support": support_axis,
    }
    if not ex.get("scope_complete", True):
        for axis in axes.values():
            axis["observed_expected"] = axis["expected"]
            axis["expected"] = None
            axis["complete"] = False
            for name in (
                "assessment_rate", "verification_rate", "declaration_rate"
            ):
                if name in axis:
                    axis[name] = None
        support_axis["atomic_total_known"] = False
    complete = input_complete and all(
        axis["complete"] for axis in axes.values()
    )
    report = {
        "ok": not failures,
        "complete": complete,
        "input_complete": input_complete,
        "policy": policy,
        "submission_ready": strict and not failures and complete,
        "coverage": axes,
        "tex": os.path.abspath(tex_path),
        "bibs": bibs,
        "n_instances": ex["n_instances"],
        "n_keys": len(cite_keys),
        "existence_counts": dict(Counter(r["status"] for r in ver.values())),
        "support_counts": dict(verdicts),
        "support_missing": len(missing),
        "n_support_requirements": len(requirements),
        "n_atomic_requirements": sum("atom_id" in c for c in requirements),
        "n_uncited_atoms": len(uncited_atoms),
        "uncited_atoms": uncited_atoms,
        "unofficial_entries": sorted(unofficial),
        "failures": failures,
        "warnings": warnings,
        "checked": _now_iso(),
    }
    report.update(
        {
            name: ex.get(name)
            for name in (
                "input_format",
                "scope_complete",
                "review_only",
                "diagnostics",
                "inline_bibliography",
                "extraction_metadata",
                "source_texts",
            )
        }
    )
    report["bibliography_locations"] = bibliography_locations
    report["corrections"] = _correction_items(
        report, ex, current_judgments, ver
    )
    report["source_files"] = list(dict.fromkeys(ex["files"] + bibs))
    report["snapshot"] = {
        "files": {**ex["source_digests"], **bib_snapshots},
        "ledger": ledger_digest,
        "sources": source_snapshots,
        "input_backend": ex.get("extraction_metadata", {}).get("extractor")
        if ex.get("input_format") == "pdf"
        else None,
    }
    coverage = {k: v.strip() or "—" for k, v in coverage.items()}
    with _file_lock(_project_path(workdir, "ledger.json")):
        ledger_changed = (
            _audit_file_digest(_project_path(workdir, "ledger.json"))
            != ledger_digest
        )
        manuscript_changed = _atomic_digest(
            extract_cites(tex_path)
        ) != _atomic_digest(ex)
        bibliography_changed = bibliography_observation_conflict or any(
            _audit_file_digest(path) != digest
            for path, digest in bib_snapshots.items()
        )
        sources_changed = source_observation_conflict or any(
            _current_source_identity(identifier) != snapshot
            for identifier, snapshot in source_snapshots.items()
        )
        if (
            ledger_changed
            or manuscript_changed
            or bibliography_changed
            or sources_changed
        ):
            failures.append(
                {
                    "type": "audit-stale",
                    "detail": (
                        "manuscript, bibliography, ledger or source "
                        "changed during audit; "
                        "rerun audit"
                    ),
                }
            )
            report["ok"] = False
            report["complete"] = False
            report["submission_ready"] = False
            _invalidate_corrections(report)
        md_path = _project_path(workdir, "audit.md")
        _atomic_write(md_path, _audit_markdown(report, ver, coverage))
        report["report"] = md_path
        _write_project(workdir, "audit.json", report)
    report["summary"] = (
        f"{policy}: ready={report['submission_ready']}; "
        f"{len(failures)} failure(s), {len(warnings)} warning(s); "
        f"{ex['n_instances']} citation instances, "
        f"{len(missing)} without a support verdict; "
        f"existence {report['existence_counts']}"
    )
    return report


def _job_priorities(
    values: list[Any] | None, requirements: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Validate scheduling advice against current occurrence/atom pairs."""
    if values is None:
        return []
    if not isinstance(values, list):
        raise ValueError("priorities must be a list")
    targets = {
        (item["occurrence_id"], item.get("atom_id")) for item in requirements
    }
    seen = set()
    result = []
    for raw in values:
        value = (
            dataclasses.asdict(raw) if isinstance(raw, ClaimPriority) else raw
        )
        if (
            not isinstance(value, dict)
            or not {"occurrence_id", "reason"} <= set(value)
            or set(value) - {"occurrence_id", "atom_id", "priority", "reason"}
        ):
            raise ValueError("priority needs a current occurrence and reason")
        value = dict(value)
        value.setdefault("atom_id", None)
        value.setdefault("priority", "high")
        occurrence, atom = value["occurrence_id"], value["atom_id"]
        if not isinstance(occurrence, str) or (
            atom is not None and not isinstance(atom, str)
        ):
            raise ValueError("priority target IDs must be strings")
        target = (occurrence, atom)
        if target not in targets or target in seen:
            raise ValueError(
                "priority target is missing, stale, ambiguous or duplicated"
            )
        if (
            value["priority"] not in ("high", "normal", "low")
            or not isinstance(value["reason"], str)
            or len(value["reason"].strip()) < 8
        ):
            raise ValueError(
                "priority must be high/normal/low with a meaningful reason"
            )
        seen.add(target)
        result.append(value)
    return sorted(
        result,
        key=lambda item: (item["occurrence_id"], item["atom_id"] or ""),
    )


def _job_scan(
    tex_path: str,
    bib_path: str | None,
    priorities: list[Any] | None,
    search_unresolved: bool,
) -> dict[str, Any]:
    """Build identity and support obligations from exact snapshots."""
    extracted = extract_cites(tex_path)
    if not extracted.get("complete"):
        raise ValueError(
            extracted.get("error", "incomplete manuscript extraction")
        )
    bibs = [os.path.abspath(bib_path)] if bib_path else extracted["bib_files"]
    if not bibs and extracted["keys"]:
        raise ValueError("no bibliography; declare it or provide bib_path")
    with _file_lock(_project_path(os.path.dirname(tex_path), "ledger.json")):
        ledger = _audit_ledger(os.path.dirname(tex_path))
        ledger_digest = _audit_file_digest(
            _project_path(os.path.dirname(tex_path), "ledger.json")
        )
    files = dict(extracted["source_digests"])
    entries: dict[str, tuple[str, dict[str, Any]]] = {}
    for path in bibs:
        with open(path, "rb") as source:
            raw = source.read()
        files[path] = hashlib.sha256(raw).hexdigest()
        parsed = _parse_bib(raw.decode("utf-8"))
        if not parsed["complete"]:
            raise ValueError(
                "incomplete bibliography: " + "; ".join(parsed["errors"])
            )
        for entry in parsed["entries"]:
            if entry["key"] in entries:
                raise ValueError("duplicate bibliography key: " + entry["key"])
            entries[entry["key"]] = (path, entry)
    requirements = _support_requirements(extracted, ledger)
    validated_priorities = _job_priorities(priorities, requirements)
    assigned = {
        (item["occurrence_id"], item["atom_id"]): item
        for item in validated_priorities
    }
    ranks = {"high": 0, "normal": 1, "low": 2}
    support = []
    for required in requirements:
        target = (required["occurrence_id"], required.get("atom_id"))
        priority = assigned.get(
            target,
            {
                "priority": "normal",
                "reason": "Default scheduling order; no "
                "consequence assessment.",
            },
        )
        support.append(
            {
                "id": _atomic_digest(["support", *target]),
                "key": required["key"],
                "occurrence_id": target[0],
                "atom_id": target[1],
                "sentence_id": required["sentence_id"],
                "file": required["file"],
                "line": required["line"],
                "page": required.get("page"),
                "page_line": required.get("page_line"),
                "source_offset_unit": required.get("source_offset_unit"),
                "claim": required["claim"],
                "context": required["context"],
                "assertion": required.get("atom", {}).get(
                    "text", required["claim"]
                ),
                "decomposition_stale": bool(
                    required.get("decomposition_stale")
                ),
                "priority": priority["priority"],
                "priority_reason": priority["reason"],
                "priority_source": "caller"
                if target in assigned
                else "default",
                "status": "UNCHECKED",
                "assessment_scope": "not assessed by this registry-only job",
                "next_action": "Use the current strict audit to inspect "
                "existing judgments. Retrieve the "
                "correct source/version and obtain any "
                "missing independent atom/occurrence "
                "judgment; register stale decompositions "
                "first.",
            }
        )
    support.sort(
        key=lambda item: (
            ranks[item["priority"]],
            item["file"],
            item["line"],
            item["id"],
        )
    )
    keys = set(extracted["keys"]) - {"*"}
    if any(item["key"] == "*" for item in extracted["cites"]):
        keys.update(entries)
    identity = []
    printed_keys = {
        item.get("key") for item in extracted.get("inline_bibliography", [])
    }
    for key in sorted(keys):
        path, entry = entries.get(key, (None, {}))
        if key in printed_keys or None in printed_keys:
            path = None
        related = [item for item in support if item["key"] == key]
        identity_priority = min(
            (item["priority"] for item in related),
            key=lambda value: ranks[value],
            default="normal",
        )
        identity.append(
            {
                "id": _atomic_digest(["identity", path, key, entry.get("raw")]),
                "key": key,
                "bib_path": path,
                "priority": identity_priority,
                "support_ids": [item["id"] for item in related],
                "occurrence_ids": [
                    item["occurrence_id"]
                    for item in extracted["cites"]
                    if item["key"] == key
                ],
                "status": "UNCHECKED",
                "result": None,
                "attempts": 0,
                "reason": "not attempted"
                if path
                else "undefined citation key; repair bibliography",
            }
        )
    identity.sort(key=lambda item: (ranks[item["priority"]], item["key"]))
    sources = {}
    for judgment in ledger["entries"].values():
        identifier = judgment.get("source_cache_id", judgment["id"])
        sources[identifier] = _current_source_identity(identifier)
    snapshot = {
        "files": files,
        "ledger": ledger_digest,
        "sources": sources,
        "input_backend": extracted.get("extraction_metadata", {}).get(
            "extractor"
        )
        if extracted.get("input_format") == "pdf"
        else None,
    }
    if not _correction_snapshot_current(snapshot, os.path.dirname(tex_path)):
        raise ValueError("inputs changed while scanning; rescan")
    return {
        "config": {
            "tex_path": tex_path,
            "bib_path": os.path.abspath(bib_path) if bib_path else None,
            "priorities": validated_priorities,
            "search_unresolved": search_unresolved,
            "tool_version": VERSION,
            "job_policy": _JOB_POLICY,
            "pricing_policy": _PRICING_POLICY,
        },
        "snapshot": snapshot,
        "identity_queue": identity,
        "support_queue": support,
        "input_scope": {
            name: extracted.get(name)
            for name in (
                "input_format",
                "scope_complete",
                "review_only",
                "diagnostics",
            )
        },
        "uncited_scope": [
            dict(atom, verified=False)
            for registration in ledger.get("decompositions", {}).values()
            if registration.get("tex_path") == tex_path
            and registration["sentence_id"]
            in {item["sentence_id"] for item in extracted["sentences"]}
            for atom in registration["atoms"]
            if atom["kind"] == "uncited"
        ],
    }


def _job_write(path: str, job: dict[str, Any]) -> None:
    """Atomically save state with a corruption-detection checksum."""
    job["updated"] = _now_iso()
    payload = dict(job)
    payload["integrity"] = _atomic_digest(job)
    _atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2))


def _job_valid_result(result: Any, key: str) -> bool:
    """Validate live and persisted registry outcomes before crediting work."""
    if not isinstance(result, dict) or result.get("key") != key:
        return False
    status = result.get("status")
    if status not in (
        "VERIFIED",
        "FOUND",
        "PROBABLE",
        "MISMATCH",
        "NOT_FOUND",
        "UNRESOLVED",
    ):
        return False
    if status in ("VERIFIED", "FOUND", "PROBABLE", "MISMATCH"):
        identifier = result.get("id")
        if (
            not isinstance(identifier, str)
            or _classify(identifier)[0] == "unknown"
        ):
            return False
    if "ids" in result and (
        not isinstance(result["ids"], dict)
        or any(not isinstance(value, str) for value in result["ids"].values())
    ):
        return False
    if "notes" in result and (
        not isinstance(result["notes"], list)
        or any(not isinstance(value, str) for value in result["notes"])
    ):
        return False
    return True


def _job_load(path: str, identifier: str) -> dict[str, Any]:
    """Reject corrupt job metadata, progress states and accounting."""
    with open(path, encoding="utf-8") as source:
        job = json.load(source)
    if not isinstance(job, dict):
        raise ValueError("job state must be an object")
    integrity = job.pop("integrity", None)
    if integrity != _atomic_digest(job):
        raise ValueError("job state checksum mismatch")
    if (
        set(job)
        != {
            "schema_version",
            "job_id",
            "created",
            "updated",
            "config",
            "snapshot",
            "identity_queue",
            "support_queue",
            "uncited_scope",
            "input_scope",
            "runs",
        }
        or type(job["schema_version"]) is not int
        or job["schema_version"] != 1
        or job["job_id"] != identifier
    ):
        raise ValueError("unsupported or malformed job state")
    if not isinstance(job["config"], dict) or set(job["config"]) != {
        "tex_path",
        "bib_path",
        "priorities",
        "search_unresolved",
        "tool_version",
        "job_policy",
        "pricing_policy",
    }:
        raise ValueError("invalid job configuration")
    config = job["config"]
    if (
        not isinstance(config["tex_path"], str)
        or (
            config["bib_path"] is not None
            and not isinstance(config["bib_path"], str)
        )
        or not isinstance(config["priorities"], list)
        or type(config["search_unresolved"]) is not bool
    ):
        raise ValueError("invalid job configuration values")
    if not isinstance(job["runs"], list) or not isinstance(
        job["identity_queue"], list
    ):
        raise ValueError("invalid job progress containers")
    identity_fields = {
        "id",
        "key",
        "bib_path",
        "priority",
        "support_ids",
        "occurrence_ids",
        "status",
        "result",
        "attempts",
        "reason",
    }
    for item in job["identity_queue"]:
        if (
            not isinstance(item, dict)
            or set(item) != identity_fields
            or not isinstance(item["key"], str)
            or not item["key"]
            or not isinstance(item["id"], str)
            or re.fullmatch(r"[a-f0-9]{64}", item["id"]) is None
            or (
                item["bib_path"] is not None
                and not isinstance(item["bib_path"], str)
            )
            or item["priority"] not in ("high", "normal", "low")
            or any(
                not isinstance(item[name], list)
                or any(not isinstance(value, str) for value in item[name])
                for name in ("support_ids", "occurrence_ids")
            )
        ):
            raise ValueError("malformed identity queue entry")
        if (
            not isinstance(item, dict)
            or item.get("status") not in ("UNCHECKED", "RUNNING", "ASSESSED")
            or type(item.get("attempts")) is not int
            or item["attempts"] < 0
            or not isinstance(item.get("reason"), str)
        ):
            raise ValueError("invalid identity progress")
        result = item.get("result")
        if result is not None and not _job_valid_result(result, item["key"]):
            raise ValueError("invalid identity result")
        if item["status"] == "ASSESSED" and (
            result is None or result["status"] == "UNRESOLVED"
        ):
            raise ValueError("incomplete result marked assessed")
    for run in job["runs"]:
        if (
            not isinstance(run, dict)
            or set(run) != {"run_id", "limits", "usage", "state"}
            or run["state"]
            not in ("RUNNING", "FINISHED", "PAUSED", "INTERRUPTED")
        ):
            raise ValueError("invalid job run")
        if not isinstance(run["limits"], dict) or set(run["limits"]) != set(
            dataclasses.asdict(VerificationBudget())
        ):
            raise ValueError("incomplete saved budget limits")
        limits = _validated_budget(run["limits"])
        usage = run["usage"]
        usage_fields = {
            "requests",
            "searches",
            "http_cache_hits",
            "elapsed_seconds",
            "unknown_price_requests",
            "estimated_service_cost_usd",
            "actual_billed_cost_usd",
            "model_tokens",
            "model_calls",
            "external_model_cost_usd",
            "deadline_exceeded",
            "deadline_overshoot_seconds",
            "stop_reason",
        }
        if not isinstance(usage, dict) or set(usage) != usage_fields:
            raise ValueError("invalid usage accounting")
        for name in (
            "requests",
            "searches",
            "http_cache_hits",
            "unknown_price_requests",
            "model_calls",
        ):
            if type(usage.get(name)) is not int or usage[name] < 0:
                raise ValueError("invalid usage counter")
        for name in ("elapsed_seconds", "deadline_overshoot_seconds"):
            if (
                type(usage.get(name)) not in (int, float)
                or not math.isfinite(usage[name])
                or usage[name] < 0
            ):
                raise ValueError("invalid elapsed-time accounting")
        if (
            usage["requests"] > limits["max_requests"]
            or usage["searches"] > limits["max_searches"]
            or usage["unknown_price_requests"] > usage["requests"]
            or usage["model_calls"] != 0
            or usage.get("actual_billed_cost_usd") is not None
            or usage.get("model_tokens") is not None
            or usage.get("external_model_cost_usd") is not None
        ):
            raise ValueError("invalid budget accounting")
        elapsed = usage["elapsed_seconds"]
        if (
            type(usage.get("deadline_exceeded")) is not bool
            or usage["deadline_exceeded"] != (elapsed > limits["max_seconds"])
            or usage["deadline_overshoot_seconds"]
            != max(0.0, elapsed - limits["max_seconds"])
            or (
                usage.get("stop_reason") is not None
                and not isinstance(usage["stop_reason"], str)
            )
        ):
            raise ValueError("invalid deadline accounting")
        expected_cost = None if usage["unknown_price_requests"] else 0.0
        if (
            usage.get("estimated_service_cost_usd") != expected_cost
            or (
                expected_cost is not None
                and type(usage["estimated_service_cost_usd"])
                not in (int, float)
            )
            or (
                limits["max_cost_usd"] is not None
                and usage["unknown_price_requests"]
            )
        ):
            raise ValueError("invalid cost accounting")
    return job


def _job_same_scan(job: dict[str, Any], scan: dict[str, Any]) -> bool:
    """Compare immutable queue/config data separately from recorded progress."""
    mutable = {"status", "result", "attempts", "reason"}

    def identity(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {key: value for key, value in item.items() if key not in mutable}
            for item in items
        ]

    return all(
        job[name] == scan[name]
        for name in (
            "config",
            "snapshot",
            "support_queue",
            "uncited_scope",
            "input_scope",
        )
    ) and identity(job["identity_queue"]) == identity(scan["identity_queue"])


def _job_paths_safe(path: str, snapshot: dict[str, Any]) -> None:
    """Reject job/lock aliases to manuscript, bibliography or source inputs."""
    inputs = list(snapshot["files"])
    inputs.append(os.path.join(os.path.dirname(path), "ledger.json"))
    for identifier in snapshot["sources"]:
        metadata = _load_text_meta(identifier)
        if metadata and metadata.get("path"):
            inputs.append(metadata["path"])
    for output in (path, path + ".lock"):
        if os.path.islink(output):
            raise ValueError("job output is a symlink")
        for source in inputs:
            if os.path.realpath(output) == os.path.realpath(source) or (
                os.path.exists(output)
                and os.path.exists(source)
                and os.path.samefile(output, source)
            ):
                raise ValueError("job output aliases an input")


def _job_result(job: dict[str, Any], path: str) -> dict[str, Any]:
    """Report identity progress without implying scientific verification."""
    queue = [
        dict(
            item,
            status="UNCHECKED",
            result=None,
            reason="interrupted saved run; identity remains unchecked",
        )
        if item["status"] == "RUNNING"
        else item
        for item in job["identity_queue"]
    ]
    total = {
        name: sum(run["usage"][name] for run in job["runs"])
        for name in (
            "requests",
            "searches",
            "http_cache_hits",
            "unknown_price_requests",
            "elapsed_seconds",
        )
    }
    total.update(
        estimated_service_cost_usd=None
        if total["unknown_price_requests"]
        else 0.0,
        actual_billed_cost_usd=None,
        model_calls=0,
        model_tokens=None,
        external_model_cost_usd=None,
    )
    result = {
        "ok": True,
        "job_id": job["job_id"],
        "job_path": path,
        "scope": "registry identity only; support is not assessed by this job",
        "submission_ready": False,
        "identity_complete": all(
            item["status"] == "ASSESSED" for item in queue
        ),
        "identity_verified": all(
            item["status"] == "ASSESSED"
            and item["result"]["status"] == "VERIFIED"
            for item in queue
        ),
        "identity_expected": len(queue),
        "input_scope": job["input_scope"],
        "identity_assessed": sum(
            item["status"] == "ASSESSED" for item in queue
        ),
        "identity_unchecked": sum(
            item["status"] != "ASSESSED" for item in queue
        ),
        "support_pending": len(job["support_queue"]),
        "identity_queue": queue,
        "support_queue": job["support_queue"],
        "uncited_scope": job["uncited_scope"],
        "config": job["config"],
        "cumulative_usage": total,
        "runs": job["runs"],
        "elapsed_accounting_complete": all(
            run["state"] not in ("INTERRUPTED", "RUNNING")
            for run in job["runs"]
        ),
        "deadline_semantics": "cooperative; OS/DNS and file operations "
        "may overshoot; elapsed and overshoot "
        "are reported",
        "accounting": "request/search counts are durable "
        "pre-operation reservations, "
        "conservatively including interrupted "
        "admissions; HTTP cache hits consume no "
        "request; actual billing and external "
        "model spend are unknown",
        "next_action": "Resume unchecked identities with "
        "another explicit per-run grant, then "
        "use existing source "
        "retrieval/independent judgment tools "
        "and a fresh submission-ready audit. Job "
        "success is not citation readiness.",
    }
    if not _correction_snapshot_current(
        job["snapshot"], os.path.dirname(job["config"]["tex_path"])
    ):
        return {
            "ok": False,
            "job_id": job["job_id"],
            "submission_ready": False,
            "identity_complete": False,
            "rescan_required": True,
            "error": "job-stale: inputs changed before "
            "publication; create a new job",
        }
    if (not job["input_scope"].get("scope_complete", True)
            or job["input_scope"].get("review_only")):
        result["identity_observed_expected"] = result["identity_expected"]
        result["identity_observed_complete"] = result["identity_complete"]
        result["identity_expected"] = None
        result["identity_complete"] = False
        result["identity_verified"] = False
    return result


def verification_job(
    tex_path: str,
    bib_path: str | None = None,
    job_id: str | None = None,
    operation: Literal["run", "status"] = "run",
    budget: VerificationBudget | None = None,
    priorities: list[ClaimPriority] | None = None,
    search_unresolved: bool | None = None,
) -> dict[str, Any]:
    """Run or inspect prioritized registry checks under per-invocation limits.

    Args:
        tex_path: Main manuscript path; required on resume too.
        bib_path: Optional override; omitted resume values use saved config.
        job_id: Existing job ID to resume/inspect; omit to create a job.
        operation: Run unchecked identities, or inspect state without network.
        budget: Fresh per-run grant, not a change to previous accounting.
        priorities: Explicit scheduling advice tied to current support IDs.
        search_unresolved: Enable title searches; defaults true for new jobs.

    Returns:
        Identity progress, an unchecked support queue, and measured usage.
        ok means the job command succeeded, never scientific readiness.
    """
    try:
        limits = _validated_budget(budget)
    except ValueError as invalid_budget:
        return {
            "ok": False,
            "submission_ready": False,
            "error": str(invalid_budget),
        }
    if job_id is not None and (
        not isinstance(job_id, str)
        or re.fullmatch(r"[a-f0-9]{32}", job_id) is None
    ):
        return {
            "ok": False,
            "submission_ready": False,
            "error": "invalid job ID",
        }

    def no_persist(usage: dict[str, Any]) -> None:
        del usage

    if (
        not isinstance(tex_path, str)
        or not tex_path.strip()
        or (
            bib_path is not None
            and (not isinstance(bib_path, str) or not bib_path.strip())
        )
    ):
        return {
            "ok": False,
            "submission_ready": False,
            "error": (
                "manuscript and bibliography paths must be nonempty strings"
            ),
        }
    controller = _RequestBudget(limits, no_persist)
    token = _request_budget.set(controller)
    identifier = job_id or uuid.uuid4().hex
    tex_path = os.path.abspath(tex_path)
    workdir = os.path.dirname(tex_path)
    path = os.path.join(workdir, PROJECT_DIR, "job-" + identifier + ".json")
    try:
        if operation not in ("run", "status") or (
            operation == "status" and job_id is None
        ):
            raise ValueError(
                "status requires job_id; operation must be run/status"
            )
        if (
            not isinstance(identifier, str)
            or re.fullmatch(r"[a-f0-9]{32}", identifier) is None
        ):
            raise ValueError("invalid job ID")
        preflight_error = _correction_preflight(tex_path, bib_path)
        if preflight_error:
            raise ValueError(preflight_error)
        # Inspect immutable config before locking, then reload under lock.
        # This also lets omitted resume parameters adopt a saved override.
        if job_id:
            if os.path.islink(path):
                raise ValueError("job output is a symlink")
            saved = _job_load(path, identifier)["config"]
            if bib_path is None:
                bib_path = saved["bib_path"]
            preflight_error = _correction_preflight(tex_path, bib_path)
            if preflight_error:
                raise ValueError(preflight_error)
        # Scan before locking so the lock-file cannot alias an input.
        provisional = _job_scan(tex_path, bib_path, None, True)
        _job_paths_safe(path, provisional["snapshot"])
        with _file_lock(path):
            job = _job_load(path, identifier) if job_id else None
            if job is not None:
                previous = job["config"]
                bib_path = (
                    previous["bib_path"] if bib_path is None else bib_path
                )
                priorities = (
                    previous["priorities"] if priorities is None else priorities
                )
                search_unresolved = (
                    previous["search_unresolved"]
                    if search_unresolved is None
                    else search_unresolved
                )
            if search_unresolved is None:
                search_unresolved = True
            if type(search_unresolved) is not bool:
                raise ValueError("search_unresolved must be boolean")
            scan = _job_scan(tex_path, bib_path, priorities, search_unresolved)
            _job_paths_safe(path, scan["snapshot"])
            if job is not None and not _job_same_scan(job, scan):
                return {
                    "ok": False,
                    "job_id": identifier,
                    "submission_ready": False,
                    "identity_complete": False,
                    "rescan_required": True,
                    "error": "job-stale: inputs, source evidence, "
                    "priorities or configuration changed; "
                    "create a new job",
                }
            if job is None:
                job = dict(
                    scan,
                    schema_version=1,
                    job_id=identifier,
                    created=_now_iso(),
                    updated=_now_iso(),
                    runs=[],
                )
            if operation == "status":
                return _job_result(job, path)
            for previous_run in job["runs"]:
                if previous_run["state"] == "RUNNING":
                    previous_run["state"] = "INTERRUPTED"
            for item in job["identity_queue"]:
                if item["status"] == "RUNNING":
                    item.update(
                        status="UNCHECKED",
                        result=None,
                        reason="interrupted; retry with cached prior "
                        "requests where available",
                    )
            run = {
                "run_id": uuid.uuid4().hex,
                "limits": limits,
                "usage": controller.usage(),
                "state": "RUNNING",
            }
            job["runs"].append(run)

            def persist(usage: dict[str, Any]) -> None:
                run["usage"] = usage
                _job_write(path, job)

            controller.persist = persist
            persist(controller.usage())
            try:
                for item in job["identity_queue"]:
                    if item["status"] == "ASSESSED" or item["bib_path"] is None:
                        continue
                    controller.remaining()
                    item.update(
                        status="RUNNING",
                        result=None,
                        reason="in progress",
                        attempts=item["attempts"] + 1,
                    )
                    persist(controller.usage())
                    result = verify_bib(
                        item["bib_path"],
                        keys=[item["key"]],
                        tex_path=tex_path,
                        search_unresolved=search_unresolved,
                    )
                    controller.remaining()
                    if not _correction_snapshot_current(
                        job["snapshot"], workdir
                    ):
                        raise ValueError(
                            "job-stale: inputs changed during "
                            "verification; create a new job"
                        )
                    rows = (
                        result.get("entries", [])
                        if isinstance(result, dict)
                        else []
                    )
                    row = (
                        rows[0]
                        if isinstance(rows, list)
                        and len(rows) == 1
                        and isinstance(rows[0], dict)
                        and rows[0].get("key") == item["key"]
                        else None
                    )
                    if row is not None and not _job_valid_result(
                        row, item["key"]
                    ):
                        raise ValueError("malformed verifier result")
                    if row is None or row.get("status") == "UNRESOLVED":
                        item.update(
                            status="UNCHECKED",
                            result=row,
                            reason="lookup incomplete; resume to retry",
                        )
                    elif row.get("status") not in {
                        "VERIFIED",
                        "FOUND",
                        "PROBABLE",
                        "MISMATCH",
                        "NOT_FOUND",
                    }:
                        raise ValueError("malformed verifier result")
                    else:
                        item.update(
                            status="ASSESSED",
                            result=row,
                            reason="registry assessment recorded; "
                            "scientific support remains unchecked",
                        )
                    persist(controller.usage())
            except (
                BudgetExhaustedError,
                OSError,
                RuntimeError,
                ValueError,
            ) as error:
                for item in job["identity_queue"]:
                    if item["status"] == "RUNNING":
                        item.update(
                            status="UNCHECKED", result=None, reason=str(error)
                        )
                run["state"] = "PAUSED"
                if str(error).startswith("job-stale:"):
                    persist(controller.usage())
                    return {
                        "ok": False,
                        "job_id": identifier,
                        "submission_ready": False,
                        "identity_complete": False,
                        "rescan_required": True,
                        "error": str(error),
                    }
            else:
                run["state"] = "FINISHED"
            finally:
                persist(controller.usage())
            if not _correction_snapshot_current(job["snapshot"], workdir):
                return {
                    "ok": False,
                    "job_id": identifier,
                    "submission_ready": False,
                    "identity_complete": False,
                    "rescan_required": True,
                    "error": "job-stale: inputs changed before "
                    "publication; create a new job",
                }
            return _job_result(job, path)
    except (OSError, ValueError, RuntimeError) as error:
        return {
            "ok": False,
            "submission_ready": False,
            "identity_complete": False,
            "error": str(error),
            "job_id": job_id,
            "run_usage": controller.usage(),
        }
    finally:
        _request_budget.reset(token)


# ---------------------------------------------------------------------------
# ping + dispatch
# ---------------------------------------------------------------------------

def ping() -> dict:
    """Liveness and capability check: token, PDF extractor, cache location."""
    info = {"ok": True, "server": "cite-check", "version": VERSION, "python": sys.version.split()[0],
            "ads_token": bool(_ads_token()), "ads_token_source": key_value("ads")[1],
            "github_token": bool(_github_token()), "github_token_source": key_value("github")[1],
            "keyring": _keyring_backend() or "file", "config_dir": _config_dir(),
            "pdftotext": bool(shutil.which("pdftotext")), "cache_dir": CACHE_DIR, "mailto": _mailto() or None}
    if _key_cache.get("warnings"):
        info["key_warnings"] = sorted(set(_key_cache["warnings"]))
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


TOOLS = {
    "register_input": register_input,
    "ping": ping,
    "resolve_citation": resolve_citation,
    "search_citation": search_citation,
    "fetch_bibtex": fetch_bibtex,
    "bib_add": bib_add,
    "verify_bib": verify_bib,
    "lint_bib": lint_bib,
    "extract_cites": extract_cites,
    "register_claims": register_claims,
    "fetch_text": fetch_text,
    "find_passages": find_passages,
    "record_support": record_support,
    "ledger_read": ledger_read,
    "audit": audit,
    "correction_report": correction_report,
    "verification_job": verification_job,
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


def _run_keys(argv):
    """server.py keys names | backend | fields <name> | list [--json] | set <name> [--no-test]
    (value on stdin) | test <name> | delete <name>|--all. Plain text for shell use."""
    sub = argv[0] if argv else "list"
    if sub == "names":
        print("\n".join(KEYS))
    elif sub == "backend":
        print(_keyring_backend() or f"file ({os.path.join(_config_dir(), 'keys')}, mode 0600)")
    elif sub == "fields" and len(argv) > 1 and argv[1] in KEYS:
        st = next(k for k in key_status() if k["name"] == argv[1])
        # unit separator: bash `read` keeps empty fields only for a non-blank IFS
        print("\x1f".join([st["label"], st["source"] if st["configured"] else "none", st["masked"] or "",
                           st["url"] or "", st["enables"], "1" if st["secret"] else "0"]))
    elif sub == "list":
        rows = key_status()
        if "--json" in argv:
            print(json.dumps(rows, indent=2, ensure_ascii=False))
        else:
            for k in rows:
                state = f"{k['source']} ({k['masked']})" if k["configured"] else "not configured"
                print(f"{k['name']:8s} {k['label']}: {state}")
            for w in sorted(set(_key_cache.get("warnings", []))):
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
        tok = key_value(argv[1])[0]
        if not tok:
            sys.exit(f"no {argv[1]} token configured")
        testers = {"ads": _ads_test, "github": _github_test,
                   "semanticscholar": _semanticscholar_test}
        r = testers[argv[1]](tok)
        print(r["detail"])
        sys.exit(0 if r["ok"] else 1)
    elif sub == "delete" and len(argv) > 1:
        names = list(KEYS) if argv[1] == "--all" else [argv[1]]
        for n in names:
            r = key_delete(n)
            print(f"{n}: " + (f"removed from {', '.join(r['removed_from'])}" if r["deleted"] else r.get("error") or "nothing stored"))
    else:
        sys.exit(
            "usage: server.py keys names|backend|fields <name>|list [--json]|"
            "set <name> [--no-test]|test ads|github|semanticscholar|"
            "delete <name>|--all")


def _run_cli(argv):
    if argv and argv[0] == "keys":
        return _run_keys(argv[1:])
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


if __name__ == "__main__":
    if sys.argv[1:] == ["_extract-pdf"]:
        _input_pdf_worker()
    elif len(sys.argv) > 1:
        _run_cli(sys.argv[1:])
    else:
        _run_mcp_server()
