#!/usr/bin/env python3
"""co-scientist MCP toolbox — deterministic verification & state for the skill.

Dual interface, same code paths:

  python3 server.py                          # MCP stdio server (needs `mcp` pkg)
  python3 server.py call <tool> '<json>'     # CLI mode (no `mcp` pkg needed)

The CLI form exists so a harness session that registered the server mid-run
(tools load at next session start) can still get identical verdicts through
its shell tool. See skills/co-scientist/SKILL.md — "MCP Toolbox".
"""

import ast
import json
import math
import os
import random
import re
import subprocess
import sys
from contextlib import contextmanager

VERSION = "0.7.0"

# ---------------------------------------------------------------------------
# ping
# ---------------------------------------------------------------------------


def ping() -> dict:
    """Liveness/versions check for the co-scientist toolbox."""
    info = {"ok": True, "server": "co-scientist", "version": VERSION,
            "python": sys.version.split()[0]}
    try:
        import sympy
        info["sympy"] = sympy.__version__
    except ImportError:
        info["sympy"] = None
        info["warning"] = "sympy not installed — verify_derivation unavailable"
    return info


# ---------------------------------------------------------------------------
# verify_derivation — step-chain CAS verification (sympy)
# ---------------------------------------------------------------------------

_ASSUMPTION_WORDS = {
    "real", "positive", "negative", "nonnegative", "nonpositive", "nonzero",
    "integer", "rational", "irrational", "finite", "complex", "imaginary",
    "even", "odd", "prime", "commutative",
}


def _build_symbols(symbols: dict | None):
    import sympy as sp
    table = {}
    for name, spec in (symbols or {}).items():
        kwargs = {}
        for word in re.split(r"[,\s]+", spec.strip()):
            if not word:
                continue
            if word not in _ASSUMPTION_WORDS:
                raise ValueError(f"unknown assumption {word!r} for symbol {name!r}")
            kwargs[word] = True
        if not isinstance(name, str) or not name.isidentifier() or name.startswith("_"):
            raise ValueError("symbol names must be public identifiers")
        table[name] = sp.Symbol(name, **kwargs)
    return table



def _math_expression(source: str, symbols: dict):
    """Construct mathematics from an allowlisted AST, without Python evaluation.

    Args:
        source: Mathematical expression, at most 10,000 characters.
        symbols: Explicit SymPy symbols and assumptions.

    Returns:
        A SymPy expression; tuples are accepted only as function arguments.

    Raises:
        ValueError: The expression uses syntax outside the mathematical grammar.
    """
    import sympy as sp

    if not isinstance(source, str) or not source or len(source) > 10000:
        raise ValueError("expression must contain 1 to 10,000 characters")
    functions = {
        name: getattr(sp, name) for name in (
            "sin", "cos", "tan", "asin", "acos", "atan", "atan2",
            "sinh", "cosh", "tanh", "asinh", "acosh", "atanh",
            "exp", "log", "sqrt", "Abs", "sign", "floor", "ceiling",
            "factorial", "gamma", "erf", "conjugate", "re", "im",
            "integrate", "diff", "limit", "summation", "product",
            "Integral", "Derivative", "Limit", "Sum", "Product",
        )
    }
    constants = {"pi": sp.pi, "E": sp.E, "I": sp.I, "oo": sp.oo}
    try:
        tree = ast.parse(source, mode="eval")
    except (SyntaxError, RecursionError) as exc:
        raise ValueError("invalid mathematical syntax") from exc
    if sum(1 for _ in ast.walk(tree)) > 1000:
        raise ValueError("expression exceeds the syntax complexity limit")

    def construct(node: ast.AST, depth: int = 0):
        if depth > 64:
            raise ValueError("expression nesting exceeds 64 levels")
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            if isinstance(node.value, float) and not math.isfinite(node.value):
                raise ValueError("numeric literals must be finite")
            return sp.Number(node.value)
        if isinstance(node, ast.Name) and not node.id.startswith("_"):
            if node.id in symbols:
                return symbols[node.id]
            if node.id in constants:
                return constants[node.id]
            if node.id in functions:
                raise ValueError("a function name requires arguments")
            return sp.Symbol(node.id)
        if isinstance(node, ast.UnaryOp) and isinstance(
            node.op, (ast.UAdd, ast.USub)
        ):
            value = construct(node.operand, depth + 1)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp):
            left = construct(node.left, depth + 1)
            right = construct(node.right, depth + 1)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.Pow):
                # Prevent enormous eager integer allocations before CAS tactics.
                if right.is_number and abs(right) > 10000:
                    raise ValueError("numeric exponent exceeds 10,000")
                return left ** right
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id not in functions or node.keywords:
                raise ValueError("only approved mathematical calls are allowed")
            args = []
            for arg in node.args:
                if isinstance(arg, ast.Tuple):
                    args.append(tuple(construct(v, depth + 1) for v in arg.elts))
                else:
                    args.append(construct(arg, depth + 1))
            return functions[node.func.id](*args)
        raise ValueError(f"unsupported mathematical syntax: {type(node).__name__}")

    return construct(tree.body)


