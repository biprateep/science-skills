# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.16.0
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---
"""Selective installer lifecycles use isolated harnesses and inert MCP stubs."""

# %%
import dataclasses
import json
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

SCRIPTS = pathlib.Path(__file__).resolve().parents[1]
SKILLS = {"cite-check", "co-scientist", "co-writer"}


@dataclasses.dataclass
class Installation:
    """A disposable clone and harness configuration tree, with no live tools."""

    root: pathlib.Path
    clone: pathlib.Path
    environment: dict[str, str]
    targets: dict[str, pathlib.Path]
    log: pathlib.Path

    def run(
        self,
        *arguments: str,
        uninstall: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        """Run the real shell entrypoint only against fixture paths."""
        script = "uninstall.sh" if uninstall else "install.sh"
        return subprocess.run(
            ["bash", str(self.clone / "scripts" / script), *arguments],
            env=self.environment,
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )

    def succeeds(self, *arguments: str, uninstall: bool = False) -> None:
        """Assert an installer command completed, preserving diagnostics."""
        result = self.run(*arguments, uninstall=uninstall)
        assert result.returncode == 0, result.stdout + result.stderr

    def calls(self) -> list[list[str]]:
        """Read inert toolbox dispatch records without executing any toolbox."""
        if not self.log.exists():
            return []
        return [line.split("\t") for line in self.log.read_text().splitlines()]

    def snapshot(self) -> dict[str, tuple[str, bytes | str]]:
        """Capture files, directories and links for before-write assertions."""
        result: dict[str, tuple[str, bytes | str]] = {}
        for path in self.root.rglob("*"):
            name = str(path.relative_to(self.root))
            if path.is_symlink():
                result[name] = ("link", str(path.readlink()))
            elif path.is_dir():
                result[name] = ("directory", "")
            else:
                result[name] = ("file", path.read_bytes())
        return result

    def visible(self, target: pathlib.Path) -> set[str]:
        """Read skill discovery as per-skill links or a whole collection."""
        found: set[str] = set()
        if not target.exists():
            return found
        for child in target.iterdir():
            if (child / "SKILL.md").is_file():
                found.add(child.name)
            elif child.name == "science-skills" and child.is_dir():
                found.update(
                    skill.name
                    for skill in child.iterdir()
                    if (skill / "SKILL.md").is_file()
                )
        return found

    def assert_visible(self, expected: set[str]) -> None:
        """Check all harnesses expose exactly the intended fixture skills."""
        for name in ("claude", "gemini"):
            assert self.visible(self.targets[name] / "skills") == expected
        assert self.visible(self.targets["agents"]) == expected


@pytest.fixture
def installation(tmp_path: pathlib.Path) -> Installation:
    """Copy installers and replace every toolbox with an inert dispatcher."""
    clone = tmp_path / "clone with spaces"
    scripts = clone / "scripts"
    scripts.mkdir(parents=True)
    for name in ("install.sh", "uninstall.sh", "install_config.py"):
        shutil.copy2(SCRIPTS / name, scripts / name)
    for name in SKILLS:
        skill = clone / "skills" / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("Fixture skill: " + name)
        if name != "co-writer":
            toolbox = skill / "mcp"
            toolbox.mkdir()
            (toolbox / ".venv").mkdir()
            (toolbox / ".venv" / "untouched").write_text("inert fixture")
            (toolbox / "setup_mcp.sh").write_text(
                "#!/usr/bin/env bash\nset -euo pipefail\n"
                'for arg in "$@"; do\n'
                '  [ "$arg" != --dry-run ] || exit 0\n'
                "done\n"
                f"printf '%s' '{name}' >> \"$SELECTIVE_TEST_LOG\"\n"
                'for arg in "$@"; do\n'
                '  printf \'\\t%s\' "$arg" >> "$SELECTIVE_TEST_LOG"\n'
                "done\n"
                "printf '\\n' >> \"$SELECTIVE_TEST_LOG\"\n"
            )
    targets = {
        name: tmp_path / name
        for name in ("claude", "gemini", "codex", "agents")
    }
    for path in targets.values():
        path.mkdir()
    binary = tmp_path / "bin"
    binary.mkdir()
    (binary / "python3").symlink_to(sys.executable)
    log = tmp_path / "mcp-calls.log"
    environment = dict(
        os.environ,
        CLAUDE_CONFIG_DIR=str(targets["claude"]),
        GEMINI_CONFIG_DIR=str(targets["gemini"]),
        CODEX_HOME=str(targets["codex"]),
        AGENTS_SKILLS_DIR=str(targets["agents"]),
        XDG_CONFIG_HOME=str(tmp_path / "config"),
        PATH=str(binary) + os.pathsep + os.environ["PATH"],
        SELECTIVE_TEST_LOG=str(log),
    )
    return Installation(tmp_path, clone, environment, targets, log)


# %%
def test_fresh_selective_install_dispatches_only_selected_toolbox(
    installation: Installation,
) -> None:
    installation.succeeds("--skill", "cite-check", "--skip-keys")
    installation.assert_visible({"cite-check"})
    assert installation.calls() == [["cite-check", "--skip-keys"]]
    assert not (installation.targets["agents"] / "science-skills").exists()
    for name in ("cite-check", "co-scientist"):
        marker = installation.clone / "skills" / name / "mcp/.venv/untouched"
        assert marker.read_text() == "inert fixture"


def test_skill_without_mcp_does_not_dispatch_other_toolboxes(
    installation: Installation,
) -> None:
    installation.succeeds("--skill", "co-writer")
    installation.assert_visible({"co-writer"})
    assert installation.calls() == []


def test_repeated_selection_is_deduplicated_and_additive(
    installation: Installation,
) -> None:
    installation.succeeds(
        "--skill", "cite-check", "--skill", "co-writer", "--skill", "cite-check"
    )
    installation.assert_visible({"cite-check", "co-writer"})
    assert installation.calls() == [["cite-check"]]
    installation.succeeds("--skill", "co-scientist", "--skip-mcp")
    installation.assert_visible(SKILLS)
    assert installation.calls() == [["cite-check"]]


@pytest.mark.parametrize(
    "arguments",
    [
        ["--skill", "missing"],
        ["--skill", "../cite-check"],
        ["--skill", ""],
        ["--skill"],
        ["--skill", "--dry-run"],
        ["--skill", "cite-check", "--skill", "missing"],
    ],
)
def test_invalid_selection_is_rejected_before_any_writes(
    installation: Installation,
    arguments: list[str],
) -> None:
    before = installation.snapshot()
    for uninstall in (False, True):
        result = installation.run(*arguments, uninstall=uninstall)
        assert result.returncode != 0
        assert installation.snapshot() == before


def test_selected_install_and_uninstall_dry_runs_write_nothing(
    installation: Installation,
) -> None:
    for uninstall in (False, True):
        before = installation.snapshot()
        installation.succeeds(
            "--skill", "cite-check", "--dry-run", uninstall=uninstall
        )
        assert installation.snapshot() == before


def test_selected_uninstall_preserves_other_links_and_dispatches_one_mcp(
    installation: Installation,
) -> None:
    installation.succeeds(
        "--skill", "cite-check", "--skill", "co-scientist", "--skip-mcp"
    )
    installation.succeeds(
        "--skill", "cite-check", "--purge-keys", uninstall=True
    )
    installation.assert_visible({"co-scientist"})
    assert installation.calls() == [
        ["cite-check", "--uninstall", "--purge-keys"]
    ]
    marker = installation.clone / "skills/co-scientist/mcp/.venv/untouched"
    assert marker.read_text() == "inert fixture"


def test_default_all_install_still_registers_collection_and_all_toolboxes(
    installation: Installation,
) -> None:
    installation.succeeds("--skip-keys")
    installation.assert_visible(SKILLS)
    collection = installation.targets["agents"] / "science-skills"
    assert collection.is_symlink()
    assert collection.resolve() == installation.clone / "skills"
    assert {tuple(call) for call in installation.calls()} == {
        ("cite-check", "--skip-keys"),
        ("co-scientist", "--skip-keys"),
    }


def test_full_install_then_selective_uninstall_preserves_unselected_skills(
    installation: Installation,
) -> None:
    installation.succeeds("--skip-mcp")
    installation.succeeds("--skill", "cite-check", "--skip-mcp", uninstall=True)
    installation.assert_visible(SKILLS - {"cite-check"})
    collection = installation.targets["agents"] / "science-skills"
    assert not collection.is_symlink()
    assert (installation.clone / "skills/cite-check/SKILL.md").is_file()
    installation.succeeds("--skill", "cite-check", "--skip-mcp", uninstall=True)
    installation.assert_visible(SKILLS - {"cite-check"})


def test_selective_install_after_full_install_keeps_previously_exposed_skills(
    installation: Installation,
) -> None:
    installation.succeeds("--skip-mcp")
    installation.succeeds("--skill", "cite-check", "--skip-mcp")
    installation.assert_visible(SKILLS)


def test_partial_to_full_to_uninstalled_lifecycle_is_idempotent(
    installation: Installation,
) -> None:
    installation.succeeds("--skill", "cite-check", "--skip-mcp")
    installation.succeeds("--skip-mcp")
    installation.assert_visible(SKILLS)
    assert (installation.targets["agents"] / "science-skills").is_symlink()
    assert not (installation.targets["agents"] / "cite-check").is_symlink()
    installation.succeeds("--skip-mcp", uninstall=True)
    installation.assert_visible(set())
    installation.succeeds("--skip-mcp", uninstall=True)
    installation.assert_visible(set())


def test_foreign_selected_link_survives_both_operations(
    installation: Installation,
) -> None:
    target = installation.targets["claude"] / "skills"
    target.mkdir()
    foreign = installation.root / "foreign-skill"
    foreign.mkdir()
    (foreign / "SKILL.md").write_text("User owned skill")
    link = target / "cite-check"
    link.symlink_to(foreign)
    for uninstall in (False, True):
        result = installation.run(
            "--skill", "cite-check", "--skip-mcp", uninstall=uninstall
        )
        assert result.returncode != 0
        assert link.readlink() == foreign
        assert (foreign / "SKILL.md").read_text() == "User owned skill"


def test_collection_conversion_conflict_preserves_original_collection(
    installation: Installation,
) -> None:
    installation.succeeds("--skip-mcp")
    agents = installation.targets["agents"]
    foreign = agents / "co-writer"
    foreign.mkdir()
    (foreign / "owned").write_text("keep")
    result = installation.run(
        "--skill", "cite-check", "--skip-mcp", uninstall=True
    )
    assert result.returncode != 0
    assert (agents / "science-skills").is_symlink()
    assert (
        agents / "science-skills"
    ).resolve() == installation.clone / "skills"
    assert (foreign / "owned").read_text() == "keep"


def test_legacy_antigravity_collection_migrates_without_losing_other_skills(
    installation: Installation,
) -> None:
    registry = installation.targets["gemini"] / "skills.json"
    foreign = {"path": "/foreign/skills", "custom": True}
    registry.write_text(
        json.dumps(
            {
                "entries": [
                    {"path": str(installation.clone / "skills")},
                    foreign,
                ],
                "unrelated": {"enabled": True},
            }
        )
    )
    installation.succeeds("--skill", "cite-check", "--skip-mcp", uninstall=True)
    assert installation.visible(installation.targets["gemini"] / "skills") == (
        SKILLS - {"cite-check"}
    )
    assert json.loads(registry.read_text()) == {
        "entries": [foreign],
        "unrelated": {"enabled": True},
    }


def test_unselected_foreign_link_and_receipt_survive_selective_install(
    installation: Installation,
) -> None:
    installation.succeeds("--skill", "co-writer", "--skip-mcp")
    agents = installation.targets["agents"]
    foreign = installation.root / "foreign"
    foreign.mkdir()
    (agents / "unrelated").symlink_to(foreign)
    installation.succeeds("--skill", "cite-check", "--skip-mcp")
    installation.assert_visible({"cite-check", "co-writer"})
    assert (agents / "unrelated").readlink() == foreign
    receipt = json.loads((agents / ".science-skills-links.json").read_text())
    assert set(receipt) == {"cite-check", "co-writer"}


# %%
def test_collection_conversion_dry_run_preserves_all_files_and_links(
    installation: Installation,
) -> None:
    installation.succeeds("--skip-mcp")
    registry = installation.targets["gemini"] / "skills.json"
    registry.write_text(
        json.dumps(
            {
                "entries": [
                    {"path": str(installation.clone / "skills")},
                    {"path": "/foreign/skills"},
                ],
                "unrelated": True,
            }
        )
    )
    before = installation.snapshot()
    installation.succeeds("--skill", "cite-check", "--dry-run", uninstall=True)
    assert installation.snapshot() == before
    installation.assert_visible(SKILLS)


def test_equals_selection_spelling_roundtrips_through_uninstaller(
    installation: Installation,
) -> None:
    installation.succeeds("--skill=cite-check", "--skip-mcp")
    installation.assert_visible({"cite-check"})
    installation.succeeds("--skill=cite-check", "--skip-mcp", uninstall=True)
    installation.assert_visible(set())
    assert installation.calls() == []


def test_symlinked_source_skill_reruns_and_uninstalls_without_touching_source(
    installation: Installation,
) -> None:
    source = installation.clone / "skills/co-writer"
    external = installation.root / "external valid skill"
    source.rename(external)
    source.symlink_to(external, target_is_directory=True)
    original = (external / "SKILL.md").read_bytes()
    installation.succeeds("--skill", "co-writer", "--skip-mcp")
    installation.assert_visible({"co-writer"})
    before = installation.snapshot()
    repeated = installation.run("--skill", "co-writer", "--skip-mcp")
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "\n  link " not in repeated.stdout
    assert installation.snapshot() == before
    installation.succeeds("--skill", "co-writer", "--skip-mcp", uninstall=True)
    installation.assert_visible(set())
    assert source.is_symlink()
    assert source.readlink() == external
    assert (external / "SKILL.md").read_bytes() == original
