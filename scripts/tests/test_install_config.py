"""Installer ownership regressions; every config and link is temporary."""

import argparse
import importlib.util
import json
import os
import subprocess
import pathlib

import pytest
import tomlkit

SOURCE = pathlib.Path(__file__).resolve().parents[1] / "install_config.py"
SPEC = importlib.util.spec_from_file_location("install_config", SOURCE)
INSTALL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALL)


def mcp_args(tmp_path: pathlib.Path, client: str = "antigravity"):
    """Builds isolated launcher/config arguments."""
    root = tmp_path / 'clone "quoted" \\ backslash'
    return argparse.Namespace(
        config=str(
            tmp_path / ("config.toml" if client == "codex" else "config.json")
        ),
        client=client,
        python=str(root / ".venv/bin/python"),
        server=str(root / "server.py"),
        name="cite-check",
        mode="install",
        dry_run=False,
    )


def links_args(tmp_path: pathlib.Path, collection: bool = False):
    """Builds an isolated two-skill collection."""
    source = tmp_path / "clone/skills"
    for name in ("cite-check", "co-writer"):
        (source / name).mkdir(parents=True)
        (source / name / "SKILL.md").write_text("test skill")
    return argparse.Namespace(
        source=str(source),
        target=str(tmp_path / "links"),
        mode="install",
        dry_run=False,
        collection=collection,
        legacy_registry=None,
    )


@pytest.mark.parametrize("collection", [False, True])
@pytest.mark.parametrize("dangling", [False, True])
def test_foreign_symlinks_survive_install_and_uninstall(
    tmp_path: pathlib.Path,
    collection: bool,
    dangling: bool,
) -> None:
    """Even same-name dangling foreign links are never overwritten/pruned."""
    args = links_args(tmp_path, collection)
    target = pathlib.Path(args.target)
    target.mkdir()
    foreign = tmp_path / "foreign"
    if not dangling:
        foreign.mkdir()
    link = target / ("science-skills" if collection else "cite-check")
    link.symlink_to(foreign)
    for mode in ("install", "uninstall"):
        args.mode = mode
        with pytest.raises(ValueError, match="unowned"):
            INSTALL.update_links(args)
        assert link.readlink() == foreign


def test_links_refresh_move_prune_and_preserve_neighbor(
    tmp_path: pathlib.Path,
) -> None:
    """A recorded moved clone refreshes while a real neighbor survives."""
    args = links_args(tmp_path)
    INSTALL.update_links(args)
    target = pathlib.Path(args.target)
    neighbor = target / "foreign"
    neighbor.mkdir()
    old = pathlib.Path(args.source)
    moved = tmp_path / "moved-skills"
    old.rename(moved)
    args.source = str(moved)
    INSTALL.update_links(args)
    assert (target / "cite-check").readlink() == moved / "cite-check"
    (moved / "co-writer/SKILL.md").unlink()
    INSTALL.update_links(args)
    assert not (target / "co-writer").is_symlink()
    args.mode = "uninstall"
    INSTALL.update_links(args)
    assert not (target / "cite-check").is_symlink()
    assert neighbor.is_dir()


@pytest.mark.parametrize("client", ["codex", "claude", "antigravity"])
def test_mcp_roundtrip_preserves_neighbors_options_and_escaped_paths(
    tmp_path: pathlib.Path,
    client: str,
) -> None:
    """Parsed serialization handles quotes, backslashes and unrelated data."""
    args = mcp_args(tmp_path, client)
    path = pathlib.Path(args.config)
    if client == "codex":
        path.write_text(
            '# keep this comment\nmodel = "test"\n[mcp_servers.other]\nurl="https://example.test"\n'
        )
    else:
        path.write_text(
            json.dumps(
                {
                    "mcpServers": {"other": {"url": "other"}},
                    "projects": {
                        "/project": {
                            "mcpServers": {"cite-check": {"command": "local"}}
                        }
                    },
                }
            )
        )
    INSTALL.update_mcp(args)
    parse = tomlkit.parse if client == "codex" else json.loads
    config = parse(path.read_text())
    field = "mcp_servers" if client == "codex" else "mcpServers"
    assert config[field]["cite-check"]["args"] == [args.server]
    config[field]["cite-check"]["env"] = {"EXAMPLE": "preserve"}
    path.write_text(
        tomlkit.dumps(config) if client == "codex" else json.dumps(config)
    )
    INSTALL.update_mcp(args)
    assert (
        parse(path.read_text())[field]["cite-check"]["env"]["EXAMPLE"]
        == "preserve"
    )
    if client == "codex":
        assert "# keep this comment" in path.read_text()
    args.mode = "uninstall"
    INSTALL.update_mcp(args)
    config = parse(path.read_text())
    assert "cite-check" not in config[field]
    assert "other" in config[field]
    if client != "codex":
        assert (
            config["projects"]["/project"]["mcpServers"]["cite-check"][
                "command"
            ]
            == "local"
        )


