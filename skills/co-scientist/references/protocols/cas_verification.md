# CAS Verification Protocol (Step-Chain)

Read this alongside `math_derivation.md` when the Independent Verification Gate
begins. It defines **how** a derivation is machine-checked with a computer
algebra system (CAS): one script per derivation that verifies **every
load-bearing step**, not just the final result. An endpoint check can pass by
luck (compensating errors) or fail without locating the bug; a step chain does
neither.

## 0. Preferred Path — the `verify_derivation` MCP tool

For derivations whose load-bearing steps are **expression transitions**
(`lhs → rhs` pairs), do not write a check script — call the `verify_derivation`
tool (MCP Toolbox; CLI fallback
`mcp/.venv/bin/python mcp/server.py call verify_derivation '<json>'`). It
implements this protocol in code: the checkability taxonomy, the full tactic
ladder of §4, and the seeded numeric fallback, returning a per-step PASS/FAIL
table you did not author. Map your derivation onto its inputs:

```json
{
  "symbols": {"x": "real", "k": "positive"},
  "steps": [
    {"label": "2->3", "cls": "A",
     "lhs": "integrate(x*exp(-k*x), (x, 0, oo))", "rhs": "1/k**2"},
    {"label": "4", "cls": "U", "note": "dominated convergence — Red-Team"}
  ]
}
```

Class-A assumptions go in `symbols` (that is where they live in code too).
Class-U steps are recorded and routed to the Red-Team, exactly as in §2.
Record the result via `manifest_update_checkpoint` with the returned summary as
evidence.

**Still write a custom check script (§3)** for structures the tool cannot
express as an expression pair: ODE solutions (`checkodesol`), `sympy.stats`
characteristic-function comparisons, Monte Carlo checks with SE-scaled
tolerance, `sympy.physics.units` dimensional analysis, matrix identities at
several shapes, or anything needing the §5 domain-specific machinery. Those
scripts follow §§3–5 unchanged, and their output is the evidence string.

## 1. CAS of Record

- **SymPy** is the CAS of record: free, open source, on PyPI, already in
  `resources/requirements.txt`, and runs on any harness with `<run-shell>` and
  Python. Default to it.
- **Escalation (optional):** if SymPy times out or cannot simplify a hard
  integral/expression, and **Maxima** or **SageMath** is locally installed
  (check with `command -v maxima` / `command -v sage`), you may use it for that
  step. Record which CAS produced each verdict. Never require the user to
  install anything beyond `requirements.txt`.
- Proprietary CAS (Mathematica, Maple) are used **only** if the user offers a
  licensed installation; never assume one exists.

## 2. Classify Every Step (Checkability Taxonomy)

Every numbered load-bearing step in the derivation must appear in the check
script with one of these classes — **no silently unchecked steps**:

| Class | Meaning | Required check |
|-------|---------|----------------|
| **S** | Symbolic — CAS can decide the transition outright | Symbolic equality must PASS |
| **A** | Assumption-dependent — true only under declared domain assumptions (positivity, realness, convergence region) | Symbolic PASS with assumptions declared on the symbols; assumptions also go to the ledger |
| **N** | Numeric-only — symbolic check infeasible (no closed form, special functions, inequalities) | Random-sample check: logged seed, stated tolerance, samples drawn from the assumed domain |
| **U** | Machine-unverifiable — existence/uniqueness, convergence, measure-theoretic, or qualitative arguments | Listed explicitly in the script header and the checkpoint, with one line on *why*; routed to the Red-Team for manual scrutiny |

A derivation whose steps are all class U is a signal the derivation is stated
too informally — reformulate at least the algebra/calculus content into
checkable transitions.

## 3. The Step-Chain Script

One script per derivation, `scripts/check_NNN_<name>.py` (id assigned by the
orchestrator). Requirements:

- Asserts each transition `step_k → step_{k+1}` independently, so a failure
  **localizes** the wrong step.
- Prints one line per step: `STEP <k> [<class>] PASS|FAIL (<method>)`.
- Exits non-zero if any step FAILs (so `<run-shell>` surfaces it).
- Sets and prints a fixed seed for any numeric sampling.

