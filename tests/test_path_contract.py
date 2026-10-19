from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from conftest import REPO_ROOT, SCRIPTS_DIR

FIELDS = ("home", "upstream", "config", "data", "output", "scripts")


def _contract_env(workspace: Path, upstream: Path, config: Path, home: Path) -> dict[str, str]:
    base = {key: value for key, value in os.environ.items() if not key.startswith("CAREER_OPS_")}
    return {
        **base,
        "HOME": str(home),
        "CAREER_OPS_HOME": str(workspace),
        "CAREER_OPS_UPSTREAM": str(upstream),
        "CAREER_OPS_CONFIG": str(config),
        "CAREER_OPS_OUTPUT": str(workspace / "real-output"),
    }


def _python_contract(env: dict[str, str]) -> dict[str, str]:
    result = subprocess.run(
        [
            "python3",
            "-c",
            "import json; from career_ops.paths import resolve_paths; "
            "p = resolve_paths(); "
            "print(json.dumps({k: str(getattr(p, k)) for k in "
            "['home','upstream','config','data','output','scripts']}))",
        ],
        env={**env, "PYTHONPATH": str(REPO_ROOT / "src")},
        text=True,
        capture_output=True,
        check=True,
        cwd=str(REPO_ROOT),
    )
    return json.loads(result.stdout)


def _node_contract(env: dict[str, str]) -> dict[str, str]:
    module = (SCRIPTS_DIR / "lib" / "paths.mjs").as_uri()
    script = (
        f"import * as p from {json.dumps(module)}; "
        "console.log(JSON.stringify({home: p.WORKSPACE_ROOT, upstream: p.UPSTREAM_ROOT, "
        "config: p.CONFIG_DIR, data: p.DATA_DIR, output: p.OUTPUT_DIR, scripts: p.SCRIPTS_DIR}))"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        env=env,
        text=True,
        capture_output=True,
        check=True,
        cwd=str(REPO_ROOT),
    )
    return json.loads(result.stdout)


def _shell_contract(env: dict[str, str]) -> dict[str, str]:
    script = (
        'set -e; . "$1"; '
        'printf "%s\\n" "$CAREER_OPS_HOME" "$CAREER_OPS_UPSTREAM" "$CAREER_OPS_CONFIG" '
        '"$CAREER_OPS_DATA" "$CAREER_OPS_OUTPUT" "$CAREER_OPS_SCRIPTS"'
    )
    result = subprocess.run(
        ["bash", "-c", script, "_", str(SCRIPTS_DIR / "lib" / "paths.sh")],
        env=env,
        text=True,
        capture_output=True,
        check=True,
        cwd=str(REPO_ROOT),
    )
    return dict(zip(FIELDS, result.stdout.splitlines(), strict=True))


def test_all_three_path_helpers_agree(tmp_path):
    workspace = tmp_path / "workspace"
    upstream = tmp_path / "upstream"
    config = workspace / "custom-config"
    home = tmp_path / "home"
    config.mkdir(parents=True)
    (config / "career-ops.env").write_text(
        "CAREER_OPS_DATA=${CAREER_OPS_HOME}/from-file\n"
        "CAREER_OPS_OUTPUT=${CAREER_OPS_HOME}/file-output\n",
        encoding="utf-8",
    )
    env = _contract_env(workspace, upstream, config, home)

    python_paths = _python_contract(env)
    node_paths = _node_contract(env)
    shell_paths = _shell_contract(env)

    assert python_paths == node_paths == shell_paths
    assert python_paths["data"] == str(workspace / "from-file")
    assert python_paths["output"] == str(workspace / "real-output")
    assert python_paths["config"] == str(config)
