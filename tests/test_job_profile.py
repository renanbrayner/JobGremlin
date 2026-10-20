from __future__ import annotations

from career_ops.job_profile import build_job_profile


def test_a_portuguese_frontend_job_gets_language_family_seniority_and_skills():
    jd = """\
Vaga: Desenvolvedor(a) Front-end Sênior

Responsabilidades:
- Desenvolver interfaces em React e TypeScript.

Requisitos:
- Experiência sólida com React, TypeScript e Git.
- Testes automatizados.

Diferenciais:
- Node.js e Docker.
"""

    profile = build_job_profile(jd, title="Desenvolvedor(a) Front-end Sênior")

    assert profile.language == "pt"
    assert profile.family == "frontend"
    assert profile.seniority == "senior"
    assert set(profile.required_skills) == {"react", "typescript", "git"}
    assert set(profile.preferred_skills) == {"node.js", "docker"}
    assert set(profile.required_skills).isdisjoint(profile.preferred_skills)


def test_an_english_job_gets_required_and_preferred_skills_from_sections():
    jd = """\
Full Stack Engineer

Requirements:
- 5+ years of experience with Node.js, TypeScript and React.
- Experience with PostgreSQL.

Nice to have:
- AWS and Docker.
"""

    profile = build_job_profile(jd, title="Full Stack Engineer")

    assert profile.language == "en"
    assert profile.family == "fullstack"
    assert profile.seniority == "senior"
    assert set(profile.required_skills) == {
        "node.js",
        "typescript",
        "react",
        "postgresql",
    }
    assert set(profile.preferred_skills) == {"aws", "docker"}


def test_a_junior_backend_job_is_classified_with_its_explicit_seniority():
    jd = """\
Desenvolvedor Backend Júnior

Requisitos:
- Python e Django.
"""

    profile = build_job_profile(jd, title="Desenvolvedor Backend Júnior")

    assert profile.language == "pt"
    assert profile.family == "backend"
    assert profile.seniority == "junior"
    assert set(profile.required_skills) == {"python", "django"}


def test_a_mobile_job_is_not_mistaken_for_a_web_frontend_job():
    jd = """\
Desenvolvedor Mobile Sênior

Requisitos:
- Flutter e Dart.
"""

    profile = build_job_profile(jd, title="Desenvolvedor Mobile Sênior")

    assert profile.family == "mobile"
    assert set(profile.required_skills) == {"flutter", "dart"}


def test_an_empty_jd_still_produces_a_structured_profile():
    profile = build_job_profile("")

    assert profile.language == "unknown"
    assert profile.family == "other"
    assert profile.seniority == "unspecified"
    assert profile.required_skills == ()
    assert profile.preferred_skills == ()


def test_bullet_lines_without_periods_still_yield_skills():
    jd = """\
Desenvolvedor React

Requisitos:
- React
- TypeScript
- Git
"""

    profile = build_job_profile(jd, title="Desenvolvedor React")

    assert set(profile.required_skills) == {"react", "typescript", "git"}


def test_a_sentence_inside_a_requirements_section_is_not_treated_as_a_heading():
    jd = """\
Desenvolvedor React

Requisitos:
Experience with React
- TypeScript
"""

    profile = build_job_profile(jd, title="Desenvolvedor React")

    assert set(profile.required_skills) == {"react", "typescript"}


def test_a_pronoun_heading_resets_the_section_but_keeps_reading_skills():
    jd = """\
Desenvolvedor React

Requisitos:
- React

Responsabilidades:
- TypeScript
"""

    profile = build_job_profile(jd, title="Desenvolvedor React")

    assert set(profile.required_skills) == {"react"}
    assert set(profile.preferred_skills) == {"typescript"}


def test_a_lead_verb_in_the_responsibilities_does_not_make_the_job_a_lead_role():
    jd = """\
Software Engineer

Responsibilities:
- Lead code reviews and mentor peers.
"""

    profile = build_job_profile(jd, title="Software Engineer")

    assert profile.seniority == "unspecified"


def test_an_explicit_lead_title_is_recorded_in_the_profile():
    jd = """\
Tech Lead

Requirements:
- React and TypeScript.
"""

    profile = build_job_profile(jd, title="Tech Lead")

    assert profile.seniority == "lead"


def test_the_profile_serializes_to_a_stable_audit_shape():
    profile = build_job_profile("Requirements:\n- React and TypeScript.", title="React Developer")

    assert profile.as_dict() == {
        "language": "en",
        "family": "frontend",
        "seniority": "unspecified",
        "required_skills": ["react", "typescript"],
        "preferred_skills": [],
    }
