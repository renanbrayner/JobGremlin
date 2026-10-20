from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from career_ops.paths import WorkspacePaths

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
# Keep subprocess tests independent of the shell's asdf shims. Some tests
# replace HOME, and an asdf shim then cannot find its version.
STABLE_PATH = os.pathsep.join([os.defpath, os.environ.get("PATH", "")])

FRONTEND_JD = """\
Desenvolvedor Front-end Sênior

Requisitos:
- React e TypeScript.
"""

DEVOPS_JD = """\
Software Engineer

Requirements:
- Kubernetes and Terraform.
"""


class FakeClock:
    """Deterministic, manually advanced clock."""

    def __init__(self, start: datetime) -> None:
        self.current = start

    def __call__(self) -> datetime:
        return self.current

    def advance(self, milliseconds: int) -> None:
        self.current += timedelta(milliseconds=milliseconds)


class FakeScreenshotter:
    def __init__(self, payload: bytes = b"png-bytes") -> None:
        self.payload = payload
        self.calls: list[Path] = []

    def __call__(self, path: Path) -> None:
        self.calls.append(path)
        path.write_bytes(self.payload)


def read_events(recorder) -> list[dict]:
    return [
        json.loads(line)
        for line in recorder.events_path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def invoke(run, *args: str) -> tuple:
    """Run ``career-ops-run`` and decode its JSON envelope."""
    result = run("career-ops-run", *args)
    payload = json.loads(result.stdout) if result.stdout.strip() else None
    return result, payload


def write_cv(workspace: Path, name: str = "cv-renan-react-2026-10-19.pdf") -> Path:
    path = workspace / "output" / name
    path.write_bytes(b"%PDF-fake")
    return path


def write_candidates(
    workspace: Path,
    count: int,
    *,
    start: int = 1,
    title: str = "Desenvolvedor React",
    location: str = "Recife, PE",
    workplace: str = "Remote",
    name: str = "candidates.json",
) -> Path:
    path = workspace / "data" / name
    path.write_text(
        json.dumps(
            [
                {
                    "id": str(index),
                    "title": title,
                    "location": location,
                    "workplace": workplace,
                    "company": f"Company {index}",
                }
                for index in range(start, start + count)
            ]
        ),
        encoding="utf-8",
    )
    return path


def read_queue(workspace: Path) -> dict[str, dict]:
    payload = json.loads(
        (workspace / "data" / "queue.json").read_text(encoding="utf-8")
    )
    return {record["id"]: record for record in payload["records"]}


def read_run_state(workspace: Path, run_id: str) -> dict:
    return json.loads(
        (workspace / "data" / "runs" / f"{run_id}.json").read_text(encoding="utf-8")
    )


def write_jd_fixtures(
    workspace: Path,
    entries: dict[str, str],
    name: str = "jd-fixtures",
) -> Path:
    root = workspace / "data" / name
    root.mkdir(parents=True, exist_ok=True)
    for job_id, text in entries.items():
        (root / f"{job_id}.txt").write_text(text, encoding="utf-8")
    return root


class ScriptedRunner:
    """Stand-in for subprocess.run that returns a scripted sequence.

    An entry may be a ``CompletedProcess`` or an exception to raise.  Used by
    tests that exercise command composition without running a browser.
    """

    def __init__(self, *responses: object) -> None:
        self.responses = list(responses)
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def completed_process(
    argv,
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(argv, returncode, stdout, stderr)


class FakeRunner:
    """Stand-in for subprocess.run used by capture/recovery tests."""

    def __init__(
        self,
        *,
        returncode: int = 0,
        error: Exception | None = None,
        stderr: str = "boom",
        write_file: bool = True,
    ) -> None:
        self.returncode = returncode
        self.error = error
        self.stderr = stderr
        self.write_file = write_file
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        if self.error is not None:
            raise self.error
        if self.returncode == 0 and self.write_file:
            Path(argv[-1]).write_bytes(b"command-png")
        return subprocess.CompletedProcess(argv, self.returncode, "", self.stderr)


@pytest.fixture
def paths(workspace: Path, fake_upstream: Path) -> WorkspacePaths:
    return WorkspacePaths(
        home=workspace,
        upstream=fake_upstream,
        config=workspace / "config",
        data=workspace / "data",
        output=workspace / "output",
        scripts=workspace / "scripts",
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A throwaway workspace with the same writable layout as the repo."""
    root = tmp_path / "workspace"
    for name in ("config", "data", "output"):
        (root / name).mkdir(parents=True)
    return root


@pytest.fixture
def fake_upstream(tmp_path: Path) -> Path:
    """A read-only stand-in for ~/.local/share/career-ops.

    It contains just enough data and helper scripts for the copied commands to
    exercise their upstream read path without touching the real installation.
    """
    upstream = tmp_path / "upstream"
    (upstream / "config").mkdir(parents=True)
    (upstream / "data").mkdir()
    (upstream / "output").mkdir()

    (upstream / "config" / "answers-hermes.json").write_text(
        json.dumps({"current company": "Freelance"}),
        encoding="utf-8",
    )
    (upstream / "data" / "cv-base-pt.json").write_text(
        json.dumps(
            {
                "candidate": {"full_name": "Test Person"},
                "sections": {},
                "competencies": [],
            }
        ),
        encoding="utf-8",
    )

    # Minimal stand-ins for the upstream build helpers. Their only job here is
    # to prove that career-ops-cv resolves them from upstream but writes its
    # own artifacts into the workspace.
    (upstream / "build-cv-html.mjs").write_text(
        "import { writeFileSync } from 'node:fs';\n"
        "writeFileSync(process.argv[3], '<html>stub</html>');\n",
        encoding="utf-8",
    )
    (upstream / "generate-pdf.mjs").write_text(
        "import { writeFileSync } from 'node:fs';\n"
        "writeFileSync(process.argv[3], 'stub-pdf');\n",
        encoding="utf-8",
    )
    return upstream


@pytest.fixture
def env(workspace: Path, fake_upstream: Path) -> dict[str, str]:
    base = {key: value for key, value in os.environ.items() if not key.startswith("CAREER_OPS_")}
    return {
        **base,
        "CAREER_OPS_HOME": str(workspace),
        "CAREER_OPS_UPSTREAM": str(fake_upstream),
        "CAREER_OPS_CONFIG": str(workspace / "config"),
        "CAREER_OPS_DATA": str(workspace / "data"),
        "CAREER_OPS_OUTPUT": str(workspace / "output"),
        "CAREER_OPS_SCRIPTS": str(SCRIPTS_DIR),
        "PATH": STABLE_PATH,
    }


@pytest.fixture
def run(env: dict[str, str]):
    def _run(
        script: str,
        *args: str,
        cwd: str | Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(SCRIPTS_DIR / script), *args],
            env=env,
            cwd=str(cwd) if cwd else None,
            text=True,
            capture_output=True,
            check=False,
            timeout=60,
        )

    return _run
