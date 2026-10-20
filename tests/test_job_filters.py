from __future__ import annotations

import pytest

from career_ops.job_filters import filter_location, filter_title


@pytest.mark.parametrize(
    ("title", "reason"),
    [
        ("Estágio em Desenvolvimento", "title_internship"),
        ("Desenvolvedor Júnior React", "title_junior"),
        ("QA Automation Engineer", "title_qa"),
        ("Analista de Segurança da Informação", "title_security"),
        ("DevOps Engineer", "title_infra"),
        ("Tech Lead React", "title_leadership"),
        ("Designer de Produto", "title_non_dev"),
        ("Business Development Representative", "title_non_dev"),
        ("", "title_missing"),
    ],
)
def test_title_filter_rejects_inadequate_titles_with_a_reason(title, reason):
    decision = filter_title(title)

    assert decision.accepted is False
    assert decision.reason == reason
    assert decision.detail["title"] == title


@pytest.mark.parametrize(
    "title",
    [
        "Desenvolvedor React",
        "Full Stack Developer",
        "Software Engineer",
        "Pessoa Desenvolvedora Front-end",
        "Engenheiro de Software Backend",
        "React Native Developer",
    ],
)
def test_title_filter_accepts_development_titles(title):
    decision = filter_title(title)

    assert decision.accepted is True
    assert decision.reason is None


@pytest.mark.parametrize(
    ("location", "workplace", "is_remote", "accepted", "reason"),
    [
        ("São Paulo, SP", "Remote", False, True, None),
        ("Anywhere", "", True, True, None),
        ("Recife, PE", "On-site", False, True, None),
        ("Olinda, PE", "Presencial", False, True, None),
        ("Recife, PE", "Hybrid", False, False, "location_hybrid"),
        ("São Paulo, SP", "Hybrid", False, False, "location_hybrid"),
        ("São Paulo, SP", "On-site", False, False, "location_outside_region"),
        ("", "On-site", False, False, "location_missing"),
    ],
)
def test_location_filter_accepts_remote_or_recife_onsite(
    location, workplace, is_remote, accepted, reason
):
    decision = filter_location(location, workplace=workplace, is_remote=is_remote)

    assert decision.accepted is accepted
    assert decision.reason == reason


def test_location_filter_accepts_recife_without_an_explicit_workplace():
    decision = filter_location("Recife - PE")

    assert decision.accepted is True
    assert decision.detail["workplace"] == "unspecified"
