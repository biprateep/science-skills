"""Bounded subprocess execution for agents and trusted graders."""

from __future__ import annotations

import dataclasses
import os
import pathlib
import signal
import subprocess
import tempfile
import time


@dataclasses.dataclass(frozen=True)
class Outcome:
    """Captured process status, exit code, output, and elapsed seconds."""

    status: str
    returncode: int | None
    output: str
    duration_s: float


def execute(
    argv: list[str],
    cwd: pathlib.Path,
    timeout_s: float,
    limit: int,
    stdin: str = "",
    response_file: pathlib.Path | None = None,
) -> Outcome:
    """Execute without a shell, limiting runtime and captured output.

    Output is spooled to temporary files rather than accumulated in memory.
    POSIX process groups are terminated on every exit, including successful
    parents that leave descendants behind. This is not a security sandbox.
    """
    started = time.monotonic()
    with (
        tempfile.TemporaryFile() as source,
        tempfile.TemporaryFile() as out,
        tempfile.TemporaryFile() as err,
    ):
        source.write(stdin.encode())
        source.seek(0)
        try:
            child = subprocess.Popen(
                argv,
                cwd=cwd,
                stdin=source,
                stdout=out,
                stderr=err,
                start_new_session=os.name == "posix",
            )
        except OSError as error:
            return Outcome(
                "blocked", None, str(error), time.monotonic() - started
            )
        status = "ok"
        try:
            while True:
                size = (
                    os.fstat(out.fileno()).st_size
                    + os.fstat(err.fileno()).st_size
                )
                if response_file is not None:
                    if response_file.is_symlink():
                        status = "error"
                        break
                    if response_file.is_file():
                        size += response_file.stat().st_size
                if size > limit:
                    status = "output_limit"
                    break
                if child.poll() is not None:
                    break
                if time.monotonic() - started > timeout_s:
                    status = "timeout"
                    break
                time.sleep(0.02)
        finally:
            if os.name == "posix":
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            elif child.poll() is None:
                child.kill()
            child.wait()
        final_size = (
            os.fstat(out.fileno()).st_size + os.fstat(err.fileno()).st_size
        )
        if response_file is not None and response_file.is_file():
            final_size += response_file.stat().st_size
        if status == "ok" and final_size > limit:
            status = "output_limit"
        if status == "ok" and child.returncode != 0:
            status = "error"
        out.seek(0)
        err.seek(0)
        output = out.read(limit).decode("utf-8", errors="replace")
        # Successful stdout must remain parseable; errors include diagnostics.
        if status != "ok":
            output += err.read(max(0, limit - len(output.encode()))).decode(
                "utf-8", errors="replace"
            )
        return Outcome(
            status, child.returncode, output, time.monotonic() - started
        )
