"""Deterministic adapter used by the CLI acceptance tests and local demos.

It performs no browser work.  The scenario name selects the outcome the runner
must handle:

* ``success``       — the expected CV is selected, submit is clicked and confirmed;
* ``failure``       — submit happens but LinkedIn never confirms;
* ``wrong_cv``      — a previous PDF is selected and the guard aborts before submit;
* ``timeout``       — the CV upload freezes the renderer on every attempt;
* ``waiting_input`` — the form stops on a required question and is left open.

The fake still writes screenshot files so every artifact path in the CLI JSON is
real and inspectable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Sequence

from career_ops.adapter import JobInfo, WaitingForInput
from career_ops.renderer import RendererTimeout

FakeScenario = Literal["success", "failure", "wrong_cv", "timeout", "waiting_input"]
FAKE_SCENARIOS: tuple[FakeScenario, ...] = (
    "success",
    "failure",
    "wrong_cv",
    "timeout",
    "waiting_input",
)
_WRONG_CV = "cv-previous-application.pdf"


class FakeApplicationAdapter:
    """Adapter contract implementation with a scripted outcome."""

    def __init__(
        self,
        *,
        job_id: str,
        cv: Path,
        scenario: FakeScenario = "success",
    ) -> None:
        if scenario not in FAKE_SCENARIOS:
            raise ValueError(f"unknown fake scenario {scenario!r}")
        self.job_id = job_id
        self.cv = Path(cv)
        self.scenario = scenario

    def open(self) -> JobInfo:
        return JobInfo(
            id=self.job_id,
            title="Fake React Engineer",
            company="Fake Company",
            url=f"https://www.linkedin.com/jobs/view/{self.job_id}/",
        )

    def attach(self, expected_cv: Path) -> None:
        if self.scenario == "timeout":
            raise RendererTimeout("upload CV", 1.0)
        if self.scenario == "waiting_input":
            raise WaitingForInput(
                ("? [radio: Yes | No]  Are you authorized to work?",)
            )

    def selected_cvs(self) -> Sequence[str]:
        if self.scenario == "wrong_cv":
            return (_WRONG_CV,)
        return (self.cv.name,)

    def submit(self) -> None:
        pass

    def verify(self) -> bool:
        return self.scenario == "success"

    def capture(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake-screenshot")

    def recover(self) -> None:
        pass
