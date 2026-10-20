"""Renderer watchdog and recovery for a frozen CDP session.

A hung renderer does not always close the CDP socket.  ``Runtime.evaluate``
simply never answers, so the application can sit there until the daily budget
is gone.  ``RendererWatchdog`` gives every browser operation a hard deadline;
``CommandRecovery`` runs the copied ``cdp-unstick`` command; and
``RecoverableBrowser`` drops the stale connection and reconnects to the same
target before the job is retried.

The pieces are deliberately independent of the concrete CDP driver so the
application adapter (#04) can inject fakes in tests.
"""

from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Generic, Mapping, Sequence, TypeVar, cast

from career_ops.paths import load_environment

DEFAULT_RENDERER_TIMEOUT_SECONDS = 30.0
DEFAULT_RECOVERY_TIMEOUT_SECONDS = 20.0
RENDERER_TIMEOUT_ENV = "CAREER_OPS_RENDERER_TIMEOUT_SECONDS"

T = TypeVar("T")
Connection = TypeVar("Connection")


class RendererError(RuntimeError):
    """Base class for renderer failures that the loop can recover from."""


class RendererTimeout(RendererError, TimeoutError):
    """The renderer did not answer within the configured deadline."""

    def __init__(self, label: str, timeout: float) -> None:
        self.label = label
        self.timeout = timeout
        super().__init__(
            f"renderer did not answer {label!r} within {timeout:g}s"
        )

    @property
    def retryable(self) -> bool:
        return True


class RendererRecoveryFailed(RendererError):
    """The unstick command ran but the renderer is still not usable."""


def resolve_renderer_timeout(environ: Mapping[str, str] | None = None) -> float:
    """Return the configured renderer deadline in seconds.

    ``CAREER_OPS_RENDERER_TIMEOUT_SECONDS`` wins over the default.  An explicit
    mapping bypasses the workspace env file (useful for tests); passing nothing
    resolves the real environment plus ``config/career-ops.env``.  Invalid
    values raise instead of silently falling back, because a missing timeout
    is exactly how the 19/10 run hung an entire round.
    """
    values = load_environment() if environ is None else environ
    raw = values.get(RENDERER_TIMEOUT_ENV)
    if raw is None or not raw.strip():
        return DEFAULT_RENDERER_TIMEOUT_SECONDS
    try:
        timeout = float(raw)
    except ValueError as exc:
        raise ValueError(
            f"{RENDERER_TIMEOUT_ENV} must be a number of seconds, got {raw!r}"
        ) from exc
    if timeout <= 0:
        raise ValueError(f"{RENDERER_TIMEOUT_ENV} must be greater than zero, got {raw!r}")
    return timeout


class RendererWatchdog:
    """Run one browser operation with a hard deadline.

    The operation runs on a daemon thread so a blocked socket read cannot stop
    the process from recording the failure.  On timeout the caller is expected
    to record evidence (the session falls back to ``grim``) and recover the
    browser before another attempt.  ``RecoverableBrowser`` closes the stale
    socket during recovery, which also unblocks the abandoned worker.
    """

    def __init__(self, timeout: float = DEFAULT_RENDERER_TIMEOUT_SECONDS) -> None:
        if timeout <= 0:
            raise ValueError("renderer timeout must be greater than zero")
        self.timeout = timeout

    @classmethod
    def from_environment(
        cls, environ: Mapping[str, str] | None = None
    ) -> "RendererWatchdog":
        return cls(resolve_renderer_timeout(environ))

    def run(self, operation: Callable[[], T], *, label: str = "renderer") -> T:
        """Return ``operation()`` or raise ``RendererTimeout`` after the deadline."""
        outcome: dict[str, object] = {}
        finished = threading.Event()

        def target() -> None:
            try:
                outcome["value"] = operation()
            except BaseException as exc:  # noqa: BLE001 - re-raised on the caller thread
                outcome["error"] = exc
            finally:
                finished.set()

        worker = threading.Thread(
            target=target,
            name=f"renderer-{label}",
            daemon=True,
        )
        worker.start()
        if not finished.wait(self.timeout):
            raise RendererTimeout(label, self.timeout)

        if "error" in outcome:
            raise cast(BaseException, outcome["error"])
        return cast(T, outcome.get("value"))


@dataclass(frozen=True)
class RecoveryCommand:
    """One command used to wake a stuck renderer."""

    argv: Sequence[str]
    timeout: float = DEFAULT_RECOVERY_TIMEOUT_SECONDS


class CommandRecovery:
    """Run recovery commands, optionally probing the browser afterwards.

    ``probe`` is the only honest way to know that ``cdp-unstick`` worked; when
    it is supplied, a non-zero exit or a false probe both fail the recovery so
    the caller can mark the job retryable instead of corrupting the session.
    """

    def __init__(
        self,
        commands: Sequence[RecoveryCommand],
        *,
        probe: Callable[[], bool] | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self.commands = list(commands)
        self.probe = probe
        self.runner = runner

    def __call__(self) -> None:
        failures: list[str] = []
        for command in self.commands:
            try:
                completed = self.runner(
                    list(command.argv),
                    text=True,
                    capture_output=True,
                    timeout=command.timeout,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                failures.append(f"{command.argv[0]}: {exc}")
                continue
            if completed.returncode != 0:
                stderr = (completed.stderr or "").strip()
                message = f"{command.argv[0]} exited {completed.returncode}"
                failures.append(f"{message}: {stderr}" if stderr else message)

        if self.probe is not None:
            try:
                alive = bool(self.probe())
            except Exception as exc:  # noqa: BLE001 - report the probe failure
                failures.append(f"probe failed: {exc}")
            else:
                if not alive:
                    failures.append("renderer still unresponsive after recovery")

        if failures:
            raise RendererRecoveryFailed("; ".join(failures))


def cdp_unstick_recovery(
    scripts_dir: Path,
    *,
    probe: Callable[[], bool] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> CommandRecovery:
    """Recovery policy using the copied ``cdp-unstick`` driver."""
    return CommandRecovery(
        [
            RecoveryCommand(
                [str(Path(scripts_dir) / "cdp-unstick")],
                timeout=DEFAULT_RECOVERY_TIMEOUT_SECONDS,
            )
        ],
        probe=probe,
        runner=runner,
    )


class RecoverableBrowser(Generic[Connection]):
    """Own a browser connection that can be discarded and reopened safely.

    The reconnect callable must bind the same CDP target id; that is what keeps
    a retry from navigating a different tab (and from destroying a parked
    form).  ``recover`` never reuses the old socket: after a frozen call the
    socket is out of phase and every following command would fail.
    """

    def __init__(
        self,
        connect: Callable[[], Connection],
        *,
        disconnect: Callable[[Connection], None] | None = None,
        unstick: Callable[[], None] | None = None,
    ) -> None:
        self._connect = connect
        self._disconnect = disconnect
        self._unstick = unstick
        self.connection = connect()

    def recover(self) -> Connection:
        old = self.connection
        if self._disconnect is not None:
            self._disconnect(old)
        try:
            if self._unstick is not None:
                self._unstick()
        finally:
            # Always leave a fresh connection behind, even when unstick failed:
            # retrying on the stale socket is what corrupts the session.
            self.connection = self._connect()
        return self.connection
