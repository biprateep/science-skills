# Mathematical Derivation Protocol

Read this when a derivation/proof begins (Derivation mode, or Full Project
Phase 6). The goal is **correct** mathematics that a reader can trust — not
verbose mathematics. Showing work is necessary but **not sufficient**: a
fully-expanded derivation can still be wrong. Every result must be sanity-checked
and independently verified.

## 1. Derivation Format

For each **load-bearing** step:

1. **State the current equation** (numbered, display math).
2. **State the operation** ("integrate by parts", "substitute X", "take the
   gradient").
3. **Justify why the operation is valid** when it is not obvious — domain,
   convergence, invertibility, sign, branch, regularity. This justification is
   the point; it is where errors hide.
4. **Show the algebra** for the step.
5. **State the result** (numbered) and **any assumptions** introduced (append
   them to the assumptions ledger — see `checkpointing.md`).

**Do not pad.** Show every load-bearing step in full, but collapse purely
mechanical algebra with a one-line note (e.g. "expanding and collecting terms
gives"). Manufacturing trivial steps to hit a count buries the one step that
actually matters. **Flag the single hardest / most error-prone step explicitly**
so the reviewer scrutinizes it.

### Example

> **Step 1.** Euler–Lagrange equation:
> $$\frac{\partial \mathcal{L}}{\partial q} - \frac{d}{dt}\frac{\partial \mathcal{L}}{\partial \dot{q}} = 0 \quad (1)$$
>
> **Step 2 (key step).** Substitute $\mathcal{L} = \tfrac12 m\dot q^2 - V(q)$.
> Valid because $\mathcal{L}$ is $C^1$ in $q,\dot q$ here, so the partials exist:
> - $\partial_q \mathcal{L} = -\partial_q V$, $\quad \partial_{\dot q}\mathcal{L} = m\dot q$
> - $\tfrac{d}{dt}(m\dot q) = m\ddot q$ *(assumes $m$ constant — to ledger)*
>
> **Step 3.** Substituting into (1): $\; -\partial_q V - m\ddot q = 0 \quad (2)$

## 2. Sanity-Check Gate (mandatory, cheap, no code)

Before claiming a result, run the checks that catch most errors in seconds:

- **Dimensions / units** balance on both sides.
- **Limiting cases** recover known results ($n\to\infty$, $x\to 0$, coupling
  $\to 0$, known special cases).
- **Symmetry** expected of the system is preserved (or its breaking is explained).
- **Order of magnitude** is physically plausible.

Record the checks and their outcomes in the derivation checkpoint. A failed
sanity check means **stop and find the error**, not "note and continue".

## 3. Independent CAS Verification Gate (mandatory for non-trivial results)

A derivation is not `complete` until machine-verified with a computer algebra
system — not by prose re-reading. The CAS of record is **SymPy** (free, open
source, in `resources/requirements.txt`). The full mechanism — step-chain
script, checkability taxonomy, tactic ladder, domain-specific checks — is in
`cas_verification.md`; **read it when this gate begins**. In brief:

- **Every load-bearing step**, not just the final result, is encoded in one
  step-chain script (`scripts/check_NNN_<name>.py`) that asserts each
  transition and prints a per-step `STEP <k> [<class>] PASS|FAIL` line.
- Steps a CAS cannot decide are **classified, never skipped**: symbolic (S) /
  assumption-dependent (A) / numeric-only (N — logged seed + stated tolerance)
  / machine-unverifiable (U — explicitly listed and routed to the Red-Team).
- Run via `<run-shell>`. Record the per-step table + script path in the
  checkpoint; set `"verified": true` in the manifest only if the script exits 0.
- A FAIL means **find the error** — in the math or, demonstrably, in the check's
  encoding. Never weaken a check (tolerance, domain, deleting a step) to pass.

## 4. Independent Review

The **Red-Team / Reviewer subagent** (a *separate* invocation — never the agent
that produced the derivation) recomputes each transition, re-checks dimensions
and limits, and challenges assumptions. See `references/subagents.md`. Self-review
does not satisfy this gate.

## Self-check before returning

1. Is every load-bearing step shown and every non-obvious operation justified?
2. Did the sanity checks (dimensions, limits, symmetry) pass?
3. Did the step-chain CAS script PASS on every step, with the script saved and
   every unverifiable (U) step explicitly listed?
4. Are all assumptions in the ledger?
5. Is the result tagged with a confidence level?
