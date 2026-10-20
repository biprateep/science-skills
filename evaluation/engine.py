"""Execute skill tasks without exposing reference answers to the agent."""

from __future__ import annotations

import datetime
import hashlib
import math
import pathlib
import shutil
import subprocess
import sys
import time
from typing import Any
import uuid

from evaluation import contracts
from evaluation import grading
from evaluation import process

EXCLUDED = {
    "eval",
    "evals",
    "tests",
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "scratch",
}
USAGE_FIELDS = {"input_tokens", "output_tokens", "tool_calls", "cost_usd"}


def _copy(
    source: pathlib.Path,
    destination: pathlib.Path,
    skill: bool = False,
    overwrite: bool = False,
) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for item in sorted(source.iterdir()):
        if skill and (item.name in EXCLUDED or item.name.startswith(".")):
            continue
        if skill and item.suffix in {".log", ".pyc"}:
            continue
        if item.is_symlink():
            raise contracts.ContractError(f"Cannot copy symlink: {item}")
        target = destination / item.name
        if item.is_dir():
            _copy(item, target, skill, overwrite)
        elif item.is_file():
            if target.is_symlink() or (target.exists() and not overwrite):
                raise contracts.ContractError(f"Input collision: {target}")
            shutil.copyfile(item, target)


def _copy_skill(
    repo: pathlib.Path, skill: str, destination: pathlib.Path
) -> None:
    source = repo / "skills" / skill
    listed = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
            "--",
            f"skills/{skill}/",
        ],
        capture_output=True,
        check=False,
    )
    if listed.returncode != 0:
        # Exported trees have no Git ignore information. Keep conservative
        # exclusions; callers should use a clean export without private data.
        _copy(source, destination, skill=True)
        return
    destination.mkdir(parents=True, exist_ok=True)
    for raw in sorted(set(listed.stdout.decode().split("\0")) - {""}):
        relative = pathlib.Path(raw).relative_to(pathlib.Path("skills") / skill)
        if any(
            part in EXCLUDED or part.startswith(".") for part in relative.parts
        ):
            continue
        if relative.suffix in {".log", ".pyc"}:
            continue
        path = contracts.contained(source, relative.as_posix())
        if not path.exists():
            continue  # A tracked file may have been deleted locally.
        if not path.is_file():
            raise contracts.ContractError(f"Skill source is not a file: {path}")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)


def _usage(value: Any) -> dict[str, Any]:
    if value is None:
        return dict.fromkeys(USAGE_FIELDS)
    if not isinstance(value, dict) or set(value) - USAGE_FIELDS:
        raise contracts.ContractError("Invalid usage envelope")
    result = {}
    for key in sorted(USAGE_FIELDS):
        observed = value.get(key)
        if observed is not None:
            types = (int, float) if key == "cost_usd" else (int,)
            if (
                type(observed) not in types
                or not math.isfinite(observed)
                or observed < 0
            ):
                raise contracts.ContractError(f"Invalid usage value: {key}")
        result[key] = observed
    return result


def _envelope(path: pathlib.Path) -> tuple[str, bool | None, dict[str, Any]]:
    value = contracts.read_object(path)
    if set(value) - {"response", "reported_success", "usage"}:
        raise contracts.ContractError("Unknown response envelope field")
    response = value.get("response")
    if not isinstance(response, str):
        raise contracts.ContractError("Envelope needs a string response")
    success = value.get("reported_success")
    if success is not None and type(success) is not bool:
        raise contracts.ContractError(
            "reported_success must be boolean or null"
        )
    return response, success, _usage(value.get("usage"))


