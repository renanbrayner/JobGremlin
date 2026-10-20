"""Deterministic eligibility rules for a structured job profile.

Eligibility is intentionally small and explainable.  It answers a different
question from the quick filters: the title and location already survived, so
the JD profile now decides whether the role fits the target language, role
family and seniority.  Every rule result is recorded, even after the first
failure, so a discarded job can be audited without re-reading the JD.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping

from career_ops.job_profile import JobProfile


@dataclass(frozen=True)
class EligibilityRules:
    languages: tuple[str, ...] = ("pt", "en")
    families: tuple[str, ...] = ("frontend", "backend", "fullstack", "mobile")
    seniorities: tuple[str, ...] = ("mid", "senior", "unspecified")
    max_required_skills: int | None = None

    def __post_init__(self) -> None:
        for name in ("languages", "families", "seniorities"):
            values = tuple(dict.fromkeys(getattr(self, name)))
            if not values:
                raise ValueError(f"{name} must not be empty")
            object.__setattr__(self, name, values)
        if self.max_required_skills is not None and self.max_required_skills < 0:
            raise ValueError("max_required_skills must not be negative")

    @classmethod
    def from_paths(cls, paths: object) -> "EligibilityRules":
        """Load ``config/eligibility.json`` when present, else use defaults."""
        reader = getattr(paths, "read_config", None)
        candidate = reader("eligibility.json") if callable(reader) else None
        if candidate is None:
            return cls()
        return cls.from_file(Path(candidate))

    @classmethod
    def from_file(cls, path: Path) -> "EligibilityRules":
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"could not read eligibility rules from {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"{path} must contain a JSON object")
        return cls.from_mapping(payload)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "EligibilityRules":
        known = {"languages", "families", "seniorities", "max_required_skills"}
        unknown = set(payload) - known
        if unknown:
            raise ValueError(f"unknown eligibility rule(s): {', '.join(sorted(unknown))}")

        def strings(name: str) -> tuple[str, ...]:
            value = payload.get(name)
            if value is None:
                return getattr(cls(), name)
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ValueError(f"{name} must be a list of strings")
            return tuple(item.strip().lower() for item in value if item.strip())

        limit = payload.get("max_required_skills")
        if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool)):
            raise ValueError("max_required_skills must be an integer or null")

        return cls(
            languages=strings("languages"),
            families=strings("families"),
            seniorities=strings("seniorities"),
            max_required_skills=limit,
        )


@dataclass(frozen=True)
class EligibilityDecision:
    eligible: bool
    reason: str
    checks: tuple[Mapping[str, object], ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, object]:
        return {
            "eligible": self.eligible,
            "reason": self.reason,
            "checks": [dict(check) for check in self.checks],
        }


def evaluate_eligibility(
    profile: JobProfile,
    rules: EligibilityRules | None = None,
) -> EligibilityDecision:
    """Apply the rules in a stable order and report every check."""
    rules = rules or EligibilityRules()
    checks: list[dict[str, object]] = []

    checks.append(_check("language", profile.language, rules.languages))
    checks.append(_check("family", profile.family, rules.families))
    checks.append(_check("seniority", profile.seniority, rules.seniorities))

    if rules.max_required_skills is not None:
        passed = len(profile.required_skills) <= rules.max_required_skills
        checks.append(
            {
                "rule": "required_skills",
                "passed": passed,
                "value": len(profile.required_skills),
                "accepted": rules.max_required_skills,
            }
        )

    for check in checks:
        if not check["passed"]:
            return EligibilityDecision(
                eligible=False,
                reason=_REASON_BY_RULE[str(check["rule"])],
                checks=tuple(checks),
            )
    return EligibilityDecision(eligible=True, reason="eligible", checks=tuple(checks))


_REASON_BY_RULE = {
    "language": "language_unsupported",
    "family": "family_not_targeted",
    "seniority": "seniority_not_targeted",
    "required_skills": "too_many_required_skills",
}


def _check(
    rule: str,
    value: str,
    accepted: Iterable[str],
) -> dict[str, object]:
    allowed = tuple(sorted(accepted))
    return {
        "rule": rule,
        "passed": value in allowed,
        "value": value,
        "accepted": list(allowed),
    }
