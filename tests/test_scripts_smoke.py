from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from conftest import SCRIPTS_DIR

NODE = shutil.which("node", path=os.defpath) or "node"


def _write_pool(path: Path) -> None:
    path.write_text(
        "id\ttitle\tkeyword\n"
        "1001\tDesenvolvedor React\treact\n"
        "1002\tQA Engineer\tqa\n"
        "1003\tEstágio Desenvolvedor\tjunior\n",
        encoding="utf-8",
    )


def test_career_ops_triage_classifies_a_pool_from_the_workspace(run, workspace):
    pool = workspace / "data" / "pool-test.tsv"
    _write_pool(pool)

    result = run("career-ops-triage", str(pool), "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["total"] == 3
    assert [row["id"] for row in payload["shortlist"]] == ["1001"]
    assert payload["descartadas"] == {"junior/estagio": 1, "qa/teste": 1}


def test_pool_fix_titles_updates_workspace_data_only(run, workspace):
    pool = workspace / "data" / "pool-fix.tsv"
    pool.write_text("id\ttitle\tkeyword\n1001\tCurto\tkw\n", encoding="utf-8")
    (workspace / "data" / "pool-fix.tsv.raw").write_text(
        "1001|Curto\tkw\n1001|Titulo bem mais completo\treact\n",
        encoding="utf-8",
    )

    result = run("career-ops-pool-fix-titles", str(pool))

    assert result.returncode == 0, result.stderr
    assert "Titulo bem mais completo" in pool.read_text(encoding="utf-8")
    assert (workspace / "data" / "pool-fix.tsv.pre-fix.bak").is_file()


def test_enrich_reports_a_missing_pool_from_the_workspace(run, workspace):
    result = run("career-ops-enrich")

    assert result.returncode == 2
    assert "pool not found" in result.stderr
    assert str(workspace / "data") in result.stderr


def test_career_ops_cv_builds_into_workspace_output(run, workspace):
    result = run("career-ops-cv", "--slug", "smoke", "--lang", "pt", "--no-pdf")

    assert result.returncode == 0, result.stderr
    assert (workspace / "output" / "cv-smoke.json").is_file()
    assert (workspace / "output" / "cv-renan-smoke.html").is_file()
    assert not (workspace / "output" / "cv-renan-smoke.pdf").exists()


def test_pool_rejects_unknown_arguments(run):
    result = run("career-ops-pool", "--nope")

    assert result.returncode == 2
    assert "arg desconhecido" in result.stderr


def test_jd_and_job_helpers_show_usage_without_a_job_id(run):
    jd = run("career-ops-jd")
    assert jd.returncode == 2
    assert "usage" in jd.stderr.lower()

    info = run("jobinfo")
    assert info.returncode != 0
    assert "uso" in info.stderr.lower()


def test_apply_entrypoints_fail_fast_without_arguments(run):
    queue = run("career-ops-apply-queue")
    assert queue.returncode != 0

    one = run("apply-one")
    assert one.returncode != 0


def test_easyapply_imports_the_copied_cdp_driver(run):
    result = run("easyapply", "--help")

    assert result.returncode == 0
    assert "easyapply" in result.stdout


def test_cdp_prints_usage_without_a_command(run):
    result = run("cdp")

    assert result.returncode == 1
    assert "cdp tabs" in result.stdout


def test_cdp_targets_lists_against_the_configured_port(run, env):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - stdlib callback name
            if self.path != "/json/list":
                self.send_error(404)
                return
            body = json.dumps(
                [
                    {
                        "type": "page",
                        "id": "target-1",
                        "title": "LinkedIn",
                        "url": "https://www.linkedin.com/jobs/",
                    }
                ]
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        env["CDP_PORT"] = str(server.server_address[1])
        result = run("cdp-targets", "--page-only")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert result.returncode == 0, result.stderr
    assert "target-1" in result.stdout


def test_browser_script_can_be_checked_without_starting_chromium(run):
    result = run("career-ops-browser", "--check")

    assert result.returncode == 0
    assert "chromium" in result.stdout.lower()


def test_javascript_snippets_parse():
    for name in ("form-dump.js", "jd-extract.js"):
        result = subprocess.run(
            [NODE, "--check", str(SCRIPTS_DIR / name)],
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, f"{name}: {result.stderr}"


def test_python_drivers_compile():
    for name in ("cdp", "cdp-unstick", "easyapply"):
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(SCRIPTS_DIR / name)],
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, f"{name}: {result.stderr}"
