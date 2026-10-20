"""Optional MP4 recording for a daily run.

Video is off by default: screenshots and ``events.jsonl`` are the primary
evidence.  When enabled, one recording covers the whole run and lands in
``output/sessions/<run_id>/video.mp4``.  Recording failures never change the
application outcome; the report simply omits the video artifact.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Protocol

VIDEO_FILENAME = "video.mp4"


class VideoRecorder(Protocol):
    def start(self, path: Path) -> None: ...

    def stop(self) -> None: ...


class NullVideoRecorder:
    """The default: recording is disabled."""

    def start(self, path: Path) -> None:
        return None

    def stop(self) -> None:
        return None


class FakeVideoRecorder:
    """Deterministic stand-in used with ``--adapter fake``."""

    def start(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake-mp4")

    def stop(self) -> None:
        return None


class WfRecorderVideo:
    """Record the screen with ``wf-recorder`` until ``stop`` is called."""

    def __init__(
        self,
        *,
        binary: str = "wf-recorder",
        popen: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
    ) -> None:
        self.binary = binary
        self._popen = popen
        self._process: subprocess.Popen[bytes] | None = None

    def start(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._process = self._popen(
                [self.binary, "-f", str(path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            # Recording is optional evidence; a missing tool must not fail the run.
            self._process = None

    def stop(self) -> None:
        process = self._process
        self._process = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
