"""Independent grading of responses and generated artifacts."""

from __future__ import annotations

import pathlib
from typing import Any

from evaluation import contracts
from evaluation import process


def expand(argv: list[str], values: dict[str, str]) -> list[str]:
    """Substitute known placeholders without invoking a shell."""
    result = []
    for argument in argv:
        for key, value in values.items():
            argument = argument.replace("{" + key + "}", value)
        result.append(argument)
    return result


def _pointer(value: Any, pointer: str) -> Any:
    if not pointer:
        return value
    for token in pointer[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            if not token.isdigit() or (
                len(token) > 1 and token.startswith("0")
            ):
                raise KeyError(token)
            value = value[int(token)]
        elif isinstance(value, dict):
            value = value[token]
        else:
            raise KeyError(token)
    return value


def grade(
    checks: list[dict[str, Any]],
    values: dict[str, str],
    limit: int,
) -> list[dict[str, Any]]:
    """Evaluate checks; malformed output fails and broken graders error."""
    results = []
    workspace = pathlib.Path(values["workspace"])
    for check in checks:
        status, detail = "fail", "Expectation not met"
        try:
            kind = check["kind"]
            passed = False
            if kind == "json_equals":
                # Reuse strict object decoding, including duplicate rejection.
                parsed = contracts.read_json(
                    pathlib.Path(values["response_file"])
                )
                actual = _pointer(parsed, check["pointer"])
                passed = contracts.digest(actual) == contracts.digest(
                    check["expected"]
                )
            elif kind in {"file_exists", "file_contains"}:
                path = contracts.contained(workspace, check["path"])
                passed = path.is_file()
                if passed and kind == "file_contains":
                    if path.stat().st_size > limit:
                        raise ValueError("Artifact exceeds output limit")
                    passed = check["text"] in contracts.read_regular(
                        path, limit
                    )
            else:
                outcome = process.execute(
                    expand(check["argv"], values),
                    workspace,
                    check.get("timeout_s", 10),
                    limit,
                )
                passed = outcome.status == "ok"
                if not passed and (
                    outcome.returncode != 1 or outcome.status != "error"
                ):
                    status = "error"
                detail = outcome.output.strip() or outcome.status
            if passed:
                status, detail = "pass", "Expectation met"
        except (ValueError, OSError, KeyError, IndexError, TypeError) as error:
            detail = str(error)
        results.append(
            {
                "id": check["id"],
                "dimension": check["dimension"],
                "critical": check["critical"],
                "status": status,
                "detail": detail,
            }
        )
    return results