def _limit_worker_resources(timeout: float) -> None:
    """Bound CAS CPU and address space on platforms with POSIX resource limits."""
    try:
        import resource
    except ImportError:
        return  # Parent still enforces the portable wall-clock process timeout.
    cpu_seconds = max(1, math.ceil(timeout))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
    memory_bytes = 2 * 1024 ** 3
    resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))

def _check_one_step(lhs_s, rhs_s, cls, symbols, seed, tolerance, samples, domain,
                    numeric_only=False):
    """Run the tactic ladder (cas_verification.md §4) on one transition."""
    import sympy as sp

    table = _build_symbols(symbols)
    lhs = _math_expression(lhs_s, table)
    rhs = _math_expression(rhs_s, table)
    diff = lhs - rhs
    free = sorted(diff.free_symbols, key=lambda s: s.name)

    def numeric_sample():
        rng = random.Random(seed)
        f = sp.lambdify(free, diff, "mpmath")
        for _ in range(samples):
            values = [_sample_symbol(s, rng, domain) for s in free]
            vals = [
                int(v) if v.is_integer else
                float(v) if v.is_real else complex(v.evalf())
                for v in values
            ]
            try:
                magnitude = abs(complex(f(*vals)))
                if not math.isfinite(magnitude) or magnitude >= tolerance:
                    return False
            except Exception:
                return False
        return True

    if not numeric_only:
        tactics = [
            ("simplify+expand", lambda d: sp.simplify(sp.expand(d))),
            ("factor", sp.factor),
            ("cancel", sp.cancel),
            ("together+simplify", lambda d: sp.simplify(sp.together(d))),
            ("radsimp", sp.radsimp),
            ("trigsimp", sp.trigsimp),
            ("powsimp+simplify", lambda d: sp.simplify(sp.powsimp(d))),
            ("rewrite(exp)+simplify", lambda d: sp.simplify(d.rewrite(sp.exp))),
        ]
        for name, fn in tactics:
            try:
                if fn(diff) == 0:
                    return True, "symbolic", name
            except Exception:
                continue
        # equals() samples numerically inside sympy: numeric-strength evidence.
        try:
            eq = lhs.equals(rhs)
            if eq is True:
                return True, "numeric", "sympy.equals (numeric-strength)"
        except Exception:
            pass

    if cls in ("A", "N") or numeric_only:
        if free and numeric_sample():
            return True, "numeric", f"random-sample seed={seed} tol={tolerance} n={samples}"
        if not free:
            try:
                if abs(complex(diff.evalf())) < tolerance:
                    return True, "numeric", f"constant-evalf tol={tolerance}"
            except Exception:
                pass
    return False, "none", "all tactics exhausted"



