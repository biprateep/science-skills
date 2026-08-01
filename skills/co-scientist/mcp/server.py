#!/usr/bin/env python3
"""co-scientist MCP toolbox — deterministic verification & state for the skill.

Dual interface, same code paths:

  python3 server.py                          # MCP stdio server (needs `mcp` pkg)
  python3 server.py call <tool> '<json>'     # CLI mode (no `mcp` pkg needed)

The CLI form exists so a harness session that registered the server mid-run
(tools load at next session start) can still get identical verdicts through
its shell tool. See skills/co-scientist/SKILL.md — "MCP Toolbox".
"""

import json
import os
import random
import re
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
from contextlib import contextmanager

VERSION = "0.5.0"

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
        table[name] = sp.symbols(name, **kwargs)
    return table


def _check_one_step(lhs_s, rhs_s, cls, symbols, seed, tolerance, samples, domain,
                    numeric_only=False):
    """Run the tactic ladder (cas_verification.md §4) on one transition."""
    import sympy as sp
    from sympy.parsing.sympy_parser import parse_expr

    table = _build_symbols(symbols)
    lhs = parse_expr(lhs_s, local_dict=table)
    rhs = parse_expr(rhs_s, local_dict=table)
    diff = lhs - rhs
    free = sorted(diff.free_symbols, key=lambda s: s.name)

    def numeric_sample():
        rng = random.Random(seed)
        f = sp.lambdify(free, diff, "mpmath")
        lo, hi = domain
        for _ in range(samples):
            vals = [rng.uniform(lo, hi) for _ in free]
            try:
                if abs(complex(f(*vals))) >= tolerance:
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


def _step_worker(q, kwargs):
    try:
        q.put(_check_one_step(**kwargs))
    except Exception as exc:  # parse errors, bad assumptions, ...
        q.put(("error", "error", f"{type(exc).__name__}: {exc}"))


def _check_with_timeout(kwargs, timeout):
    """sympy.simplify can hang; isolate each step in a killable process."""
    import multiprocessing as mp
    try:
        ctx = mp.get_context("fork")
    except ValueError:
        return _check_one_step(**kwargs)  # non-fork platform: no timeout guard
    q = ctx.Queue()
    p = ctx.Process(target=_step_worker, args=(q, kwargs))
    p.start()
    p.join(timeout)
    if p.is_alive():
        p.terminate()
        p.join()
        if kwargs["cls"] in ("A", "N") and not kwargs.get("numeric_only"):
            retry = dict(kwargs, numeric_only=True)
            ok, method, detail = _check_with_timeout(retry, max(timeout // 2, 10))
            if ok is not True:
                return False, "timeout", f"symbolic timed out after {timeout}s; numeric fallback: {detail}"
            return ok, method, f"symbolic timed out; {detail}"
        return False, "timeout", f"exceeded {timeout}s"
    return q.get()


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
    domain = domain or [0.1, 3.0]
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
                 seed=seed, tolerance=tolerance, samples=samples, domain=domain),
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
    verified = not failures
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
                   else f"FAIL at step(s) {failures} — locate the error there",
    }


# ---------------------------------------------------------------------------
# resolve_citation — arXiv / DOI / OpenAlex
# ---------------------------------------------------------------------------

_ARXIV_NEW = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$")
_ARXIV_OLD = re.compile(r"^[a-z-]+(\.[A-Z]{2})?/\d{7}$")


def _http_get(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": f"co-scientist-mcp/{VERSION}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def resolve_citation(identifier: str, timeout: int = 20) -> dict:
    """Resolve an arXiv id, DOI, or OpenAlex id to real bibliographic metadata.

    Returns resolved=False with a reason if the identifier does not exist —
    a citation may not enter the manifest/report unless resolved=True.
    """
    raw = identifier.strip()
    ident = re.sub(r"^(arxiv:|doi:)\s*", "", raw, flags=re.I)
    ident = re.sub(r"^https?://(www\.)?(arxiv\.org/(abs|pdf)/|doi\.org/|openalex\.org/)", "", ident, flags=re.I)
    ident = ident.strip().rstrip("/").removesuffix(".pdf")

    try:
        if _ARXIV_NEW.match(ident) or _ARXIV_OLD.match(ident):
            body = _http_get(f"http://export.arxiv.org/api/query?id_list={ident}", timeout)
            ns = {"a": "http://www.w3.org/2005/Atom"}
            entry = ET.fromstring(body).find("a:entry", ns)
            title = entry.findtext("a:title", "", ns).strip() if entry is not None else ""
            if not title or title == "Error":
                return {"resolved": False, "id": raw, "id_type": "arxiv",
                        "reason": "arXiv API returned no entry for this id"}
            return {
                "resolved": True, "id": f"arXiv:{ident}", "id_type": "arxiv",
                "title": re.sub(r"\s+", " ", title),
                "authors": [a.findtext("a:name", "", ns)
                            for a in entry.findall("a:author", ns)][:10],
                "year": (entry.findtext("a:published", "", ns) or "")[:4],
                "venue": "arXiv",
                "url": f"https://arxiv.org/abs/{ident}",
            }
        if ident.startswith("10."):
            data = json.loads(_http_get(f"https://api.crossref.org/works/{ident}", timeout))
            msg = data.get("message", {})
            issued = (msg.get("issued", {}).get("date-parts") or [[None]])[0][0]
            return {
                "resolved": True, "id": ident, "id_type": "doi",
                "title": (msg.get("title") or ["(untitled)"])[0],
                "authors": [f"{a.get('given', '')} {a.get('family', '')}".strip()
                            for a in msg.get("author", [])][:10],
                "year": str(issued) if issued else "",
                "venue": (msg.get("container-title") or [""])[0],
                "url": f"https://doi.org/{ident}",
            }
        if re.match(r"^[Ww]\d+$", ident):
            data = json.loads(_http_get(f"https://api.openalex.org/works/{ident.upper()}", timeout))
            return {
                "resolved": True, "id": ident.upper(), "id_type": "openalex",
                "title": data.get("display_name", "(untitled)"),
                "authors": [a["author"]["display_name"]
                            for a in data.get("authorships", [])][:10],
                "year": str(data.get("publication_year", "")),
                "venue": ((data.get("primary_location") or {}).get("source") or {}).get("display_name", ""),
                "url": data.get("id", ""),
            }
        return {"resolved": False, "id": raw,
                "reason": "unrecognized identifier — expected arXiv id, DOI (10.*), or OpenAlex Wnnn"}
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {"resolved": False, "id": raw, "reason": "identifier not found (HTTP 404)"}
        return {"resolved": False, "id": raw, "reason": f"HTTP {exc.code} from registry"}
    except Exception as exc:
        return {"resolved": False, "id": raw,
                "reason": f"lookup failed ({type(exc).__name__}: {exc}) — retry or mark UNVERIFIED"}


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
    with evidence can flip it. Citations with resolved!=true are recorded but
    flagged — they may not enter the report.
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
            notes.append("citation is NOT resolved — verify with resolve_citation "
                         "before it may enter the report")
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
    resolve_citation result. This is the only way verified becomes true.
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
    "resolve_citation": resolve_citation,
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
                                     or result.get("resolved") is False
                                     or result.get("ok") is False):
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        _run_cli(sys.argv[1:])
    else:
        _run_mcp_server()
