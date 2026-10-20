"""Reusable CV cache keyed by the structured job profile.

A cached CV is reused only when every hard gate passes:

* the language is identical;
* the role family is compatible;
* the seniority is the same (or both sides are unspecified);
* no must-have skill from the job is missing.

The remaining decision is a weighted skill similarity (required skills weigh
three times a preferred skill).  The default threshold is ``0.90`` and can be
lowered or raised in ``config/cv-cache.json`` or with
``CAREER_OPS_CV_MIN_SCORE``.  On a miss the caller generates one CV and indexes
it; on a hit the job is appended to the CV's origins.

The cache has two readable layers: ``data/cv-cache/index.json`` is the queryable
index and ``data/cv-cache/<cv-id>.json`` is the per-CV metadata file.  PDFs stay
under ``output/cv-cache/``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

from career_ops.cv_tailoring import (
    CvGenerationError,
    CvTailor,
    TailorRequest,
)
from career_ops.job_filters import fold
from career_ops.job_profile import JobProfile
from career_ops.paths import WorkspacePaths

CACHE_DIRNAME = "cv-cache"
INDEX_FILENAME = "index.json"
CACHE_VERSION = 1
DEFAULT_MIN_SCORE = 0.90
REQUIRED_WEIGHT = 3.0
PREFERRED_WEIGHT = 1.0

# CV families a job family may reuse.  A full-stack CV can serve a frontend or
# backend role, but a frontend-only CV must not serve a full-stack role.
_CV_FAMILIES_FOR_JOB: dict[str, frozenset[str]] = {
    "frontend": frozenset({"frontend", "fullstack"}),
    "backend": frozenset({"backend", "fullstack"}),
    "fullstack": frozenset({"fullstack"}),
    "mobile": frozenset({"mobile"}),
    "data": frozenset({"data"}),
    "devops": frozenset({"devops"}),
    "qa": frozenset({"qa"}),
    "other": frozenset({"other"}),
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", fold(value)).strip("-") or "x"


def build_cv_id(profile: JobProfile) -> str:
    """Readable identifier: family, stack, language, seniority and fingerprint."""
    family = _slug(profile.family)
    language = _slug(profile.language)
    seniority = _slug(profile.seniority)
    skills = list(profile.required_skills) or list(profile.preferred_skills)
    stack = "-".join(_slug(skill) for skill in skills[:2])[:40].strip("-") or "general"
    return f"cv-{family}-{stack}-{language}-{seniority}-{profile.skills_fingerprint()}"


def family_compatible(job_family: str, cv_family: str) -> bool:
    return cv_family in _CV_FAMILIES_FOR_JOB.get(job_family, frozenset({job_family}))


def seniority_compatible(job_seniority: str, cv_seniority: str) -> bool:
    return job_seniority == cv_seniority or "unspecified" in {job_seniority, cv_seniority}


def _cached_skills(cached: "CvMetadata") -> frozenset[str]:
    return frozenset(cached.required_skills) | frozenset(cached.preferred_skills)


def weighted_similarity(profile: JobProfile, cached: "CvMetadata") -> float:
    """Coverage of the job's skills, weighting required skills above preferred."""
    cached_skills = _cached_skills(cached)
    total = 0.0
    matched = 0.0
    for skill in profile.required_skills:
        total += REQUIRED_WEIGHT
        if skill in cached_skills:
            matched += REQUIRED_WEIGHT
    for skill in profile.preferred_skills:
        if skill in profile.required_skills:
            continue
        total += PREFERRED_WEIGHT
        if skill in cached_skills:
            matched += PREFERRED_WEIGHT
    return matched / total if total else 0.0


def missing_required(profile: JobProfile, cached: "CvMetadata") -> tuple[str, ...]:
    cached_skills = _cached_skills(cached)
    return tuple(skill for skill in profile.required_skills if skill not in cached_skills)


