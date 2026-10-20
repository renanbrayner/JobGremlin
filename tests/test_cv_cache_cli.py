from __future__ import annotations

import json
from pathlib import Path

from conftest import FRONTEND_JD, invoke, write_cv, write_jd_fixtures

ENGLISH_FRONTEND_JD = """\
Frontend Developer

Requirements:
- React and TypeScript.
"""


def _candidate(workspace: Path, *, job_id: str, title: str, company: str) -> Path:
    path = workspace / "data" / "candidates.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": job_id,
                    "title": title,
                    "company": company,
                    "location": "Recife, PE",
                    "workplace": "Remote",
                }
            ]
        ),
        encoding="utf-8",
    )
    return path


def _tailor_calls(workspace: Path) -> list[dict]:
    path = workspace / "data" / "tailor-calls.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def _metadata(workspace: Path) -> list[dict]:
    return [
        json.loads(path.read_text())
        for path in sorted((workspace / "data" / "cv-cache").glob("cv-*.json"))
    ]


def test_queue_mode_generates_on_a_miss_and_reuses_on_the_next_run(run, workspace):
    jds = write_jd_fixtures(workspace, {"1": FRONTEND_JD, "2": FRONTEND_JD})
    candidates = _candidate(
        workspace, job_id="1", title="Desenvolvedor React", company="Acme"
    )

    first, first_payload = invoke(
        run,
        "--candidates",
        str(candidates),
        "--jd-dir",
        str(jds),
        "--adapter",
        "fake",
        "--run-id",
        "cache-first",
    )

    assert first.returncode == 0
    assert first_payload["cv_cache"]["hit"] is False
    assert first_payload["cv_cache"]["reason"] == "cache_miss"
    assert first_payload["cv_cache"]["miss_reason"] == "cache_empty"
    assert first_payload["cv_cache"]["cv"] == first_payload["cv"]
    generated = Path(first_payload["cv"])
    assert generated.is_file()
    assert "Acme" not in generated.read_text(encoding="utf-8")
    assert "React" in generated.read_text(encoding="utf-8")
    assert len(_tailor_calls(workspace)) == 1
    first_record = first_payload["queue"]["record"]
    assert first_record["detail"]["cv"] == first_payload["cv"]
    assert first_record["detail"]["cv_cache"]["hit"] is False

    candidates = _candidate(
        workspace, job_id="2", title="Desenvolvedor React", company="Globex"
    )
    second, second_payload = invoke(
        run,
        "--candidates",
        str(candidates),
        "--jd-dir",
        str(jds),
        "--adapter",
        "fake",
        "--run-id",
        "cache-second",
    )

    assert second.returncode == 0
    assert second_payload["status"] == "verified"
    assert second_payload["cv_cache"]["hit"] is True
    assert second_payload["cv_cache"]["reason"] == "cache_hit"
    assert second_payload["cv_cache"]["score"] == 1.0
    assert second_payload["cv"] == first_payload["cv"]
    assert len(_tailor_calls(workspace)) == 1

    metadata = _metadata(workspace)
    assert len(metadata) == 1
    assert [origin["job_id"] for origin in metadata[0]["origins"]] == ["1", "2"]
    assert second_payload["queue"]["record"]["detail"]["cv_cache"]["hit"] is True


def test_a_different_language_generates_a_second_cv(run, workspace):
    jds = write_jd_fixtures(workspace, {"1": FRONTEND_JD, "2": ENGLISH_FRONTEND_JD})
    candidates = _candidate(
        workspace, job_id="1", title="Desenvolvedor React", company="Acme"
    )

    first, first_payload = invoke(
        run,
        "--candidates",
        str(candidates),
        "--jd-dir",
        str(jds),
        "--adapter",
        "fake",
        "--run-id",
        "cache-pt",
    )

    candidates = _candidate(
        workspace, job_id="2", title="React Developer", company="Globex"
    )
    second, second_payload = invoke(
        run,
        "--candidates",
        str(candidates),
        "--jd-dir",
        str(jds),
        "--adapter",
        "fake",
        "--run-id",
        "cache-en",
    )

    assert first.returncode == 0
    assert second.returncode == 0
    assert second_payload["cv_cache"]["hit"] is False
    assert second_payload["cv_cache"]["miss_reason"] == "language_mismatch"
    assert second_payload["cv"] != first_payload["cv"]
    assert len(_tailor_calls(workspace)) == 2
    assert len(_metadata(workspace)) == 2