def _run_case(
    repo: pathlib.Path,
    case: contracts.Case,
    repeat: int,
    runner: dict[str, Any],
    directory: pathlib.Path,
    seed: int,
    limit: int,
) -> dict[str, Any]:
    started = time.monotonic()
    spec = case.specification
    directory.mkdir(parents=True)
    workspace = directory / "workspace"
    workspace.mkdir()
    response_file = directory / "response.txt"
    prompt_file = directory / "prompt.txt"
    result: dict[str, Any] = {
        "skill": case.skill,
        "case_id": spec["id"],
        "repeat": repeat,
        "case_fingerprint": contracts.digest(
            {
                "case": case.fingerprint,
                "framework": contracts.tree_digest(
                    pathlib.Path(__file__).parent
                ),
            }
        ),
        "seed": seed,
        "status": "error",
        "reported_success": None,
        "usage": _usage(None),
        "duration_s": 0.0,
        "checks": [
            dict(
                id=check["id"],
                dimension=check["dimension"],
                critical=check["critical"],
                status="not_run",
                detail="Runner did not complete",
            )
            for check in spec["checks"]
        ],
    }
    try:
        replay = runner["id"] == "replay"
        missing = set(spec.get("capabilities", [])) - set(
            runner.get("capabilities", [])
        )
        if missing and not replay:
            result.update(
                status="blocked",
                detail=f"Missing capabilities: {sorted(missing)}",
            )
            return result
        for skill in dict.fromkeys((case.skill, *case.dependencies)):
            _copy_skill(repo, skill, workspace / "skills" / skill)
        result["skill_content_sha256"] = contracts.tree_digest(
            workspace / "skills"
        )
        if "inputs" in spec:
            _copy(
                contracts.contained(case.manifest_dir, spec["inputs"]),
                workspace,
            )
        prompt = contracts.contained(
            case.manifest_dir, spec["prompt"]
        ).read_text(encoding="utf-8")
        prompt = (
            f"Work in {workspace}. Follow skills/{case.skill}/SKILL.md "
            "and its relevant references.\n"
            "Do not read files outside this workspace for task answers "
            "or grading criteria.\n\n" + prompt
        )
        prompt_file.write_text(prompt, encoding="utf-8")
        values = {
            "repo": str(repo),
            "python": sys.executable,
            "workspace": str(workspace),
            "prompt_file": str(prompt_file),
            "response_file": str(response_file),
            "skill_dir": str(workspace / "skills" / case.skill),
            "seed": str(seed),
        }
        if replay:
            if "reference" not in spec:
                result.update(status="blocked", detail="No replay reference")
                return result
            reference = contracts.contained(
                case.manifest_dir, spec["reference"]
            )
            response = contracts.contained(reference, "response.txt").read_text(
                encoding="utf-8"
            )
            if (reference / "artifacts").is_dir():
                _copy(reference / "artifacts", workspace, overwrite=True)
        else:
            outcome = process.execute(
                grading.expand(runner["argv"], values),
                workspace,
                case.timeout_s,
                limit,
                prompt if runner.get("stdin", "prompt") == "prompt" else "",
                response_file if runner["output"] == "file" else None,
            )
            (directory / "runner-output.txt").write_text(
                outcome.output, encoding="utf-8"
            )
            (directory / "runner-stderr.txt").write_text(
                outcome.stderr, encoding="utf-8"
            )
            if outcome.status != "ok":
                result.update(
                    status=outcome.status
                    if outcome.status in {"timeout", "blocked"}
                    else "error",
                    detail=outcome.output or outcome.status,
                )
                return result
            if runner["output"] == "file":
                if response_file.is_symlink():
                    raise contracts.ContractError(
                        "Response file must not be a symlink"
                    )
                response = contracts.read_regular(response_file, limit)
            elif runner["output"] == "envelope":
                response, result["reported_success"], result["usage"] = (
                    _envelope(directory / "runner-output.txt")
                )
            else:
                response = outcome.output
        if not response.strip() or len(response.encode()) > limit:
            raise contracts.ContractError(
                "Response is empty or exceeds output limit"
            )
        response_file.write_text(response, encoding="utf-8")
        result["checks"] = grading.grade(spec["checks"], values, limit)
        statuses = {check["status"] for check in result["checks"]}
        result["status"] = (
            "error"
            if "error" in statuses
            else "fail"
            if "fail" in statuses
            else "pass"
        )
    except (OSError, ValueError) as error:
        result.update(status="error", detail=str(error))
    finally:
        result["duration_s"] = time.monotonic() - started
    return result


def provenance(repo: pathlib.Path) -> dict[str, Any]:
    """Record Git identity and content provenance without source diffs."""

    def git(*arguments: str) -> str:
        outcome = subprocess.run(
            ["git", "-C", str(repo), *arguments],
            capture_output=True,
            text=True,
            check=False,
        )
        return outcome.stdout.strip() if outcome.returncode == 0 else ""

    status = git("status", "--porcelain", "--untracked-files=normal")
    return {
        "commit": git("rev-parse", "HEAD") or None,
        "dirty": bool(status),
        "diff_sha256": hashlib.sha256(git("diff", "HEAD").encode()).hexdigest(),
    }


def run(
    repo: pathlib.Path,
    cases: list[contracts.Case],
    inventory: list[str],
    covered: list[str],
    runner: dict[str, Any],
    output_root: pathlib.Path,
    repeats: int = 1,
    seed: int = 0,
) -> tuple[dict[str, Any], pathlib.Path]:
    """Run tasks and return a versioned report and fresh run directory."""
    if repeats < 1:
        raise contracts.ContractError("repeats must be positive")
    output_root = output_root.resolve()
    if (
        output_root == repo
        or output_root.is_relative_to(repo / "skills")
        or output_root.is_relative_to(repo / "evaluation")
        or output_root.is_relative_to(repo / "evals")
    ):
        raise contracts.ContractError(
            "Output must not be placed in source directories"
        )
    directory = output_root / (
        datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid.uuid4().hex[:10]
    )
    directory.mkdir(parents=True)
    defaults = contracts.load_defaults(repo)
    results = []
    for case in cases:
        for repeat in range(1, repeats + 1):
            result = _run_case(
                repo,
                case,
                repeat,
                runner,
                directory / case.skill / case.specification["id"] / str(repeat),
                seed + repeat - 1,
                defaults["max_output_bytes"],
            )
            results.append(result)
    report = {
        "schema_version": 1,
        "mode": "replay" if runner["id"] == "replay" else "live",
        "runner": {
            key: runner.get(key)
            for key in ("id", "agent", "model", "config_sha256")
        },
        "repository": provenance(repo),
        "inventory": {"skills": inventory, "covered_skills": covered},
        "results": results,
    }
    return report, directory
