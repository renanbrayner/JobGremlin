"""Verification that the CV attached to an application is the expected one.

LinkedIn reuses the PDF selected in a previous application when the upload
fails, so "the form has a CV" is not enough: the filename actually *selected*
on the review page must match the exact PDF this run generated.  The caller is
responsible for reading only the selected CV (not every PDF listed in the
profile library); this module keeps the comparison pure so the submission
guard (#03) and the real adapter (#04) share one rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

AttachmentReason = Literal["attached", "missing", "wrong_cv"]


def _display_name(name: str | Path) -> str:
    return Path(str(name).replace("\\", "/")).name


def normalize_cv_name(name: str | Path) -> str:
    """Reduce a path, label or DOM value to a comparable basename.

    LinkedIn shows the PDF basename, but callers may pass a full path from the
    CV builder.  Whitespace is collapsed and comparison is case-insensitive so
    a formatting difference never causes a false mismatch (or a false match).
    """
    return " ".join(_display_name(name).split()).casefold()


@dataclass(frozen=True)
class CvAttachmentCheck:
    """Result of comparing the selected CV with the expected PDF."""

    ok: bool
    expected: str
    selected: tuple[str, ...]
    reason: AttachmentReason

    def detail(self) -> dict[str, object]:
        """Structured evidence suitable for an ``events.jsonl`` detail field."""
        return {
            "reason": self.reason,
            "expected_cv": self.expected,
            "selected_cvs": list(self.selected),
        }


class WrongCvAttached(RuntimeError):
    """The page would submit with a CV the run did not generate."""

    def __init__(self, check: CvAttachmentCheck) -> None:
        self.check = check
        if check.reason == "missing":
            message = f"no CV is selected; expected {check.expected!r}"
        else:
            message = (
                f"wrong CV selected: expected {check.expected!r}, "
                f"found {list(check.selected)!r}"
            )
        super().__init__(message)


def verify_cv_attachment(
    expected_cv: str | Path,
    selected: Iterable[str],
) -> CvAttachmentCheck:
    """Check that ``expected_cv`` is the CV selected on the form.

    ``selected`` must contain only the selected attachment(s), never the whole
    profile library: otherwise an old PDF listed next to the right one would
    silently pass.  No fallback is accepted here on purpose.
    """
    expected_name = _display_name(expected_cv)
    expected = normalize_cv_name(expected_cv)

    names: list[str] = []
    seen: set[str] = set()
    for name in selected:
        key = normalize_cv_name(name)
        if key in seen:
            continue
        seen.add(key)
        names.append(str(name))

    return CvAttachmentCheck(
        ok=expected in seen,
        expected=expected_name,
        selected=tuple(names),
        reason="attached" if expected in seen else ("missing" if not names else "wrong_cv"),
    )
