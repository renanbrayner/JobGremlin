from __future__ import annotations

from pathlib import Path

from career_ops.paths import REPO_ROOT, expand_path, load_environment, resolve_paths


def _clean_environ(monkeypatch, tmp_path: Path) -> None:
    for key in (
        "CAREER_OPS_HOME",
        "CAREER_OPS_UPSTREAM",
        "CAREER_OPS_CONFIG",
        "CAREER_OPS_DATA",
        "CAREER_OPS_OUTPUT",
        "CAREER_OPS_SCRIPTS",
        "CAREER_OPS_ENV_FILE",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


def test_defaults_keep_writes_inside_the_repo(monkeypatch, tmp_path):
    _clean_environ(monkeypatch, tmp_path)

    paths = resolve_paths()

    assert paths.home == REPO_ROOT
    assert paths.config == REPO_ROOT / "config"
    assert paths.data == REPO_ROOT / "data"
    assert paths.output == REPO_ROOT / "output"
    assert paths.scripts == REPO_ROOT / "scripts"
    assert paths.upstream == tmp_path / "home" / ".local" / "share" / "career-ops"


def test_environment_moves_every_writable_directory(monkeypatch, tmp_path):
    _clean_environ(monkeypatch, tmp_path)
    home = tmp_path / "parallel"
    monkeypatch.setenv("CAREER_OPS_HOME", str(home))
    monkeypatch.setenv("CAREER_OPS_UPSTREAM", str(tmp_path / "upstream"))
    monkeypatch.setenv("CAREER_OPS_CONFIG", str(home / "cfg"))
    monkeypatch.setenv("CAREER_OPS_DATA", str(home / "state"))
    monkeypatch.setenv("CAREER_OPS_OUTPUT", str(home / "artifacts"))
    monkeypatch.setenv("CAREER_OPS_SCRIPTS", str(home / "bin"))

    paths = resolve_paths()

    assert paths.home == home
    assert paths.config == home / "cfg"
    assert paths.data == home / "state"
    assert paths.output == home / "artifacts"
    assert paths.scripts == home / "bin"
    assert paths.upstream == tmp_path / "upstream"


def test_workspace_config_wins_over_upstream_and_upstream_is_the_fallback(tmp_path):
    workspace = tmp_path / "workspace"
    upstream = tmp_path / "upstream"
    (workspace / "config").mkdir(parents=True)
    (workspace / "data").mkdir(parents=True)
    (upstream / "config").mkdir(parents=True)
    (upstream / "data").mkdir(parents=True)

    (workspace / "config" / "answers.json").write_text("workspace", encoding="utf-8")
    (upstream / "config" / "answers.json").write_text("upstream", encoding="utf-8")
    (upstream / "data" / "cv-base-pt.json").write_text("upstream", encoding="utf-8")

    paths = resolve_paths(
        {
            "HOME": str(tmp_path / "home"),
            "CAREER_OPS_HOME": str(workspace),
            "CAREER_OPS_UPSTREAM": str(upstream),
        }
    )

    assert paths.read_config("answers.json") == workspace / "config" / "answers.json"
    assert paths.read_config("missing.json") is None
    assert paths.read_data("cv-base-pt.json") == upstream / "data" / "cv-base-pt.json"


def test_env_file_is_loaded_without_overriding_real_environment(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / "config").mkdir(parents=True)
    env_file = workspace / "config" / "career-ops.env"
    env_file.write_text(
        "CAREER_OPS_UPSTREAM=${HOME}/upstream-from-file\n"
        "CAREER_OPS_DATA=${CAREER_OPS_HOME}/state-from-file\n",
        encoding="utf-8",
    )

    paths = resolve_paths(
        {
            "HOME": str(tmp_path / "home"),
            "CAREER_OPS_HOME": str(workspace),
            "CAREER_OPS_OUTPUT": str(workspace / "explicit-output"),
        }
    )

    assert paths.upstream == tmp_path / "home" / "upstream-from-file"
    assert paths.data == workspace / "state-from-file"
    assert paths.output == workspace / "explicit-output"


def test_env_file_can_live_under_a_custom_config_directory(tmp_path):
    workspace = tmp_path / "workspace"
    config = workspace / "custom-config"
    config.mkdir(parents=True)
    (config / "career-ops.env").write_text(
        "CAREER_OPS_DATA=${CAREER_OPS_HOME}/custom-data\n", encoding="utf-8"
    )

    paths = resolve_paths(
        {
            "HOME": str(tmp_path / "home"),
            "CAREER_OPS_HOME": str(workspace),
            "CAREER_OPS_CONFIG": str(config),
        }
    )

    assert paths.config == config
    assert paths.data == workspace / "custom-data"


def test_configured_values_expand_like_env_file_entries(tmp_path):
    environment = {
        "HOME": str(tmp_path / "home"),
        "CAREER_OPS_OUTPUT": str(tmp_path / "workspace" / "output"),
    }

    assert expand_path("$CAREER_OPS_OUTPUT/cv.pdf", environment) == (
        tmp_path / "workspace" / "output" / "cv.pdf"
    )
    assert expand_path("~/cv.pdf", environment) == tmp_path / "home" / "cv.pdf"


def test_load_environment_exposes_the_same_precedence_to_other_modules(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / "config").mkdir(parents=True)
    (workspace / "config" / "career-ops.env").write_text(
        "FROM_FILE=file\nEXPLICIT=file\n", encoding="utf-8"
    )

    values = load_environment(
        {
            "HOME": str(tmp_path / "home"),
            "CAREER_OPS_HOME": str(workspace),
            "EXPLICIT": "environment",
        }
    )

    assert values["FROM_FILE"] == "file"
    assert values["EXPLICIT"] == "environment"
    assert values["CAREER_OPS_HOME"] == str(workspace)


def test_writable_guard_still_refuses_upstream_nested_under_home(tmp_path):
    home = tmp_path / "home"
    upstream = home / ".local" / "share" / "career-ops"
    paths = resolve_paths(
        {
            "HOME": str(home),
            "CAREER_OPS_HOME": str(home),
            "CAREER_OPS_UPSTREAM": str(upstream),
        }
    )

    try:
        paths.assert_writable(upstream / "data" / "nope.json")
    except ValueError as exc:
        assert "read-only" in str(exc)
    else:  # pragma: no cover - failure path
        raise AssertionError("writing into upstream must be refused")


def test_writable_directories_cannot_live_inside_upstream(tmp_path):
    upstream = tmp_path / "upstream"

    try:
        resolve_paths(
            {
                "HOME": str(tmp_path / "home"),
                "CAREER_OPS_HOME": str(upstream / "workspace"),
                "CAREER_OPS_UPSTREAM": str(upstream),
            }
        )
    except ValueError as exc:
        assert "read-only" in str(exc)
    else:  # pragma: no cover - failure path
        raise AssertionError("a workspace nested inside upstream must be refused")


def test_ensure_directories_and_writability_guard(tmp_path):
    workspace = tmp_path / "workspace"
    paths = resolve_paths(
        {
            "HOME": str(tmp_path / "home"),
            "CAREER_OPS_HOME": str(workspace),
            "CAREER_OPS_UPSTREAM": str(tmp_path / "upstream"),
        }
    )

    paths.ensure_directories()

    assert (workspace / "config").is_dir()
    assert (workspace / "data").is_dir()
    assert (workspace / "output").is_dir()

    paths.assert_writable(workspace / "data" / "ok.json")
    try:
        paths.assert_writable(tmp_path / "upstream" / "nope.json")
    except ValueError as exc:
        assert "read-only upstream" in str(exc)
    else:  # pragma: no cover - failure path
        raise AssertionError("writing into upstream must be refused")

    try:
        paths.assert_writable(tmp_path / "elsewhere" / "nope.json")
    except ValueError as exc:
        assert "outside the workspace" in str(exc)
    else:  # pragma: no cover - failure path
        raise AssertionError("writing outside the workspace must be refused")
