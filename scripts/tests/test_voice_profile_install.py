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


def _init_git_voice_repo(
    repo: pathlib.Path, version: str = "1.0.0", branch: str = "main"
) -> None:
    """Initializes a local git repository containing a voice profile."""
    repo.mkdir(parents=True, exist_ok=True)
    git = ["git", "-C", str(repo)]
    subprocess.run([*git, "init", "-b", branch], check=True)
    subprocess.run([*git, "config", "user.name", "Author"], check=True)
    subprocess.run(
        [*git, "config", "user.email", "author@example.com"], check=True
    )
    (repo / "voice-profile.md").write_text(
        f"# Voice\n**Version:** {version}\n", encoding="utf-8"
    )
    subprocess.run([*git, "add", "voice-profile.md"], check=True)
    subprocess.run([*git, "commit", "-m", f"voice {version}"], check=True)


def test_reinstall_auto_syncs_cloned_git_voice_profile(
    tmp_path: pathlib.Path,
) -> None:
    """Rerunning install.sh fast-forwards a cloned voice repo to upstream."""
    env = _isolated_env(tmp_path)
    origin = tmp_path / "voice-origin"
    _init_git_voice_repo(origin, version="1.0.0", branch="main")

    first = _run_install(["--voice-profile", f"file://{origin}"], env)
    assert first.returncode == 0, first.stdout + first.stderr
    cloned = pathlib.Path(env["CO_WRITER_HOME"]) / "profile"
    assert "1.0.0" in (cloned / "voice-profile.md").read_text(encoding="utf-8")

    # Advance upstream to v1.1.0.
    (origin / "voice-profile.md").write_text(
        "# Voice\n**Version:** 1.1.0\n", encoding="utf-8"
    )
    subprocess.run(
        ["git", "-C", str(origin), "commit", "-am", "voice 1.1.0"], check=True
    )

    # Dry-run reports sync without modifying the clone.
    dry = _run_install(["--dry-run"], env)
    assert dry.returncode == 0, dry.stdout + dry.stderr
    assert "would sync" in dry.stdout
    assert "1.0.0" in (cloned / "voice-profile.md").read_text(encoding="utf-8")

    # Plain reinstall fast-forwards automatically and prints the new version.
    second = _run_install([], env)
    assert second.returncode == 0, second.stdout + second.stderr
    assert "synced:" in second.stdout
    assert "1.1.0" in second.stdout
    assert "1.1.0" in (cloned / "voice-profile.md").read_text(encoding="utf-8")

    # Re-running with the same --voice-profile URL also syncs instead of
    # failing on an existing directory, and honors --voice-branch switches.
    subprocess.run(
        ["git", "-C", str(origin), "checkout", "-b", "alt"], check=True
    )
    (origin / "voice-profile.md").write_text(
        "# Voice\n**Version:** 2.0.0\n", encoding="utf-8"
    )
    subprocess.run(
        ["git", "-C", str(origin), "commit", "-am", "voice 2.0.0"], check=True
    )
    third = _run_install(
        ["--voice-profile", f"file://{origin}", "--voice-branch", "alt"], env
    )
    assert third.returncode == 0, third.stdout + third.stderr
    assert "2.0.0" in third.stdout
    assert "2.0.0" in (cloned / "voice-profile.md").read_text(encoding="utf-8")


def test_reinstall_auto_syncs_symlinked_git_repo_and_respects_dirty_tree(
    tmp_path: pathlib.Path,
) -> None:
    """Reinstall syncs symlinked git voice repos unless locally modified."""
    env = _isolated_env(tmp_path)
    origin = tmp_path / "voice-origin"
    _init_git_voice_repo(origin, version="1.0.0", branch="main")
    local_clone = tmp_path / "local-voice"
    subprocess.run(
        ["git", "clone", f"file://{origin}", str(local_clone)], check=True
    )

    first = _run_install(["--voice-profile", str(local_clone)], env)
    assert first.returncode == 0, first.stdout + first.stderr

    # Advance upstream to 1.2.0 and verify plain reinstall syncs via symlink.
    (origin / "voice-profile.md").write_text(
        "# Voice\n**Version:** 1.2.0\n", encoding="utf-8"
    )
    subprocess.run(
        ["git", "-C", str(origin), "commit", "-am", "voice 1.2.0"], check=True
    )
    second = _run_install([], env)
    assert second.returncode == 0, second.stdout + second.stderr
    assert "1.2.0" in (local_clone / "voice-profile.md").read_text(
        encoding="utf-8"
    )

    # Dirty local edit must not be clobbered on reinstall.
    (local_clone / "voice-profile.md").write_text(
        "# Voice\n**Version:** 1.2.0-local\n", encoding="utf-8"
    )
    (origin / "voice-profile.md").write_text(
        "# Voice\n**Version:** 1.3.0\n", encoding="utf-8"
    )
    subprocess.run(
        ["git", "-C", str(origin), "commit", "-am", "voice 1.3.0"], check=True
    )
    third = _run_install([], env)
    assert third.returncode == 0, third.stdout + third.stderr
    assert "uncommitted local changes" in third.stderr
    assert "1.2.0-local" in (local_clone / "voice-profile.md").read_text(
        encoding="utf-8"
    )