def _check_with_timeout(kwargs: dict, timeout: float) -> tuple:
    """Run CAS in a bounded child process on both fork and spawn platforms."""
    try:
        child = subprocess.run(
            [sys.executable, os.path.abspath(__file__), "--verify-step"],
            input=json.dumps({"kwargs": kwargs, "timeout": timeout}),
            text=True, capture_output=True, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        return False, "timeout", f"exceeded {timeout}s"
    if child.returncode != 0:
        return False, "worker_failed", f"CAS worker exited {child.returncode}"
    try:
        result = json.loads(child.stdout)
    except json.JSONDecodeError:
        return False, "worker_failed", "CAS worker produced invalid output"
    if not isinstance(result, list) or len(result) != 3:
        return False, "worker_failed", "CAS worker produced invalid result"
    return tuple(result)


def _run_step_worker() -> None:
    """Execute the private, JSON-only subprocess protocol."""
    payload = json.load(sys.stdin)
    _limit_worker_resources(payload["timeout"])
    try:
        result = _check_one_step(**payload["kwargs"])
    except Exception as exc:  # Isolated CAS boundary: report all library errors.
        result = ("error", "error", f"{type(exc).__name__}: {exc}")
    print(json.dumps(result))


def _sample_symbol(symbol, rng: random.Random, domain: list):
    """Draw a finite value satisfying the symbol's declared assumptions."""
    import sympy as sp

    lo, hi = domain
    if symbol.is_commutative is False:
        raise ValueError("numeric sampling cannot test noncommutative symbols")
    if symbol.is_positive:
        lo = max(lo, math.nextafter(0.0, math.inf))
    elif symbol.is_nonnegative:
        lo = max(lo, 0.0)
    if symbol.is_negative:
        hi = min(hi, math.nextafter(0.0, -math.inf))
    elif symbol.is_nonpositive:
        hi = min(hi, 0.0)
    if lo > hi:
        raise ValueError(f"domain has no values satisfying {symbol}")
    if symbol.is_integer:
        lower, upper = math.ceil(lo), math.floor(hi)
        if symbol.is_even or symbol.is_odd:
            parity = int(bool(symbol.is_odd))
            lower += (parity - lower) % 2
            upper -= (upper - parity) % 2
            stride = 2
        else:
            stride = 1
        if lower > upper:
            raise ValueError(f"domain has no admissible integer for {symbol}")
        if symbol.is_prime:
            lower = int(sp.nextprime(lower - 1))
            if lower > upper:
                raise ValueError(f"domain has no prime for {symbol}")
        for _ in range(100):
            value = rng.randrange(lower, upper + 1, stride)
            if symbol.is_prime:
                value = int(sp.nextprime(value - 1))
            if value <= upper and (value != 0 or not symbol.is_nonzero):
                return sp.Integer(value)
    else:
        for _ in range(100):
            real = sp.Rational(str(rng.uniform(lo, hi)))
            if symbol.is_irrational:
                # A small irrational offset, kept strictly inside the domain.
                width = sp.Rational(str(hi)) - sp.Rational(str(lo))
                if width <= 0:
                    break
                real = (
                    sp.Rational(str(lo)) + width / 4
                    + width * sp.sqrt(2) / 4
                    + width * sp.Rational(str(rng.random())) / 4
                )
            if symbol.is_imaginary:
                value = sp.I * real
            elif symbol.is_real is not True:
                value = real + sp.I * sp.Rational(str(rng.uniform(lo, hi)))
            else:
                value = real
            if value != 0 or not (symbol.is_nonzero or symbol.is_imaginary):
                return value
    raise ValueError(f"could not sample the domain for {symbol}")


def _validate_derivation_settings(
    steps: list, symbols: dict | None, seed: int, tolerance: float,
    samples: int, domain: list, step_timeout: int,
) -> None:
    """Reject incomplete work and settings that could create vacuous passes."""
    if not isinstance(steps, list) or not steps:
        raise ValueError("steps must be a nonempty list")
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    if type(samples) is not int or samples <= 0:
        raise ValueError("samples must be a positive integer")
    for label, value in (("tolerance", tolerance), ("step_timeout", step_timeout)):
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{label} must be positive and finite")
    if not isinstance(domain, (list, tuple)) or len(domain) != 2:
        raise ValueError("domain must contain two finite ascending bounds")
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in domain):
        raise ValueError("domain bounds must be finite numbers")
    if domain[0] >= domain[1]:
        raise ValueError("domain bounds must be strictly ascending")
    if symbols is not None and not isinstance(symbols, dict):
        raise ValueError("symbols must map names to assumption strings")
    if any(not isinstance(v, str) for v in (symbols or {}).values()):
        raise ValueError("symbol assumptions must be strings")
    _build_symbols(symbols)
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError("each step must be an object")
        cls = step.get("cls", "S")
        if not isinstance(cls, str) or cls.upper() not in ("S", "A", "N", "U"):
            raise ValueError("step class must be S, A, N, or U")
        if cls.upper() != "U" and any(
            not isinstance(step.get(side), str) or not step[side].strip()
            for side in ("lhs", "rhs")
        ):
            raise ValueError("checked steps require nonempty lhs and rhs strings")

