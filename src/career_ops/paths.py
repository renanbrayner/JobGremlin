"""Workspace paths for the parallel career-automation system.

The new system must be able to read the installed career-ops checkout while
only ever writing inside this repository.  Every command should resolve paths
through this module (or its shell/Node twins in ``scripts/lib``) instead of
hardcoding ``$HOME`` locations.

Resolution order for each value:

1. the real environment;
2. ``config/career-ops.env`` in the workspace (simple ``KEY=VALUE`` file);
3. a safe workspace-relative default.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Mapping

REPO_ROOT = Path(__file__).resolve().parents[2]
_UPSTREAM_DEFAULT = "~/.local/share/career-ops"


def _environment(environ: Mapping[str, str] | None) -> dict[str, str]:
    return dict(os.environ if environ is None else environ)


def _expand(raw: str, environ: Mapping[str, str]) -> Path:
    text = Template(raw).safe_substitute(environ)
    if text == "~" or text.startswith("~/"):
        home = environ.get("HOME") or str(Path.home())
        text = home + text[1:]
    return Path(text).expanduser()


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, separator, raw = line.partition("=")
        if not separator:
            continue
        key = key.strip()
        raw = raw.strip()
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "'\"":
            raw = raw[1:-1]
        values[key] = raw
    return values


def _load_env_file(environ: dict[str, str]) -> None:
    home = _expand(environ.get("CAREER_OPS_HOME", str(REPO_ROOT)), environ)
    config = _expand(environ.get("CAREER_OPS_CONFIG", str(home / "config")), environ)
    env_file = _expand(
        environ.get("CAREER_OPS_ENV_FILE", str(config / "career-ops.env")),
        environ,
    )
    if not env_file.is_file():
        return

    context = {**environ, "CAREER_OPS_HOME": str(home)}
    for key, raw in _parse_env_file(env_file).items():
        if key in environ:
            continue
        environ[key] = Template(raw).safe_substitute(context)
        context[key] = environ[key]


def _resolved(environ: Mapping[str, str], key: str, default: str) -> Path:
    return _expand(environ.get(key, default), environ).resolve()


@dataclass(frozen=True)
class WorkspacePaths:
    """The only writable locations the parallel system may use."""

    home: Path
    upstream: Path
    config: Path
    data: Path
    output: Path
    scripts: Path

    def ensure_directories(self) -> None:
        for directory in (self.config, self.data, self.output):
            directory.mkdir(parents=True, exist_ok=True)

    def read_config(self, name: str) -> Path | None:
        """Prefer the workspace copy, fall back to the read-only upstream one."""
        return self._first_existing(self.config / name, self.upstream / "config" / name)

    def read_data(self, name: str) -> Path | None:
        """Prefer workspace data, fall back to the read-only upstream data."""
        return self._first_existing(self.data / name, self.upstream / "data" / name)

    def assert_writable(self, path: str | Path) -> None:
        candidate = Path(path).resolve()
        upstream = self.upstream.resolve()
        if candidate == upstream or candidate.is_relative_to(upstream):
            raise ValueError(
                f"refusing to write {candidate}: it is inside the read-only upstream {upstream}"
            )

        root = self.home.resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError(
                f"refusing to write {candidate}: it is outside the workspace {root}"
            ) from exc

    @staticmethod
    def _first_existing(*candidates: Path) -> Path | None:
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return None


def load_environment(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return the environment with ``config/career-ops.env`` applied.

    Real environment variables win; the env file fills the gaps.  An explicit
    mapping replaces the process environment but still honours the workspace
    env file, matching the path contract used by the copied scripts.
    """
    values = _environment(environ)
    _load_env_file(values)
    return values


def expand_path(raw: str, environ: Mapping[str, str] | None = None) -> Path:
    """Expand ``$VARS`` and ``~`` in a configured path.

    Configuration values follow the same precedence and expansion rules as the
    env file, including values that arrive through the real environment.
    """
    return _expand(raw, _environment(environ))


def resolve_paths(environ: Mapping[str, str] | None = None) -> WorkspacePaths:
    """Build the workspace path contract from the environment/env file."""
    values = load_environment(environ)
    home = _resolved(values, "CAREER_OPS_HOME", str(REPO_ROOT))
    upstream = _resolved(values, "CAREER_OPS_UPSTREAM", _UPSTREAM_DEFAULT)
    paths = WorkspacePaths(
        home=home,
        upstream=upstream,
        config=_resolved(values, "CAREER_OPS_CONFIG", str(home / "config")),
        data=_resolved(values, "CAREER_OPS_DATA", str(home / "data")),
        output=_resolved(values, "CAREER_OPS_OUTPUT", str(home / "output")),
        scripts=_resolved(values, "CAREER_OPS_SCRIPTS", str(home / "scripts")),
    )
    for name, directory in (
        ("CAREER_OPS_CONFIG", paths.config),
        ("CAREER_OPS_DATA", paths.data),
        ("CAREER_OPS_OUTPUT", paths.output),
    ):
        if directory == upstream or directory.is_relative_to(upstream):
            raise ValueError(
                f"{name}={directory} is inside the read-only upstream checkout {upstream}"
            )
    return paths
