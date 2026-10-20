"""Real application adapter backed by the copied career-ops scripts.

This module does not modify or reimplement the browser flow.  It composes the
same commands the current installation uses:

* ``jobinfo`` opens a job and reports ``applied``/``closed``/``easy``;
* ``cdp`` preloads the tailor-made PDF into the LinkedIn library and reads the
  selected resume from the open form;
* ``easyapply --cv-library-only`` fills the form (without submitting) and later
  submits it with ``--resume --submit``;
* ``cdp-unstick`` recovers a frozen renderer between guarded attempts.

All commands run with an explicit deadline.  A subprocess timeout is translated
into ``RendererTimeout`` so the submission guard records evidence, recovers the
browser and applies the "never retry after a click" rule from ADR 0002.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence
from urllib.parse import quote

from career_ops.adapter import (
    AdapterError,
    AdapterUnavailable,
    ApplicationFailed,
    JobInfo,
    LinkedInDailyLimit,
    WaitingForInput,
)
from career_ops.capture import cdp_screenshotter
from career_ops.paths import WorkspacePaths
from career_ops.renderer import RendererTimeout, cdp_unstick_recovery

APPLICATION_SETTINGS_URL = "https://www.linkedin.com/jobs/application-settings/"
DEFAULT_APPLY_TIMEOUT_SECONDS = 420.0
DEFAULT_JOBINFO_TIMEOUT_SECONDS = 90.0
DEFAULT_VERIFY_ATTEMPTS = 3
DEFAULT_VERIFY_DELAY_SECONDS = 2.0

_SELECTED_CVS_JS = r"""(() => {
  const pdf = /[A-Za-z0-9][A-Za-z0-9 ._()\-]*\.pdf/gi;
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  const names = s => (String(s || '').match(pdf) || []).map(clean);
  const checked = new Set();
  for (const radio of document.querySelectorAll('input[type=radio]')) {
    if (!radio.checked) continue;
    const raw = [
      radio.getAttribute('aria-label') || '',
      radio.value || '',
      (radio.parentElement && radio.parentElement.innerText) || '',
    ].join(' ');
    for (const name of names(raw)) checked.add(name);
  }
  if (checked.size) return JSON.stringify([...checked]);

  // Review page: the selected resume is shown once.  Accept a name only when
  // the page exposes exactly one PDF; a longer list means we are looking at
  // the profile library, which must never satisfy the CV guard.
  const found = new Set();
  for (const element of document.querySelectorAll('a, span, div, p, [aria-label]')) {
    const text = clean((element.getAttribute && element.getAttribute('aria-label')) || '') +
      ' ' + clean(element.innerText || '');
    if (text.length > 300) continue;
    for (const name of names(text)) found.add(name);
  }
  return JSON.stringify(found.size === 1 ? [...found] : []);
})()"""

_SELECT_CV_JS = r"""(() => {
  const wanted = __NAME__;
  const radios = [...document.querySelectorAll('input[type=radio]')];
  const radio = radios.find(r => {
    const raw = ((r.getAttribute('aria-label') || '') + ' ' + (r.value || '')).toLowerCase();
    return raw.includes(wanted);
  });
  if (!radio) return JSON.stringify({status: 'not_found'});
  if (radio.checked) return JSON.stringify({status: 'already_selected'});
  radio.click();
  return JSON.stringify({status: 'selected', label: radio.getAttribute('aria-label') || ''});
})()"""


@dataclass(frozen=True)
class CommandOutput:
    returncode: int
    stdout: str
    stderr: str


class RealApplicationAdapter:
    """Wrap the copied scripts behind the application-adapter contract."""

    def __init__(
        self,
        paths: WorkspacePaths,
        *,
        job_id: str,
        cv: Path,
        answers: Path,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        sleep: Callable[[float], None] = time.sleep,
        environ: Mapping[str, str] | None = None,
        apply_timeout: float = DEFAULT_APPLY_TIMEOUT_SECONDS,
        jobinfo_timeout: float = DEFAULT_JOBINFO_TIMEOUT_SECONDS,
        verify_attempts: int = DEFAULT_VERIFY_ATTEMPTS,
        verify_delay: float = DEFAULT_VERIFY_DELAY_SECONDS,
    ) -> None:
        if apply_timeout <= 0 or jobinfo_timeout <= 0:
            raise ValueError("adapter timeouts must be greater than zero")
        if verify_attempts < 1:
            raise ValueError("verify_attempts must be at least 1")
        self.paths = paths
        self.job_id = job_id
        self.cv = Path(cv)
        self.answers = Path(answers)
        self.job_url = f"https://www.linkedin.com/jobs/view/{quote(job_id, safe='')}/"
        self.apply_timeout = apply_timeout
        self.jobinfo_timeout = jobinfo_timeout
        self.verify_attempts = verify_attempts
        self.verify_delay = verify_delay
        self._runner = runner
        self._sleep = sleep
        self._environ = dict(environ) if environ is not None else None
        self._attached_cv: Path | None = None
        self._screenshotter = cdp_screenshotter(paths.scripts, runner=runner)
        self._recovery = cdp_unstick_recovery(paths.scripts, runner=runner)

    @property
    def jobinfo(self) -> Path:
        return self.paths.scripts / "jobinfo"

    @property
    def easyapply(self) -> Path:
        return self.paths.scripts / "easyapply"

    @property
    def cdp(self) -> Path:
        return self.paths.scripts / "cdp"

    def open(self) -> JobInfo:
        output = self._run(
            [str(self.jobinfo), self.job_id],
            label="open job",
            timeout=self.jobinfo_timeout,
        )
        if output.returncode != 0:
            raise AdapterUnavailable(
                f"jobinfo exited {output.returncode}: {_tail(output.stderr or output.stdout)}"
            )
        payload = _last_json(output.stdout)
        if not isinstance(payload, dict):
            raise AdapterError("jobinfo did not return the expected JSON object")
        return JobInfo(
            id=self.job_id,
            title=str(payload.get("title") or ""),
            company=str(payload.get("company") or ""),
            url=str(payload.get("url") or self.job_url),
            applied=bool(payload.get("applied")),
            easy_apply=bool(payload.get("easy", True)),
            closed=bool(payload.get("closed")),
        )

    def attach(self, expected_cv: Path) -> None:
        expected_cv = Path(expected_cv)
        self._preload_cv(expected_cv)
        output = self._run(
            [
                str(self.easyapply),
                "--url",
                self.job_url,
                "--cv",
                str(expected_cv),
                "--answers",
                str(self.answers),
                "--cv-library-only",
                "--max-steps",
                "20",
            ],
            label="fill application form",
            timeout=self.apply_timeout,
        )
        _raise_if_waiting(output)
        _raise_if_daily_limit(output)
        if output.returncode != 0:
            raise ApplicationFailed(
                f"easyapply exited {output.returncode} while filling the form: "
                f"{_tail(output.stdout or output.stderr)}"
            )
        # ``easyapply`` already selects the PDF on the CV page.  The one-page
        # variant never reaches that branch, so select the radio here too when
        # the form exposes one.  A missing radio is fine: the guard reads back
        # only the selected CV and aborts if it is not the expected PDF.
        self._select_cv(expected_cv)
        self._attached_cv = expected_cv

    def selected_cvs(self) -> Sequence[str]:
        payload = self._cdp_eval(_SELECTED_CVS_JS, label="read selected CV")
        if not isinstance(payload, list):
            raise AdapterError("the selected CV response is not a list")
        return tuple(str(name) for name in payload)

    def submit(self) -> None:
        expected_cv = self._attached_cv or self.cv
        output = self._run(
            [
                str(self.easyapply),
                "--resume",
                "--url",
                self.job_url,
                "--cv",
                str(expected_cv),
                "--answers",
                str(self.answers),
                "--cv-library-only",
                "--submit",
                "--max-steps",
                "20",
            ],
            label="submit application",
            timeout=self.apply_timeout,
        )
        _raise_if_waiting(output)
        _raise_if_daily_limit(output)
        # Exit 1 means the submit click happened but the script did not see the
        # confirmation text.  The guard verifies through jobinfo next, so this is
        # not a failure yet.
        if output.returncode not in (0, 1):
            raise ApplicationFailed(
                f"easyapply exited {output.returncode} while submitting: "
                f"{_tail(output.stdout or output.stderr)}"
            )

    def verify(self) -> bool:
        last_error = ""
        for attempt in range(1, self.verify_attempts + 1):
            output = self._run(
                [str(self.jobinfo), self.job_id],
                label="verify submission",
                timeout=self.jobinfo_timeout,
            )
            if output.returncode != 0:
                last_error = _tail(output.stderr or output.stdout)
            else:
                payload = _last_json(output.stdout)
                if isinstance(payload, dict) and payload.get("applied") is True:
                    return True
            if attempt < self.verify_attempts:
                self._sleep(self.verify_delay)
        if last_error:
            raise AdapterUnavailable(f"jobinfo could not verify the application: {last_error}")
        return False

    def capture(self, path: Path) -> None:
        self._screenshotter(Path(path))

    def recover(self) -> None:
        self._recovery()

    def _select_cv(self, cv: Path) -> None:
        script = _SELECT_CV_JS.replace("__NAME__", json.dumps(cv.name.lower()))
        payload = self._cdp_eval(script, label="select CV")
        if not isinstance(payload, dict):
            raise AdapterError("the CV selection response is not an object")

    def _cdp_eval(self, script: str, *, label: str) -> object:
        output = self._run(
            [str(self.cdp), "eval", script],
            label=label,
            timeout=self.jobinfo_timeout,
        )
        if output.returncode != 0:
            raise AdapterError(
                f"cdp could not {label}: {_tail(output.stderr or output.stdout)}"
            )
        raw = _last_line(output.stdout)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AdapterError(f"could not parse the {label} response: {raw!r}") from exc

    def _preload_cv(self, cv: Path) -> None:
        """Put the PDF in LinkedIn's library without opening a native picker.

        The 19/10 freeze happened when the React handler reopened the native
        file chooser.  Preloading through ``application-settings`` and applying
        with ``--cv-library-only`` is the same path the current ``apply-one``
        uses since that incident.
        """
        opened = self._run(
            [str(self.cdp), "goto", APPLICATION_SETTINGS_URL, "--sleep", "3"],
            label="open application settings",
            timeout=self.jobinfo_timeout,
        )
        if opened.returncode != 0:
            raise AdapterUnavailable(
                f"cdp could not open the application settings: "
                f"{_tail(opened.stderr or opened.stdout)}"
            )
        uploaded = self._run(
            [str(self.cdp), "upload", "input[type=file]", str(cv)],
            label="preload CV",
            timeout=self.jobinfo_timeout,
        )
        if uploaded.returncode != 0 or "arquivo setado" not in uploaded.stdout:
            raise ApplicationFailed(
                "could not preload the CV into the LinkedIn library: "
                f"{_tail(uploaded.stderr or uploaded.stdout)}"
            )
        # LinkedIn indexes a freshly uploaded PDF asynchronously; the radio for
        # the new file may not exist for a few seconds.
        self._sleep(5.0)

    def _run(
        self,
        argv: Sequence[str],
        *,
        label: str,
        timeout: float,
    ) -> CommandOutput:
        try:
            completed = self._runner(
                list(argv),
                text=True,
                capture_output=True,
                timeout=timeout,
                env=self._environ,
            )
        except subprocess.TimeoutExpired as exc:
            raise RendererTimeout(label, timeout) from exc
        except OSError as exc:
            raise AdapterUnavailable(
                f"could not run {Path(argv[0]).name}: {exc}"
            ) from exc
        return CommandOutput(
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )


def _last_line(text: str) -> str:
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line:
            return line
    return ""


def _last_json(text: str) -> object | None:
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return None


def _tail(text: str, limit: int = 400) -> str:
    text = " ".join(text.split())
    return text[-limit:] if len(text) > limit else text


def _raise_if_waiting(output: CommandOutput) -> None:
    if output.returncode == 6 or "FORMULARIO EM ESPERA" in output.stdout:
        raise WaitingForInput(_pending_questions(output.stdout))


_DAILY_LIMIT_MARKERS = (
    "daily limit",
    "limite diário",
    "limite diario",
    "reached the limit",
    "atingiu o limite",
    "try again tomorrow",
)


def _raise_if_daily_limit(output: CommandOutput) -> None:
    text = f"{output.stdout}\n{output.stderr}".lower()
    if any(marker in text for marker in _DAILY_LIMIT_MARKERS):
        raise LinkedInDailyLimit()


def _pending_questions(stdout: str) -> tuple[str, ...]:
    questions: list[str] = []
    for line in stdout.splitlines():
        text = line.strip()
        if not text:
            continue
        if text.startswith("?") or text.startswith("[radio:") or text.startswith("SELECT:"):
            questions.append(text)
    return tuple(questions)