def verify_derivation(steps: list, symbols: dict | None = None, seed: int = 12345,
                      tolerance: float = 1e-9, samples: int = 20,
                      domain: list | None = None, step_timeout: int = 60) -> dict:
    """Verify every load-bearing transition of a derivation with SymPy.

    steps: [{"label": "2->3", "cls": "S|A|N|U", "lhs": "<sympy expr>",
             "rhs": "<sympy expr>", "note": "optional"}]
    symbols: {"x": "real", "k": "positive"} — class-A assumptions live here.
    Classes per cas_verification.md: S symbolic, A assumption-dependent,
    N numeric-only, U machine-unverifiable (recorded, not checked).
    """
    try:
        import sympy  # noqa: F401
    except ImportError:
        return {"error": "sympy not installed — run mcp/setup_mcp.sh"}
    domain = [0.1, 3.0] if domain is None else domain
    try:
        _validate_derivation_settings(
            steps, symbols, seed, tolerance, samples, domain, step_timeout
        )
    except (ValueError, TypeError) as exc:
        return {"error": str(exc), "verified": False}
    results, unverifiable, failures = [], [], []
    for step in steps:
        label = step.get("label", "?")
        cls = step.get("cls", "S").upper()
        if cls not in ("S", "A", "N", "U"):
            return {"error": f"step {label!r}: class must be S, A, N, or U, got {cls!r}"}
        if cls == "U":
            unverifiable.append({"label": label, "note": step.get("note", "")})
            results.append({"label": label, "cls": "U", "ok": None,
                            "method": "unchecked", "detail": "routed to Red-Team"})
            continue
        if "lhs" not in step or "rhs" not in step:
            return {"error": f"step {label!r}: lhs and rhs are required for class {cls}"}
        ok, method, detail = _check_with_timeout(
            dict(lhs_s=step["lhs"], rhs_s=step["rhs"], cls=cls, symbols=symbols,
                 seed=seed, tolerance=tolerance, samples=samples, domain=domain,
                 numeric_only=cls == "N"),
            step_timeout)
        if ok == "error":
            return {"error": f"step {label!r}: {detail}"}
        entry = {"label": label, "cls": cls, "ok": ok, "method": method, "detail": detail}
        if cls == "S" and ok and method == "numeric":
            entry["warning"] = ("class-S step passed only with numeric-strength "
                                "evidence — consider reclassifying S→A/N")
        results.append(entry)
        if not ok:
            failures.append(label)
    import sympy
    verified = bool(len(results) - len(unverifiable)) and not failures
    return {
        "verified": verified,
        "cas": f"sympy {sympy.__version__}",
        "seed": seed,
        "steps": results,
        "unverifiable": unverifiable,
        "failed_steps": failures,
        "summary": ("all checked steps PASS"
                    + (f"; {len(unverifiable)} class-U step(s) need Red-Team review"
                       if unverifiable else "")) if verified
                   else (f"FAIL at step(s) {failures} — locate the error there"
                         if failures else "no machine-checkable steps"),
    }


# ---------------------------------------------------------------------------
# manifest — single-writer, file-locked run state
# ---------------------------------------------------------------------------

_SCALAR_FIELDS = {"phase", "next_action", "goal", "mode", "harness", "run_id"}
_LIST_SECTIONS = {"hypotheses", "checkpoints", "citations", "figures"}


def _manifest_path(workdir):
    return os.path.join(workdir, "checkpoints", "manifest.json")


