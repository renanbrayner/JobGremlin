from __future__ import annotations

import json
from pathlib import Path

from career_ops.cv_cache import (
    CvCache,
    CvCacheRules,
    CvSelector,
    build_cv_id,
    family_compatible,
    seniority_compatible,
)
from career_ops.cv_tailoring import TailorRequest, build_tailor_report
from career_ops.job_profile import JobProfile


def _profile(**overrides) -> JobProfile:
    values: dict[str, object] = {
        "language": "pt",
        "family": "frontend",
        "seniority": "senior",
        "required_skills": ("react", "typescript"),
        "preferred_skills": (),
    }
    values.update(overrides)
    return JobProfile(**values)  # type: ignore[arg-type]


def _seed(cache: CvCache, profile: JobProfile, job_id: str = "1") -> None:
    target = cache.target(profile)
    target.path.parent.mkdir(parents=True, exist_ok=True)
    target.path.write_bytes(b"%PDF-cached")
    cache.record_generated(profile, target, {"id": job_id, "title": "Cached role"})


class RecordingTailor:
    def __init__(self) -> None:
        self.requests: list[TailorRequest] = []

    def generate(self, request: TailorRequest) -> Path:
        self.requests.append(request)
        request.destination.parent.mkdir(parents=True, exist_ok=True)
        request.destination.write_text(
            "%PDF-fake\n" + build_tailor_report(request.profile, title=request.title),
            encoding="utf-8",
        )
        return request.destination


def test_an_exact_profile_is_reused_with_score_one(paths):
    cache = CvCache.load(paths)
    profile = _profile()
    _seed(cache, profile)

    match = CvCache.load(paths).lookup(profile)

    assert match.reusable is True
    assert match.score == 1.0
    assert match.metadata is not None
    assert match.metadata.cv_id == build_cv_id(profile)


def test_a_high_similarity_profile_is_reused(paths):
    cache = CvCache.load(paths)
    cached = _profile(
        required_skills=("react", "typescript", "node.js"),
        preferred_skills=("jest",),
    )
    job = _profile(
        required_skills=("react", "typescript", "node.js"),
        preferred_skills=("jest", "cypress"),
    )
    _seed(cache, cached)

    match = CvCache.load(paths).lookup(job)

    assert match.reusable is True
    assert 0.90 <= match.score < 1.0


def test_a_different_language_is_never_reused(paths):
    cache = CvCache.load(paths)
    _seed(cache, _profile(language="en"))

    match = CvCache.load(paths).lookup(_profile(language="pt"))

    assert match.reusable is False
    assert match.reason == "language_mismatch"


def test_an_incompatible_family_is_never_reused(paths):
    cache = CvCache.load(paths)
    _seed(cache, _profile(family="backend"))

    match = CvCache.load(paths).lookup(_profile(family="frontend"))

    assert match.reusable is False
    assert match.reason == "family_incompatible"


def test_an_incompatible_seniority_is_never_reused(paths):
    cache = CvCache.load(paths)
    _seed(cache, _profile(seniority="mid"))

    match = CvCache.load(paths).lookup(_profile(seniority="senior"))

    assert match.reusable is False
    assert match.reason == "seniority_incompatible"


def test_a_missing_must_have_skill_is_never_reused(paths):
    cache = CvCache.load(paths)
    _seed(cache, _profile(required_skills=("react",)))

    match = CvCache.load(paths).lookup(
        _profile(required_skills=("react", "typescript"))
    )

    assert match.reusable is False
    assert match.reason == "must_have_missing"
    assert match.missing_required == ("typescript",)


def test_a_score_below_the_threshold_is_a_miss(paths):
    cache = CvCache.load(paths)
    _seed(cache, _profile(preferred_skills=()))

    match = CvCache.load(paths).lookup(
        _profile(preferred_skills=("jest", "cypress"))
    )

    assert match.reusable is False
    assert match.reason == "score_below_threshold"
    assert match.score < 0.90


def test_the_threshold_is_configurable_from_the_config_file(paths, workspace):
    cache = CvCache.load(paths)
    cached = _profile(
        required_skills=("react", "typescript", "node.js"),
        preferred_skills=("jest",),
    )
    job = _profile(
        required_skills=("react", "typescript", "node.js"),
        preferred_skills=("jest", "cypress"),
    )
    _seed(cache, cached)
    (workspace / "config" / "cv-cache.json").write_text(
        json.dumps({"min_score": 0.95}),
        encoding="utf-8",
    )

    rules = CvCacheRules.from_paths(paths, {})

    assert rules.min_score == 0.95
    assert CvCache.load(paths).lookup(job, rules).reason == "score_below_threshold"


