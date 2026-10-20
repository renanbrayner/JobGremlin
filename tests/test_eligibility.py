from __future__ import annotations

import json

from career_ops.eligibility import EligibilityRules, evaluate_eligibility
from career_ops.job_profile import JobProfile
from career_ops.paths import WorkspacePaths


def _profile(
    *,
    language: str = "pt",
    family: str = "frontend",
    seniority: str = "senior",
    required_skills: tuple[str, ...] = ("react", "typescript"),
    preferred_skills: tuple[str, ...] = ("docker",),
) -> JobProfile:
    return JobProfile(
        language=language,
        family=family,
        seniority=seniority,
        required_skills=required_skills,
        preferred_skills=preferred_skills,
    )


def test_a_target_language_family_and_seniority_is_eligible():
    decision = evaluate_eligibility(_profile())

    assert decision.eligible is True
    assert decision.reason == "eligible"
    assert all(check["passed"] for check in decision.checks)


def test_an_unsupported_language_is_ineligible_with_an_auditable_reason():
    decision = evaluate_eligibility(_profile(language="es"))

    assert decision.eligible is False
    assert decision.reason == "language_unsupported"
    language = next(check for check in decision.checks if check["rule"] == "language")
    assert language == {
        "rule": "language",
        "passed": False,
        "value": "es",
        "accepted": ["en", "pt"],
    }


def test_a_family_outside_the_target_is_ineligible():
    decision = evaluate_eligibility(_profile(family="devops"))

    assert decision.eligible is False
    assert decision.reason == "family_not_targeted"


def test_a_lead_or_junior_seniority_is_ineligible():
    assert evaluate_eligibility(_profile(seniority="lead")).reason == (
        "seniority_not_targeted"
    )
    assert evaluate_eligibility(_profile(seniority="junior")).reason == (
        "seniority_not_targeted"
    )


def test_an_unspecified_seniority_is_accepted():
    decision = evaluate_eligibility(_profile(seniority="unspecified"))

    assert decision.eligible is True
    assert decision.reason == "eligible"


def test_rules_can_be_loaded_from_a_workspace_config(paths: WorkspacePaths):
    (paths.config / "eligibility.json").write_text(
        json.dumps(
            {
                "languages": ["en"],
                "families": ["backend"],
                "seniorities": ["mid"],
            }
        ),
        encoding="utf-8",
    )

    rules = EligibilityRules.from_paths(paths)

    assert rules.languages == ("en",)
    assert rules.families == ("backend",)
    assert rules.seniorities == ("mid",)
    assert evaluate_eligibility(_profile(), rules).reason == "language_unsupported"
    assert (
        evaluate_eligibility(
            _profile(language="en", family="backend", seniority="mid"), rules
        ).eligible
        is True
    )


def test_the_decision_serializes_for_the_queue_report():
    decision = evaluate_eligibility(_profile())

    assert decision.as_dict()["eligible"] is True
    assert decision.as_dict()["reason"] == "eligible"
    assert len(decision.as_dict()["checks"]) == 3