def test_an_explicit_cv_bypasses_the_cache(run, workspace):
    jds = write_jd_fixtures(workspace, {"1": FRONTEND_JD})
    candidates = _candidate(
        workspace, job_id="1", title="Desenvolvedor React", company="Acme"
    )
    cv = write_cv(workspace, "manual-cv.pdf")

    result, payload = invoke(
        run,
        "--candidates",
        str(candidates),
        "--jd-dir",
        str(jds),
        "--cv",
        str(cv),
        "--adapter",
        "fake",
        "--run-id",
        "manual-cv",
    )

    assert result.returncode == 0
    assert payload["cv"] == str(cv.resolve())
    assert "cv_cache" not in payload
    assert _tailor_calls(workspace) == []
    assert not (workspace / "data" / "cv-cache" / "index.json").exists()


def test_cv_min_score_requires_queue_mode(run):
    result = run("career-ops-run", "--job", "1", "--cv-min-score", "0.95")

    assert result.returncode == 2
    assert "--cv-min-score requires --candidates" in result.stderr


GRAPHQL_JD = """\
Desenvolvedor Front-end Sênior

Requisitos:
- React, TypeScript e GraphQL.
"""

PREFERRED_ONLY_JD = """\
Desenvolvedor Front-end Sênior

Requisitos:
- React e TypeScript.

Diferenciais:
- Jest e Cypress.
"""


def _first_run(run, workspace, jd: str, *, run_id: str) -> tuple:
    jds = write_jd_fixtures(workspace, {"1": jd})
    candidates = _candidate(
        workspace, job_id="1", title="Desenvolvedor React", company="Acme"
    )
    return invoke(
        run,
        "--candidates",
        str(candidates),
        "--jd-dir",
        str(jds),
        "--adapter",
        "fake",
        "--run-id",
        run_id,
    )


def _second_run(
    run,
    workspace,
    jd: str,
    *,
    title: str,
    run_id: str,
    extra: tuple[str, ...] = (),
) -> tuple:
    jds = write_jd_fixtures(workspace, {"2": jd})
    candidates = _candidate(workspace, job_id="2", title=title, company="Globex")
    return invoke(
        run,
        "--candidates",
        str(candidates),
        "--jd-dir",
        str(jds),
        "--adapter",
        "fake",
        "--run-id",
        run_id,
        *extra,
    )


MID_FRONTEND_JD = """\
Desenvolvedor Front-end

Requisitos:
- React e TypeScript.
- 3 anos de experiência.
"""


def test_an_incompatible_seniority_generates_a_new_cv(run, workspace):
    first, first_payload = _first_run(run, workspace, FRONTEND_JD, run_id="senior")
    second, second_payload = _second_run(
        run,
        workspace,
        MID_FRONTEND_JD,
        title="Desenvolvedor React",
        run_id="mid",
    )

    assert first.returncode == 0
    assert second.returncode == 0
    assert second_payload["cv_cache"]["hit"] is False
    assert second_payload["cv_cache"]["miss_reason"] == "seniority_incompatible"
    assert second_payload["cv"] != first_payload["cv"]
    assert len(_tailor_calls(workspace)) == 2


def test_a_missing_must_have_generates_a_new_cv(run, workspace):
    first, first_payload = _first_run(run, workspace, FRONTEND_JD, run_id="base")
    second, second_payload = _second_run(
        run,
        workspace,
        GRAPHQL_JD,
        title="Desenvolvedor React",
        run_id="graphql",
    )

    assert first.returncode == 0
    assert second.returncode == 0
    assert second_payload["cv_cache"]["hit"] is False
    assert second_payload["cv_cache"]["miss_reason"] == "must_have_missing"
    assert second_payload["cv_cache"]["missing_required"] == ["graphql"]
    assert len(_tailor_calls(workspace)) == 2


def test_a_score_below_the_threshold_generates_a_new_cv(run, workspace):
    first, first_payload = _first_run(run, workspace, FRONTEND_JD, run_id="narrow")
    second, second_payload = _second_run(
        run,
        workspace,
        PREFERRED_ONLY_JD,
        title="Desenvolvedor React",
        run_id="preferred",
        extra=("--cv-min-score", "0.90"),
    )

    assert first.returncode == 0
    assert second.returncode == 0
    assert second_payload["cv_cache"]["hit"] is False
    assert second_payload["cv_cache"]["miss_reason"] == "score_below_threshold"
    assert second_payload["cv_cache"]["score"] == 0.75
    assert second_payload["cv"] != first_payload["cv"]
    assert len(_tailor_calls(workspace)) == 2
