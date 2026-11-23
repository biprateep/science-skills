"""Tests for decoupled voice profiles, lexicon loading, and harvester fixes."""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import types

SKILL = pathlib.Path(__file__).resolve().parents[1]
COWRITER_PATH = SKILL / "scripts" / "cowriter.py"
MANNERED_PATH = SKILL / "scripts" / "check_mannered.py"


def _load_module(name: str, path: pathlib.Path) -> types.ModuleType:
    """Loads a standalone script as a module."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _run_cowriter(
    args: list[str], env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    """Runs cowriter.py with the given arguments and environment."""
    return subprocess.run(
        [sys.executable, str(COWRITER_PATH), *args],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_starter_profile_init_and_override(tmp_path: pathlib.Path) -> None:
    """Fresh users start at v0.0.0 and build a profile without touching repo."""
    store = tmp_path / "store"
    env = {
        key: val
        for key, val in os.environ.items()
        if key not in ("CO_WRITER_HOME", "CO_WRITER_PROFILE_DIR")
    }
    env["CO_WRITER_HOME"] = str(store)

    before = _run_cowriter(["profile", "--json"], env)
    assert before.returncode == 0, before.stderr
    info_before = json.loads(before.stdout)
    assert info_before["initialized"] is False
    assert info_before["starter"] is True
    assert info_before["version"] == "0.0.0"

    init_res = _run_cowriter(["init"], env)
    assert init_res.returncode == 0, init_res.stderr
    voice = store / "profile" / "voice-profile.md"
    assert voice.is_file()
    assert (store / "profile" / "counterexamples.md").is_file()
    assert (store / "profile" / "lexicon.json").is_file()

    # Re-running init must not clobber user edits.
    voice.write_text("# Voice\n**Version:** 0.1.0\n", encoding="utf-8")
    init_again = _run_cowriter(["init"], env)
    assert init_again.returncode == 0, init_again.stderr
    assert "0.1.0" in voice.read_text(encoding="utf-8")

    after = _run_cowriter(["profile", "--json"], env)
    assert after.returncode == 0, after.stderr
    info_after = json.loads(after.stdout)
    assert info_after["initialized"] is True
    assert info_after["starter"] is False
    assert info_after["version"] == "0.1.0"


def test_link_private_voice_repo(tmp_path: pathlib.Path) -> None:
    """Linking a private voice directory symlinks ~/.co-writer/profile."""
    store = tmp_path / "store"
    private_repo = tmp_path / "private-voice"
    private_repo.mkdir()
    (private_repo / "voice-profile.md").write_text(
        "# Voice\n**Version:** 1.2.3\n", encoding="utf-8"
    )
    (private_repo / "counterexamples.md").write_text(
        "# Counterexamples\n", encoding="utf-8"
    )
    env = {
        key: val
        for key, val in os.environ.items()
        if key not in ("CO_WRITER_HOME", "CO_WRITER_PROFILE_DIR")
    }
    env["CO_WRITER_HOME"] = str(store)

    res = _run_cowriter(["init", "--link", str(private_repo)], env)
    assert res.returncode == 0, res.stderr
    assert (store / "profile").is_symlink()
    assert (store / "profile").resolve() == private_repo.resolve()

    prof = _run_cowriter(["profile", "--json"], env)
    assert prof.returncode == 0, prof.stderr
    info = json.loads(prof.stdout)
    assert info["linked"] is True
    assert info["version"] == "1.2.3"

    # CO_WRITER_PROFILE_DIR overrides the symlinked store profile.
    other = tmp_path / "other-profile"
    other.mkdir()
    (other / "voice-profile.md").write_text(
        "# Voice\n**Version:** 9.0.0\n", encoding="utf-8"
    )
    env_override = dict(env, CO_WRITER_PROFILE_DIR=str(other))
    prof_override = _run_cowriter(["profile", "--json"], env_override)
    assert prof_override.returncode == 0, prof_override.stderr
    assert json.loads(prof_override.stdout)["version"] == "9.0.0"


def test_check_mannered_profile_lexicon(tmp_path: pathlib.Path) -> None:
    """Profile lexicon adds personal Never rules and allow-list exemptions."""
    mannered = _load_module("check_mannered_test", MANNERED_PATH)
    sample = tmp_path / "draft.tex"
    sample.write_text(
        "Notably, we delve into this topic. It is worth noting that x = 1.\n",
        encoding="utf-8",
    )

    starter_dir = tmp_path / "starter"
    starter_dir.mkdir()
    starter_hits, _ = mannered.hits(sample, profile_dir=starter_dir)
    starter_phrases = {hit[2] for hit in starter_hits}
    assert "delve" in starter_phrases
    assert "It is worth noting" in starter_phrases
    assert "Notably," not in starter_phrases

    custom_dir = tmp_path / "custom"
    custom_dir.mkdir()
    (custom_dir / "lexicon.json").write_text(
        json.dumps(
            {
                "never": [[r"(?:^|[.!?]\s+)(Notably),", "remove"]],
                "allow": [r"\bdelve\b"],
            }
        ),
        encoding="utf-8",
    )
    custom_hits, _ = mannered.hits(sample, profile_dir=custom_dir)
    custom_phrases = {hit[2] for hit in custom_hits}
    assert "Notably," in custom_phrases
    assert "It is worth noting" in custom_phrases
    assert "delve" not in custom_phrases


def test_antigravity_new_edit_tools() -> None:
    """Harvester recognizes Antigravity edit_file and write_file arguments."""
    cw = _load_module("cowriter_test", COWRITER_PATH)
    needle = "/tmp/paper"
    edit_args = json.dumps(
        {
            "Path": "/tmp/paper/main.tex",
            "Target": "Old sentence in draft.",
            "Replacement": "New sentence in draft.",
        }
    )
    events = list(
        cw._antigravity_edit(edit_args, needle, "2026-11-21T19:00:00", "ag#1")
    )
    assert len(events) == 1
    assert events[0].text == "New sentence in draft."
    assert events[0].before == "Old sentence in draft."

    write_args = json.dumps(
        {
            "Path": "/tmp/paper/main.tex",
            "Content": "Full rewritten section text.",
        }
    )
    write_events = list(
        cw._antigravity_edit(write_args, needle, "2026-11-21T19:05:00", "ag#2")
    )
    assert len(write_events) == 1
    assert write_events[0].text == "Full rewritten section text."
    assert not write_events[0].before


def test_git_fingerprints_scoped_and_ai_trailers(
    tmp_path: pathlib.Path,
) -> None:
    """Bib fingerprints do not taint main.tex; AI trailers flag commits."""
    cw = _load_module("cowriter_git_test", COWRITER_PATH)
    repo = tmp_path / "paper"
    repo.mkdir()
    git = ["git", "-C", str(repo)]
    subprocess.run([*git, "init", "-b", "main"], check=True)
    subprocess.run([*git, "config", "user.name", "Author"], check=True)
    subprocess.run(
        [*git, "config", "user.email", "author@example.com"], check=True
    )

    (repo / "main.tex").write_text(
        "Initial paragraph text.\n", encoding="utf-8"
    )
    (repo / "bibliography.bib").write_text(
        "@comment{cite-check: source=ads; id=123}\n", encoding="utf-8"
    )
    subprocess.run([*git, "add", "main.tex", "bibliography.bib"], check=True)
    subprocess.run([*git, "commit", "-m", "human edit with bib"], check=True)
    sha_human = subprocess.run(
        [*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert cw._agent_fingerprints(repo, sha_human, "main.tex") is False

    (repo / "main.tex").write_text("Agent tightened prose.\n", encoding="utf-8")
    subprocess.run([*git, "add", "main.tex"], check=True)
    subprocess.run(
        [
            *git,
            "commit",
            "-m",
            (
                "tighten prose\n\n"
                "Co-Authored-By: Claude Sonnet <noreply@anthropic.com>"
            ),
        ],
        check=True,
    )
    sha_ai = subprocess.run(
        [*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert cw._agent_fingerprints(repo, sha_ai, "main.tex") is True
