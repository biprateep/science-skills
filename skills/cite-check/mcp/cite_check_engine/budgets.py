"""Per-invocation budgets and worker context propagation."""

import contextvars
import dataclasses
import math
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
from collections.abc import Callable
from cite_check_engine import models as _engine_models


class BudgetExhaustedError(RuntimeError):
    """A registry operation was not admitted; this is never absence evidence."""

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
    value: _engine_models.VerificationBudget | dict[str, Any] | None,
) -> dict[str, Any]:
    """Validate CLI input as strictly as the native nested schema."""
    defaults = dataclasses.asdict(_engine_models.VerificationBudget())
    supplied = (
        dataclasses.asdict(value)
        if isinstance(value, _engine_models.VerificationBudget)
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
