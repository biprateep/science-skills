"""HTTP, redirects, throttling and budget-aware response acquisition."""

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
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

def _budget_open(request: Any, timeout: float) -> Any:
    """Close redirect bodies and admit each hop immediately before opening."""
    budget = _engine_budgets._request_budget.get()
    credential_header = any(name.lower() == "x-api-key"
                            for name, _ in request.header_items())
    if credential_header:
        # Never forward API keys, even to same-origin or downgrade redirects.
        opener = urllib.request.build_opener(_BudgetRedirectHandler())
        if budget is not None:
            budget.reserve("request", request.full_url)
            timeout = min(timeout, budget.remaining())
        return opener.open(request, timeout=timeout)
    opener = urllib.request.build_opener(_BudgetRedirectHandler())
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
    interval = _engine_config._HOST_INTERVAL.get(host, 0.2)
    budget = _engine_budgets._request_budget.get()
    acquired = (
        _engine_config._host_lock.acquire(timeout=budget.remaining())
        if budget
        else _engine_config._host_lock.acquire()
    )
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
        _engine_config._host_lock.release()

def _http(url: str, method: str = "GET", data: bytes | None = None, headers: dict | None = None,
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
    hdrs = {"User-Agent": _engine_credentials._user_agent(), "Accept": "application/json, text/plain, */*"}
    hdrs.update(headers or {})
    cache_key = hashlib.sha1(
        f"{method} {url} {data.decode('utf-8', 'replace') if data else ''} "
        f"{hdrs.get('Accept', '')}".encode()).hexdigest()
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
    for attempt in range(1, retries + 1):
        _throttle(host)
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with _budget_open(req, timeout=timeout) as resp:
                raw = _budget_read(resp, max_bytes=limit)
                status = resp.status
            body = raw if binary else raw.decode("utf-8", errors="replace")
            if cache and not binary and status == 200:
                _engine_persistence._atomic_write(path, json.dumps(
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
                _engine_budgets._budget_sleep(min(delay, 30))
                last_error = exc
                continue
            try:
                body = (b"" if binary else _budget_read(exc, max_bytes=limit).decode(
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
            if attempt < retries:
                _engine_budgets._budget_sleep(2.0 ** attempt)
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
