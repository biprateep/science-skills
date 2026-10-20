"""Versioned evaluation manifests and runner configuration.

Repository defaults are applied to every discovered skill, including future
skills. Manifests contain trusted grading instructions, never agent input.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import os
import pathlib
import re
import stat
from typing import Any

DIMENSIONS = {"task_success", "constraint_adherence", "coverage"}
CHECK_KINDS = {"json_equals", "file_exists", "file_contains", "command"}
IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9_-]*")
PLACEHOLDERS = {
    "python",
    "repo",
    "workspace",
    "prompt_file",
    "response_file",
    "skill_dir",
    "seed",
}


class ContractError(ValueError):
    """A configuration cannot be evaluated without ambiguity."""


def read_regular(path: pathlib.Path, limit: int) -> str:
    """Read bounded UTF-8 text, refusing symlinks and special files."""
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    if path.is_symlink():
        raise ContractError(f"Symlink output: {path}")
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ContractError(f"Output is not a regular file: {path}")
        content = stream.read(limit + 1)
    if len(content) > limit:
        raise ContractError(f"Output exceeds limit: {path}")
    return content.decode("utf-8")


@dataclasses.dataclass(frozen=True)
class Case:
    """A validated task and its private grading specification.

    Attributes:
      skill: Skill directory name.
      manifest_dir: Directory containing task files.
      specification: Validated case configuration.
      dependencies: Other skill directories needed by this task.
      timeout_s: Runner wall-clock budget in seconds.
      fingerprint: Digest of task, inputs, reference, and grading contract.
    """

    skill: str
    manifest_dir: pathlib.Path
    specification: dict[str, Any]
    dependencies: tuple[str, ...]
    timeout_s: float
    fingerprint: str


def read_json(path: pathlib.Path) -> Any:
    """Decode strict JSON, including scalar and array responses."""
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_invalid_constant,
            parse_float=_finite_float,
        )
    except (OSError, ValueError, RecursionError) as error:
        raise ContractError(f"Invalid JSON in {path}: {error}") from error


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ContractError(f"Nonfinite JSON number: {value}")
    return number


def read_object(path: pathlib.Path) -> dict[str, Any]:
    """Read a JSON object, rejecting duplicate fields and nonfinite constants.

    Args:
      path: UTF-8 JSON file.

    Returns:
      The decoded object.

    Raises:
      ContractError: The input is not an unambiguous JSON object.
    """
    value = read_json(path)
    if not isinstance(value, dict):
        raise ContractError(f"Expected an object in {path}")
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ContractError(f"Nonfinite JSON value: {value}")


def digest(value: Any) -> str:
    """Return a deterministic SHA-256 digest of a JSON-serializable value."""
    encoded = json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def contained(root: pathlib.Path, relative: str) -> pathlib.Path:
    """Resolve a relative path without permitting escape or symlink traversal.

    Args:
      root: Directory that owns the path.
      relative: Nonempty relative POSIX path.

    Returns:
      The resolved path, which need not exist yet.

    Raises:
      ContractError: An absolute, parent-traversing, or symlink path is given.
    """
    if not isinstance(relative, str) or not relative:
        raise ContractError("Path must be a nonempty string")
    candidate = pathlib.PurePosixPath(relative)
    if candidate.is_absolute() or ".." in candidate.parts or "\\" in relative:
        raise ContractError(f"Path must stay within its directory: {relative}")
    target = root
    for part in candidate.parts:
        target = target / part
        if target.is_symlink():
            raise ContractError(f"Symlink paths are not allowed: {target}")
    if not target.resolve().is_relative_to(root.resolve()):
        raise ContractError(f"Path escapes its directory: {relative}")
    return target


def tree_digest(root: pathlib.Path) -> str:
    """Hash all regular files in a fixture tree, refusing symlinks."""
    entries = []
    paths = [root] if root.is_file() else sorted(root.rglob("*"))
    for path in paths:
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        if path.is_symlink():
            raise ContractError(f"Symlink in fixture: {path}")
        if path.is_file():
            name = path.name if root.is_file() else str(path.relative_to(root))
            entries.append(
                (name, hashlib.sha256(path.read_bytes()).hexdigest())
            )
    return digest(entries)


def _fields(value: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise ContractError(f"Unknown {label} fields: {sorted(unknown)}")


def positive(value: Any, label: str) -> float:
    """Validate a strictly positive finite number, excluding booleans."""
    if (
        type(value) not in (int, float)
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ContractError(f"{label} must be positive and finite")
    return float(value)


def _strings(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise ContractError(f"{label} must be a list of nonempty strings")
    if len(set(value)) != len(value):
        raise ContractError(f"{label} contains duplicates")
    return value


def identifier(value: Any, label: str) -> str:
    """Validate a portable identifier for directories and report keys."""
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ContractError(f"Invalid {label}: {value!r}")
    return value


def validate_command(command: Any) -> list[str]:
    """Validate argument arrays and the supported substitution vocabulary."""
    if not isinstance(command, list) or not command:
        raise ContractError("argv must be a nonempty list")
    for argument in command:
        if not isinstance(argument, str) or not argument or "\x00" in argument:
            raise ContractError("argv members must be nonempty strings")
        for placeholder in re.findall(r"\{([^{}]+)\}", argument):
            if placeholder not in PLACEHOLDERS:
                raise ContractError(
                    f"Unknown command placeholder: {placeholder}"
                )
    return command


def _validate_check(check: Any) -> None:
    if not isinstance(check, dict):
        raise ContractError("Each check must be an object")
    common = {"id", "kind", "dimension", "critical"}
    fields = {
        "json_equals": {"pointer", "expected"},
        "file_exists": {"path"},
        "file_contains": {"path", "text"},
        "command": {"argv", "timeout_s"},
    }
    kind = check.get("kind")
    if not isinstance(kind, str) or kind not in CHECK_KINDS:
        raise ContractError(f"Unknown check kind: {kind}")
    _fields(check, common | fields[kind], "check")
    identifier(check.get("id"), "check id")
    if (
        not isinstance(check.get("dimension"), str)
        or check["dimension"] not in DIMENSIONS
    ):
        raise ContractError("Unknown check dimension")
    if type(check.get("critical")) is not bool:
        raise ContractError("Each check must explicitly declare critical")
    if kind == "json_equals":
        pointer = check.get("pointer")
        if not isinstance(pointer, str) or (
            pointer and not pointer.startswith("/")
        ):
            raise ContractError("JSON pointer must be empty or start with /")
        if re.search(r"~(?![01])", pointer):
            raise ContractError("Invalid JSON pointer escape")
        if "expected" not in check:
            raise ContractError("json_equals requires expected")
    elif kind in {"file_exists", "file_contains"}:
        relative = check.get("path")
        if not isinstance(relative, str):
            raise ContractError("File check requires a string path")
        contained(pathlib.Path.cwd(), relative)
        if kind == "file_contains" and not isinstance(check.get("text"), str):
            raise ContractError("file_contains requires text")
    else:
        validate_command(check.get("argv"))
        positive(check.get("timeout_s", 10), "grader timeout_s")


def load_defaults(repo: pathlib.Path) -> dict[str, Any]:
    """Load the inherited repository execution defaults."""
    defaults = read_object(repo / "evals" / "defaults.json")
    _fields(
        defaults,
        {"schema_version", "timeout_s", "max_output_bytes"},
        "defaults",
    )
    if (
        type(defaults.get("schema_version")) is not int
        or defaults["schema_version"] != 1
    ):
        raise ContractError("Unsupported defaults schema_version")
    positive(defaults.get("timeout_s"), "timeout_s")
    limit = defaults.get("max_output_bytes")
    if type(limit) is not int or limit < 1024:
        raise ContractError("max_output_bytes must be an integer >= 1024")
    return defaults


def discover(repo: pathlib.Path) -> tuple[list[Case], list[str], list[str]]:
    """Discover every skill and validate its optional evaluation manifest.

    Args:
      repo: Repository root.

    Returns:
      Cases, all skill names, and skill names with manifests.

    Raises:
      ContractError: A manifest is incomplete or points outside its fixture.
    """
    defaults = load_defaults(repo)
    inventory = sorted(
        path.parent.name for path in (repo / "skills").glob("*/SKILL.md")
    )
    cases: list[Case] = []
    covered = []
    for skill in inventory:
        identifier(skill, "skill name")
        path = repo / "skills" / skill / "evals" / "manifest.json"
        if not path.exists():
            continue
        manifest = read_object(path)
        _fields(
            manifest,
            {"schema_version", "skill", "skill_dependencies", "cases"},
            "manifest",
        )
        if (
            type(manifest.get("schema_version")) is not int
            or manifest["schema_version"] != 1
        ):
            raise ContractError(f"Unsupported manifest schema in {path}")
        if manifest.get("skill") != skill:
            raise ContractError(
                f"Manifest skill does not match directory: {path}"
            )
        dependencies = _strings(
            manifest.get("skill_dependencies", []), "skill_dependencies"
        )
        if set(dependencies) - set(inventory):
            raise ContractError(f"Unknown skill dependency in {path}")
        specifications = manifest.get("cases")
        if not isinstance(specifications, list) or not specifications:
            raise ContractError(f"Manifest needs at least one case: {path}")
        identifiers = set()
        for specification in specifications:
            case = _load_case(
                skill, path.parent, specification, dependencies, defaults
            )
            case_id = case.specification["id"]
            if case_id in identifiers:
                raise ContractError(f"Duplicate case id: {skill}/{case_id}")
            identifiers.add(case_id)
            cases.append(case)
        covered.append(skill)
    return cases, inventory, covered


def _load_case(
    skill: str,
    directory: pathlib.Path,
    specification: Any,
    dependencies: list[str],
    defaults: dict[str, Any],
) -> Case:
    if not isinstance(specification, dict):
        raise ContractError("Each case must be an object")
    _fields(
        specification,
        {
            "id",
            "description",
            "prompt",
            "inputs",
            "reference",
            "capabilities",
            "checks",
            "tags",
            "timeout_s",
        },
        "case",
    )
    identifier(specification.get("id"), "case id")
    if (
        not isinstance(specification.get("description"), str)
        or not specification["description"].strip()
    ):
        raise ContractError("Case requires a description")
    _strings(specification.get("capabilities", []), "capabilities")
    _strings(specification.get("tags", []), "tags")
    checks = specification.get("checks")
    if not isinstance(checks, list) or not checks:
        raise ContractError("Case requires nonempty checks")
    for check in checks:
        _validate_check(check)
    if len({check["id"] for check in checks}) != len(checks):
        raise ContractError("Duplicate check id")
    if not any(check["dimension"] == "task_success" for check in checks):
        raise ContractError(
            "Case requires an independently scored task_success check"
        )
    files = {}
    for field in ("prompt", "inputs", "reference"):
        relative = specification.get(field)
        if relative is None and field != "prompt":
            continue
        if not isinstance(relative, str):
            raise ContractError(f"{field} must be a string path")
        target = contained(directory, relative)
        if field == "prompt":
            if (
                not target.is_file()
                or not target.read_text(encoding="utf-8").strip()
            ):
                raise ContractError(f"Missing or empty prompt: {target}")
        elif not target.is_dir():
            raise ContractError(f"Missing {field} directory: {target}")
        files[field] = tree_digest(target)
    timeout = positive(
        specification.get("timeout_s", defaults["timeout_s"]), "timeout_s"
    )
    return Case(
        skill,
        directory,
        specification,
        tuple(dependencies),
        timeout,
        digest(
            {
                "case": specification,
                "files": files,
                "grading_tree": tree_digest(directory),
                "timeout_s": timeout,
                "max_output_bytes": defaults["max_output_bytes"],
                "dependencies": dependencies,
            }
        ),
    )


def load_runner(path: pathlib.Path, name: str) -> dict[str, Any]:
    """Load a named live runner; replay is provided by the framework itself."""
    config = read_object(path)
    _fields(config, {"schema_version", "runners"}, "runner configuration")
    if (
        type(config.get("schema_version")) is not int
        or config["schema_version"] != 1
    ):
        raise ContractError("Unsupported runner schema_version")
    runners = config.get("runners")
    if not isinstance(runners, dict) or name not in runners:
        raise ContractError(f"Runner not configured: {name}")
    runner = runners[name]
    if not isinstance(runner, dict):
        raise ContractError("Runner must be an object")
    _fields(
        runner,
        {
            "agent",
            "model",
            "argv",
            "output",
            "stdin",
            "capabilities",
            "description",
        },
        "runner",
    )
    identifier(name, "runner name")
    if not isinstance(runner.get("agent"), str) or not runner["agent"]:
        raise ContractError("Runner requires an agent label")
    if runner.get("model") is not None and not isinstance(runner["model"], str):
        raise ContractError("model must be a string or null")
    validate_command(runner.get("argv"))
    if runner.get("output") not in ("stdout", "file", "envelope"):
        raise ContractError("Runner output must be stdout, file or envelope")
    if runner.get("stdin", "prompt") not in ("prompt", "none"):
        raise ContractError("Runner stdin must be prompt or none")
    _strings(runner.get("capabilities", []), "runner capabilities")
    return dict(runner, id=name, config_sha256=digest(runner))