@pytest.mark.parametrize("client", ["codex", "claude", "antigravity"])
def test_foreign_mcp_name_preserved(
    tmp_path: pathlib.Path, client: str
) -> None:
    """A familiar name alone never authorizes replacement or removal."""
    args = mcp_args(tmp_path, client)
    path = pathlib.Path(args.config)
    if client == "codex":
        path.write_text(
            '[mcp_servers."cite-check"]\ncommand="foreign"\nargs=[]\n'
        )
    else:
        path.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "cite-check": {"command": "foreign", "args": []}
                    }
                }
            )
        )
    original = path.read_bytes()
    for mode in ("install", "uninstall"):
        args.mode = mode
        with pytest.raises(ValueError, match="not owned"):
            INSTALL.update_mcp(args)
        assert path.read_bytes() == original


def test_mcp_moved_clone_updates_only_recorded_unchanged_launcher(
    tmp_path: pathlib.Path,
) -> None:
    """Receipts permit a missing old clone to refresh, not an edited launcher."""
    args = mcp_args(tmp_path)
    INSTALL.update_mcp(args)
    args.server = str(tmp_path / "moved/server.py")
    args.python = str(tmp_path / "moved/.venv/bin/python")
    INSTALL.update_mcp(args)
    path = pathlib.Path(args.config)
    config = json.loads(path.read_text())
    assert config["mcpServers"]["cite-check"]["args"] == [args.server]
    config["mcpServers"]["cite-check"]["command"] = "foreign"
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="not owned"):
        INSTALL.update_mcp(args)


def test_legacy_codex_alias_removed_with_nested_options(
    tmp_path: pathlib.Path,
) -> None:
    """Removing a legacy owned table removes its nested env but no neighbors."""
    args = mcp_args(tmp_path, "codex")
    doc = tomlkit.document()
    doc["mcp_servers"] = {
        "cite_check": {
            "command": args.python,
            "args": [args.server],
            "env": {"X": "1"},
        },
        "other": {"command": "foreign"},
    }
    path = pathlib.Path(args.config)
    path.write_text(tomlkit.dumps(doc))
    INSTALL.update_mcp(args)
    config = tomlkit.parse(path.read_text())
    assert config["mcp_servers"]["cite-check"]["env"]["X"] == "1"
    assert "cite_check" not in config["mcp_servers"]
    assert config["mcp_servers"]["other"]["command"] == "foreign"


def test_dry_run_writes_nothing(tmp_path: pathlib.Path) -> None:
    """Dry runs neither create lockfiles nor configs nor ownership receipts."""
    args = links_args(tmp_path)
    args.dry_run = True
    before = sorted(str(path) for path in tmp_path.rglob("*"))
    INSTALL.update_links(args)
    mcp = mcp_args(tmp_path, "codex")
    mcp.dry_run = True
    INSTALL.update_mcp(mcp)
    assert sorted(str(path) for path in tmp_path.rglob("*")) == before


def test_antigravity_registry_migrates_only_owned_entry(
    tmp_path: pathlib.Path,
) -> None:
    """Move to documented global skill folders preserves foreign entries."""
    args = links_args(tmp_path)
    legacy = tmp_path / "skills.json"
    legacy.write_text(
        json.dumps(
            {
                "entries": [{"path": args.source}, {"path": "/foreign"}],
                "other": True,
            }
        )
    )
    args.legacy_registry = str(legacy)
    INSTALL.update_links(args)
    assert json.loads(legacy.read_text()) == {
        "entries": [{"path": "/foreign"}],
        "other": True,
    }
    assert (pathlib.Path(args.target) / "cite-check/SKILL.md").is_file()


@pytest.mark.parametrize("contents", ["{broken", "[]", '{"mcpServers": []}'])
def test_malformed_config_is_not_overwritten(
    tmp_path: pathlib.Path, contents: str
) -> None:
    """Incomplete/unexpected configs must fail closed without changing bytes."""
    args = mcp_args(tmp_path)
    path = pathlib.Path(args.config)
    path.write_text(contents)
    with pytest.raises(ValueError):
        INSTALL.update_mcp(args)
    assert path.read_text() == contents


def test_skill_real_directory_survives(tmp_path: pathlib.Path) -> None:
    """A user-owned same-name directory is a conflict, never a link target."""
    args = links_args(tmp_path)
    existing = pathlib.Path(args.target) / "cite-check"
    existing.mkdir(parents=True)
    marker = existing / "mine"
    marker.write_text("keep")
    with pytest.raises(ValueError, match="unowned"):
        INSTALL.update_links(args)
    assert marker.read_text() == "keep"


def test_shell_skill_install_and_uninstall(tmp_path: pathlib.Path) -> None:
    """The shell entrypoint uses isolated targets for every skill harness."""
    targets = {
        "CLAUDE_CONFIG_DIR": tmp_path / "claude",
        "GEMINI_CONFIG_DIR": tmp_path / "gemini",
        "AGENTS_SKILLS_DIR": tmp_path / "agents",
    }
    for path in targets.values():
        path.mkdir()
    env = dict(
        os.environ, **{key: str(value) for key, value in targets.items()}
    )
    script = SOURCE.parent / "install.sh"
    for extra in ([], ["--uninstall"]):
        result = subprocess.run(
            ["bash", str(script), "--skip-mcp", *extra],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        for key in ("CLAUDE_CONFIG_DIR", "GEMINI_CONFIG_DIR"):
            link = targets[key] / "skills/cite-check"
            assert link.is_symlink() is (not extra)
        assert (
            targets["AGENTS_SKILLS_DIR"] / "science-skills"
        ).is_symlink() is (not extra)
