"""Human and machine-readable reports for one daily run.

A **Run** owns the funnel (candidates, discards, eligible jobs, CV reuse and
verified applications), while each job keeps its session directory with the
events and screenshots collected by :mod:`career_ops.session`.  This module
reads those persisted artifacts and writes four files next to them:

* ``report.md`` — readable report with the funnel and one row per job;
* ``report.html`` — the same report with screenshot thumbnails;
* ``summary.txt`` — short text summary for humans;
* ``summary.json`` — machine-readable summary for Hermes.

Reports are generated from persisted state only, so ``career-ops-report`` can
regenerate an old run without replaying it.  Retention is opt-in at the caller
(``prune_runs``) and only removes finished runs, never the protected/current one.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from career_ops.paths import WorkspacePaths
from career_ops.queue import JobQueue, StoredJob
from career_ops.run_state import RUNS_DIRNAME, validate_run_id
from career_ops.session import SESSION_DIRNAME
from career_ops.video import VIDEO_FILENAME

REPORT_MARKDOWN = "report.md"
REPORT_HTML = "report.html"
SUMMARY_TEXT = "summary.txt"
SUMMARY_JSON = "summary.json"
DEFAULT_RETENTION_RUNS = 3

_FUNNEL_STAGES = (
    ("Candidatos", "candidates"),
    ("Descartes", "discarded"),
    ("Elegíveis", "eligible"),
    ("CVs gerados", "cvs_generated"),
    ("CVs reutilizados", "cvs_reused"),
    ("Aplicadas", "applied"),
    ("Verificadas", "verified"),
    ("Falhas", "failures"),
    ("Aguardando resposta", "waiting"),
)

_ELIGIBLE_STATES = frozenset(
    {"eligible", "applying", "waiting_input", "submitted", "verified"}
)
_DISCARD_STATES = frozenset({"title_rejected", "ineligible"})


class ReportError(ValueError):
    """A report could not be built from the requested run."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


@dataclass(frozen=True)
class ReportScreenshot:
    stage: str
    path: str

    def as_dict(self) -> dict[str, str]:
        return {"stage": self.stage, "path": self.path}


@dataclass(frozen=True)
class ReportJob:
    job_id: str
    title: str
    company: str
    state: str
    reason: str | None
    duration_ms: int
    cv: str | None
    cv_cache: Mapping[str, object] | None
    session_dir: str | None
    screenshots: tuple[ReportScreenshot, ...]
    submitted: bool = False
    verified: bool = False
    waiting: bool = False

    @property
    def cv_reused(self) -> bool | None:
        if self.cv_cache is None:
            return None
        return bool(self.cv_cache.get("hit"))

    @property
    def cv_id(self) -> str | None:
        if self.cv_cache is None:
            return None
        value = self.cv_cache.get("cv_id")
        return str(value) if value else None

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.job_id,
            "title": self.title,
            "company": self.company,
            "state": self.state,
            "reason": self.reason,
            "duration_ms": self.duration_ms,
            "cv": self.cv,
            "cv_reused": self.cv_reused,
            "cv_id": self.cv_id,
            "cv_cache": dict(self.cv_cache) if self.cv_cache is not None else None,
            "session_dir": self.session_dir,
            "screenshots": [screenshot.as_dict() for screenshot in self.screenshots],
            "submitted": self.submitted,
            "verified": self.verified,
            "waiting": self.waiting,
        }


@dataclass(frozen=True)
class ReportArtifacts:
    run_dir: Path
    markdown: Path
    html: Path
    summary_text: Path
    summary_json: Path
    video: Path | None

    def as_dict(self) -> dict[str, object]:
        return {
            "session_dir": str(self.run_dir),
            "markdown": str(self.markdown),
            "html": str(self.html),
            "summary_text": str(self.summary_text),
            "summary_json": str(self.summary_json),
            "video": str(self.video) if self.video is not None else None,
        }


