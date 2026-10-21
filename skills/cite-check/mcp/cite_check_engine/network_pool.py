"""Optional pooled HTTP transport beneath the engine's admission checks."""

import atexit
import http.cookiejar
import importlib
import threading
from typing import Any
import urllib.error
import urllib.request

_client: Any = None
_client_lock = threading.Lock()


class _RejectCookies(http.cookiejar.DefaultCookiePolicy):
    """Do not retain response cookies in a process-wide registry client."""

    def set_ok(self, cookie: Any, request: Any) -> bool:
        del cookie, request
        return False


class _Response:
    """Expose an un-decoded, explicitly closed stream to urllib processors."""

    def __init__(self, response: Any, httpx: Any) -> None:
        self.response = response
        self.httpx = httpx
        self.status = self.code = response.status_code
        self.msg = response.reason_phrase
        self.headers = response.headers
        self.url = str(response.url)
        self._stream = response.iter_raw()
        self._buffer = b""
        self._finished = False

    def info(self) -> Any:
        return self.headers

    def geturl(self) -> str:
        return self.url

    def read1(self, size: int = 65536) -> bytes:
        if size < 1:
            return b""
        if not self._buffer and not self._finished:
            try:
                self._buffer = next(self._stream)
            except StopIteration:
                self._finished = True
            except self.httpx.HTTPError as error:
                raise urllib.error.URLError(str(error)) from error
        result, self._buffer = self._buffer[:size], self._buffer[size:]
        return result

    def read(self, size: int = 65536) -> bytes:
        return self.read1(size)

    def close(self) -> None:
        self.response.close()

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


class _PooledHandler(urllib.request.BaseHandler):
    """Run before urllib's default handlers; leave redirects to the engine."""

    handler_order = 400

    def __init__(self, httpx: Any) -> None:
        self.httpx = httpx

    def http_open(self, request: Any) -> _Response:
        global _client
        with _client_lock:
            if _client is None:
                _client = self.httpx.Client(
                    limits=self.httpx.Limits(
                        max_connections=32,
                        max_keepalive_connections=16,
                        keepalive_expiry=30.0,
                    ),
                    follow_redirects=False,
                    http2=False,
                    trust_env=True,
                    cookies=http.cookiejar.CookieJar(policy=_RejectCookies()),
                )
            client = _client
        headers = {
            name.lower(): value for name, value in request.header_items()
        }
        headers["accept-encoding"] = "identity"
        timeout = float(request.timeout)
        raw = self.httpx.Request(
            request.get_method(),
            request.full_url,
            headers=headers,
            content=request.data,
            extensions={
                "timeout": {
                    name: timeout
                    for name in ("connect", "read", "write", "pool")
                }
            },
        )
        try:
            response = client.send(raw, stream=True, follow_redirects=False)
        except self.httpx.HTTPError as error:
            raise urllib.error.URLError(str(error)) from error
        return _Response(response, self.httpx)

    https_open = http_open


def pooled_handlers() -> list[Any]:
    """Keep bare-stdlib CLI support when the optional pool is unavailable."""
    try:
        httpx = importlib.import_module("httpx")
    except ImportError:
        return []
    # HTTPX honors proxy/TLS environment configuration itself. Do not let
    # urllib rewrite the URL to a proxy first, or route through it twice.
    return [urllib.request.ProxyHandler({}), _PooledHandler(httpx)]


def close_pool() -> None:
    """Close idle/live pooled connections at shutdown or between tests."""
    global _client
    with _client_lock:
        client, _client = _client, None
    if client is not None:
        client.close()


atexit.register(close_pool)
