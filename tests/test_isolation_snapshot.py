from __future__ import annotations

import subprocess
import sys

from career_ops.isolation import IsolationTarget, default_targets, take_snapshot


def test_the_default_targets_cover_hermes_cron_allowlist_local_bin_and_upstream(
    paths, sensitive_home
):
    home = sensitive_home

    targets = default_targets(paths, environ={}, home=home)
    names = {target.name for target in targets}

    assert names == {
        "hermes",
        "allowlist",
        "cron",
        "local_bin",
        "career_ops_upstream",
    }
    allowlist = next(target for target in targets if target.name == "allowlist")
    assert allowlist.paths == (home / ".hermes" / "allowlist.json",)
    upstream = next(target for target in targets if target.name == "career_ops_upstream")
    assert upstream.paths == (paths.upstream,)


def test_the_allowlist_path_can_be_overridden_for_the_real_installation(
    paths, sensitive_home, tmp_path
):
    home = sensitive_home
    custom = tmp_path / "custom-allowlist.json"
    custom.write_text("{}", encoding="utf-8")

    targets = default_targets(
        paths,
        environ={"HERMES_ALLOWLIST": str(custom)},
        home=home,
    )

    allowlist = next(target for target in targets if target.name == "allowlist")
    assert allowlist.paths == (custom,)


def test_two_identical_snapshots_are_unchanged(tmp_path):
    root = tmp_path / "hermes"
    root.mkdir()
    (root / "state.json").write_text("keep", encoding="utf-8")
    target = IsolationTarget("hermes", paths=(root,))

    before = take_snapshot([target])
    after = take_snapshot([target])

    comparison = before.compare(after)
    assert comparison["unchanged"] is True
    assert comparison["targets"][0]["name"] == "hermes"
    assert comparison["targets"][0]["differences"] == []


def test_a_modified_added_or_removed_file_is_reported(tmp_path):
    root = tmp_path / "hermes"
    root.mkdir()
    changed = root / "changed.json"
    removed = root / "removed.json"
    changed.write_text("before", encoding="utf-8")
    removed.write_text("keep", encoding="utf-8")
    target = IsolationTarget("hermes", paths=(root,))
    before = take_snapshot([target])

    changed.write_text("after", encoding="utf-8")
    removed.unlink()
    (root / "added.json").write_text("new", encoding="utf-8")
    after = take_snapshot([target])

    comparison = after.compare(before)
    assert comparison["unchanged"] is False
    differences = comparison["targets"][0]["differences"]
    assert any(path.endswith("changed.json") for path in differences)
    assert any(path.endswith("added.json") for path in differences)
    assert any(path.endswith("removed.json") for path in differences)


def test_a_new_directory_or_symlink_is_reported(tmp_path):
    root = tmp_path / "local-bin"
    root.mkdir()
    target = IsolationTarget("local_bin", paths=(root,))
    before = take_snapshot([target])

    (root / "tool").symlink_to(tmp_path / "elsewhere")
    (root / "nested").mkdir()
    after = take_snapshot([target])

    comparison = after.compare(before)
    assert comparison["unchanged"] is False
    differences = comparison["targets"][0]["differences"]
    assert any(path.endswith("/tool") for path in differences)
    assert any(path.endswith("/nested") for path in differences)


def test_absent_paths_are_still_compared(tmp_path):
    target = IsolationTarget("hermes", paths=(tmp_path / "missing",))
    before = take_snapshot([target])
    after = take_snapshot([target])

    assert before.compare(after)["unchanged"] is True

    (tmp_path / "missing").mkdir()
    comparison = take_snapshot([target]).compare(before)
    assert comparison["unchanged"] is False


def test_command_targets_compare_command_output(tmp_path):
    calls: list[list[str]] = []

    def runner(argv, **kwargs):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "fixed crontab\n", "")

    target = IsolationTarget(
        "cron",
        commands=((sys.executable, "-c", "print('fixed crontab')"),),
    )
    before = take_snapshot([target], runner=runner)
    after = take_snapshot([target], runner=runner)

    assert before.compare(after)["unchanged"] is True
    assert len(calls) == 2
    entry = next(iter(before.as_dict()["targets"]["cron"]["entries"].values()))
    assert entry["kind"] == "command"
    assert entry["returncode"] == 0
