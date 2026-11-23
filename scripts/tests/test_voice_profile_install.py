"""Tests for co-writer voice profile setup in scripts/install.sh."""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
INSTALL_SH = REPO_ROOT / "scripts" / "install.sh"


def _isolated_env(tmp_path: pathlib.Path) -> dict[str, str]:
    """Builds an isolated harness and co-writer environment under tmp_path."""
    for name in ("claude", "gemini", "codex", "agents"):
        (tmp_path / name).mkdir(exist_ok=True)
    env = {
        key: val
        for key, val in os.environ.items()
        if key not in ("CO_WRITER_HOME", "CO_WRITER_PROFILE_DIR")
    }
    env.update(
        {
            "CLAUDE_CONFIG_DIR": str(tmp_path / "claude"),
            "GEMINI_CONFIG_DIR": str(tmp_path / "gemini"),
            "CODEX_HOME": str(tmp_path / "codex"),
            "AGENTS_SKILLS_DIR": str(tmp_path / "agents"),
            "CO_WRITER_HOME": str(tmp_path / "co-writer-store"),
        }
    )
    return env


def _run_install(
    args: list[str], env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    """Runs scripts/install.sh non-interactively with stdin closed."""
    return subprocess.run(
        ["bash", str(INSTALL_SH), "--skill", "co-writer", "--skip-mcp", *args],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def test_fresh_install_initializes_starter_profile(
    tmp_path: pathlib.Path,
) -> None:
    """Non-interactive install creates a starter profile and prints path."""
    env = _isolated_env(tmp_path)
    dry = _run_install(["--dry-run"], env)
    assert dry.returncode == 0, dry.stdout + dry.stderr
    store = pathlib.Path(env["CO_WRITER_HOME"])
    assert not (store / "profile").exists()

    res = _run_install([], env)
    assert res.returncode == 0, res.stdout + res.stderr
    voice = store / "profile" / "voice-profile.md"
    assert voice.is_file()
    assert "**Version:** 0.0.0" in voice.read_text(encoding="utf-8")
    assert str(store / "profile") in res.stdout

    # Uninstall must keep the user's personal voice profile intact.
    un = _run_install(["--uninstall"], env)
    assert un.returncode == 0, un.stdout + un.stderr
    assert voice.is_file()


def test_install_links_local_voice_profile(tmp_path: pathlib.Path) -> None:
    """Passing a local directory links ~/.co-writer/profile to that repo."""
    env = _isolated_env(tmp_path)
    private_dir = tmp_path / "my-voice"
    private_dir.mkdir()
    (private_dir / "voice-profile.md").write_text(
        "# Voice\n**Version:** 0.4.0\n", encoding="utf-8"
    )
    res = _run_install(["--voice-profile", str(private_dir)], env)
    assert res.returncode == 0, res.stdout + res.stderr
    profile_link = pathlib.Path(env["CO_WRITER_HOME"]) / "profile"
    assert profile_link.is_symlink()
    assert profile_link.resolve() == private_dir.resolve()
    assert "0.4.0" in res.stdout


def test_install_clones_git_voice_profile_and_branch(
    tmp_path: pathlib.Path,
) -> None:
    """Passing a git URL and --voice-branch clones directly into profile."""
    env = _isolated_env(tmp_path)
    origin = tmp_path / "voice-origin"
    origin.mkdir()
    git = ["git", "-C", str(origin)]
    subprocess.run([*git, "init", "-b", "main"], check=True)
    subprocess.run([*git, "config", "user.name", "Author"], check=True)
    subprocess.run(
        [*git, "config", "user.email", "author@example.com"], check=True
    )
    (origin / "voice-profile.md").write_text(
        "# Voice\n**Version:** 1.0.0\n", encoding="utf-8"
    )
    subprocess.run([*git, "add", "voice-profile.md"], check=True)
    subprocess.run([*git, "commit", "-m", "main voice"], check=True)

    subprocess.run([*git, "checkout", "-b", "custom"], check=True)
    (origin / "voice-profile.md").write_text(
        "# Voice\n**Version:** 2.0.0\n", encoding="utf-8"
    )
    subprocess.run([*git, "add", "voice-profile.md"], check=True)
    subprocess.run([*git, "commit", "-m", "custom branch voice"], check=True)

    res = _run_install(
        [
            "--voice-profile",
            f"file://{origin}",
            "--voice-branch",
            "custom",
        ],
        env,
    )
    assert res.returncode == 0, res.stdout + res.stderr
    cloned = pathlib.Path(env["CO_WRITER_HOME"]) / "profile"
    assert (cloned / ".git").is_dir()
    assert "2.0.0" in (cloned / "voice-profile.md").read_text(encoding="utf-8")
    assert "2.0.0" in res.stdout

    # Verify cowriter.py sees the cloned profile directly.
    check = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "skills/co-writer/scripts/cowriter.py"),
            "profile",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "2.0.0 (personalized)" in check.stdout
