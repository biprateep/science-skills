"""Atomic files, locks, project ledgers and source/record caches."""

import contextlib
import functools
import tempfile
import hashlib
import json
import os
import re
import typing
import time
from datetime import datetime, timezone
from cite_check_engine import quality as _engine_quality
from cite_check_engine import models as _engine_models
from cite_check_engine import budgets as _engine_budgets
from cite_check_engine import config as _engine_config
from cite_check_engine import identifiers as _engine_identifiers


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
        budget = _engine_budgets._request_budget.get()
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
    d = os.path.join(_engine_config.CACHE_DIR, kind)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name)

def _record_cache_put(rec: typing.Mapping[str, typing.Any]) -> None:
    if rec.get("discovery_only"):
        return  # Never promote discovery metadata into authoritative caches.
    cid = _engine_identifiers._canonical(rec)
    if cid and (rec.get("repo") or {}).get("partial") and _record_cache_get(cid):
        return              # a search hit must not replace the repository's full record
    if cid:
        _atomic_write(_cache_file("records", _engine_identifiers._cache_key(cid) + ".json"), json.dumps(rec))

def _record_cache_get(
    cid: str, max_age: float | None = None
) -> _engine_models.Work | None:
    path = _cache_file("records", _engine_identifiers._cache_key(cid) + ".json")
    if os.path.exists(path) and (max_age is None or time.time() - os.path.getmtime(path) < max_age):
        with open(path) as fh:
            return json.load(fh)
    return None

def _alias_put(kind: str, value: str, cid: str) -> None:
    _atomic_write(
        _cache_file("records", "alias_" + _engine_identifiers._cache_key(f"{kind}_{value}") + ".json"),
        json.dumps({"id": cid})
    )

def _alias_get(kind: str, value: str) -> str | None:
    path = _cache_file("records", "alias_" + _engine_identifiers._cache_key(f"{kind}_{value}") + ".json")
    if os.path.exists(path):
        with open(path) as fh:
            return json.load(fh).get("id")
    return None

def _text_paths(cid: str) -> tuple:
    return _cache_file("text", _engine_identifiers._cache_key(cid) + ".txt"), _cache_file("text", _engine_identifiers._cache_key(cid) + ".json")

def _load_text_meta(cid: str) -> dict | None:
    legacy_path, metadata_path = _text_paths(cid)
    try:
        meta = json.loads(_engine_quality.read_bytes(metadata_path, 65536))
        if not isinstance(meta, dict):
            return None
        digest = meta.get("text_sha256")
        path = (os.path.join(os.path.dirname(legacy_path), digest + ".txt")
                if isinstance(digest, str) and re.fullmatch(r"[a-f0-9]{64}", digest)
                else legacy_path)
        text = _engine_quality.read_text(path)
        if digest and hashlib.sha256(text.encode("utf-8")).hexdigest() != digest:
            return None
        meta["path"] = path
        meta["quality"] = _engine_quality.current(meta, text)
        return meta
    except (OSError, ValueError, TypeError, _engine_quality.SourceLimitError):
        return None

def _project_path(workdir: str, name: str) -> str:
    d = os.path.join(os.path.abspath(workdir), _engine_config.PROJECT_DIR)
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

def _audit_file_digest(path: str) -> str | None:
    """Return a local input digest, or None when its bytes are unavailable."""
    try:
        with open(path, "rb") as source:
            return hashlib.sha256(source.read()).hexdigest()
    except OSError:
        return None
