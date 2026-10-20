"""Portable logging and explicit in-session digest regression tests."""

import os
import pathlib
import subprocess
import sys

import pytest

SKILL = pathlib.Path(__file__).resolve().parents[1]


def test_codex_log_and_session(tmp_path: pathlib.Path) -> None:
    """Codex records deliveries and closing notes without transcript access."""
    paper = tmp_path / "main.tex"
    paper.write_text("The observed signal has a measured amplitude of 10.")
    env = dict(os.environ, CO_WRITER_HOME=str(tmp_path / "store"))
    common = [sys.executable, str(SKILL / "scripts/cowriter.py")]
    for args in (
        [
            "log",
            "--slot",
            "results",
            "--register",
            "journal",
            "--input",
            "Draft passage.",
            "--output",
            "Delivered passage.",
        ],
        [
            "session",
            "--asked",
            "Rewrite",
            "--produced",
            "Rewritten passage",
            "--wrong",
            "nothing",
        ],
    ):
        result = subprocess.run(
            common + args + ["--file", str(paper), "--agent", "codex"],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
    logs = list((tmp_path / "store/papers").glob("*/log/*.md"))
    assert len(logs) == 2
    assert all("agent: codex" in path.read_text() for path in logs)


@pytest.mark.parametrize("packet_status", [0, 3, 7])
def test_manual_digest_never_launches_agent(
    tmp_path: pathlib.Path, packet_status: int
) -> None:
    """Manual mode prepares a packet or propagates errors without an agent."""
    binaries = tmp_path / "bin"
    binaries.mkdir()
    packet = tmp_path / "packet with spaces"
    packet.mkdir()
    python_stub = binaries / "python3"
    python_stub.write_text(
        "#!/bin/bash\n"
        'if [[ "$2" == "packet" ]]; then\n'
        '  echo "$TEST_PACKET"\n'
        '  exit "$TEST_STATUS"\n'
        "fi\n"
        '[[ "$2" == "harvest" ]]\n'
    )
    python_stub.chmod(0o755)
    agent = binaries / "claude"
    agent.write_text('#!/bin/bash\ntouch "$TEST_MARKER"\nexit 17\n')
    agent.chmod(0o755)
    marker = tmp_path / "agent-started"
    env = dict(
        os.environ,
        PATH=f"{binaries}:{os.environ['PATH']}",
        CO_WRITER_HOME=str(tmp_path / "store"),
        CO_WRITER_DIGEST_CMD=str(agent),
        TEST_PACKET=str(packet),
        TEST_STATUS=str(packet_status),
        TEST_MARKER=str(marker),
    )
    result = subprocess.run(
        ["bash", str(SKILL / "scripts/update.sh"), "--manual"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == (7 if packet_status == 7 else 0)
    assert not marker.exists()
    if packet_status == 0:
        assert "current agent session" in result.stdout


def test_update_rejects_unknown_options() -> None:
    """Misspelled manual mode must not accidentally launch an agent."""
    result = subprocess.run(
        ["bash", str(SKILL / "scripts/update.sh"), "--manul"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
