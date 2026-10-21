# Acquisition efficiency and isolation

The engine shares network resources while keeping request admission, source
quality and citation judgments separate. Faster retrieval does not establish
that a work supports a claim.

## Connections and deployment

Installed environments use a lazily created HTTPX client for real connection
pooling, with at most 32 connections, 16 idle keep-alive connections and a
30-second idle expiry. HTTP/2 is disabled. Complete consumed responses can
return their connection to the pool; an interrupted or rejected response is
closed without draining an unbounded body. The process closes the client at
shutdown.

Requests are constructed explicitly. Response cookies do not become credentials
for later citation requests. Redirect decisions remain in the engine: bodies
are closed unread, hops are bounded, HTTPS downgrades are refused, cross-origin
credentials are removed, and API-key requests do not follow redirects.

HTTPX is an explicit installed dependency. A bare Python CLI without it retains
the standard-library transport, but does not claim connection reuse. Environment
proxy and certificate configuration remains applicable. Restart a running MCP
server after changing its environment or dependencies.

The pool follows HTTPX's documented [client lifecycle](https://www.python-httpx.org/advanced/clients/),
[resource limits](https://www.python-httpx.org/advanced/resource-limits/), and
[proxy/certificate environment settings](https://www.python-httpx.org/environment_variables/).

## Registry throttles

Each host has its own throttle lock and spacing. Waiting for one registry does
not hold a global lock that prevents requests to another registry. Same-host
requests still obey the configured interval, including retry and redirect
requests. An active verification budget also limits waiting time.

## Duplicate reads and accounting

Concurrent identical GET requests can share one in-flight result only within
the same active verification-budget object. The identity includes the URL,
method, body, headers and transport settings such as response bounds. Different
credentials, representations, limits or budget objects do not share in-flight
work. Unbudgeted calls use the normal response cache and connection pool without
in-flight coalescing.

A waiting caller checks its deadline; failures release waiting callers and
remove the in-flight entry. A physical request is still admitted before every
network attempt, including retries and redirect hops. `coalesced_waits` counts joined wait attempts, including those ending in a
failure or timeout. It is separate from disk-cache hits, so a reduction in
physical requests is visible without pretending another registry call occurred.

HTTP cache identities include request headers and body bytes. Credentials are
part of the digest used to separate representations; they are not stored as
plaintext cache filenames. This change can cause a one-time cache miss for
older entries.

## Bounded retries

Retry counts are bounded to 1–5 attempts. Timeouts must be finite, positive and
no greater than 300 seconds.
Only GET and HEAD are automatically retried; other methods make one attempt.
Retry-After supports nonnegative finite delays and HTTP dates, capped at 30
seconds. Invalid values use bounded backoff. Active deadlines can stop a wait
before the next attempt. The deadline remains cooperative: the engine checks
it between bounded reads, but an in-progress library/socket read can finish
after the deadline. Usage reports retain measured elapsed time and overshoot.

All response-size, extraction-quality and source-identity checks remain in
force. Pooling and duplicate suppression do not bypass byte limits, turn an
unavailable source into absence evidence, or change strict audit readiness.
Tests use local HTTP servers and deterministic fixtures; they are not a claim
of a universal speedup or of current provider availability.