Pattern (adapt, don't copy blindly):

```python
"""Step-chain check of derivation NNN (<name>).

Each load-bearing step is checked on its own and printed as one STEP line; the
exit status is 1 if any step fails.

Unverifiable (class U): step 4 (dominated convergence), for Red-Team review.
"""

from collections.abc import Sequence
import random
import sys

import sympy

SEED = 12345  # Log this in the checkpoint.


def numeric_ok(
    lhs: sympy.Expr,
    rhs: sympy.Expr,
    symbols: Sequence[sympy.Symbol],
    rng: random.Random,
    low: float = 0.1,
    high: float = 3.0,
    n_samples: int = 20,
    tolerance: float = 1e-9,
) -> bool:
    """Returns whether lhs - rhs vanishes at random points of the domain.

    Args:
      lhs: The expression before the step.
      rhs: The expression after it.
      symbols: The free symbols, each drawn uniformly from [low, high].
      rng: The seeded generator the points are drawn from.
      low: The lower end of the sampled domain.
      high: The upper end of the sampled domain.
      n_samples: How many points to try.
      tolerance: The largest |lhs - rhs| that counts as zero.
    """
    difference = sympy.lambdify(symbols, lhs - rhs, "mpmath")
    for _ in range(n_samples):
        point = [rng.uniform(low, high) for _ in symbols]
        # `not <` rather than `>=`, so that a NaN fails the step.
        if not abs(complex(difference(*point))) < tolerance:
            return False
    return True


def check(
    label: str,
    step_class: str,
    lhs: sympy.Expr,
    rhs: sympy.Expr,
    rng: random.Random,
    symbols: Sequence[sympy.Symbol] = (),
) -> bool:
    """Checks one step, prints its STEP line and returns whether it passed.

    Args:
      label: The step, e.g. "2->3".
      step_class: Its class in the checkability taxonomy: "S", "A" or "N".
      lhs: The expression before the step.
      rhs: The expression after it.
      rng: The seeded generator for the numeric fallback.
      symbols: The free symbols the numeric fallback samples.
    """
    passed = sympy.simplify(sympy.expand(lhs - rhs)) == 0
    method = "symbolic"
    if not passed and step_class in ("A", "N"):  # Documented fallback only.
        passed = numeric_ok(lhs, rhs, symbols, rng)
        method = f"numeric(seed={SEED})"
    verdict = "PASS" if passed else "FAIL"
    print(f"STEP {label} [{step_class}] {verdict} ({method})")
    return passed


def main() -> int:
    """Checks every step; returns the exit status, 1 if any step failed."""
    rng = random.Random(SEED)
    # The derivation's own symbols; class-A assumptions live HERE.
    x = sympy.symbols("x", real=True)
    k = sympy.symbols("k", positive=True)

    results = [
        # Step 2 -> 3: integration by parts.
        check(
            "2->3",
            "S",
            sympy.integrate(x * sympy.exp(-k * x), (x, 0, sympy.oo)),
            1 / k**2,
            rng,
        ),
    ]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
```

## 4. Tactic Ladder (before concluding FAIL)

`simplify(lhs - rhs) != 0` does **not** prove the identity false — SymPy often
needs help. Before recording FAIL on a symbolic step, escalate in order:

1. `expand`, `factor`, `cancel`, `together`, `radsimp` on the difference.
2. Domain-specific simplifiers: `trigsimp`, `powsimp`, `logcombine`
   (`force=True` only when the class-A assumptions justify it).
3. Declare tighter symbol assumptions (`positive=True`, `integer=True`) or use
   `sympy.posify` — then reclassify the step S → A and ledger the assumption.
4. `rewrite` to a common form (e.g. `.rewrite(sympy.exp)` for trig/hyperbolic).
5. `lhs.equals(rhs)` — note this samples numerically internally, so a PASS here
   is **numeric-strength** evidence: report the method as numeric, not symbolic.
6. Numeric sampling fallback (class N) with logged seed and tolerance.

Conversely, never weaken a check to force a PASS: no loosening tolerances, no
shrinking the sample domain to dodge a failing region, no deleting the failing
step. A genuine FAIL means **stop and find the error** — in the mathematics or,
demonstrably, in the encoding of the check itself (prove the encoding wrong by
hand before blaming it).

## 5. Domain-Specific Checks (cheaper and stronger than generic simplify)

Use the targeted check for the kind of mathematics at hand — these succeed
where a generic `simplify(lhs - rhs)` stalls or fails.

### 5.1 Differentiation & integration

- **Differentiation steps** (derivatives, partials, gradients, chain rule) are
  almost always class S: recompute with `sympy.diff`; multivariable via
  `sympy.Matrix([...]).jacobian([...])` and `sympy.hessian`.
- **Antiderivatives:** differentiate the claimed result and compare to the
  integrand — `sympy.diff` is reliable even when `sympy.integrate` is not.
- **Definite integrals:** compare against `sympy.integrate` **with the class-A
  assumptions declared on the symbols** — convergence usually depends on them
  (with `k = sympy.symbols("k", positive=True)`,
  `integrate(x*exp(-k*x), (x, 0, oo))` returns `1/k**2`; without it you get a
  conditional or an unevaluated integral). If `integrate` hangs or returns
  unevaluated, fall back to numeric quadrature at several sampled parameter
  values (class N): `mpmath.quad` for smooth/improper integrands,
  `mpmath.quadosc` (with the oscillation period) for oscillatory ones — these
  handle improper and oscillatory integrals that lambdify-at-random-points
  cannot.
- **Multi-step integral manipulations** (integration by parts,
  u-substitution): check the integrand identity at **each rewrite**, not just
  the final value. Interchange-of-limit steps (Fubini, dominated convergence,
  term-by-term integration) are class U — flag them for the Red-Team.
- **ODE solutions:** `sympy.checkodesol(ode, sol)` instead of re-deriving.

### 5.2 Probability & statistics (`sympy.stats`)

Statistical and probabilistic derivations are machine-checkable too — use
`sympy.stats` (`Normal`, `Exponential`, `Poisson`, `Binomial`, …):

- **Expectations / moments:** compare `E(g(X))`, `variance(X)`,
  `moment(X, n)` against the claimed closed form (class S/A — declare scale
  parameters positive).
- **Densities / CDFs:** compare `density(X)(x)` / `cdf(X)(x)` to the claimed
  expression; independently assert any claimed pdf is nonnegative on its
  support and integrates to 1 over it.
- **Derived distributions** (transformations, sums of independent RVs,
  CLT-style limits): comparing **characteristic functions**
  (`characteristic_function(X)(t)`) or MGFs is usually far easier than the
  change-of-variables integral — equal CFs imply equal distributions. For a
  CLT-style argument, also assert the claimed CF limit with
  `sympy.limit` / `sympy.series` as its own step in the chain.
- **Conditional / Bayes identities:** substitute the explicit densities and
  check algebraically (class S).
- **Monte Carlo fallback (class N) — the tolerance MUST scale with the
  standard error.** When symbolic expectation fails, estimate with a seeded
  `numpy.random.default_rng(SEED)` and accept iff
  `abs(estimate - claim) < 6 * sd / sqrt(n)` (sd = sample standard deviation
  of the summand). A fixed tolerance like `1e-9` falsely FAILs every Monte
  Carlo check; a tolerance untied to n proves nothing. Record n, the seed, and
  the computed tolerance in the step output.
- **Inequalities** (Jensen, Cauchy–Schwarz, concentration bounds): a CAS
  cannot prove these in general — sample numerically across the domain
  (class N; evidence, not proof) or classify U and route to the Red-Team.

### 5.3 Other structures

- **Algebraic solutions:** substitute back with `.subs(...)` and simplify to 0.
- **Limiting cases** (from the sanity gate): `sympy.limit`, `sympy.series` —
  assert each claimed limit/leading order symbolically.
- **Dimensional analysis:** `sympy.physics.units` — build both sides with units
  and assert `convert_to(lhs - rhs, base_units)` vanishes, or check the
  dimension system directly.
- **Finite sums / products:** compare `sympy.summation` against the closed form,
  plus explicit evaluation at small `n` (n = 1, 2, 3).
- **Matrix identities:** verify on symbolic matrices of the stated shape; if a
  claim is for general n, verify n = 2, 3, 4 explicitly and mark the general
  claim class N or U.

## 6. Recording & Gate Integration

- The checkpoint records: script path, per-step PASS/FAIL table (copy the
  script output), the class of each step, seed, tolerance, and which CAS ran.
- `"verified": true` in the manifest **only if** the script exits 0 — every
  S/A/N step PASSed — and every U step is listed in the checkpoint. U steps do
  not block `verified`, but they must be explicitly named for the Red-Team.
- The Red-Team subagent independently **re-runs** the check script and
  scrutinizes hardest the steps classified N and U — those are where machine
  verification is weakest.
- If symbolic verification is genuinely infeasible for the *entire* result,
  say so in the checkpoint and rely on the numeric chain — but this is the
  exception and needs a stated reason, not a default.