@dataclass(frozen=True)
class CvCacheRules:
    min_score: float = DEFAULT_MIN_SCORE

    def __post_init__(self) -> None:
        if not 0.0 < self.min_score <= 1.0:
            raise ValueError(f"min_score must be between 0 and 1, got {self.min_score!r}")

    @classmethod
    def from_paths(
        cls,
        paths: WorkspacePaths,
        environ: Mapping[str, str] | None = None,
    ) -> "CvCacheRules":
        candidate = paths.read_config("cv-cache.json")
        rules = cls.from_file(Path(candidate)) if candidate is not None else cls()
        raw = (environ or {}).get("CAREER_OPS_CV_MIN_SCORE")
        if raw is not None and raw.strip():
            return replace(rules, min_score=_parse_score(raw))
        return rules

    @classmethod
    def from_file(cls, path: Path) -> "CvCacheRules":
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"could not read CV cache rules from {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"{path} must contain a JSON object")
        unknown = set(payload) - {"min_score"}
        if unknown:
            raise ValueError(f"unknown CV cache rule(s): {', '.join(sorted(unknown))}")
        return cls(min_score=_parse_score(payload.get("min_score", DEFAULT_MIN_SCORE)))

    def raised_to(self, raw: float | None) -> "CvCacheRules":
        if raw is None:
            return self
        return replace(self, min_score=raw)


def _parse_score(value: object) -> float:
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError as exc:
            raise ValueError(f"min_score must be a number, got {value!r}") from exc
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"min_score must be a number, got {value!r}")
    return float(value)


@dataclass(frozen=True)
class CvMetadata:
    cv_id: str
    path: str
    language: str
    family: str
    seniority: str
    required_skills: tuple[str, ...]
    preferred_skills: tuple[str, ...]
    fingerprint: str
    created_at: str
    updated_at: str
    origins: tuple[Mapping[str, object], ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "cv_id": self.cv_id,
            "path": self.path,
            "language": self.language,
            "family": self.family,
            "seniority": self.seniority,
            "required_skills": list(self.required_skills),
            "preferred_skills": list(self.preferred_skills),
            "fingerprint": self.fingerprint,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "origins": [dict(origin) for origin in self.origins],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "CvMetadata":
        if not isinstance(payload, Mapping):
            raise ValueError("CV cache entry must be an object")

        def text(name: str) -> str:
            value = payload.get(name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"CV cache entry field {name!r} must be a string")
            return value

        def skills(name: str) -> tuple[str, ...]:
            value = payload.get(name, [])
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ValueError(f"CV cache entry field {name!r} must be a list of strings")
            return tuple(value)

        origins = payload.get("origins", [])
        if not isinstance(origins, list) or not all(isinstance(item, Mapping) for item in origins):
            raise ValueError("CV cache entry field 'origins' must be a list of objects")
        return cls(
            cv_id=text("cv_id"),
            path=text("path"),
            language=text("language"),
            family=text("family"),
            seniority=text("seniority"),
            required_skills=skills("required_skills"),
            preferred_skills=skills("preferred_skills"),
            fingerprint=text("fingerprint"),
            created_at=text("created_at"),
            updated_at=text("updated_at"),
            origins=tuple(dict(origin) for origin in origins),
        )

    def absolute(self, paths: WorkspacePaths) -> Path:
        path = Path(self.path)
        return path if path.is_absolute() else (paths.home / path).resolve()


@dataclass(frozen=True)
class CvTarget:
    cv_id: str
    path: Path
    relative_path: str


@dataclass(frozen=True)
class CvMatch:
    metadata: CvMetadata | None
    score: float
    reason: str | None
    considered: int
    missing_required: tuple[str, ...] = ()

    @property
    def reusable(self) -> bool:
        return self.reason is None and self.metadata is not None


@dataclass(frozen=True)
class CvDecision:
    hit: bool
    reason: str
    miss_reason: str | None
    score: float
    threshold: float
    cv_id: str
    cv: Path
    fingerprint: str
    considered: int
    missing_required: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "hit": self.hit,
            "reason": self.reason,
            "miss_reason": self.miss_reason,
            "score": self.score,
            "threshold": self.threshold,
            "cv_id": self.cv_id,
            "cv": str(self.cv),
            "fingerprint": self.fingerprint,
            "considered": self.considered,
            "missing_required": list(self.missing_required),
        }


