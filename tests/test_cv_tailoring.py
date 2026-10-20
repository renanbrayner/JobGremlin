from __future__ import annotations

from pathlib import Path

import pytest

from career_ops.cv_tailoring import (
    CommandCvTailor,
    CvGenerationError,
    TailorRequest,
    build_tailor_report,
    redact_company,
)
from career_ops.job_profile import JobProfile
from conftest import completed_process


def _profile() -> JobProfile:
    return JobProfile(
        language="pt",
        family="frontend",
        seniority="senior",
        required_skills=("react", "typescript"),
        preferred_skills=("jest",),
    )


def _request(paths, *, company: str = "Acme") -> TailorRequest:
    return TailorRequest(
        cv_id="cv-frontend-react-pt-senior-deadbeef",
        job_id="42",
        title="Frontend Engineer",
        profile=_profile(),
        jd_text="Acme is hiring. Requirements: React and TypeScript.",
        destination=paths.output / "cv-cache" / "cv-frontend-react-pt-senior-deadbeef.pdf",
        company=company,
    )


class TailorRunner:
    """Stand-in for node that writes the files the real helpers would write."""

    def __init__(self, *, html: str = "<html>tailored</html>") -> None:
        self.html = html
        self.calls: list[list[str]] = []
        self.report = ""
        self.jd = ""

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        runtime = Path(kwargs["env"]["CAREER_OPS_ROOT"])
        if Path(argv[1]).name == "openai-tailor.mjs":
            self.report = Path(argv[argv.index("--report") + 1]).read_text()
            self.jd = Path(argv[argv.index("--jd") + 1]).read_text()
            html_path = runtime / "output" / "cv-test.html"
            html_path.write_text(self.html, encoding="utf-8")
            return completed_process(
                argv,
                stdout=f"✅  Tailored HTML saved: {html_path}\n",
            )
        pdf_path = Path(argv[3])
        pdf_path.write_bytes(b"%PDF-1.4 tailored")
        return completed_process(argv)


def _tailoring_context(paths) -> None:
    (paths.upstream / "cv.md").write_text("# Candidate CV\n", encoding="utf-8")
    (paths.upstream / "config" / "profile.yml").write_text(
        "name: Candidate\n",
        encoding="utf-8",
    )


def _tailor_files(paths) -> None:
    (paths.upstream / "openai-tailor.mjs").write_text("// stub\n", encoding="utf-8")
    (paths.upstream / "generate-pdf.mjs").write_text("// stub\n", encoding="utf-8")


def test_the_command_tailor_uses_a_company_free_report_and_redacts_the_jd(paths):
    _tailoring_context(paths)
    _tailor_files(paths)
    runner = TailorRunner()
    tailor = CommandCvTailor(paths, runner=runner, environ={})
    request = _request(paths)

    result = tailor.generate(request)

    assert result == request.destination
    assert result.read_bytes() == b"%PDF-1.4 tailored"
    assert [Path(call[1]).name for call in runner.calls] == [
        "openai-tailor.mjs",
        "generate-pdf.mjs",
    ]
    assert "Acme" not in runner.report
    assert "[company]" in runner.jd
    assert "Acme" not in runner.jd
    assert "react" in runner.report
    assert "typescript" in runner.report
    assert not (paths.upstream / "output" / "cv-test.html").exists()


def test_the_command_tailor_rejects_a_leaked_company_name(paths):
    _tailoring_context(paths)
    _tailor_files(paths)
    runner = TailorRunner(html="<html>Built for Acme</html>")
    tailor = CommandCvTailor(paths, runner=runner, environ={})

    with pytest.raises(CvGenerationError) as caught:
        tailor.generate(_request(paths))

    assert caught.value.reason == "company_name_in_cv"
    assert caught.value.retryable is False
    assert not _request(paths).destination.exists()
    assert len(runner.calls) == 1


def test_the_command_tailor_rejects_a_partial_company_name(paths):
    _tailoring_context(paths)
    _tailor_files(paths)
    runner = TailorRunner(html="<html>Built for Acme</html>")
    tailor = CommandCvTailor(paths, runner=runner, environ={})

    with pytest.raises(CvGenerationError) as caught:
        tailor.generate(_request(paths, company="Acme Inc"))

    assert caught.value.reason == "company_name_in_cv"


def test_redaction_removes_the_brand_token_of_a_legal_name():
    text = redact_company("Acme Inc is hiring at Acme.", "Acme Inc")

    assert "Acme" not in text
    assert text.count("[company]") == 2


def test_the_command_tailor_requires_cv_and_profile_context(paths):
    _tailor_files(paths)
    tailor = CommandCvTailor(paths, runner=TailorRunner(), environ={})

    with pytest.raises(CvGenerationError) as caught:
        tailor.generate(_request(paths))

    assert caught.value.reason == "tailor_context_missing"


def test_the_minimal_report_carries_the_profile_but_not_the_company():
    report = build_tailor_report(_profile(), title="Frontend Engineer")

    assert "Frontend Engineer" in report
    assert "react" in report
    assert "company name" in report
    assert "Acme" not in report
