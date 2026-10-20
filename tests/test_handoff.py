from __future__ import annotations

import json
import re
from typing import Mapping

from career_ops.catalog import build_catalog, registered_commands
from conftest import REPO_ROOT

HANDOFF = REPO_ROOT / "docs" / "HANDOFF.md"
CATALOG_SNAPSHOT = REPO_ROOT / "docs" / "handoff" / "help-catalog.json"
REHEARSAL = REPO_ROOT / "docs" / "rehearsals" / "2026-10-20.md"


def _sections(markdown: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current: str | None = None
    body: list[str] = []
    for line in markdown.splitlines():
        match = re.match(r"^###\s+`?(career-ops-[a-z-]+)`?\s*$", line)
        if match:
            if current is not None:
                sections[current] = "\n".join(body)
            current = match.group(1)
            body = []
            continue
        if line.startswith("## ") and current is not None:
            sections[current] = "\n".join(body)
            current = None
            body = []
            continue
        if current is not None:
            body.append(line)
    if current is not None:
        sections[current] = "\n".join(body)
    return sections


def test_the_handoff_documents_every_registered_command_and_its_exit_codes():
    markdown = HANDOFF.read_text(encoding="utf-8")
    sections = _sections(markdown)

    for command in registered_commands():
        assert command.name in markdown
        section = sections.get(command.name)
        assert section is not None, f"missing handoff section for {command.name}"
        for code, _meaning in command.exit_codes:
            assert f"| {code} |" in section, (
                f"{command.name} exit code {code} is not documented"
            )
        assert "--help" in section


def test_the_handoff_snapshot_matches_the_help_catalog_generated_from_the_registry():
    snapshot = json.loads(CATALOG_SNAPSHOT.read_text(encoding="utf-8"))

    assert snapshot == build_catalog()
    assert snapshot["schema_version"] == 1
    assert snapshot["isolation"]["parallel"] is True
    assert [command["name"] for command in snapshot["commands"]] == [
        command.name for command in registered_commands()
    ]


def test_the_handoff_documents_the_output_contract_and_the_artifact_paths():
    markdown = HANDOFF.read_text(encoding="utf-8")

    for field in (
        "status",
        "submitted",
        "target",
        "waiting",
        "run_id",
        "report",
        "artifacts",
        "waiting_input",
    ):
        assert f"`{field}`" in markdown, f"missing output field {field}"
    assert "career-ops-help --json" in markdown
    assert "docs/handoff/help-catalog.json" in markdown
    assert "docs/schema/help-catalog.schema.json" in markdown
    assert "output/sessions/<run_id>" in markdown
    assert "events.jsonl" in markdown
    assert "summary.json" in markdown
    assert "data/runs/<run_id>.json" in markdown
    assert "career-ops-reply" in markdown


def test_the_handoff_lists_known_limitations_and_the_hermes_dependencies():
    markdown = HANDOFF.read_text(encoding="utf-8")

    assert "career-ops-status" in markdown
    assert "Limitações" in markdown
    assert "Hermes" in markdown
    assert "Telegram" in markdown
    assert "cron" in markdown
    assert "allowlist" in markdown
    assert "~/.local/bin" in markdown
    assert "~/.hermes" in markdown
    assert "adaptador real" in markdown
    assert "smoke" in markdown.lower()


def test_the_handoff_points_at_the_rehearsal_and_the_isolation_result():
    markdown = HANDOFF.read_text(encoding="utf-8")
    rehearsal = REHEARSAL.read_text(encoding="utf-8")

    assert "docs/rehearsals/2026-10-20.md" in markdown
    assert "inalterado" in markdown.lower()
    assert "scripts/rehearsal" in markdown
    for value in ("1950", "344", "129", "12", "4"):
        assert value in rehearsal
    assert "| Verificadas | 0 | 1 | 3 | 20 |" in rehearsal
    assert "resultado" in rehearsal.lower()


def test_the_rehearsal_evidence_is_valid_json():
    payload: Mapping[str, object] = json.loads(
        (REPO_ROOT / "docs" / "rehearsals" / "2026-10-20.json").read_text(
            encoding="utf-8"
        )
    )

    assert payload["mode"] == "fake-adapter-offline"
    assert payload["baseline"]["cards"] == 1950
    steps = payload["steps"]
    assert isinstance(steps, list)
    assert [step["metrics"]["verified"] for step in steps] == [1, 3, 20]
    assert payload["isolation"]["unchanged"] is True
