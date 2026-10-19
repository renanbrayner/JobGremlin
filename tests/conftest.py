from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"


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
