# Prioritized verification jobs

Use `verification_job` for a manuscript whose registry checks need a resource
limit or several resumable passes. It automatically checks cited bibliography
identities through the existing verifier. It also orders every current
citation occurrence/atom as support work for the independent judge. Source
retrieval, PDF parsing and model judgments are outside this job's automatic
work; the tool does not spend a model budget or fabricate support verdicts.

## Start, inspect and resume

Native MCP and CLI expose the same arguments. A new job uses `operation="run"`
(the default) with no `job_id`:

```json
{
  "tex_path": "/project/main.tex",
  "bib_path": "/project/refs.bib",
  "budget": {
    "max_requests": 50,
    "max_searches": 10,
    "max_seconds": 60,
    "max_cost_usd": 0
  },
  "search_unresolved": true
}
```

```sh
python <skills>/cite-check/mcp/server.py call verification_job '<json>'
```

Progress is stored under the main manuscript's ignored `.cite-check`
directory as `job-<job_id>.json`. Keep the returned ID. Inspect it without
network work using `operation="status"`, `tex_path` and `job_id`. Resume with
`operation="run"` and that ID, supplying the next per-run budget. Each run
receives a fresh grant; limits are not a lifetime cap, and cumulative usage
from earlier runs remains visible. Omitted budget fields use their defaults.

Omit `priorities`, `search_unresolved` and an explicit bibliography override
on resume to retain the stored configuration. Supplying different priorities
or search configuration is refused; start a new job for a changed plan.
Completed identity units are retained rather than repeated. A unit interrupted
by a budget denial remains UNCHECKED; a later run may reuse valid HTTP cache
entries while repeating its incomplete work. Lookup failures that could not
establish an outcome remain UNCHECKED for a later attempt, never NOT_FOUND
merely because a limit or registry failure prevented checking.

Jobs bind their queue and configuration to current manuscript, included
files, bibliography, ledger/source snapshots and tool policy/version. Changes
require a new job (`rescan_required`); old results are not silently presented
as current. A lock serializes resumes of the same job, and completed units
are persisted before proceeding. Malformed or inconsistent job state is
refused. Job artifacts and verifier outputs cannot alias manuscript,
bibliography or evidence inputs; symlinked report directories are refused.
Ordinary symlinked workspace ancestors remain usable.

## Schedule consequential claims first

Use priorities from the user's research priorities or the caller's explicit
review plan. Identify the current occurrence with `extract_cites`; include
its registered `atom_id` when prioritizing an atomic support requirement.
For example, mark a central numerical result high and explain why:

```json
{
  "occurrence_id": "<current occurrence ID>",
  "atom_id": "<current attached atom ID>",
  "priority": "high",
  "reason": "The main conclusion depends on this numerical result."
}
```

Pass such objects in the `priorities` list. `priority` is `high`, `normal` or
`low`; unspecified requirements default to normal. IDs and reasons must be
valid for the current manuscript, and duplicate assignments are refused.
The highest attached priority schedules each cited key's identity check;
all affected occurrences remain attached to that unit. The support-work
queue retains full assertions, sentence/context and locations, keeping
repeated occurrences and separate atoms distinct.

Priority changes the order of work, never a verdict, confidence score or
readiness requirement. Low-priority requirements remain in the denominator
and visible when the budget ends. Declared uncited scope stays unverified;
priority cannot attach it to unrelated source evidence.

## What each budget measures

| Limit | Default | Meaning |
|---|---:|---|
| `max_requests` | 50 | Admission reservations for physical HTTP attempts, including fallback calls, retries and redirects |
| `max_searches` | 10 | Registry backend search invocations; one multi-registry search may use several |
| `max_seconds` | 60 | Cooperative elapsed-time deadline for the run |
| `max_cost_usd` | 0 | Admission cap against the declared service-fee pricing assumption; `null` permits unknown-priced requests |

Request/search limits are nonnegative integers; time and cost limits must be
finite nonnegative numbers. Zero request/search limits allow planning while
refusing those operations. A zero time limit can expire before the job can
be scanned or created; it does not promise an inspection result. HTTP cache
hits consume no network request
reservations and are reported separately, while deadline checks still apply.
A search invocation may hit an HTTP cache but still consumes a search unit.

The same locked budget is shared by the verifier's worker threads. A request
is reserved and its usage persisted before it is sent, including automatic
fallbacks and redirects. A crash after reservation can therefore overcount an
attempt that never reached the network; these are conservative reservations,
not provider billing telemetry. If a run is interrupted, its last saved
elapsed time is only a lower bound: `elapsed_accounting_complete=false` makes
that uncertainty explicit in cumulative results. Completed units are saved transactionally;
interrupted work cannot become a completed or negative finding just because
some partial results were available.

Deadline checks cover throttle/backoff waits, request timeouts and response
reads. Remaining time bounds newly admitted blocking work, and no further
work is admitted after exhaustion. This is a cooperative deadline rather
than a process-kill guarantee: DNS, operating-system scheduling or a blocking
operation can overshoot. Reports expose elapsed seconds, `deadline_exceeded`
and `deadline_overshoot_seconds`; do not describe the configured seconds as
a guaranteed wall-clock termination time.

The declared `public-registry-service-fee-zero-v1` pricing policy estimates
zero service fees for the supported public registry host allowlist. This is
an admission assumption, not a measurement or provider billing guarantee.
A cost cap refuses requests and redirects to hosts whose service price is
unknown. With `max_cost_usd=null`, those requests may proceed, and their
service-cost estimate is unknown. This cap does not measure infrastructure,
network costs or any external agent's subscriptions. Actual billed cost is
unknown; model calls are zero, model tokens are unmeasured, and any external
model cost is unknown/unperformed by the job. A zero service-fee estimate
must never be reported as verified total spend.

## Finish the scientific checks

`identity_complete` reports whether all queued identities have assessed
outcomes; negative identity outcomes can still be complete. Read the results
and `identity_verified` separately. UNCHECKED units and `support_pending`
remain explicit. The source-reading/independent-judgment queue is UNCHECKED
by this registry-only tool, even if the manuscript already has a ledger:
current evidence and readiness belong to the ordinary audit.

No job result establishes submission readiness: `submission_ready` is always
false. Complete source retrieval, independent atomic judgments and any
necessary correction through the existing workflow. Run
`audit(..., policy="submission-ready")` and require the existing readiness
flags before treating the manuscript as citation-clean. That separate audit
performs its own current checks; it does not inherit the job's budget or
silently trust persisted identity results.

`ok=true` means the job command returned usable progress, including a budget
pause; it does not mean all identity checks passed or support was assessed.
CLI exits zero for that progress result. Input/state errors and stale jobs
return `ok=false` and exit one. Check the separate identity counts, every
queue item, and the strict audit gate before drawing scientific conclusions.
