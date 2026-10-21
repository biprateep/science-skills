"""HTTP, redirects, throttling and budget-aware response acquisition."""

import concurrent.futures
import datetime
import email.utils
import hashlib
import json
import math
import os
import time
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
from cite_check_engine import network_pool as _engine_network_pool
from cite_check_engine import budgets as _engine_budgets
from cite_check_engine import config as _engine_config
from cite_check_engine import credentials as _engine_credentials
from cite_check_engine import persistence as _engine_persistence
from cite_check_engine import quality as _engine_quality


class _BudgetRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Disable implicit redirects so each physical request is admitted here."""

    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        del req, fp, code, msg, headers, newurl
        return None

def _new_opener() -> Any:
    return urllib.request.build_opener(
        _BudgetRedirectHandler(), *_engine_network_pool.pooled_handlers()
    )


def _budget_open(request: Any, timeout: float) -> Any:
    """Close redirect bodies and admit each hop immediately before opening."""
    budget = _engine_budgets._request_budget.get()
    credential_header = any(name.lower() == "x-api-key"
                            for name, _ in request.header_items())
    if credential_header:
        # Never forward API keys, even to same-origin or downgrade redirects.
        opener = _new_opener()
        if budget is not None:
            budget.reserve("request", request.full_url)
            timeout = min(timeout, budget.remaining())
        return opener.open(request, timeout=timeout)
    opener = _new_opener()
    visited: dict[str, int] = {}
    while True:
        if budget is not None:
            budget.reserve("request", request.full_url)
        try:
            return opener.open(
                request, timeout=min(timeout, budget.remaining()) if budget else timeout
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
                    if budget is not None:
                        budget.stop("unsupported-redirect-protocol")
                    raise RuntimeError("unsupported-redirect-protocol")
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
                    if budget is not None:
                        budget.stop("insecure-redirect-downgrade")
                    raise RuntimeError("insecure-redirect-downgrade")
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

def _budget_read(response: Any, max_bytes: int | None = None) -> bytes:
    """Bound actual body bytes and deadline for success and error responses."""
    limit = _engine_config.MAX_HTTP_BYTES if max_bytes is None else max_bytes
    budget = _engine_budgets._request_budget.get()
    headers = getattr(response, "headers", None)
    declared = headers.get("Content-Length") if headers is not None else None
    encoding = headers.get("Content-Encoding", "identity") if headers is not None else "identity"
    if isinstance(encoding, str) and encoding.strip().lower() not in {"", "identity"}:
        raise RuntimeError("unexpected HTTP Content-Encoding; identity bytes required")
    expected = None
    if isinstance(declared, str) and declared.isascii() and declared.isdigit():
        digits = declared.lstrip("0") or "0"
        if len(digits) > len(str(limit)):
            raise _engine_quality.SourceLimitError("HTTP Content-Length exceeds byte limit")
        expected = int(digits)
    if expected is not None and expected > limit:
        raise _engine_quality.SourceLimitError("HTTP Content-Length exceeds byte limit")
    chunks: list[bytes] = []
    size = 0
    while True:
        if budget is not None:
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
        chunk = read(min(65536, limit - size + 1))
        if budget is not None:
            budget.remaining()
        if not chunk:
            if expected is not None and size != expected:
                raise RuntimeError("HTTP body is incomplete or has inconsistent Content-Length")
            return b"".join(chunks)
        size += len(chunk)
        if size > limit:
            raise _engine_quality.SourceLimitError("HTTP body exceeds byte limit")
        chunks.append(chunk)

def _throttle(host: str) -> None:
    host = host.lower()
    interval = _engine_config._HOST_INTERVAL.get(host, 0.2)
    budget = _engine_budgets._request_budget.get()
    # Only registry access holds the global lock; sleeps are host-local.
    registry_lock = _engine_config._host_lock
    acquired = registry_lock.acquire(timeout=budget.remaining()) if budget else registry_lock.acquire()
    if not acquired:
        budget.stop("deadline-waiting-for-throttle")
    try:
        lock = _engine_config._host_locks.setdefault(host, threading.Lock())
    finally:
        registry_lock.release()
    acquired = lock.acquire(timeout=budget.remaining()) if budget else lock.acquire()
    if not acquired:
        budget.stop("deadline-waiting-for-throttle")
    try:
        if budget is not None:
            budget.remaining()
        wait = _engine_config._host_last.get(host, 0.0) + interval - time.monotonic()
        if wait > 0:
            _engine_budgets._budget_sleep(wait)
        _engine_config._host_last[host] = time.monotonic()
    finally:
        lock.release()


def _retry_delay(value: str | None, attempt: int) -> float:
    """Bound delta/date Retry-After and fall back on malformed values."""
    fallback = min(2.0 ** min(attempt, 5), 30.0)
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        return fallback
    try:
        delay = float(value)
    except ValueError:
        try:
            date = email.utils.parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=datetime.timezone.utc)
            delay = max(0.0, date.timestamp() - time.time())
        except (ValueError, TypeError, OverflowError):
            return fallback
    return min(delay, 30.0) if math.isfinite(delay) and delay >= 0 else fallback


def _request_headers(headers: dict | None) -> dict[str, str]:
    result = {
        "user-agent": _engine_credentials._user_agent(),
        "accept": "application/json, text/plain, */*",
        "accept-encoding": "identity",
    }
    result.update({str(name).lower(): str(value) for name, value in (headers or {}).items()})
    result["accept-encoding"] = "identity"
    return result


def _request_key(url: str, method: str, data: bytes | None, headers: dict) -> str:
    """Hash exact bytes and header identity; never persist secret values."""
    encoded = json.dumps([method, url, data is not None, sorted(headers.items())], ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8") + b"\0" + (data or b"")).hexdigest()


_flights: dict[tuple[Any, ...], concurrent.futures.Future] = {}
_flights_lock = threading.Lock()


def _http(url: str, method: str = "GET", data: bytes | None = None, headers: dict | None = None,
          timeout: int = 30, cache: bool = True, binary: bool = False, retries: int = 3,
          max_bytes: int | None = None):
    """Coalesce concurrent identical GETs only within one admitted budget."""
    limit = _engine_config.MAX_HTTP_BYTES if max_bytes is None else max_bytes
    if type(limit) is not int or limit < 1:
        raise ValueError("max_bytes must be a positive integer")
    if type(retries) is not int or not 1 <= retries <= 5:
        raise ValueError("retries must be an integer between 1 and 5")
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 300:
        raise ValueError("timeout must be finite and between 0 and 300 seconds")
    if not isinstance(method, str) or not method:
        raise ValueError("method must be a nonempty string")
    method = method.upper()
    hdrs = _request_headers(headers)
    budget = _engine_budgets._request_budget.get()
    if budget is not None:
        budget.remaining()
    arguments = (url, method, data, hdrs, timeout, cache, binary, retries, limit)
    if budget is None or method != "GET":
        return _http_request(*arguments)
    key = (budget, _request_key(url, method, data, hdrs), timeout, cache, binary, retries, limit)
    with _flights_lock:
        future = _flights.get(key)
        leader = future is None
        if leader:
            future = concurrent.futures.Future()
            _flights[key] = future
    if not leader:
        budget.coalesced_wait()
        try:
            result = future.result(timeout=budget.remaining())
        except concurrent.futures.TimeoutError:
            budget.stop("deadline-waiting-for-coalesced-request")
        budget.remaining()
        return result
    try:
        result = _http_request(*arguments)
    except BaseException as error:
        future.set_exception(error)
        raise
    else:
        future.set_result(result)
        return result
    finally:
        with _flights_lock:
            _flights.pop(key, None)


def _http_request(url: str, method: str = "GET", data: bytes | None = None, headers: dict | None = None,
          timeout: int = 30, cache: bool = True, binary: bool = False, retries: int = 3,
          max_bytes: int | None = None):
    """Return (status, body). body is str, or bytes when binary=True.

    200 and 404 text responses are cached (404 for one day: a fabricated
    identifier stays fabricated; a freshly minted DOI shows up tomorrow).
    429/5xx are retried with backoff. Network failure raises RuntimeError.
    """
    limit = _engine_config.MAX_HTTP_BYTES if max_bytes is None else max_bytes
    if type(limit) is not int or limit < 1:
        raise ValueError("max_bytes must be a positive integer")
    budget = _engine_budgets._request_budget.get()
    if budget is not None:
        budget.remaining()
    hdrs = _request_headers(headers)
    cache_key = _request_key(url, method, data, hdrs)
    path = _engine_persistence._cache_file("http", cache_key + ".json")
    if cache and not binary and os.path.exists(path):
        try:
            raw_cache = _engine_quality.read_bytes(path, limit * 6 + 4096)
            hit = json.loads(raw_cache)
            if not isinstance(hit, dict) or not isinstance(hit.get("body"), str) or len(hit["body"].encode("utf-8")) > limit:
                raise _engine_quality.SourceLimitError("cached HTTP body exceeds byte limit")
            ttl = _engine_config.META_TTL if hit["status"] == 200 else _engine_config.NEG_TTL
            if time.time() - hit["at"] < ttl:
                if budget is not None:
                    budget.cache_hit()
                return hit["status"], hit["body"]
        except (OSError, ValueError, KeyError, TypeError, _engine_quality.SourceLimitError):
            pass
    host = urllib.parse.urlparse(url).netloc
    last_error = None
    attempts = retries if method in {"GET", "HEAD"} else 1
    for attempt in range(1, attempts + 1):
        _throttle(host)
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with _budget_open(req, timeout=timeout) as resp:
                raw = b"" if method == "HEAD" else _budget_read(resp, max_bytes=limit)
                status = resp.status
            body = raw if binary else raw.decode("utf-8", errors="replace")
            if cache and not binary and status == 200:
                _engine_persistence._atomic_write(path, json.dumps(
                    {"status": status, "body": body, "at": time.time(), "url": url}
                ))
            return status, body
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < attempts:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                delay = _retry_delay(retry_after, attempt)
                exc.close()
                _engine_budgets._budget_sleep(delay)
                last_error = exc
                continue
            try:
                body = (b"" if binary else "" if method == "HEAD" else _budget_read(exc, max_bytes=limit).decode(
                    "utf-8", errors="replace"
                ))
            finally:
                exc.close()
            if cache and not binary and exc.code == 404:
                _engine_persistence._atomic_write(path, json.dumps(
                    {"status": 404, "body": "", "at": time.time(), "url": url}
                ))
            return exc.code, body
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt < attempts:
                _engine_budgets._budget_sleep(_retry_delay(None, attempt))
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