class CvCache:
    """Persistent index and per-CV metadata, with no LLM involvement."""

    def __init__(
        self,
        paths: WorkspacePaths,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.paths = paths
        self.root = paths.data / CACHE_DIRNAME
        self.index_path = self.root / INDEX_FILENAME
        self.entries: dict[str, CvMetadata] = {}
        self._clock = clock or _utcnow

    @classmethod
    def load(
        cls,
        paths: WorkspacePaths,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> "CvCache":
        cache = cls(paths, clock=clock)
        if cache.index_path.is_file():
            cache._load_index()
        elif cache.root.is_dir():
            cache._load_metadata_files()
        return cache

    def _load_index(self) -> None:
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"could not read CV cache index {self.index_path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"CV cache index {self.index_path} must contain an object")
        entries = payload.get("entries")
        if not isinstance(entries, list):
            raise ValueError(f"CV cache index {self.index_path} has no entries list")
        for item in entries:
            metadata = CvMetadata.from_dict(item)
            self.entries[metadata.cv_id] = metadata

    def _load_metadata_files(self) -> None:
        for path in sorted(self.root.glob("*.json")):
            if path.name == INDEX_FILENAME:
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"could not read CV metadata {path}: {exc}") from exc
            metadata = CvMetadata.from_dict(payload)
            self.entries[metadata.cv_id] = metadata

    def lookup(self, profile: JobProfile, rules: CvCacheRules | None = None) -> CvMatch:
        rules = rules or CvCacheRules()
        evaluations = [
            self._evaluate(metadata, profile, rules.min_score)
            for metadata in self.entries.values()
        ]
        if not evaluations:
            return CvMatch(metadata=None, score=0.0, reason="cache_empty", considered=0)

        usable = [evaluation for evaluation in evaluations if evaluation.reason is None]
        if usable:
            best = max(usable, key=lambda evaluation: evaluation.score)
            return CvMatch(
                metadata=best.metadata,
                score=best.score,
                reason=None,
                considered=len(evaluations),
            )

        # Prefer the actionable "just missed the score" explanation; otherwise
        # report the closest candidate by skill overlap.
        near = [e for e in evaluations if e.reason == "score_below_threshold"]
        best = max(near or evaluations, key=lambda evaluation: evaluation.score)
        return CvMatch(
            metadata=best.metadata,
            score=best.score,
            reason=best.reason,
            considered=len(evaluations),
            missing_required=best.missing_required,
        )

    def _evaluate(
        self,
        metadata: CvMetadata,
        profile: JobProfile,
        min_score: float,
    ) -> "_Evaluation":
        cv_path = metadata.absolute(self.paths)
        missing = missing_required(profile, metadata)
        score = weighted_similarity(profile, metadata)
        reason: str | None = None
        if not cv_path.is_file():
            reason = "cv_file_missing"
        elif metadata.language != profile.language or profile.language == "unknown":
            # An undetected language is not evidence of a match; generate anew.
            reason = "language_mismatch"
        elif not family_compatible(profile.family, metadata.family):
            reason = "family_incompatible"
        elif not seniority_compatible(profile.seniority, metadata.seniority):
            reason = "seniority_incompatible"
        elif missing:
            reason = "must_have_missing"
        elif score <= 0.0:
            reason = "no_skills"
        elif score + 1e-9 < min_score:
            reason = "score_below_threshold"
        return _Evaluation(metadata=metadata, score=score, reason=reason, missing_required=missing)

    def target(self, profile: JobProfile) -> CvTarget:
        cv_id = build_cv_id(profile)
        path = (self.paths.output / CACHE_DIRNAME / f"{cv_id}.pdf").resolve()
        self.paths.assert_writable(path)
        return CvTarget(
            cv_id=cv_id,
            path=path,
            relative_path=self._relative(path),
        )

    def record_generated(
        self,
        profile: JobProfile,
        target: CvTarget,
        job: Mapping[str, object],
    ) -> CvMetadata:
        now = _iso(self._clock())
        origin = _origin(job)
        metadata = CvMetadata(
            cv_id=target.cv_id,
            path=target.relative_path,
            language=profile.language,
            family=profile.family,
            seniority=profile.seniority,
            required_skills=tuple(profile.required_skills),
            preferred_skills=tuple(profile.preferred_skills),
            fingerprint=profile.skills_fingerprint(),
            created_at=now,
            updated_at=now,
            origins=(origin,) if origin else (),
        )
        self.entries[metadata.cv_id] = metadata
        self._write_metadata(metadata)
        self.save()
        return metadata

    def add_origin(self, cv_id: str, job: Mapping[str, object]) -> CvMetadata:
        metadata = self.entries[cv_id]
        origin = _origin(job)
        if not origin:
            return metadata
        origins = list(metadata.origins)
        if not any(item.get("job_id") == origin["job_id"] for item in origins):
            origins.append(origin)
        updated = replace(
            metadata,
            origins=tuple(origins),
            updated_at=_iso(self._clock()),
        )
        self.entries[cv_id] = updated
        self._write_metadata(updated)
        self.save()
        return updated

    def save(self) -> None:
        payload = {
            "version": CACHE_VERSION,
            "updated_at": _iso(self._clock()),
            "entries": [
                self.entries[cv_id].as_dict() for cv_id in sorted(self.entries)
            ],
        }
        self._write_json(self.index_path, payload)

    def _write_metadata(self, metadata: CvMetadata) -> None:
        self._write_json(self.root / f"{metadata.cv_id}.json", metadata.as_dict())

    def _write_json(self, path: Path, payload: Mapping[str, object]) -> None:
        self.paths.assert_writable(path)
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    def _relative(self, path: Path) -> str:
        try:
            return path.relative_to(self.paths.home.resolve()).as_posix()
        except ValueError:
            return str(path)


@dataclass(frozen=True)
class _Evaluation:
    metadata: CvMetadata
    score: float
    reason: str | None
    missing_required: tuple[str, ...]


def _origin(job: Mapping[str, object]) -> dict[str, object] | None:
    job_id = job.get("id", job.get("job_id"))
    if job_id is None or not str(job_id).strip():
        return None
    title = str(job.get("title") or "").strip()
    return {"job_id": str(job_id).strip(), "title": title}


class CvSelector:
    """Reuse a cached CV or generate and index one for a cache miss."""

    def __init__(
        self,
        cache: CvCache,
        tailor: CvTailor,
        rules: CvCacheRules | None = None,
    ) -> None:
        self.cache = cache
        self.tailor = tailor
        self.rules = rules or CvCacheRules()

    def resolve(
        self,
        profile: JobProfile,
        *,
        job: Mapping[str, object],
        jd_text: str,
    ) -> CvDecision:
        match = self.cache.lookup(profile, self.rules)
        if match.reusable and match.metadata is not None:
            metadata = self.cache.add_origin(match.metadata.cv_id, job)
            return CvDecision(
                hit=True,
                reason="cache_hit",
                miss_reason=None,
                score=round(match.score, 6),
                threshold=self.rules.min_score,
                cv_id=metadata.cv_id,
                cv=metadata.absolute(self.cache.paths),
                fingerprint=metadata.fingerprint,
                considered=match.considered,
            )

        target = self.cache.target(profile)
        request = TailorRequest(
            cv_id=target.cv_id,
            job_id=str(job.get("id", job.get("job_id")) or ""),
            title=str(job.get("title") or ""),
            profile=profile,
            jd_text=jd_text,
            destination=target.path,
            company=str(job.get("company") or ""),
        )
        self.tailor.generate(request)
        if not target.path.is_file():
            raise CvGenerationError(
                "the CV generator returned without writing the expected PDF",
                reason="cv_generation_failed",
            )
        metadata = self.cache.record_generated(profile, target, job)
        return CvDecision(
            hit=False,
            reason="cache_miss",
            miss_reason=match.reason or "cache_empty",
            score=round(match.score, 6),
            threshold=self.rules.min_score,
            cv_id=metadata.cv_id,
            cv=metadata.absolute(self.cache.paths),
            fingerprint=metadata.fingerprint,
            considered=match.considered,
            missing_required=match.missing_required,
        )
