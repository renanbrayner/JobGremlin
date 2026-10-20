from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from career_ops.renderer import (
    DEFAULT_RENDERER_TIMEOUT_SECONDS,
    RENDERER_TIMEOUT_ENV,
    CommandRecovery,
    RecoverableBrowser,
    RecoveryCommand,
    RendererRecoveryFailed,
    RendererTimeout,
    RendererWatchdog,
    cdp_unstick_recovery,
    resolve_renderer_timeout,
)
from conftest import FakeRunner


def test_the_watchdog_returns_a_fast_operation_result():
    watchdog = RendererWatchdog(timeout=1.0)

    assert watchdog.run(lambda: 41 + 1, label="eval") == 42


def test_a_frozen_operation_times_out_within_the_configured_limit():
    watchdog = RendererWatchdog(timeout=0.05)

    started = time.monotonic()
    with pytest.raises(RendererTimeout) as raised:
        watchdog.run(lambda: time.sleep(1.0), label="upload CV")
    elapsed = time.monotonic() - started

    assert elapsed < 0.5
    assert raised.value.label == "upload CV"
    assert raised.value.timeout == 0.05
    assert raised.value.retryable is True
    assert "upload CV" in str(raised.value)


def test_the_watchdog_re_raises_the_operation_error():
    def fail():
        raise ValueError("selector not found")

    with pytest.raises(ValueError, match="selector not found"):
        RendererWatchdog(timeout=1.0).run(fail)


def test_the_timeout_can_be_configured_from_the_environment():
    assert resolve_renderer_timeout({}) == DEFAULT_RENDERER_TIMEOUT_SECONDS
    assert resolve_renderer_timeout({RENDERER_TIMEOUT_ENV: "7.5"}) == 7.5
    assert RendererWatchdog.from_environment({RENDERER_TIMEOUT_ENV: "2"}).timeout == 2.0


def test_the_timeout_is_read_from_the_workspace_env_file(monkeypatch, tmp_path):
    env_file = tmp_path / "career-ops.env"
    env_file.write_text(f"{RENDERER_TIMEOUT_ENV}=7\n", encoding="utf-8")
    monkeypatch.delenv(RENDERER_TIMEOUT_ENV, raising=False)
    monkeypatch.setenv("CAREER_OPS_ENV_FILE", str(env_file))

    assert resolve_renderer_timeout() == 7.0
    assert RendererWatchdog.from_environment().timeout == 7.0


def test_a_real_environment_variable_still_wins_over_the_env_file(monkeypatch, tmp_path):
    env_file = tmp_path / "career-ops.env"
    env_file.write_text(f"{RENDERER_TIMEOUT_ENV}=7\n", encoding="utf-8")
    monkeypatch.setenv("CAREER_OPS_ENV_FILE", str(env_file))
    monkeypatch.setenv(RENDERER_TIMEOUT_ENV, "9")

    assert resolve_renderer_timeout() == 9.0


@pytest.mark.parametrize("raw", ["not-a-number", "0", "-1"])
def test_an_invalid_timeout_is_rejected_instead_of_silently_hanging(raw):
    with pytest.raises(ValueError, match=RENDERER_TIMEOUT_ENV):
        resolve_renderer_timeout({RENDERER_TIMEOUT_ENV: raw})


def test_command_recovery_runs_the_copied_unstick_command(tmp_path):
    runner = FakeRunner(write_file=False)
    recovery = cdp_unstick_recovery(tmp_path / "scripts", runner=runner)

    recovery()

    assert runner.calls == [[str(tmp_path / "scripts" / "cdp-unstick")]]


def test_command_recovery_fails_when_unstick_exits_non_zero():
    runner = FakeRunner(write_file=False, returncode=3, stderr="still hung")
    recovery = CommandRecovery([RecoveryCommand(["cdp-unstick"])], runner=runner)

    with pytest.raises(RendererRecoveryFailed, match="exited 3: still hung"):
        recovery()


def test_command_recovery_fails_when_the_probe_still_hangs():
    recovery = CommandRecovery(
        [RecoveryCommand(["cdp-unstick"])],
        probe=lambda: False,
        runner=FakeRunner(write_file=False),
    )

    with pytest.raises(RendererRecoveryFailed, match="still unresponsive"):
        recovery()


def test_command_recovery_fails_on_a_command_timeout():
    runner = FakeRunner(write_file=False, error=subprocess.TimeoutExpired(["cdp-unstick"], 20))
    recovery = CommandRecovery([RecoveryCommand(["cdp-unstick"])], runner=runner)

    with pytest.raises(RendererRecoveryFailed, match="timed out"):
        recovery()


def test_recovering_a_browser_drops_the_stale_socket_and_reconnects_the_same_target():
    connections: list[dict[str, str]] = []
    disconnected: list[dict[str, str]] = []

    def connect():
        connection = {"target": "job-tab-1", "generation": str(len(connections) + 1)}
        connections.append(connection)
        return connection

    def disconnect(connection):
        disconnected.append(connection)

    events: list[str] = []
    browser = RecoverableBrowser(
        connect,
        disconnect=disconnect,
        unstick=lambda: events.append("unstick"),
    )
    stale = browser.connection

    recovered = browser.recover()

    assert disconnected == [stale]
    assert events == ["unstick"]
    assert recovered is browser.connection
    assert recovered["target"] == stale["target"] == "job-tab-1"
    assert recovered["generation"] == "2"
    assert recovered is not stale


def test_a_failed_unstick_still_leaves_a_fresh_connection():
    generations: list[int] = []

    def connect():
        generations.append(len(generations) + 1)
        return generations[-1]

    def broken_unstick():
        raise OSError("cdp-unstick died")

    browser = RecoverableBrowser(connect, unstick=broken_unstick)

    with pytest.raises(OSError, match="cdp-unstick died"):
        browser.recover()

    assert browser.connection == 2
    assert generations == [1, 2]


def test_recovery_commands_accept_a_path_sequence(tmp_path: Path):
    runner = FakeRunner(write_file=False)
    recovery = CommandRecovery(
        [RecoveryCommand([str(tmp_path / "cdp-unstick")])],
        runner=runner,
    )

    recovery()

    assert runner.calls == [[str(tmp_path / "cdp-unstick")]]