@contextmanager
def _locked(workdir):
    import fcntl
    lock_path = os.path.join(workdir, "checkpoints", ".manifest.lock")
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    with open(lock_path, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _load_manifest(workdir):
    path = _manifest_path(workdir)
    if not os.path.exists(path):
        raise FileNotFoundError(f"no manifest at {path} — call manifest_init first")
    with open(path) as fh:
        return json.load(fh)


def _save_manifest(workdir, manifest):
    path = _manifest_path(workdir)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(manifest, fh, indent=2)
    os.replace(tmp, path)


def manifest_init(workdir: str, run_id: str, goal: str, harness: str = "unknown",
                  mode: str = "full-project") -> dict:
    """Create checkpoints/, figures/, scripts/ and the run manifest (Phase 0).

    Idempotent: if a manifest already exists it is returned unchanged with
    created=false — never overwritten.
    """
    workdir = os.path.abspath(workdir)
    for sub in ("checkpoints", "figures", "scripts"):
        os.makedirs(os.path.join(workdir, sub), exist_ok=True)
    with _locked(workdir):
        if os.path.exists(_manifest_path(workdir)):
            return {"created": False, "manifest": _load_manifest(workdir),
                    "note": "manifest already exists — resuming"}
        manifest = {"run_id": run_id, "harness": harness, "mode": mode, "goal": goal,
                    "next_id": 0, "phase": "init", "hypotheses": [], "checkpoints": [],
                    "citations": [], "figures": [], "next_action": ""}
        _save_manifest(workdir, manifest)
    return {"created": True, "manifest": manifest}


def manifest_read(workdir: str) -> dict:
    """Read the run manifest (do this first on resume)."""
    workdir = os.path.abspath(workdir)
    try:
        return {"manifest": _load_manifest(workdir)}
    except FileNotFoundError as exc:
        return {"error": str(exc)}


def manifest_append(workdir: str, section: str, entry: dict) -> dict:
    """Append an entry to hypotheses / checkpoints / citations / figures.

    For checkpoints: the id and filename are ALLOCATED HERE (single-writer id
    authority) — pass "descriptor" and "phase"; never pass an id. New
    checkpoints always start verified=false; only manifest_update_checkpoint
    with evidence can flip it. Citations come from the cite-check skill; one
    with resolved!=true is recorded but flagged — it may not enter the report.
    """
    workdir = os.path.abspath(workdir)
    if section not in _LIST_SECTIONS:
        return {"error": f"section must be one of {sorted(_LIST_SECTIONS)}"}
    notes = []
    with _locked(workdir):
        try:
            manifest = _load_manifest(workdir)
        except FileNotFoundError as exc:
            return {"error": str(exc)}
        entry = dict(entry)
        if section == "checkpoints":
            descriptor = entry.pop("descriptor", None)
            if not descriptor or not entry.get("phase"):
                return {"error": "checkpoint entries need 'descriptor' and 'phase'"}
            slug = re.sub(r"[^a-z0-9]+", "_", descriptor.lower()).strip("_")
            cid = f"{manifest['next_id']:03d}"
            if entry.pop("verified", False):
                notes.append("ignored verified=true — use manifest_update_checkpoint with evidence")
            entry.update({"id": cid, "file": f"checkpoint_{cid}_{slug}.md",
                          "verified": False})
            entry.setdefault("status", "in-progress")
            manifest["next_id"] += 1
        if section == "citations" and entry.get("resolved") is not True:
            notes.append("citation is NOT resolved — identify it through the "
                         "cite-check skill before it may enter the report")
        manifest[section].append(entry)
        _save_manifest(workdir, manifest)
    result = {"appended": entry, "section": section}
    if notes:
        result["notes"] = notes
    return result


def manifest_set(workdir: str, fields: dict) -> dict:
    """Set scalar run fields: phase, next_action, goal, mode, harness, run_id."""
    workdir = os.path.abspath(workdir)
    bad = set(fields) - _SCALAR_FIELDS
    if bad:
        return {"error": f"not settable here: {sorted(bad)} — "
                         f"allowed: {sorted(_SCALAR_FIELDS)}"}
    with _locked(workdir):
        try:
            manifest = _load_manifest(workdir)
        except FileNotFoundError as exc:
            return {"error": str(exc)}
        manifest.update(fields)
        _save_manifest(workdir, manifest)
    return {"updated": fields}


def manifest_update_checkpoint(workdir: str, checkpoint_id: str, status: str | None = None,
                               verified: bool | None = None, evidence: str | None = None) -> dict:
    """Update a checkpoint's status and/or verified flag.

    Setting verified=true REQUIRES evidence: a concrete pointer such as the
    verify_derivation summary, a check-script path + exit status, or a
    cite-check audit result. This is the only way verified becomes true.
    """
    workdir = os.path.abspath(workdir)
    if verified is True and not (evidence and len(evidence.strip()) >= 10):
        return {"error": "verified=true requires evidence (what check ran, where, result)"}
    if status is not None and status not in ("in-progress", "complete", "needs-revision"):
        return {"error": "status must be in-progress | complete | needs-revision"}
    with _locked(workdir):
        try:
            manifest = _load_manifest(workdir)
        except FileNotFoundError as exc:
            return {"error": str(exc)}
        for cp in manifest["checkpoints"]:
            if cp["id"] == checkpoint_id:
                if status is not None:
                    cp["status"] = status
                if verified is not None:
                    cp["verified"] = verified
                    if verified:
                        cp["verification_evidence"] = evidence.strip()
                _save_manifest(workdir, manifest)
                return {"updated": cp}
    return {"error": f"no checkpoint with id {checkpoint_id!r}"}


# ---------------------------------------------------------------------------
# validate_figures / compile_report
# ---------------------------------------------------------------------------

_INCLUDEGRAPHICS = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}")
_IMG_EXTS = (".png", ".pdf", ".jpg", ".jpeg", ".eps")


