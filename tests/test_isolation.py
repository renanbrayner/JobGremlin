from __future__ import annotations

import re
from pathlib import Path

from conftest import SCRIPTS_DIR


def _snapshot(root: Path) -> dict[str, tuple[int, bytes]]:
    return {
        str(path.relative_to(root)): (path.stat().st_mtime_ns, path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_workspace_commands_never_write_to_upstream(run, workspace, fake_upstream):
    pool = workspace / "data" / "pool-test.tsv"
    pool.write_text(
        "id\ttitle\tkeyword\n1001\tDesenvolvedor React\treact\n",
        encoding="utf-8",
    )
    Path(f"{pool}.raw").write_text("1001|Desenvolvedor React\treact\n", encoding="utf-8")
    cv = workspace / "output" / "cv-run-isolation.pdf"
    cv.write_bytes(b"%PDF")
    before = _snapshot(fake_upstream)

    assert run("career-ops-triage", str(pool), "--json").returncode == 0
    assert run("career-ops-pool-fix-titles", str(pool)).returncode == 0
    assert run("career-ops-enrich").returncode == 2
    assert run("career-ops-cv", "--slug", "iso", "--no-pdf").returncode == 0
    assert (
        run(
            "career-ops-run",
            "--job",
            "4411222",
            "--cv",
            str(cv),
            "--adapter",
            "fake",
        ).returncode
        == 0
    )

    assert _snapshot(fake_upstream) == before


def test_commands_refuse_to_write_into_upstream(run, fake_upstream, env):
    upstream_pool = fake_upstream / "data" / "pool-test.tsv"
    upstream_pool.write_text(
        "id\ttitle\tkeyword\n1001\tDesenvolvedor React\treact\n",
        encoding="utf-8",
    )
    Path(f"{upstream_pool}.raw").write_text(
        "1001|Desenvolvedor React\treact\n", encoding="utf-8"
    )
    before = _snapshot(fake_upstream)

    fix = run("career-ops-pool-fix-titles", str(upstream_pool))
    assert fix.returncode != 0
    assert "upstream" in (fix.stderr + fix.stdout).lower()

    pool = run("career-ops-pool", "--out", str(fake_upstream / "data" / "pool"))
    assert pool.returncode != 0
    assert "upstream" in (pool.stderr + pool.stdout).lower()

    env["CAREER_OPS_OUTPUT"] = str(fake_upstream / "output")
    cv = run("career-ops-cv", "--slug", "nope", "--no-pdf")
    assert cv.returncode != 0
    assert "upstream" in (cv.stderr + cv.stdout).lower()

    assert _snapshot(fake_upstream) == before


def test_commands_do_not_touch_home_sensitive_locations(run, env, workspace, tmp_path):
    home = tmp_path / "home"
    (home / ".hermes").mkdir(parents=True)
    (home / ".local" / "bin").mkdir(parents=True)
    (home / ".hermes" / "state.json").write_text("keep", encoding="utf-8")
    (home / ".local" / "bin" / "tool").write_text("keep", encoding="utf-8")
    env["HOME"] = str(home)

    pool = workspace / "data" / "pool-home.tsv"
    pool.write_text(
        "id\ttitle\tkeyword\n1001\tDesenvolvedor React\treact\n", encoding="utf-8"
    )
    cv = workspace / "output" / "cv-home-isolation.pdf"
    cv.write_bytes(b"%PDF")
    before = _snapshot(home)

    assert run("career-ops-triage", str(pool), "--json").returncode == 0
    assert run("career-ops-browser", "--check").returncode == 0
    assert run("career-ops-cv", "--slug", "home", "--no-pdf").returncode == 0
    assert (
        run(
            "career-ops-run",
            "--job",
            "4411222",
            "--cv",
            str(cv),
            "--adapter",
            "fake",
        ).returncode
        == 0
    )

    assert _snapshot(home) == before


def test_cv_refuses_an_upstream_tracker_or_pdf_index(run, env, fake_upstream):
    env["CAREER_OPS_TRACKER"] = str(fake_upstream / "data" / "applications.md")
    result = run("career-ops-cv", "--slug", "guard", "--no-pdf")

    assert result.returncode != 0
    assert "upstream" in (result.stderr + result.stdout).lower()

    env.pop("CAREER_OPS_TRACKER")
    env["CAREER_OPS_PDF_INDEX"] = str(fake_upstream / "data" / "pdf-index.tsv")
    result = run("career-ops-cv", "--slug", "guard", "--no-pdf")

    assert result.returncode != 0
    assert "upstream" in (result.stderr + result.stdout).lower()


def test_copied_scripts_are_real_files_not_symlinks():
    files = [path for path in SCRIPTS_DIR.rglob("*") if path.is_file()]

    assert files
    assert all(not path.is_symlink() for path in files)


def test_no_copied_script_points_at_the_original_installation():
    allowed_upstream_defaults = {
        SCRIPTS_DIR / "lib" / "paths.sh",
        SCRIPTS_DIR / "lib" / "paths.mjs",
    }

    for path in SCRIPTS_DIR.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        assert not re.search(r"/home/[^/\s]+/", text), f"{path} hardcodes a user home"
        assert "/.local/bin" not in text, f"{path} hardcodes ~/.local/bin"
        if path not in allowed_upstream_defaults:
            assert ".local/share/career-ops" not in text, (
                f"{path} hardcodes the upstream career-ops checkout"
            )
