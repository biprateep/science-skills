#!/usr/bin/env python3
"""Ownership-aware skill links and MCP config transactions for installers."""

from __future__ import annotations

import argparse
from collections.abc import Iterator, MutableMapping
import contextlib
import fcntl
import json
import os
import pathlib
import tempfile
from typing import Any


def atomic_write(path: pathlib.Path, text: str) -> None:
    """Replaces a config without exposing truncated data or broader permissions.

    Args:
      path: Destination file.
      text: Complete serialized content.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=path.parent, prefix=".install-"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            if path.exists():
                os.fchmod(stream.fileno(), path.stat().st_mode & 0o777)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        pathlib.Path(temporary).unlink(missing_ok=True)


@contextlib.contextmanager
def locked(path: pathlib.Path, dry_run: bool) -> Iterator[None]:
    """Serializes installer transactions, without writing during dry runs.

    Args:
      path: Config file or collection directory.
      dry_run: Whether to avoid all filesystem writes.

    Yields:
      Control while the advisory installation lock is held.
    """
    if dry_run:
        yield
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with pathlib.Path(f"{path}.science-skills.lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def read_json(path: pathlib.Path) -> dict[str, Any]:
    """Reads an object or an absent file; refuses malformed configurations.

    Args:
      path: JSON object file.

    Returns:
      The parsed object, or an empty object for an absent file.
    """
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def owned_launcher(entry: Any, receipt: Any, command: str, server: str) -> bool:
    """Checks exact current ownership or a recorded installation that moved.

    Args:
      entry: Existing client registration.
      receipt: Previously recorded launcher, without credentials.
      command: Expected Python executable.
      server: Expected server path.

    Returns:
      Whether this installer can safely update or remove this registration.
    """
    if not isinstance(entry, MutableMapping):
        return False
    actual = {"command": entry.get("command"), "args": entry.get("args")}
    if actual == {"command": command, "args": [server]}:
        return True
    if actual != receipt or not isinstance(receipt, dict):
        return False
    previous = receipt.get("args")
    return (
        isinstance(previous, list)
        and len(previous) == 1
        and isinstance(previous[0], str)
        and not pathlib.Path(previous[0]).exists()
    )


def update_mcp(args: argparse.Namespace) -> None:
    """Updates only owned entries in a client config, retaining custom options.

    Args:
      args: Parsed mcp arguments including client, path, launcher and mode.
    """
    path = pathlib.Path(args.config)
    receipt_path = pathlib.Path(f"{path}.science-skills.json")
    with locked(path, args.dry_run):
        config: MutableMapping[str, Any]
        if args.client == "codex":
            try:
                # Skill-only installs must not require MCP dependencies.
                import tomlkit  # noqa: PLC0415
            except ImportError as error:
                raise ValueError(
                    "TOML editing requires tomlkit; rerun MCP setup to "
                    "install its requirements before changing this config"
                ) from error
            raw = path.read_text(encoding="utf-8") if path.exists() else ""
            config = tomlkit.parse(raw)
            field = "mcp_servers"
        else:
            config = read_json(path)
            field = "mcpServers"
        servers = config.setdefault(field, {})
        if not isinstance(servers, dict):
            # TOML tables implement MutableMapping, rather than plain dict.
            if not isinstance(servers, MutableMapping):
                raise ValueError(f"{path}: {field} must be a table/object")
        receipts = read_json(receipt_path)
        desired = {"command": args.python, "args": [args.server]}
        names = [args.name]
        if args.client == "codex":
            names.append(args.name.replace("-", "_"))
        for name in names:
            if name not in servers:
                continue
            entry = servers[name]
            if not owned_launcher(
                entry, receipts.get(name), args.python, args.server
            ):
                raise ValueError(
                    f"{path}: {name} is not owned by this installation; "
                    "left unchanged (inspect the existing launcher)"
                )
        changed = False
        # Carry custom options across the legacy underscore-name migration.
        if args.mode == "install" and args.name not in servers:
            for name in names[1:]:
                if name in servers:
                    servers[args.name] = dict(servers[name])
                    changed = True
                    break
        for name in names:
            if name in servers and (
                args.mode == "uninstall" or name != args.name
            ):
                del servers[name]
                receipts.pop(name, None)
                changed = True
        if args.mode == "install":
            entry = servers.setdefault(args.name, {})
            changed = changed or any(
                entry.get(key) != val for key, val in desired.items()
            )
            entry.update(desired)
            receipts[args.name] = desired
        if args.dry_run:
            print(f"  [dry-run] {args.mode} owned {args.name} in {path}")
            return
        if changed:
            if args.client == "codex":
                serialized = tomlkit.dumps(config)
            else:
                serialized = json.dumps(config, indent=2) + "\n"
            atomic_write(path, serialized)
        if receipts or receipt_path.exists():
            atomic_write(receipt_path, json.dumps(receipts, indent=2) + "\n")
        print(f"  {args.client}: {args.mode} {args.name} ({path})")


def update_links(args: argparse.Namespace) -> None:
    """Installs/removes symlinks only when their destination proves ownership.

    Args:
      args: Parsed link arguments: source, target, mode and collection.
    """
    source = pathlib.Path(args.source).resolve()
    target = pathlib.Path(args.target)
    receipt_path = target / ".science-skills-links.json"
    with locked(target, args.dry_run):
        receipts = read_json(receipt_path)
        desired = (
            {"science-skills": str(source)}
            if args.collection
            else {
                item.name: str(item)
                for item in source.iterdir()
                if (item / "SKILL.md").is_file()
            }
        )
        names = set(desired) | set(receipts)
        if target.exists():
            for link in target.iterdir():
                if link.is_symlink() and link.readlink().parent == source:
                    names.add(link.name)
        conflicts = []
        for name in sorted(names):
            link = target / name
            exists = link.exists() or link.is_symlink()
            actual = str(link.readlink()) if link.is_symlink() else None
            expected = desired.get(name)
            receipt = receipts.get(name)
            owned = actual is not None and (
                actual == str(source)
                or (
                    pathlib.Path(actual).parent == source
                    and pathlib.Path(actual).name == name
                )
                or (actual == receipt and not pathlib.Path(actual).exists())
            )
            if exists and not owned:
                if name in desired:
                    conflicts.append(str(link))
                continue
            if args.mode == "uninstall" or expected is None:
                if owned and not args.dry_run:
                    link.unlink()
                    receipts.pop(name, None)
            elif not args.dry_run:
                target.mkdir(parents=True, exist_ok=True)
                if actual != expected:
                    if exists:
                        link.unlink()
                    link.symlink_to(expected)
                receipts[name] = expected
        if not args.dry_run and (receipts or receipt_path.exists()):
            atomic_write(receipt_path, json.dumps(receipts, indent=2) + "\n")
        if args.legacy_registry:
            legacy_path = pathlib.Path(args.legacy_registry)
            legacy = read_json(legacy_path)
            entries = legacy.get("entries", [])
            if not isinstance(entries, list):
                raise ValueError(f"{legacy_path}: entries must be an array")
            kept = [
                entry
                for entry in entries
                if not (
                    isinstance(entry, dict) and entry.get("path") == str(source)
                )
            ]
            if kept != entries and not args.dry_run:
                legacy["entries"] = kept
                atomic_write(legacy_path, json.dumps(legacy, indent=2) + "\n")
        if conflicts:
            raise ValueError(
                "unowned paths left unchanged: " + ", ".join(conflicts)
            )
        prefix = "[dry-run] " if args.dry_run else ""
        print(f"  {prefix}{args.mode} links: {target}")


def main() -> int:
    """Runs installer transactions and reports conflicts without secrets."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    for operation in ("mcp", "links"):
        command = commands.add_parser(operation)
        command.add_argument(
            "--mode", choices=("install", "uninstall"), required=True
        )
        command.add_argument("--dry-run", action="store_true")
        if operation == "mcp":
            command.add_argument(
                "--client",
                choices=("claude", "codex", "antigravity"),
                required=True,
            )
            for option in ("config", "name", "python", "server"):
                command.add_argument(f"--{option}", required=True)
        else:
            command.add_argument("--source", required=True)
            command.add_argument("--target", required=True)
            command.add_argument("--collection", action="store_true")
            command.add_argument("--legacy-registry")
    args = parser.parse_args()
    try:
        (update_mcp if args.operation == "mcp" else update_links)(args)
    except (OSError, ValueError) as error:
        parser.exit(1, f"installation conflict: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
