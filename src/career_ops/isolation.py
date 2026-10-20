"""Read-only fingerprints proving the parallel run did not change the old setup.

The rehearsal and the automated suite both need evidence that JobGremlin only
wrote inside its own workspace.  This module snapshots the current installation
without writing to it:

* ``~/.hermes`` (Hermes state and, by default, its allowlist);
* the user cron table and ``~/.config/systemd/user`` timers;
* ``~/.local/bin`` (the installed command entry points);
* the configured read-only career-ops checkout (``CAREER_OPS_UPSTREAM``).

A snapshot records file hashes, sizes and mtimes, symlink targets, directory
entries and the output of read-only commands such as ``crontab -l``.  Comparing
two snapshots names every entry that changed.  Nothing here reads file contents
back into the report, so the evidence does not leak personal data.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from career_ops.paths import WorkspacePaths, expand_path

SNAPSHOT_VERSION = 1
_COMMAND_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class IsolationTarget:
    """One part of the current installation that must stay untouched."""

    name: str
    paths: tuple[Path, ...] = ()
    commands: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class TargetSnapshot:
    """Everything observed for one target at one moment."""

    name: str
    paths: tuple[str, ...]
    commands: tuple[str, ...]
    entries: Mapping[str, Mapping[str, object]]

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "paths": list(self.paths),
            "commands": list(self.commands),
            "entries": {key: dict(value) for key, value in self.entries.items()},
        }

    @property
    def present(self) -> bool:
        return _present(self.entries.values())

    @property
    def observed(self) -> bool:
        return self.present or any(
            _command_available(self, command) for command in self.commands
        )


@dataclass(frozen=True)
class IsolationSnapshot:
    """A comparable view of every target, taken before or after a rehearsal."""

    targets: Mapping[str, TargetSnapshot]

    def as_dict(self) -> dict[str, object]:
        return {
            "version": SNAPSHOT_VERSION,
            "targets": {
                name: target.as_dict() for name, target in self.targets.items()
            },
        }

    def compare(self, earlier: "IsolationSnapshot") -> dict[str, object]:
        """Report entries that differ from ``earlier``, per target."""
        names = list(dict.fromkeys([*earlier.targets, *self.targets]))
        results: list[dict[str, object]] = []
        for name in names:
            before = earlier.targets.get(name)
            after = self.targets.get(name)
            before_entries = dict(before.entries) if before is not None else {}
            after_entries = dict(after.entries) if after is not None else {}
            differences = sorted(
                key
                for key in set(before_entries) | set(after_entries)
                if before_entries.get(key) != after_entries.get(key)
            )
            target = after or before
            command_status = [
                {
                    "command": command,
                    "available": (
                        _command_available(target, command)
                        if target is not None
                        else False
                    ),
                }
                for command in (target.commands if target is not None else ())
            ]
            results.append(
                {
                    "name": name,
                    "paths": list(target.paths) if target is not None else [],
                    "commands": list(target.commands) if target is not None else [],
                    "command_status": command_status,
                    "present_before": before.present if before is not None else False,
                    "present_after": after.present if after is not None else False,
                    "observed": after.observed if after is not None else False,
                    "changed": bool(differences),
                    "differences": differences,
                }
            )
        unobserved = [
            str(result["name"]) for result in results if not result["observed"]
        ]
        return {
            "unchanged": not any(result["changed"] for result in results),
            "observed": not unobserved,
            "unobserved": unobserved,
            "targets": results,
        }


def default_targets(
    paths: WorkspacePaths,
    *,
    environ: Mapping[str, str],
    home: Path | None = None,
) -> tuple[IsolationTarget, ...]:
    """Resolve the current installation targets without writing to them."""
    home = home or expand_path("~", environ)
    allowlist = environ.get("HERMES_ALLOWLIST", "").strip()
    allowlist_path = (
        expand_path(allowlist, environ)
        if allowlist
        else home / ".hermes" / "allowlist.json"
    )
    cron_file = environ.get("HERMES_CRON", "").strip()
    # A user timer directory is not a cron table by itself, so also fingerprint
    # the system cron sources when the user can read them.
    cron_paths = [
        home / ".config" / "systemd" / "user",
        Path("/etc/crontab"),
        Path("/etc/cron.d"),
        Path("/var/spool/cron"),
    ]
    if cron_file:
        cron_paths.append(expand_path(cron_file, environ))
    return (
        IsolationTarget("hermes", paths=(home / ".hermes",)),
        IsolationTarget("allowlist", paths=(allowlist_path,)),
        IsolationTarget(
            "cron",
            paths=tuple(cron_paths),
            commands=(("crontab", "-l"),),
        ),
        IsolationTarget("local_bin", paths=(home / ".local" / "bin",)),
        IsolationTarget("career_ops_upstream", paths=(paths.upstream,)),
    )


def take_snapshot(
    targets: Sequence[IsolationTarget],
    *,
    home: Path | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> IsolationSnapshot:
    """Read every target without modifying it."""
    snapshots: dict[str, TargetSnapshot] = {}
    for target in targets:
        entries: dict[str, Mapping[str, object]] = {}
        for path in target.paths:
            _snapshot_path(path, entries)
        for command in target.commands:
            entries[f"$ {' '.join(command)}"] = _snapshot_command(command, runner)
        snapshots[target.name] = TargetSnapshot(
            name=target.name,
            paths=tuple(_display(path, home) for path in target.paths),
            commands=tuple(" ".join(command) for command in target.commands),
            entries=entries,
        )
    return IsolationSnapshot(targets=snapshots)


def _snapshot_path(path: Path, entries: dict[str, Mapping[str, object]]) -> None:
    key = str(path)
    if path.is_symlink():
        entries[key] = {
            "kind": "symlink",
            "target": os.readlink(path),
        }
        return
    if not path.exists():
        entries[key] = {"kind": "absent"}
        return
    if path.is_file():
        entries[key] = _file_entry(path)
        return
    if not path.is_dir():
        entries[key] = {"kind": "other"}
        return

    entries[key] = {
        "kind": "directory",
        "mtime_ns": path.stat().st_mtime_ns,
    }
    for root, directories, files in os.walk(path, followlinks=False):
        root_path = Path(root)
        for name in sorted(directories):
            child = root_path / name
            if child.is_symlink():
                entries[str(child)] = {
                    "kind": "symlink",
                    "target": os.readlink(child),
                }
            else:
                try:
                    entries[str(child)] = {
                        "kind": "directory",
                        "mtime_ns": child.stat().st_mtime_ns,
                    }
                except OSError as exc:
                    entries[str(child)] = _unreadable(exc)
        for name in sorted(files):
            child = root_path / name
            if child.is_symlink():
                entries[str(child)] = {
                    "kind": "symlink",
                    "target": os.readlink(child),
                }
                continue
            try:
                entries[str(child)] = _file_entry(child)
            except OSError as exc:
                entries[str(child)] = _unreadable(exc)


def _file_entry(path: Path) -> Mapping[str, object]:
    stat = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "kind": "file",
        "sha256": digest.hexdigest(),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _snapshot_command(
    command: Sequence[str],
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> Mapping[str, object]:
    if shutil.which(command[0]) is None:
        return {"kind": "command", "available": False}
    try:
        completed = runner(
            list(command),
            text=True,
            capture_output=True,
            check=False,
            timeout=_COMMAND_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "kind": "command",
            "available": True,
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {
        "kind": "command",
        "available": True,
        "returncode": completed.returncode,
        "stdout_sha256": hashlib.sha256(
            (completed.stdout or "").encode("utf-8")
        ).hexdigest(),
        "stderr_sha256": hashlib.sha256(
            (completed.stderr or "").encode("utf-8")
        ).hexdigest(),
    }


def _unreadable(error: OSError) -> Mapping[str, object]:
    return {"kind": "unreadable", "error": f"{type(error).__name__}: {error}"}


def _command_available(target: TargetSnapshot, command: str) -> bool:
    entry = target.entries.get(f"$ {command}")
    return bool(
        isinstance(entry, Mapping)
        and entry.get("kind") == "command"
        and entry.get("available")
    )


def _present(entries: Iterable[Mapping[str, object]]) -> bool:
    for entry in entries:
        kind = entry.get("kind")
        if kind in {"file", "directory", "symlink", "other", "unreadable"}:
            return True
        if kind == "command" and entry.get("available"):
            return True
    return False


def _display(path: Path, home: Path | None) -> str:
    if home is None:
        return str(path)
    try:
        relative = path.relative_to(home)
    except ValueError:
        return str(path)
    return "~" if not relative.parts else f"~/{relative.as_posix()}"


__all__ = [
    "IsolationSnapshot",
    "IsolationTarget",
    "SNAPSHOT_VERSION",
    "TargetSnapshot",
    "default_targets",
    "take_snapshot",
]
