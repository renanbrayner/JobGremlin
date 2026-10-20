"""Screenshot capture with a deterministic timeout fallback.

The application adapter talks to Chromium through CDP.  When the renderer is
frozen the CDP call hangs or times out, so the run must still leave visual
evidence behind.  ``capture_with_fallback`` tries the primary capture first
(CDP) and, only on a timeout, falls back to a system-level capture (``grim``).

Captures are injectable: tests and callers pass any ``path -> None`` callable,
which keeps this module free of browser details.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Protocol, Sequence

_TIMEOUT_MARKERS = re.compile(
    r"timeout|timed out|renderer (?:is )?(?:frozen|not responding)|TimeoutError",
    re.IGNORECASE,
)


class CaptureError(RuntimeError):
    """A screenshot could not be taken and no fallback is available."""


class CaptureTimeout(CaptureError):
    """The primary capture (CDP) timed out or the renderer did not answer."""


class Screenshotter(Protocol):
    def __call__(self, path: Path) -> None: ...


@dataclass(frozen=True)
class CaptureResult:
    """Outcome of one capture attempt, including whether the fallback ran."""

    status: Literal["ok", "timeout", "failed"]
    source: Literal["primary", "fallback"] | None
    error: str | None


def capture_with_fallback(
    primary: Screenshotter,
    path: Path,
    fallback: Screenshotter | None = None,
) -> CaptureResult:
    """Capture ``path`` with ``primary``, trying ``fallback`` only on timeout.

    Any unexpected failure is contained: observability must never mask the
    application error that is being recorded.
    """
    try:
        primary(path)
    except CaptureTimeout as exc:
        if fallback is None:
            return CaptureResult(status="timeout", source=None, error=str(exc))
        try:
            fallback(path)
        except CaptureError as fallback_exc:
            return CaptureResult(
                status="failed",
                source=None,
                error=f"{exc}; grim fallback failed: {fallback_exc}",
            )
        except Exception as fallback_exc:  # noqa: BLE001 - evidence must not mask the app error
            return CaptureResult(
                status="failed",
                source=None,
                error=f"{exc}; grim fallback crashed: {fallback_exc}",
            )
        return CaptureResult(status="timeout", source="fallback", error=str(exc))
    except CaptureError as exc:
        return CaptureResult(status="failed", source=None, error=str(exc))
    except Exception as exc:  # noqa: BLE001 - evidence must not mask the app error
        return CaptureResult(status="failed", source=None, error=f"unexpected capture error: {exc}")
    return CaptureResult(status="ok", source="primary", error=None)


class CommandScreenshotter:
    """Run a screenshot command, mapping timeouts to ``CaptureTimeout``."""

    def __init__(
        self,
        argv: Sequence[str],
        *,
        timeout: float = 10.0,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self.argv = list(argv)
        self.timeout = timeout
        self.runner = runner

    def __call__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            completed = self.runner(
                [*self.argv, str(path)],
                text=True,
                capture_output=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise CaptureTimeout(f"{self.argv[0]} timed out after {self.timeout}s") from exc
        except OSError as exc:
            raise CaptureError(f"{self.argv[0]} could not start: {exc}") from exc

        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            message = f"{self.argv[0]} exited {completed.returncode}" + (
                f": {stderr}" if stderr else ""
            )
            if _TIMEOUT_MARKERS.search(stderr):
                raise CaptureTimeout(message)
            raise CaptureError(message)
        if not path.is_file():
            raise CaptureError(f"{self.argv[0]} exited 0 but wrote no screenshot")


def cdp_screenshotter(
    scripts_dir: Path,
    *,
    timeout: float = 10.0,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    target_id: str | None = None,
) -> CommandScreenshotter:
    """Capture through the copied ``cdp shot`` command.

    ``target_id`` binds the capture to the tab that owns the form, so a parked
    form never replaces the screenshot of the current application.
    """
    argv = [str(Path(scripts_dir) / "cdp"), "shot"]
    if target_id is not None:
        argv.extend(["--target-id", target_id])
    return CommandScreenshotter(
        argv,
        timeout=timeout,
        runner=runner,
    )


def grim_screenshotter(
    *,
    timeout: float = 10.0,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> CommandScreenshotter:
    """Capture the whole screen through ``grim``, even when CDP is stuck."""
    return CommandScreenshotter(["grim", "-t", "png"], timeout=timeout, runner=runner)
