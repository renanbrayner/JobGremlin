"""Evidence package for the parallel rehearsal and the Hermes handoff.

The rehearsal runs the real CLI with the fake application adapter, so it proves
the deterministic orchestration, the artifacts and the report without touching
LinkedIn.  This module keeps the comparison against the 19/10 reference round
and renders the Markdown report; the developer script that performs the runs
lives in ``scripts/rehearsal``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from career_ops.job_description import JD_MISSING_REASON
from career_ops.job_filters import LOCATION_REJECTION_REASONS
from career_ops.queue import TITLE_REJECTED_STATE

BASELINE_DATE = "2026-10-19"
BASELINE_2026_10_19: Mapping[str, object] = {
    "cards": 1950,
    "unique_jobs": 344,
    "shortlist": 129,
    "jds_read": 12,
    "eligible": 4,
    "submitted": 0,
    "verified": 0,
    "screenshots": 0,
    "note": (
        "o renderer congelou no upload do CV; nenhuma candidatura foi enviada e "
        "não existe screenshot por vaga"
    ),
}

_TITLE_STATE = TITLE_REJECTED_STATE
_LOCATION_REASONS = LOCATION_REJECTION_REASONS
_JD_MISSING = JD_MISSING_REASON

_COMPARISON_ROWS: tuple[tuple[str, str], ...] = (
    ("unique_jobs", "Vagas únicas na rodada"),
    ("shortlist", "Shortlist"),
    ("jds_read", "JDs lidas"),
    ("eligible", "Elegíveis"),
    ("submitted", "Enviadas (clique)"),
    ("verified", "Verificadas"),
    ("screenshots", "Screenshots"),
)


@dataclass(frozen=True)
class RehearsalStep:
    """One rehearsal round, loaded from its persisted ``summary.json``."""

    label: str
    run_id: str
    summary: Mapping[str, object]

    @property
    def target(self) -> int:
        return _as_int(self.summary.get("target"))

    @property
    def status(self) -> str:
        return str(self.summary.get("status") or "unknown")

    @property
    def stop_reason(self) -> str:
        return str(self.summary.get("stop_reason") or "unknown")

    def metrics(self) -> dict[str, int]:
        funnel = _mapping(self.summary.get("funnel"))
        jobs = _jobs(self.summary)
        candidates = _as_int(funnel.get("candidates"))
        title_rejected = sum(
            1 for job in jobs if job.get("state") == _TITLE_STATE
        )
        location_rejected = sum(
            1 for job in jobs if job.get("reason") in _LOCATION_REASONS
        )
        jds_read = sum(1 for job in jobs if _read_jd(job))
        screenshots = sum(_screenshot_count(job) for job in jobs)
        return {
            "unique_jobs": candidates,
            "shortlist": max(candidates - title_rejected - location_rejected, 0),
            "jds_read": jds_read,
            "eligible": _as_int(funnel.get("eligible")),
            "submitted": _as_int(funnel.get("applied")),
            "verified": _as_int(funnel.get("verified")),
            "failures": _as_int(funnel.get("failures")),
            "waiting": _as_int(funnel.get("waiting")),
            "cvs_generated": _as_int(funnel.get("cvs_generated")),
            "cvs_reused": _as_int(funnel.get("cvs_reused")),
            "screenshots": screenshots,
        }

    def artifacts(self, *, root: Path | None = None) -> dict[str, str]:
        return _artifacts(self.summary, root=root)

    def results(self) -> tuple[Mapping[str, object], ...]:
        return tuple(
            {
                "job_id": str(job.get("id") or ""),
                "state": str(job.get("state") or "unknown"),
                "reason": job.get("reason"),
                "cv_reused": job.get("cv_reused"),
                "cv_id": job.get("cv_id"),
            }
            for job in _jobs(self.summary)
        )


@dataclass(frozen=True)
class _StepPayload:
    label: str
    run_id: str
    status: str
    stop_reason: str
    target: int
    metrics: Mapping[str, int]
    artifacts: Mapping[str, str]
    results: tuple[Mapping[str, object], ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "run_id": self.run_id,
            "status": self.status,
            "stop_reason": self.stop_reason,
            "target": self.target,
            "metrics": dict(self.metrics),
            "artifacts": dict(self.artifacts),
            "results": [dict(result) for result in self.results],
        }


@dataclass(frozen=True)
class _ComparisonRow:
    metric: str
    label: str
    baseline: object
    values: tuple[int, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "metric": self.metric,
            "label": self.label,
            "baseline": self.baseline,
            "values": list(self.values),
        }


def render_rehearsal_report(
    *,
    date: str,
    steps: Sequence[RehearsalStep],
    isolation: Mapping[str, object] | None,
    root: Path | None = None,
) -> tuple[str, dict[str, object]]:
    """Return the Markdown report and its machine-readable evidence."""
    if not steps:
        raise ValueError("a rehearsal report needs at least one step")
    step_payloads = [
        _StepPayload(
            label=step.label,
            run_id=step.run_id,
            status=step.status,
            stop_reason=step.stop_reason,
            target=step.target,
            metrics=step.metrics(),
            artifacts=step.artifacts(root=root),
            results=step.results(),
        )
        for step in steps
    ]
    rows = [
        _ComparisonRow(
            metric=metric,
            label=label,
            baseline=BASELINE_2026_10_19[metric],
            values=tuple(
                step_payload.metrics[metric] for step_payload in step_payloads
            ),
        )
        for metric, label in _COMPARISON_ROWS
    ]
    payload: dict[str, object] = {
        "date": date,
        "mode": "fake-adapter-offline",
        "baseline": dict(BASELINE_2026_10_19),
        "steps": [step_payload.as_dict() for step_payload in step_payloads],
        "comparison": {
            "baseline_date": BASELINE_DATE,
            "rows": [row.as_dict() for row in rows],
            "cards_replayed": False,
        },
        "isolation": dict(isolation) if isolation is not None else None,
    }
    return _render_markdown(payload, step_payloads, rows), payload


def _render_markdown(
    payload: Mapping[str, object],
    step_payloads: Sequence[_StepPayload],
    rows: Sequence[_ComparisonRow],
) -> str:
    date = payload["date"]
    lines = [
        f"# Ensaio paralelo — {date}",
        "",
        (
            "Execução do CLI real com o adaptador fake, em um workspace isolado: "
            "não toca no LinkedIn, no Hermes, no cron, na allowlist, em "
            "`~/.local/bin` nem no checkout atual do career-ops."
        ),
        "",
        (
            "O ensaio valida orquestração, decisões, artefatos e isolamento. "
            "Ele não valida o comportamento do LinkedIn nem o adaptador real."
        ),
        "",
        "## Rodadas",
        "",
        "| Rodada | Run ID | Meta | Status | Parada | Verificadas | CVs (gerado+reuso) | Screenshots |",
        "| --- | --- | ---: | --- | --- | ---: | ---: | ---: |",
    ]
    for step_payload in step_payloads:
        metrics = step_payload.metrics
        lines.append(
            "| {label} | `{run_id}` | {target} | {status} | `{stop}` | "
            "{verified} | {generated}+{reused} | {shots} |".format(
                label=step_payload.label,
                run_id=step_payload.run_id,
                target=step_payload.target,
                status=step_payload.status,
                stop=step_payload.stop_reason,
                verified=metrics["verified"],
                generated=metrics["cvs_generated"],
                reused=metrics["cvs_reused"],
                shots=metrics["screenshots"],
            )
        )

    lines.extend(
        [
            "",
            "## Comparação com a linha de base de 19/10",
            "",
            "| Métrica | 19/10 | "
            + " | ".join(step.label for step in step_payloads)
            + " |",
            "| --- | ---: | " + " | ".join("---:" for _ in step_payloads) + " |",
        ]
    )
    for row in rows:
        values = " | ".join(
            "—" if value is None else str(value) for value in row.values
        )
        lines.append(f"| {row.label} | {row.baseline} | {values} |")

    baseline = _mapping(payload.get("baseline"))
    lines.extend(
        [
            "",
            (
                "A linha de base de 19/10 partiu de "
                f"{baseline['cards']} cards, {baseline['unique_jobs']} vagas únicas, "
                f"{baseline['shortlist']} na shortlist, {baseline['jds_read']} JDs "
                f"lidas e {baseline['eligible']} elegíveis. Terminou com "
                f"{baseline['submitted']} envios e {baseline['verified']} verificadas: "
                f"{baseline['note']}."
            ),
            "",
            (
                "Os cards de pool não são reexecutados no ensaio: a rodada começa "
                "de listas de candidatos e fixtures de JD. Vagas únicas, shortlist, "
                "JDs lidas, elegíveis, envios e verificadas são comparáveis; o "
                "tempo real e o comportamento do LinkedIn não são."
            ),
            "",
            "## Decisões e resultados por rodada",
            "",
        ]
    )
    for step_payload in step_payloads:
        metrics = step_payload.metrics
        lines.extend(
            [
                f"### {step_payload.label} (`{step_payload.run_id}`)",
                "",
                (
                    f"Funil: {metrics['unique_jobs']} candidato(s), "
                    f"{metrics['shortlist']} na shortlist, "
                    f"{metrics['jds_read']} JD(s) lida(s), "
                    f"{metrics['eligible']} elegível(is), "
                    f"{metrics['cvs_generated']} CV(s) gerado(s), "
                    f"{metrics['cvs_reused']} reutilizado(s), "
                    f"{metrics['submitted']} enviada(s), "
                    f"{metrics['verified']} verificada(s), "
                    f"{metrics['failures']} falha(s) e "
                    f"{metrics['waiting']} aguardando resposta."
                ),
                "",
            ]
        )
        if step_payload.results:
            lines.extend(
                [
                    "| Vaga | Estado | Motivo | CV |",
                    "| --- | --- | --- | --- |",
                ]
            )
            for result in step_payload.results:
                reuse = result.get("cv_reused")
                cv_id = str(result.get("cv_id") or "—")
                if reuse is True:
                    cv_id = f"{cv_id} (reutilizado)"
                elif reuse is False:
                    cv_id = f"{cv_id} (gerado)"
                lines.append(
                    "| {job} | {state} | {reason} | {cv} |".format(
                        job=result.get("job_id") or "—",
                        state=result.get("state") or "—",
                        reason=result.get("reason") or "—",
                        cv=cv_id,
                    )
                )
            lines.append("")
        if step_payload.artifacts:
            lines.extend(
                [
                    "Artefatos:",
                    "",
                    *(
                        f"- {name}: `{path}`"
                        for name, path in step_payload.artifacts.items()
                    ),
                    "",
                ]
            )

    lines.extend(["## Verificação de isolamento", ""])
    isolation = payload.get("isolation")
    if not isinstance(isolation, Mapping):
        lines.extend(
            [
                "Não executada nesta rodada.",
                "",
            ]
        )
    else:
        overall = "inalterado" if isolation.get("unchanged") else "ALTERADO"
        lines.extend(
            [
                f"Resultado geral: **{overall}**.",
                "",
                "| Alvo | Caminhos e comandos | Resultado |",
                "| --- | --- | --- |",
            ]
        )
        targets = isolation.get("targets")
        if isinstance(targets, list):
            for target in targets:
                if not isinstance(target, Mapping):
                    continue
                locations = [
                    f"`{path}`" for path in target.get("paths", [])
                ] + [
                    f"`$ {command}`" for command in target.get("commands", [])
                ]
                paths = ", ".join(locations) or "—"
                if target.get("changed"):
                    status = "ALTERADO"
                elif not target.get("present_before") and not target.get("present_after"):
                    status = "ausente (antes e depois), inalterado"
                else:
                    status = "inalterado"
                command_status = target.get("command_status")
                if isinstance(command_status, list) and any(
                    isinstance(item, Mapping) and not item.get("available")
                    for item in command_status
                ):
                    status += " (comando indisponível)"
                lines.append(f"| {target.get('name')} | {paths} | {status} |")
        lines.append("")

    lines.extend(
        [
            "## Como repetir",
            "",
            "```bash",
            f"scripts/rehearsal --date {date}",
            "```",
            "",
            (
                "O script recria o workspace abaixo de "
                f"`output/rehearsals/{date}/`, executa as três rodadas com "
                "`--adapter fake` e regrava este relatório. Os alvos reais podem "
                "ser apontados por `HERMES_ALLOWLIST`, `HERMES_CRON`, "
                "`HOME` e `CAREER_OPS_UPSTREAM`."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _screenshot_count(job: Mapping[str, object]) -> int:
    screenshots = job.get("screenshots")
    return len(screenshots) if isinstance(screenshots, list) else 0


def _read_jd(job: Mapping[str, object]) -> bool:
    state = str(job.get("state") or "")
    reason = job.get("reason")
    if state in {"new", _TITLE_STATE}:
        return False
    if reason in _LOCATION_REASONS or reason == _JD_MISSING:
        return False
    return True


def _artifacts(
    summary: Mapping[str, object],
    *,
    root: Path | None,
) -> dict[str, str]:
    report = _mapping(summary.get("report"))
    session_path = summary.get("session_path")
    session = Path(str(session_path)) if isinstance(session_path, str) else None
    paths = {
        "Sessão": session_path,
        "report.md": report.get("markdown"),
        "report.html": report.get("html"),
        "summary.txt": str(session / "summary.txt") if session is not None else None,
        "summary.json": str(session / "summary.json") if session is not None else None,
    }
    return {
        name: _display_path(path, root)
        for name, path in paths.items()
        if isinstance(path, str) and path
    }


def _display_path(path: str, root: Path | None) -> str:
    if root is None:
        return path
    try:
        return str(Path(path).resolve().relative_to(root.resolve()))
    except ValueError:
        return path


def _jobs(summary: Mapping[str, object]) -> list[Mapping[str, object]]:
    jobs = summary.get("jobs")
    if not isinstance(jobs, list):
        return []
    return [job for job in jobs if isinstance(job, Mapping)]


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _as_int(value: object) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return 0


__all__ = [
    "BASELINE_2026_10_19",
    "BASELINE_DATE",
    "RehearsalStep",
    "render_rehearsal_report",
]