def validate_figures(tex_path: str) -> dict:
    """Check every \\includegraphics target in a .tex file exists on disk."""
    tex_path = os.path.abspath(tex_path)
    if not os.path.exists(tex_path):
        return {"error": f"{tex_path} not found"}
    base = os.path.dirname(tex_path)
    with open(tex_path) as fh:
        # strip LaTeX comments (unescaped %) before matching
        text = "\n".join(re.split(r"(?<!\\)%", line, maxsplit=1)[0] for line in fh)
    gp = re.search(r"\\graphicspath\{((?:\{[^}]*\})+)\}", text)
    search_dirs = ([d for d in re.findall(r"\{([^}]*)\}", gp.group(1))] if gp else []) + ["", "figures/"]
    found, missing = [], []
    for target in _INCLUDEGRAPHICS.findall(text):
        candidates = [os.path.join(base, d, target) for d in search_dirs]
        if not os.path.splitext(target)[1]:
            candidates = [c + ext for c in candidates for ext in _IMG_EXTS]
        hit = next((c for c in candidates if os.path.exists(c)), None)
        (found if hit else missing).append({"target": target, "resolved": hit})
    return {"ok": not missing, "found": found, "missing": missing}


def _unverified_checkpoints(manifest):
    return [cp for cp in manifest.get("checkpoints", [])
            if cp.get("phase") in ("derivation", "data", "computation")
            and not cp.get("verified")]


