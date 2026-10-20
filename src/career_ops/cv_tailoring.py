"""CV generation behind a narrow adapter.

A CV is generated only when the cache cannot reuse an existing one.  The
request deliberately carries the structured job profile instead of the raw
company data, and the real adapter redacts the company name from the JD before
calling the upstream ``openai-tailor``.  A generated document that still
contains the company name is rejected: the same CV must be safe to reuse across
employers, while the cover letter stays job-specific.

``CommandCvTailor`` orchestrates the upstream ``openai-tailor.mjs`` and
``generate-pdf.mjs`` inside a staging root under ``data/``.  The staging root
receives copies of ``cv.md`` and ``config/profile.yml`` so the upstream
checkout stays read-only and every generated file lands in the workspace.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Protocol

from career_ops.job_filters import fold
from career_ops.job_profile import JobProfile
from career_ops.paths import WorkspacePaths

DEFAULT_TAILOR_TIMEOUT_SECONDS = 600.0
TAILOR_CALLS_FILENAME = "tailor-calls.jsonl"


NON_RETRYABLE_REASONS = frozenset(
    {"company_name_in_cv", "tailor_context_missing", "jd_missing"}
)


class CvGenerationError(RuntimeError):
    """The tailored CV could not be produced safely."""

    def __init__(self, message: str, *, reason: str = "cv_generation_failed") -> None:
        super().__init__(message)
        self.reason = reason
        self.retryable = reason not in NON_RETRYABLE_REASONS


@dataclass(frozen=True)
class TailorRequest:
    """Everything the CV generator may use for one cache miss.

    ``company`` is used only to redact and to reject a leaked employer name.  It
    is never written into the report sent to the model.
    """

    cv_id: str
    job_id: str
    title: str
    profile: JobProfile
    jd_text: str
    destination: Path
    company: str = ""


class CvTailor(Protocol):
    def generate(self, request: TailorRequest) -> Path:
        """Write the PDF for ``request`` and return its path."""


def build_tailor_report(profile: JobProfile, *, title: str = "") -> str:
    """Minimal evaluation report derived from the structured profile.

    No company or raw JD is included.  The report keeps the shape
    ``openai-tailor`` expects while making the reuse invariant explicit.
    """
    heading = title.strip() or "Target role"
    required = ", ".join(profile.required_skills) or "(none extracted)"
    preferred = ", ".join(profile.preferred_skills) or "(none extracted)"
    return "\n".join(
        [
            f"# Evaluation: Role - {heading}",
            "",
            "## Job profile",
            f"- Language: {profile.language}",
            f"- Family: {profile.family}",
            f"- Seniority: {profile.seniority}",
            "",
            "## Required skills",
            required,
            "",
            "## Preferred skills",
            preferred,
            "",
            "## Constraints",
            "- Do not include the employer or company name anywhere in the CV.",
            "- Keep every claim traceable to the candidate's existing CV.",
            "- The cover letter, not the CV, carries job-specific company context.",
            "",
        ]
    )


def redact_company(text: str, company: str) -> str:
    """Remove an employer name from text sent to the model.

    The full name is always replaced; distinctive brand tokens are replaced as
    well so a later ``Acme`` mention cannot survive an initial ``Acme Inc``.
    """
    name = company.strip()
    if not name:
        return text
    redacted = re.sub(re.escape(name), "[company]", text, flags=re.IGNORECASE)
    for token in _company_tokens(company):
        redacted = re.sub(rf"\b{re.escape(token)}\b", "[company]", redacted, flags=re.IGNORECASE)
    return redacted


# Legal forms and generic trading words carry no identity, so they are not
# evidence that a CV names the employer.
_GENERIC_COMPANY_WORDS = frozenset(
    """
    inc llc ltd ltda sa s.a corp corporation company co gmbh plc me eireli group
    grupo holdings technologies technology tech solutions solucoes services
    servicos systems sistemas digital software studio labs lab consulting
    consultoria international global do da de e the and of
    """.split()
)


def _company_tokens(company: str) -> tuple[str, ...]:
    tokens = re.findall(r"[a-z0-9.+#]+", fold(company))
    return tuple(
        token
        for token in dict.fromkeys(tokens)
        if len(token) >= 4 and token not in _GENERIC_COMPANY_WORDS
    )


def _company_leaked(html: str, company: str) -> bool:
    name = fold(company).strip()
    if len(name) < 3:
        return False
    folded_html = fold(html)
    tokens = _company_tokens(company)
    if not tokens:
        return name in folded_html
    return any(
        re.search(rf"\b{re.escape(token)}\b", folded_html) is not None
        for token in tokens
    )


@dataclass(frozen=True)
class CommandOutput:
    returncode: int
    stdout: str
    stderr: str


class CommandCvTailor:
    """Run the upstream tailor and PDF helpers without writing to the upstream."""

    def __init__(
        self,
        paths: WorkspacePaths,
        *,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        environ: Mapping[str, str] | None = None,
        timeout: float = DEFAULT_TAILOR_TIMEOUT_SECONDS,
    ) -> None:
        if timeout <= 0:
            raise ValueError("tailor timeout must be greater than zero")
        self.paths = paths
        self.timeout = timeout
        self._runner = runner
        self._environ = dict(environ) if environ is not None else None

    @property
    def tailor_script(self) -> Path:
        return self.paths.upstream / "openai-tailor.mjs"

    @property
    def pdf_script(self) -> Path:
        return self.paths.upstream / "generate-pdf.mjs"

    def generate(self, request: TailorRequest) -> Path:
        destination = Path(request.destination)
        self.paths.assert_writable(destination)
        if not self.tailor_script.is_file() or not self.pdf_script.is_file():
            raise CvGenerationError(
                f"CV tailoring helpers not found in {self.paths.upstream}",
                reason="tailor_unavailable",
            )

        runtime = self._prepare_runtime(request)
        report_path = runtime / "report.md"
        report_path.write_text(
            build_tailor_report(request.profile, title=request.title),
            encoding="utf-8",
        )
        jd_path = runtime / "jd.txt"
        jd_path.write_text(
            redact_company(request.jd_text, request.company),
            encoding="utf-8",
        )

        env = self._child_environment(runtime)
        tailored = self._run(
            [
                "node",
                str(self.tailor_script),
                "--jd",
                str(jd_path),
                "--report",
                str(report_path),
            ],
            env=env,
            label="generate tailored HTML",
            reason="tailor_failed",
        )
        html_path = self._tailored_html(tailored)
        if not html_path.is_file():
            raise CvGenerationError(
                f"the tailor reported {html_path}, but the file does not exist",
                reason="tailor_failed",
            )
        html = html_path.read_text(encoding="utf-8", errors="replace")
        if _company_leaked(html, request.company):
            raise CvGenerationError(
                "the generated CV contains the company name and cannot be reused",
                reason="company_name_in_cv",
            )

        staged_pdf = runtime / "output" / f"{request.cv_id}.pdf"
        self._run(
            ["node", str(self.pdf_script), str(html_path), str(staged_pdf)],
            env=env,
            label="generate CV PDF",
            reason="pdf_generation_failed",
        )
        if not staged_pdf.is_file():
            raise CvGenerationError(
                "the PDF helper did not write the CV",
                reason="pdf_generation_failed",
            )

        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staged_pdf), str(destination))
        return destination

    def _prepare_runtime(self, request: TailorRequest) -> Path:
        runtime = self.paths.data / "cv-cache" / "work" / request.cv_id / "root"
        self.paths.assert_writable(runtime)
        for directory in (runtime / "config", runtime / "output", runtime / "data"):
            directory.mkdir(parents=True, exist_ok=True)

        profile_source = self.paths.read_config("profile.yml")
        cv_source = self._first_file(
            self.paths.home / "cv.md",
            self.paths.upstream / "cv.md",
        )
        if profile_source is None or cv_source is None:
            raise CvGenerationError(
                "CV tailoring needs cv.md and config/profile.yml in the workspace "
                "or in the read-only upstream",
                reason="tailor_context_missing",
            )
        shutil.copyfile(profile_source, runtime / "config" / "profile.yml")
        shutil.copyfile(cv_source, runtime / "cv.md")
        return runtime

    def _child_environment(self, runtime: Path) -> dict[str, str]:
        base = dict(os.environ) if self._environ is None else dict(self._environ)
        base.update(
            {
                "CAREER_OPS_ROOT": str(runtime),
                "CAREER_OPS_TRACKER": str(runtime / "data" / "applications.md"),
                "CAREER_OPS_PDF_INDEX": str(runtime / "data" / "pdf-index.tsv"),
            }
        )
        return base

    def _run(
        self,
        argv: list[str],
        *,
        env: Mapping[str, str],
        label: str,
        reason: str,
    ) -> CommandOutput:
        try:
            completed = self._runner(
                argv,
                text=True,
                capture_output=True,
                timeout=self.timeout,
                env=dict(env),
                cwd=str(self.paths.home),
            )
        except subprocess.TimeoutExpired as exc:
            raise CvGenerationError(
                f"{label} did not finish within {self.timeout:g}s",
                reason="tailor_timeout",
            ) from exc
        except OSError as exc:
            raise CvGenerationError(f"{label} could not run: {exc}", reason="tailor_unavailable") from exc
        output = CommandOutput(
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )
        if output.returncode != 0:
            detail = _tail(output.stderr or output.stdout)
            raise CvGenerationError(
                f"{label} exited {output.returncode}: {detail}",
                reason=reason,
            )
        return output

    @staticmethod
    def _tailored_html(output: CommandOutput) -> Path:
        marker = "Tailored HTML saved:"
        for line in reversed(output.stdout.splitlines()):
            if marker in line:
                return Path(line.split(marker, 1)[1].strip())
        raise CvGenerationError(
            "the tailor did not report where the HTML was written",
            reason="tailor_failed",
        )

    @staticmethod
    def _first_file(*candidates: Path) -> Path | None:
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return None


class FakeCvTailor:
    """Offline generator used with ``--adapter fake``.

    It writes a readable placeholder and an audit line per call so a test can
    prove that generation happened only on cache misses.
    """

    def __init__(self, paths: WorkspacePaths) -> None:
        self.paths = paths

    def generate(self, request: TailorRequest) -> Path:
        destination = Path(request.destination)
        self.paths.assert_writable(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        report = build_tailor_report(request.profile, title=request.title)
        destination.write_text("%PDF-fake\n" + report, encoding="utf-8")

        log = self.paths.data / TAILOR_CALLS_FILENAME
        self.paths.assert_writable(log)
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "cv_id": request.cv_id,
                        "job_id": request.job_id,
                        "required_skills": list(request.profile.required_skills),
                        "preferred_skills": list(request.profile.preferred_skills),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        return destination


def _tail(text: str, limit: int = 400) -> str:
    compact = " ".join((text or "").split())
    return compact[-limit:] if len(compact) > limit else compact