@dataclass(frozen=True)
class RunReport:
    run_id: str
    summary: Mapping[str, object]
    jobs: tuple[ReportJob, ...]
    artifacts: ReportArtifacts
    markdown: str
    html: str
    text: str


def build_run_report(
    paths: WorkspacePaths,
    run_id: str,
) -> RunReport:
    """Read one finished (or in-flight) run and write its report artifacts."""
    validate_run_id(run_id)
    state_path = paths.data / RUNS_DIRNAME / f"{run_id}.json"
    if not state_path.is_file():
        raise ReportError(
            "run_not_found",
            f"run state not found: {state_path}",
        )

    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReportError("run_unreadable", f"could not read {state_path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ReportError("run_unreadable", f"run state {state_path} must be an object")

    try:
        queue = JobQueue.load(paths)
    except ValueError as exc:
        raise ReportError("queue_unreadable", str(exc)) from exc

    run_dir = paths.output / SESSION_DIRNAME / run_id
    history = _history_in_window(queue, payload)
    history_outcomes = _history_outcomes(history)
    state_jobs = _state_jobs(payload)
    job_ids = _ordered_job_ids(history, state_jobs)
    jobs = tuple(
        _build_job(
            job_id,
            run_dir,
            queue.records.get(job_id),
            state_jobs.get(job_id),
            history_outcomes.get(job_id),
        )
        for job_id in job_ids
    )
    funnel = _funnel(payload, jobs, history)
    summary = _summary(payload, run_id, run_dir, funnel, jobs)
    markdown = _render_markdown(run_id, summary, jobs)
    html_document = _render_html(run_id, summary, jobs)
    text = _render_text(run_id, summary, jobs)

    video = run_dir / VIDEO_FILENAME
    artifacts = ReportArtifacts(
        run_dir=run_dir,
        markdown=run_dir / REPORT_MARKDOWN,
        html=run_dir / REPORT_HTML,
        summary_text=run_dir / SUMMARY_TEXT,
        summary_json=run_dir / SUMMARY_JSON,
        video=video if video.is_file() else None,
    )
    try:
        paths.assert_writable(run_dir)
        _write_text(artifacts.markdown, markdown)
        _write_text(artifacts.html, html_document)
        _write_text(artifacts.summary_text, text)
        _write_text(
            artifacts.summary_json,
            json.dumps(dict(summary), ensure_ascii=False, indent=2) + "\n",
        )
    except (OSError, ValueError) as exc:
        raise ReportError(
            "report_unwritable",
            f"could not write the report in {run_dir}: {exc}",
        ) from exc
    return RunReport(
        run_id=run_id,
        summary=summary,
        jobs=jobs,
        artifacts=artifacts,
        markdown=markdown,
        html=html_document,
        text=text,
    )


def retention_limit(
    raw: int | None,
    environment: Mapping[str, str],
) -> int:
    """Resolve the retention window from a flag, the environment or the default."""
    if raw is not None:
        if raw < 1:
            raise ValueError("keep must be at least 1")
        return raw
    value = environment.get("CAREER_OPS_RETENTION_RUNS")
    if value is None or not value.strip():
        return DEFAULT_RETENTION_RUNS
    try:
        parsed = int(value.strip())
    except ValueError as exc:
        raise ValueError(
            f"CAREER_OPS_RETENTION_RUNS must be an integer, got {value!r}"
        ) from exc
    if parsed < 1:
        raise ValueError(
            f"CAREER_OPS_RETENTION_RUNS must be at least 1, got {value!r}"
        )
    return parsed


def latest_run_id(paths: WorkspacePaths) -> str | None:
    """Return the most recently finished run id, if any."""
    runs = _finished_runs(paths)
    if not runs:
        return None
    return max(runs, key=lambda run: (run.updated_at, run.run_id)).run_id


def prune_runs(
    paths: WorkspacePaths,
    *,
    keep: int = DEFAULT_RETENTION_RUNS,
    protected: Iterable[str] = (),
) -> tuple[str, ...]:
    """Delete finished runs beyond the retention window.

    Only runs with a finished state file are candidates.  The current run (or
    any explicitly protected id) is never removed.  Each removed run loses its
    ``output/sessions/<run_id>`` directory and ``data/runs/<run_id>.json``.
    """
    if keep < 1:
        raise ValueError("keep must be at least 1")
    protected_ids = set(protected)
    runs = _finished_runs(paths)
    runs.sort(key=lambda run: (run.updated_at, run.run_id), reverse=True)
    kept = {run.run_id for run in runs[:keep]} | protected_ids
    removed: list[str] = []
    for run in runs:
        if run.run_id in kept:
            continue
        _remove_run(paths, run.run_id)
        removed.append(run.run_id)
    return tuple(removed)


@dataclass(frozen=True)
class _FinishedRun:
    run_id: str
    updated_at: str


def _finished_runs(paths: WorkspacePaths) -> list[_FinishedRun]:
    runs_dir = paths.data / RUNS_DIRNAME
    if not runs_dir.is_dir():
        return []
    finished: list[_FinishedRun] = []
    for path in sorted(runs_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, Mapping):
            continue
        if payload.get("status") not in {"verified", "failed"}:
            continue
        if not payload.get("stop_reason"):
            continue
        run_id = str(payload.get("run_id") or path.stem)
        try:
            validate_run_id(run_id)
        except ValueError:
            # A corrupt state file must never turn into a path outside the
            # workspace when retention deletes the run.
            continue
        finished.append(
            _FinishedRun(
                run_id=run_id,
                updated_at=str(payload.get("updated_at") or payload.get("started_at") or ""),
            )
        )
    return finished


def _remove_run(paths: WorkspacePaths, run_id: str) -> None:
    validate_run_id(run_id)
    session_dir = paths.output / SESSION_DIRNAME / run_id
    if session_dir.is_dir():
        paths.assert_writable(session_dir)
        _remove_tree(session_dir)
    state_path = paths.data / RUNS_DIRNAME / f"{run_id}.json"
    if state_path.is_file():
        paths.assert_writable(state_path)
        state_path.unlink()


def _remove_tree(root: Path) -> None:
    for child in sorted(root.rglob("*"), key=lambda path: len(path.parts), reverse=True):
        if child.is_dir():
            child.rmdir()
        else:
            child.unlink()
    root.rmdir()


def _history_in_window(
    queue: JobQueue, payload: Mapping[str, object]
) -> list[Mapping[str, object]]:
    started = _parse_timestamp(payload.get("started_at"))
    finished = _parse_timestamp(payload.get("updated_at"))
    history: list[Mapping[str, object]] = []
    for entry in queue.history:
        moment = _parse_timestamp(entry.get("ts"))
        if started is not None and moment is not None and moment < started:
            continue
        if finished is not None and moment is not None and moment > finished:
            continue
        history.append(entry)
    return history


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _state_jobs(payload: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    raw = payload.get("jobs")
    if not isinstance(raw, Mapping):
        return {}
    return {
        str(job_id): info
        for job_id, info in raw.items()
        if isinstance(info, Mapping)
    }


def _ordered_job_ids(
    history: Sequence[Mapping[str, object]],
    state_jobs: Mapping[str, Mapping[str, object]],
) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for entry in history:
        job_id = entry.get("id")
        # Duplicate discovery only writes `skipped`; it must not inflate the
        # funnel or add a row from a previous run.
        if entry.get("action") == "skipped":
            continue
        if job_id is not None and str(job_id) not in seen:
            seen.add(str(job_id))
            ordered.append(str(job_id))
    for job_id in state_jobs:
        if job_id not in seen:
            seen.add(job_id)
            ordered.append(job_id)
    return ordered


def _history_outcomes(
    history: Sequence[Mapping[str, object]],
) -> dict[str, tuple[str, str | None]]:
    """Latest meaningful queue state per job inside the run window.

    ``skipped`` entries only describe duplicate discovery, so they never change
    the historical outcome.  Later queue changes fall outside the window and
    therefore cannot rewrite an old report.
    """
    outcomes: dict[str, tuple[str, str | None]] = {}
    for entry in history:
        job_id = entry.get("id")
        state = entry.get("state")
        if job_id is None or entry.get("action") == "skipped":
            continue
        if not isinstance(state, str) or not state:
            continue
        outcomes[str(job_id)] = (state, _optional_str(entry.get("reason")))
    return outcomes


def _build_job(
    job_id: str,
    run_dir: Path,
    record: StoredJob | None,
    state_job: Mapping[str, object] | None,
    history_outcome: tuple[str, str | None] | None,
) -> ReportJob:
    state_job = state_job or {}
    detail = record.detail if record is not None else {}
    history_state, history_reason = history_outcome or (None, None)
    state = _optional_str(state_job.get("state")) or history_state
    reason = _optional_str(state_job.get("reason"))
    if reason is None:
        reason = history_reason
    if state is None and record is not None:
        state = record.state
        if reason is None:
            reason = record.reason
    state = state or "unknown"

    session_dirs = _session_dirs(run_dir, job_id, state_job, detail)
    session_dir = _first_session(session_dirs)
    duration_ms = _as_int(state_job.get("duration_ms"))
    if duration_ms == 0:
        duration_ms = _session_duration(session_dirs)
    cv = _optional_str(state_job.get("cv")) or _optional_str(detail.get("cv"))
    cv_cache = state_job.get("cv_cache")
    if not isinstance(cv_cache, Mapping):
        possible = detail.get("cv_cache")
        cv_cache = possible if isinstance(possible, Mapping) else None

    if state == "running":
        state = "unknown"

    title = record.candidate.title if record is not None else ""
    company = record.candidate.company if record is not None else ""
    screenshots = _screenshots(run_dir, session_dirs)
    return ReportJob(
        job_id=job_id,
        title=title,
        company=company,
        state=state,
        reason=reason,
        duration_ms=duration_ms,
        cv=cv,
        cv_cache=dict(cv_cache) if isinstance(cv_cache, Mapping) else None,
        session_dir=session_dir,
        screenshots=screenshots,
        submitted=_as_bool(state_job.get("submitted")),
        verified=_as_bool(state_job.get("verified")),
        waiting=_as_bool(state_job.get("waiting")),
    )


def _session_dirs(
    run_dir: Path,
    job_id: str,
    state_job: Mapping[str, object],
    detail: Mapping[str, object],
) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        resolved = path if path.is_absolute() else run_dir / path
        if resolved in seen or not resolved.is_dir():
            return
        seen.add(resolved)
        found.append(resolved)

    recorded = state_job.get("session_dir") or detail.get("session_dir")
    if isinstance(recorded, str) and recorded:
        add(Path(recorded))
    if run_dir.is_dir():
        pattern = re.compile(rf"{re.escape(job_id)}(?:-\d+)?")
        for candidate in sorted(run_dir.iterdir()):
            if candidate.is_dir() and pattern.fullmatch(candidate.name):
                add(candidate)
    return found


def _first_session(session_dirs: Sequence[Path]) -> str | None:
    return str(session_dirs[0]) if session_dirs else None


def _session_duration(session_dirs: Sequence[Path]) -> int:
    total = 0
    for directory in session_dirs:
        metadata_path = directory / "session.json"
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        created = _parse_timestamp(metadata.get("created_at"))
        finished = _parse_timestamp(metadata.get("finished_at"))
        if created is not None and finished is not None and finished >= created:
            total += int((finished - created).total_seconds() * 1000)
    return total


def _screenshots(run_dir: Path, session_dirs: Sequence[Path]) -> tuple[ReportScreenshot, ...]:
    screenshots: list[ReportScreenshot] = []
    seen: set[str] = set()
    for directory in session_dirs:
        stages = _stage_by_artifact(directory)
        for path in sorted((directory / "screenshots").glob("*.png")):
            artifact = path.relative_to(directory).as_posix()
            try:
                relative = path.relative_to(run_dir).as_posix()
            except ValueError:
                relative = path.as_posix()
            if relative in seen:
                continue
            seen.add(relative)
            screenshots.append(
                ReportScreenshot(
                    stage=stages.get(artifact) or path.stem,
                    path=relative,
                )
            )
    return tuple(screenshots)


def _stage_by_artifact(session_dir: Path) -> dict[str, str]:
    stages: dict[str, str] = {}
    try:
        lines = (session_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return stages
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, Mapping):
            continue
        artifact = event.get("artifact")
        stage = event.get("stage")
        if isinstance(artifact, str) and isinstance(stage, str):
            stages[artifact] = stage
    return stages


def _funnel(
    payload: Mapping[str, object],
    jobs: Sequence[ReportJob],
    history: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    discards: dict[str, int] = {}
    failures: list[dict[str, str]] = []
    waiting = 0
    applied = 0
    verified = 0
    cvs_generated = 0
    cvs_reused = 0
    eligible = 0

    states_by_job: dict[str, set[str]] = {}
    for entry in history:
        job_id = entry.get("id")
        state = entry.get("state")
        if job_id is None or not isinstance(state, str):
            continue
        states_by_job.setdefault(str(job_id), set()).add(state)

    for job in jobs:
        state = job.state
        reason = job.reason
        if state in _DISCARD_STATES:
            key = reason or state
            discards[key] = discards.get(key, 0) + 1
        if state == "failed":
            failures.append({"id": job.job_id, "reason": reason or "failed"})
        if job.waiting or state == "waiting_input":
            waiting += 1
        if state in _ELIGIBLE_STATES or _ELIGIBLE_STATES & states_by_job.get(job.job_id, set()):
            eligible += 1
        if job.submitted or job.verified or state in {"submitted", "verified"}:
            applied += 1
        if job.verified or state == "verified":
            verified += 1
        if job.cv_reused is True:
            cvs_reused += 1
        elif job.cv_reused is False:
            cvs_generated += 1

    verified = max(verified, _as_int(payload.get("verified")))
    # A verified application is necessarily an applied one; keep the funnel
    # monotonic even when an old run state predates the `submitted` flag.
    applied = max(applied, verified)
    return {
        "candidates": len(jobs),
        "discarded": sum(discards.values()),
        "discards_by_reason": dict(sorted(discards.items())),
        "eligible": eligible,
        "cvs_generated": cvs_generated,
        "cvs_reused": cvs_reused,
        "applied": applied,
        "verified": verified,
        "failures": len(failures),
        "failure_reasons": failures,
        "waiting": waiting,
    }


def _summary(
    payload: Mapping[str, object],
    run_id: str,
    run_dir: Path,
    funnel: Mapping[str, object],
    jobs: Sequence[ReportJob],
) -> dict[str, object]:
    status = str(payload.get("status") or "running")
    markdown = run_dir / REPORT_MARKDOWN
    html_path = run_dir / REPORT_HTML
    video = run_dir / VIDEO_FILENAME
    return {
        "run_id": run_id,
        "status": status,
        "stop_reason": _optional_str(payload.get("stop_reason")),
        "target": _as_int(payload.get("target")),
        "started_at": _optional_str(payload.get("started_at")),
        "finished_at": _optional_str(payload.get("updated_at")),
        "submitted": funnel["applied"],
        "verified": funnel["verified"],
        "waiting": funnel["waiting"],
        "funnel": dict(funnel),
        "blockers": dict(_mapping(funnel.get("discards_by_reason"))),
        "failures": _list_of_mappings(funnel.get("failure_reasons")),
        "session_path": str(run_dir),
        "report": {
            "markdown": str(markdown),
            "html": str(html_path),
        },
        "video": str(video) if video.is_file() else None,
        "jobs": [job.as_dict() for job in jobs],
    }


def _render_markdown(
    run_id: str,
    summary: Mapping[str, object],
    jobs: Sequence[ReportJob],
) -> str:
    funnel = _mapping(summary.get("funnel"))
    lines = [
        f"# Relatório diário — {run_id}",
        "",
        f"- Status: **{summary.get('status')}**",
        f"- Parada: `{summary.get('stop_reason')}`",
        f"- Meta: {summary.get('target')} verificadas",
        f"- Sessão: `{summary.get('session_path')}`",
        "",
        "## Funil",
        "",
        "| Etapa | Quantidade |",
        "| --- | ---: |",
    ]
    lines.extend(
        f"| {label} | {funnel.get(key, 0)} |" for label, key in _FUNNEL_STAGES
    )
    lines.append("")

    discards = _mapping(funnel.get("discards_by_reason"))
    lines.extend(["## Descartes por motivo", ""])
    if discards:
        lines.extend(["| Motivo | Quantidade |", "| --- | ---: |"])
        lines.extend(f"| `{reason}` | {count} |" for reason, count in discards.items())
    else:
        lines.append("Nenhum descarte.")
    lines.append("")

    lines.extend(
        [
            "## Vagas",
            "",
            "| Vaga | Título | Status | Duração | CV | Motivo | Evidências |",
            "| --- | --- | --- | ---: | --- | --- | --- |",
        ]
    )
    for job in jobs:
        screenshots = " ".join(
            f"[{escape_markdown(shot.stage)}]({shot.path})" for shot in job.screenshots
        )
        cv = f"`{_cv_label(job)}`" if job.cv else "—"
        lines.append(
            "| {id} | {title} | {state} | {duration} | {cv} | {reason} | {shots} |".format(
                id=escape_markdown(job.job_id),
                title=escape_markdown(job.title or "—"),
                state=escape_markdown(job.state),
                duration=_duration_label(job.duration_ms),
                cv=cv,
                reason=escape_markdown(job.reason or "—"),
                shots=screenshots or "—",
            )
        )
    lines.extend(["", _video_line(summary), ""])
    return "\n".join(lines)


def _render_html(
    run_id: str,
    summary: Mapping[str, object],
    jobs: Sequence[ReportJob],
) -> str:
    funnel = _mapping(summary.get("funnel"))
    discards = _mapping(funnel.get("discards_by_reason"))
    discard_rows = "".join(
        f"<tr><td><code>{html.escape(str(reason))}</code></td><td>{count}</td></tr>"
        for reason, count in discards.items()
    ) or '<tr><td colspan="2">Nenhum descarte.</td></tr>'
    funnel_rows = "".join(
        f"<tr><td>{label}</td><td>{funnel.get(key, 0)}</td></tr>"
        for label, key in _FUNNEL_STAGES
    )
    job_rows: list[str] = []
    for job in jobs:
        thumbnails = "".join(
            '<figure><a href="{path}"><img class="thumb" src="{path}" alt="{stage}"></a>'
            "<figcaption>{stage}</figcaption></figure>".format(
                path=html.escape(shot.path, quote=True),
                stage=html.escape(shot.stage),
            )
            for shot in job.screenshots
        )
        job_rows.append(
            "<tr>"
            f"<td>{html.escape(job.job_id)}</td>"
            f"<td>{html.escape(job.title or '—')}</td>"
            f"<td>{html.escape(job.state)}</td>"
            f"<td>{_duration_label(job.duration_ms)}</td>"
            f"<td>{html.escape(_cv_label(job))}</td>"
            f"<td>{html.escape(job.reason or '—')}</td>"
            f'<td class="evidence">{thumbnails or "—"}</td>'
            "</tr>"
        )
    video = summary.get("video")
    video_block = (
        f'<p>Vídeo: <a href="{html.escape(str(video), quote=True)}">'
        f"{Path(str(video)).name}</a></p>"
        if video
        else ""
    )
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Relatório diário — {html.escape(run_id)}</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 2rem; color: #1f2933; }}
table {{ border-collapse: collapse; width: 100%; margin-bottom: 1.5rem; }}
th, td {{ border: 1px solid #d9e2ec; padding: .4rem .6rem; text-align: left; vertical-align: top; }}
th {{ background: #f0f4f8; }}
.evidence {{ display: flex; gap: .75rem; flex-wrap: wrap; }}
figure {{ margin: 0; text-align: center; }}
.thumb {{ max-width: 220px; max-height: 140px; border: 1px solid #bcccdc; }}
figcaption {{ font-size: .8rem; color: #52606d; }}
</style>
</head>
<body>
<h1>Relatório diário — {html.escape(run_id)}</h1>
<p>Status: <strong>{html.escape(str(summary.get('status')))}</strong> · Parada:
<code>{html.escape(str(summary.get('stop_reason')))}</code> · Meta:
{summary.get('target')} verificadas</p>
<p>Sessão: <code>{html.escape(str(summary.get('session_path')))}</code></p>
<h2>Funil</h2>
<table>
<tr><th>Etapa</th><th>Quantidade</th></tr>
{funnel_rows}
</table>
<h2>Descartes por motivo</h2>
<table><tr><th>Motivo</th><th>Quantidade</th></tr>{discard_rows}</table>
<h2>Vagas</h2>
<table>
<tr><th>Vaga</th><th>Título</th><th>Status</th><th>Duração</th><th>CV</th><th>Motivo</th><th>Evidências</th></tr>
{''.join(job_rows)}
</table>
{video_block}
</body>
</html>
"""


def _render_text(
    run_id: str,
    summary: Mapping[str, object],
    jobs: Sequence[ReportJob],
) -> str:
    funnel = _mapping(summary.get("funnel"))
    discards = _mapping(funnel.get("discards_by_reason"))
    discard_text = ", ".join(f"{reason}={count}" for reason, count in discards.items())
    failure_text = ", ".join(
        f"{item.get('id')}={item.get('reason')}"
        for item in _list_of_mappings(summary.get("failures"))
    )
    lines = [
        f"Sessão {run_id}: {summary.get('status')} ({summary.get('stop_reason')})",
        (
            "Funil: candidatos={candidates} descartes={discarded} elegíveis={eligible} "
            "CVs={reused}+{generated} aplicadas={applied} verificadas={verified} "
            "falhas={failures} aguardando={waiting}"
        ).format(
            candidates=funnel.get("candidates", 0),
            discarded=funnel.get("discarded", 0),
            eligible=funnel.get("eligible", 0),
            reused=funnel.get("cvs_reused", 0),
            generated=funnel.get("cvs_generated", 0),
            applied=funnel.get("applied", 0),
            verified=funnel.get("verified", 0),
            failures=funnel.get("failures", 0),
            waiting=funnel.get("waiting", 0),
        ),
        f"Descartes: {discard_text or 'nenhum'}",
        f"Falhas: {failure_text or 'nenhuma'}",
        f"Sessão: {summary.get('session_path')}",
        f"Relatório: {_mapping(summary.get('report')).get('markdown')}",
    ]
    if summary.get("video"):
        lines.append(f"Vídeo: {summary.get('video')}")
    return "\n".join(lines) + "\n"


def _cv_label(job: ReportJob) -> str:
    if not job.cv:
        return "—"
    suffix = ""
    if job.cv_reused is True:
        suffix = " (reutilizado)"
    elif job.cv_reused is False:
        suffix = " (gerado)"
    return f"{Path(job.cv).name}{suffix}"


def _duration_label(duration_ms: int) -> str:
    if duration_ms <= 0:
        return "—"
    seconds = duration_ms / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, remainder = divmod(int(seconds), 60)
    return f"{minutes}m{remainder:02d}s"


def _video_line(summary: Mapping[str, object]) -> str:
    video = summary.get("video")
    if not video:
        return "Vídeo: desligado."
    return f"Vídeo: [{Path(str(video)).name}]({Path(str(video)).name})"


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _list_of_mappings(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


def _as_int(value: object) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return 0


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "sim"}
    return bool(value)


def escape_markdown(value: str) -> str:
    return (value or "").replace("|", "\\|").replace("\n", " ")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)