def test_the_threshold_can_be_overridden_by_the_environment(paths):
    (paths.config / "cv-cache.json").write_text(
        json.dumps({"min_score": 0.8}),
        encoding="utf-8",
    )

    rules = CvCacheRules.from_paths(paths, {"CAREER_OPS_CV_MIN_SCORE": "0.95"})

    assert rules.min_score == 0.95


def test_the_cache_has_an_index_and_per_cv_metadata(paths):
    cache = CvCache.load(paths)
    profile = _profile()
    _seed(cache, profile, job_id="42")

    index = json.loads((paths.data / "cv-cache" / "index.json").read_text())
    metadata_path = paths.data / "cv-cache" / f"{build_cv_id(profile)}.json"
    metadata = json.loads(metadata_path.read_text())

    assert index["entries"][0]["cv_id"] == build_cv_id(profile)
    assert index["entries"][0]["fingerprint"] == profile.skills_fingerprint()
    assert metadata["origins"] == [{"job_id": "42", "title": "Cached role"}]
    assert (paths.home / metadata["path"]).is_file()
    assert CvCache.load(paths).entries[build_cv_id(profile)].fingerprint == (
        profile.skills_fingerprint()
    )


def test_the_selector_generates_on_a_miss_and_adds_origins_on_a_hit(paths):
    cache = CvCache.load(paths)
    tailor = RecordingTailor()
    selector = CvSelector(cache, tailor)
    profile = _profile()

    first = selector.resolve(
        profile,
        job={"id": "1", "title": "Frontend Engineer", "company": "Acme"},
        jd_text="Acme is hiring. React and TypeScript.",
    )
    second = selector.resolve(
        profile,
        job={"id": "2", "title": "Frontend Engineer", "company": "Globex"},
        jd_text="Globex is hiring. React and TypeScript.",
    )

    assert first.hit is False
    assert first.reason == "cache_miss"
    assert first.miss_reason == "cache_empty"
    assert first.cv.is_file()
    assert second.hit is True
    assert second.reason == "cache_hit"
    assert second.score == 1.0
    assert second.cv == first.cv
    assert len(tailor.requests) == 1

    metadata = cache.entries[first.cv_id]
    assert [origin["job_id"] for origin in metadata.origins] == ["1", "2"]

    request = tailor.requests[0]
    report = build_tailor_report(request.profile, title=request.title)
    assert "Acme" not in report
    assert "Acme" not in first.cv.read_text(encoding="utf-8")
    assert "TypeScript".lower() in first.cv.read_text(encoding="utf-8").lower()


def test_a_mismatched_profile_generates_a_second_cv(paths):
    cache = CvCache.load(paths)
    tailor = RecordingTailor()
    selector = CvSelector(cache, tailor)

    first = selector.resolve(
        _profile(language="pt"),
        job={"id": "1", "title": "Frontend Engineer"},
        jd_text="Requisitos: React e TypeScript.",
    )
    second = selector.resolve(
        _profile(language="en"),
        job={"id": "2", "title": "Frontend Engineer"},
        jd_text="Requirements: React and TypeScript.",
    )

    assert first.hit is False
    assert second.hit is False
    assert second.miss_reason == "language_mismatch"
    assert second.cv != first.cv
    assert len(tailor.requests) == 2


def test_family_and_seniority_compatibility_are_explained():
    assert family_compatible("frontend", "fullstack") is True
    assert family_compatible("backend", "fullstack") is True
    assert family_compatible("fullstack", "fullstack") is True
    assert family_compatible("fullstack", "frontend") is False
    assert family_compatible("fullstack", "backend") is False
    assert family_compatible("frontend", "backend") is False
    assert seniority_compatible("unspecified", "senior") is True
    assert seniority_compatible("mid", "senior") is False


def test_a_fullstack_job_does_not_reuse_a_frontend_only_cv(paths):
    cache = CvCache.load(paths)
    _seed(cache, _profile(family="frontend"))

    match = CvCache.load(paths).lookup(_profile(family="fullstack"))

    assert match.reusable is False
    assert match.reason == "family_incompatible"


def test_an_undetected_language_is_never_reused(paths):
    cache = CvCache.load(paths)
    _seed(cache, _profile(language="unknown"))

    match = CvCache.load(paths).lookup(_profile(language="unknown"))

    assert match.reusable is False
    assert match.reason == "language_mismatch"


def test_the_skill_fingerprint_ignores_order_and_duplicates():
    first = _profile(
        required_skills=("react", "typescript"),
        preferred_skills=("jest",),
    )
    second = _profile(
        required_skills=("typescript", "typescript", "react"),
        preferred_skills=("jest", "react"),
    )
    different = _profile(
        required_skills=("react", "typescript"),
        preferred_skills=("cypress",),
    )

    assert first.skills_fingerprint() == second.skills_fingerprint()
    assert first.skills_fingerprint() != different.skills_fingerprint()
    assert JobProfile.from_dict(first.as_dict()) == first