def compile_report(workdir: str, name: str = "report", allow_unverified: bool = False) -> dict:
    """Compile the LaTeX report — gated: refuses if the manifest still has
    unverified derivation/data checkpoints, or if any figure target is missing.

    allow_unverified=true bypasses the verification gate ONLY for explicitly
    negative-result / limitations-documented reports; the bypass is recorded
    in the result so it cannot happen silently.
    """
    workdir = os.path.abspath(workdir)
    name = name.removesuffix(".tex")
    tex = os.path.join(workdir, f"{name}.tex")
    if not os.path.exists(tex):
        return {"success": False, "gate": "missing_tex",
                "detail": f"{tex} not found — copy resources/paper_template.tex there first"}

    gates = {"verification": "skipped (no manifest — Derivation mode?)"}
    if os.path.exists(_manifest_path(workdir)):
        manifest = _load_manifest(workdir)
        bad = _unverified_checkpoints(manifest)
        if bad and not allow_unverified:
            return {"success": False, "gate": "unverified_checkpoints",
                    "detail": [{"id": c["id"], "file": c["file"]} for c in bad],
                    "fix": "verify via verify_derivation (or check scripts) and record "
                           "with manifest_update_checkpoint, or pass allow_unverified=true "
                           "for an explicit negative-result report"}
        gates["verification"] = ("BYPASSED (allow_unverified) — "
                                 f"{len(bad)} unverified checkpoint(s)") if bad else "passed"

    figs = validate_figures(tex)
    if not figs.get("ok"):
        return {"success": False, "gate": "missing_figures", "detail": figs.get("missing")}
    gates["figures"] = "passed"

    def latex():
        subprocess.run(["pdflatex", "-interaction=nonstopmode", f"{name}.tex"],
                       cwd=workdir, capture_output=True, timeout=180)

    pdf = os.path.join(workdir, f"{name}.pdf")
    if os.path.exists(pdf):
        os.remove(pdf)  # a stale PDF must not pass the existence check
    try:
        latex()
        bibtex_ran = False
        bib = os.path.join(workdir, f"{name}.bib")
        with open(tex) as fh:
            active_bib = any(re.match(r"^[^%]*\\bibliography\{", ln) for ln in fh)
        if os.path.exists(bib) and active_bib:
            subprocess.run(["bibtex", name], cwd=workdir, capture_output=True, timeout=60)
            latex()
            latex()
            bibtex_ran = True
    except FileNotFoundError as exc:
        return {"success": False, "gate": "toolchain", "detail": f"{exc.filename} not installed"}
    except subprocess.TimeoutExpired:
        return {"success": False, "gate": "toolchain", "detail": "pdflatex/bibtex timed out"}

    errors = []
    log = os.path.join(workdir, f"{name}.log")
    if os.path.exists(log):
        with open(log, errors="replace") as fh:
            lines = fh.read().splitlines()
        errors = [ln for ln in lines if ln.startswith("!")][:20]
    return {"success": os.path.exists(pdf), "pdf": pdf if os.path.exists(pdf) else None,
            "gates": gates, "bibtex_ran": bibtex_ran, "latex_errors": errors,
            "detail": None if os.path.exists(pdf) else f"no PDF produced — see {log}"}


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------

TOOLS = {
    "ping": ping,
    "verify_derivation": verify_derivation,
    "manifest_init": manifest_init,
    "manifest_read": manifest_read,
    "manifest_append": manifest_append,
    "manifest_set": manifest_set,
    "manifest_update_checkpoint": manifest_update_checkpoint,
    "validate_figures": validate_figures,
    "compile_report": compile_report,
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
    app = ServerClass("co-scientist")
    for fn in TOOLS.values():
        app.tool()(fn)
    app.run()


def _run_cli(argv):
    if not argv or argv[0] in ("-h", "--help") or argv[0] != "call":
        names = "\n  ".join(TOOLS)
        sys.exit(f"usage: server.py                      (MCP stdio server)\n"
                 f"       server.py call <tool> '<json-args>'\n\ntools:\n  {names}")
    if len(argv) < 2 or argv[1] not in TOOLS:
        sys.exit(f"unknown tool {argv[1] if len(argv) > 1 else '(none)'!r} — "
                 f"one of: {', '.join(TOOLS)}")
    try:
        kwargs = json.loads(argv[2]) if len(argv) > 2 else {}
    except json.JSONDecodeError as exc:
        sys.exit(f"invalid JSON args: {exc}")
    result = TOOLS[argv[1]](**kwargs)
    print(json.dumps(result, indent=2))
    if isinstance(result, dict) and (result.get("error")
                                     or result.get("verified") is False
                                     or result.get("success") is False
                                     or result.get("ok") is False):
        sys.exit(1)


if __name__ == "__main__":
    if sys.argv[1:] == ["--verify-step"]:
        _run_step_worker()
    elif len(sys.argv) > 1:
        _run_cli(sys.argv[1:])
    else:
        _run_mcp_server()
