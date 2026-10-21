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
import re
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


def _safe_skill_name(name: object) -> bool:
    """Accept one skill basename, never a path or receipt traversal."""
    return isinstance(name, str) and bool(
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name)
    )


def _destination(link: pathlib.Path, value: str) -> pathlib.Path:
    path = pathlib.Path(value)
    return (path if path.is_absolute() else link.parent / path).resolve()


def _owned_link(
    link: pathlib.Path, source: pathlib.Path, receipt: str | None
) -> bool:
    if not link.is_symlink():
        return False
    actual = _destination(link, str(link.readlink()))
    expected = source if link.name == "science-skills" else source / link.name
    return actual == expected.resolve() or bool(
        receipt
        and actual == _destination(link, receipt)
        and not actual.exists()
    )


def _link_plan(args: argparse.Namespace) -> dict[str, Any]:
    """Validate the entire link/legacy migration before any filesystem write."""
    source = pathlib.Path(args.source).resolve()
    target = pathlib.Path(args.target)
    if target.resolve() == source or source in target.resolve().parents:
        raise ValueError(
            "skill target must not be inside the source collection"
        )
    discovered = {
        item.name: str(item)
        for item in source.iterdir()
        if (item / "SKILL.md").is_file()
    }
    if any(not _safe_skill_name(name) for name in discovered):
        raise ValueError("source contains an invalid skill name")
    selection = list(dict.fromkeys(getattr(args, "skill", None) or []))
    if any(
        not _safe_skill_name(name) or name not in discovered
        for name in selection
    ):
        raise ValueError("unknown or invalid selected skill")
    if args.collection and "science-skills" in discovered:
        raise ValueError(
            "science-skills is reserved for the Codex collection link"
        )
    receipt_path = target / ".science-skills-links.json"
    if receipt_path.is_symlink():
        raise ValueError("skill ownership receipt must not be a symlink")
    receipts = read_json(receipt_path)
    if any(
        not _safe_skill_name(name) or not isinstance(value, str)
        for name, value in receipts.items()
    ):
        raise ValueError("malformed skill ownership receipt")
    legacy_path = (
        pathlib.Path(args.legacy_registry) if args.legacy_registry else None
    )
    legacy = read_json(legacy_path) if legacy_path else {}
    entries = legacy.get("entries", [])
    if not isinstance(entries, list) or any(
        not isinstance(entry, dict) or not isinstance(entry.get("path"), str)
        for entry in entries
    ):
        raise ValueError("legacy skill registry entries must have string paths")
    kept = [entry for entry in entries if entry["path"] != str(source)]
    legacy_owned = kept != entries
    collection = target / "science-skills"
    collection_exists = collection.exists() or collection.is_symlink()
    collection_owned = _owned_link(
        collection, source, receipts.get("science-skills")
    )
    if (
        args.collection
        and selection
        and collection_exists
        and not collection_owned
    ):
        raise ValueError(f"unowned collection left unchanged: {collection}")
    converting = bool(
        selection and (collection_owned and args.collection or legacy_owned)
    )
    notes = []
    if converting:
        notes.append(
            "convert owned collection discovery to individual links; "
            "preserve unselected skills"
        )
        retained = (
            set(discovered) - set(selection)
            if args.mode == "uninstall"
            else set(discovered)
        )
        desired = {name: discovered[name] for name in retained}
        names = set(discovered)
        if args.collection and collection_owned:
            names.add("science-skills")
    elif selection:
        desired = (
            {name: discovered[name] for name in selection}
            if args.mode == "install"
            else {}
        )
        names = set(selection)
    else:
        desired = (
            ({"science-skills": str(source)} if args.collection else discovered)
            if args.mode == "install"
            else {}
        )
        names = set(discovered) | set(receipts)
        if args.collection:
            names.add("science-skills")
        if target.exists():
            names.update(
                link.name
                for link in target.iterdir()
                if link.is_symlink() and _owned_link(link, source, None)
            )
    install, remove, conflicts = {}, [], []
    updated_receipts = dict(receipts)
    for name in sorted(names):
        link = target / name
        exists = link.exists() or link.is_symlink()
        owned = _owned_link(link, source, receipts.get(name))
        expected = desired.get(name)
        if exists and not owned:
            if (
                expected is not None
                or name in selection
                or (
                    not args.collection and not selection and name in discovered
                )
                or (args.collection and name == "science-skills")
            ):
                conflicts.append(str(link))
            continue
        if expected is not None:
            if not exists or _destination(
                link, str(link.readlink())
            ) != pathlib.Path(expected).resolve():
                install[name] = expected
            updated_receipts[name] = expected
        else:
            if owned:
                remove.append(name)
            updated_receipts.pop(name, None)
    if conflicts:
        raise ValueError(
            "unowned paths left unchanged: " + ", ".join(conflicts)
        )
    if legacy_owned:
        legacy["entries"] = kept
    return {
        "target": target,
        "receipt_path": receipt_path,
        "receipts": updated_receipts,
        "install": install,
        "remove": remove,
        "legacy_path": legacy_path if legacy_owned else None,
        "legacy": legacy,
        "notes": notes,
        "selection": selection,
    }


def _publish_link(link: pathlib.Path, destination: str) -> None:
    """Atomically replace a proven owned link without following its target."""
    with tempfile.TemporaryDirectory(
        dir=link.parent, prefix=".install-links-"
    ) as directory:
        staged = pathlib.Path(directory) / "link"
        staged.symlink_to(destination)
        os.replace(staged, link)


def update_links(args: argparse.Namespace) -> None:
    """Apply a validated selection while preserving unselected/foreign skills.

    Collection conversions publish retained links before removing the old
    discovery path. Default-all installs publish the collection before pruning
    owned individual links. No operation writes through a collection symlink.

    Args:
      args: Link source, target, mode, optional skill selection and collection.
    """
    plan = _link_plan(args)
    target = plan["target"]
    scope = ", ".join(plan["selection"]) or "all skills"
    prefix = "[dry-run] " if args.dry_run else ""
    print(f"  {prefix}{args.mode} links: {target} ({scope})")
    for note in plan["notes"]:
        print(f"  {prefix}{note}")
    for name, destination in sorted(plan["install"].items()):
        print(f"  {prefix}link {target / name} -> {destination}")
    for name in plan["remove"]:
        print(f"  {prefix}remove owned link {target / name}")
    if plan["legacy_path"]:
        print(
            f"  {prefix}remove owned collection registration "
            f"from {plan['legacy_path']}"
        )
    if args.dry_run:
        return
    with locked(target, False):
        plan = _link_plan(args)
        if plan["install"]:
            target.mkdir(parents=True, exist_ok=True)
        for name, destination in sorted(plan["install"].items()):
            _publish_link(target / name, destination)
        # Retained links exist before a whole-collection alias is removed.
        for name in plan["remove"]:
            (target / name).unlink()
        if plan["receipts"] or plan["receipt_path"].exists():
            atomic_write(
                plan["receipt_path"],
                json.dumps(plan["receipts"], indent=2) + "\n",
            )
        if plan["legacy_path"]:
            atomic_write(
                plan["legacy_path"], json.dumps(plan["legacy"], indent=2) + "\n"
            )

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
            command.add_argument("--skill", action="append")
            command.add_argument("--legacy-registry")
    args = parser.parse_args()
    try:
        (update_mcp if args.operation == "mcp" else update_links)(args)
    except (OSError, ValueError) as error:
        parser.exit(1, f"installation conflict: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
