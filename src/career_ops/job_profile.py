"""Structured, deterministic profile of a job description.

The profile is what later slices use to decide eligibility and to pick or
generate a CV.  It records only facts that can be derived from the text with
stable rules: language, role family, seniority, required skills and preferred
skills.  No LLM participates in this step.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Iterable, Mapping

from career_ops.job_filters import fold

ProfileLanguage = str
ProfileFamily = str
ProfileSeniority = str


@dataclass(frozen=True)
class JobProfile:
    language: ProfileLanguage
    family: ProfileFamily
    seniority: ProfileSeniority
    required_skills: tuple[str, ...] = ()
    preferred_skills: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "language": self.language,
            "family": self.family,
            "seniority": self.seniority,
            "required_skills": list(self.required_skills),
            "preferred_skills": list(self.preferred_skills),
        }

    def skills_fingerprint(self) -> str:
        """Stable fingerprint of the skill set, independent of extraction order."""
        required = set(self.required_skills)
        payload = {
            "required": sorted(required),
            "preferred": sorted(set(self.preferred_skills) - required),
        }
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()[:12]

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "JobProfile":
        """Rebuild a profile stored in the queue or in a cache entry."""
        if not isinstance(payload, Mapping):
            raise ValueError("job profile must be an object")

        def text(name: str) -> str:
            value = payload.get(name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"job profile field {name!r} must be a non-empty string")
            return value.strip()

        def skills(name: str) -> tuple[str, ...]:
            value = payload.get(name, [])
            if not isinstance(value, (list, tuple)) or not all(
                isinstance(skill, str) and skill.strip() for skill in value
            ):
                raise ValueError(f"job profile field {name!r} must be a list of strings")
            return tuple(skill.strip() for skill in value)

        return cls(
            language=text("language"),
            family=text("family"),
            seniority=text("seniority"),
            required_skills=skills("required_skills"),
            preferred_skills=skills("preferred_skills"),
        )


_PT_WORDS = frozenset(
    """
    a ao aos as com como da das de do dos e em entre essa esse esta este eu
    experiencia conhecimento desenvolvimento desenvolvedor desenvolvedora
    requisitos responsabilidades vaga empresa equipe trabalho atuacao beneficios
    necessario desejavel sobre sera nossa nosso voce nos para por mais
    habilidades qualificacoes solidos solida solido
    """.split()
)
_EN_WORDS = frozenset(
    """
    a an and are as at be by for from have has in is it of on or our that the
    their to we will with you your experience knowledge development developer
    requirements responsibilities team work about role company benefits must
    need needs preferred required years plus nice good
    """.split()
)

_SKILLS: dict[str, tuple[str, ...]] = {
    "react": ("react", "react.js", "reactjs"),
    "react native": ("react native", "react-native", "reactnative"),
    "vue": ("vue", "vue.js", "vuejs"),
    "angular": ("angular", "angularjs"),
    "next.js": ("next.js", "nextjs", "next js"),
    "typescript": ("typescript",),
    "javascript": ("javascript", "ecmascript"),
    "node.js": ("node.js", "nodejs", "node js", "node"),
    "python": ("python",),
    "django": ("django",),
    "flask": ("flask",),
    "fastapi": ("fastapi",),
    "java": ("java",),
    "spring": ("spring", "spring boot"),
    "kotlin": ("kotlin",),
    "swift": ("swift",),
    "flutter": ("flutter",),
    "dart": ("dart",),
    ".net": (".net", "asp.net"),
    "c#": ("c#", "csharp", "c sharp"),
    "golang": ("golang",),
    "ruby": ("ruby",),
    "rails": ("rails", "ruby on rails"),
    "php": ("php",),
    "laravel": ("laravel",),
    "sql": ("sql",),
    "postgresql": ("postgresql", "postgres"),
    "mysql": ("mysql",),
    "mongodb": ("mongodb", "mongo"),
    "redis": ("redis",),
    "docker": ("docker",),
    "kubernetes": ("kubernetes", "k8s"),
    "aws": ("aws", "amazon web services"),
    "azure": ("azure",),
    "gcp": ("gcp", "google cloud"),
    "terraform": ("terraform",),
    "graphql": ("graphql",),
    "rest": ("rest api", "rest apis", "restful"),
    "html": ("html", "html5"),
    "css": ("css", "css3"),
    "sass": ("sass", "scss"),
    "tailwind": ("tailwind", "tailwindcss"),
    "jest": ("jest",),
    "cypress": ("cypress",),
    "playwright": ("playwright",),
    "git": ("git",),
    "linux": ("linux",),
    "kafka": ("kafka",),
    "spark": ("spark", "apache spark"),
    "airflow": ("airflow",),
    "pandas": ("pandas",),
    "numpy": ("numpy",),
    "power bi": ("power bi", "powerbi"),
    "figma": ("figma",),
}

_REQUIRED_HEADER = re.compile(
    r"^(requisitos?|requirements?|must[\s-]?have|qualifications?|qualificacoes|"
    r"what you(?:\s+will|\s*'ll)?\s+need|what you need|voce precisa|necessario|"
    r"obrigatori\w*)\b"
)
_PREFERRED_HEADER = re.compile(
    r"^(diferenciais?|preferred|nice[\s-]?to[\s-]?have|desirable|desejavel|bonus|"
    r"plus|good[\s-]?to[\s-]?have|diferencial)\b"
)
_NEUTRAL_HEADER = re.compile(
    r"^(responsabilidades|responsibilities|about(?:\s+the)?\s+(?:role|team|company)|"
    r"sobre\s+(?:a\s+)?(?:vaga|empresa|equipe)|the\s+role|role|o\s+papel|"
    r"beneficios|benefits|perks|why\s+join|descricao|description|job\s+description|"
    r"o\s+que\s+voce\s+(?:vai\s+)?fara|atuacao|local|location|contrato|contract)\b"
)
_REQUIRED_HINT = re.compile(
    r"\b(required|must|obrigatori\w*|necessari\w*|experiencia (?:solida |com |em )?|"
    r"proficien\w*|strong|solid|hands[\s-]?on|conhecimento (?:solido )?em)\b"
)

_FAMILY_TITLE_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("fullstack", re.compile(r"\b(full[\s-]?stack|fullstack)\b")),
    (
        "mobile",
        re.compile(
            r"\b(mobile|android|ios|flutter|react[\s-]?native|kotlin|swift)\b"
        ),
    ),
    (
        "data",
        re.compile(
            r"\b(data engineer|data scientist|machine learning|analytics|power bi|"
            r"spark|airflow|data science)\b"
        ),
    ),
    (
        "devops",
        re.compile(
            r"\b(devops|sre|site reliability|platform engineer|cloud engineer|"
            r"cloud architect|infraestrutura|infra|kubernetes|terraform)\b"
        ),
    ),
    ("qa", re.compile(r"\b(qa|quality assurance|quality engineer|test engineer|sdet)\b")),
    (
        "frontend",
        re.compile(
            r"\b(front[\s-]?end|frontend|react|vue|angular|next\.?js|javascript|"
            r"typescript|css|html|ui)\b"
        ),
    ),
    (
        "backend",
        re.compile(
            r"\b(back[\s-]?end|backend|node(?:\.js)?|python|django|flask|fastapi|"
            r"java|spring|\.net|c#|golang|ruby|rails|php|laravel|api|graphql)\b"
        ),
    ),
)

_FRONTEND_SKILLS = frozenset(
    {"react", "react native", "vue", "angular", "next.js", "typescript", "javascript", "html", "css", "sass", "tailwind", "jest", "cypress", "playwright"}
)
_BACKEND_SKILLS = frozenset(
    {"node.js", "python", "django", "flask", "fastapi", "java", "spring", ".net", "c#", "golang", "ruby", "rails", "php", "laravel", "sql", "postgresql", "mysql", "mongodb", "redis", "graphql", "rest", "kafka"}
)
_MOBILE_SKILLS = frozenset({"react native", "flutter", "dart", "kotlin", "swift"})
_DATA_SKILLS = frozenset({"spark", "airflow", "pandas", "numpy", "power bi"})
_DEVOPS_SKILLS = frozenset({"docker", "kubernetes", "aws", "azure", "gcp", "terraform", "linux"})


def build_job_profile(
    jd_text: str,
    *,
    title: str = "",
) -> JobProfile:
    """Build the auditable profile of one job description."""
    text = jd_text or ""
    combined_title = f"{title}\n{_first_line(text)}".strip()
    required, preferred = _extract_skills(text, title=title)
    return JobProfile(
        language=_detect_language(text),
        family=_detect_family(combined_title, required + preferred),
        seniority=_detect_seniority(title, text),
        required_skills=required,
        preferred_skills=preferred,
    )


def _first_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _detect_language(text: str) -> str:
    tokens = re.findall(r"[a-z0-9.+#]+", fold(text))
    if not tokens:
        return "unknown"
    pt_score = sum(1 for token in tokens if token in _PT_WORDS)
    en_score = sum(1 for token in tokens if token in _EN_WORDS)
    if pt_score > en_score:
        return "pt"
    if en_score > pt_score:
        return "en"
    return "unknown"


def _skill_pattern(alias: str) -> re.Pattern[str]:
    escaped = re.escape(alias)
    if alias[0].isalnum():
        body = rf"(?<![\w.]){escaped}(?![\w])"
    else:
        body = rf"(?<!\w){escaped}(?![\w])"
    if alias == "java":
        body = r"(?<![\w.])java(?!script)(?![\w])"
    return re.compile(body)


_SKILL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (canonical, _skill_pattern(alias))
    for canonical, aliases in _SKILLS.items()
    for alias in aliases
)


def _skills_in(text: str) -> list[str]:
    folded = fold(text)
    matches: list[tuple[int, int, str]] = []
    for canonical, pattern in _SKILL_PATTERNS:
        for match in pattern.finditer(folded):
            matches.append((match.start(), match.end(), canonical))
    # When aliases overlap ("react native" vs "react"), keep the longest match.
    matches.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    skills: list[str] = []
    covered_until = -1
    for start, end, canonical in matches:
        if start < covered_until:
            continue
        if canonical not in skills:
            skills.append(canonical)
        covered_until = end
    return skills


def _extract_skills(text: str, *, title: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    required: list[str] = []
    preferred: list[str] = []
    section = "neutral"

    for skill in _skills_in(title):
        if skill not in required:
            required.append(skill)

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        folded_line = fold(line).lstrip("-*• ").strip(" :")
        if _REQUIRED_HEADER.search(folded_line):
            section = "required"
        elif _PREFERRED_HEADER.search(folded_line):
            section = "preferred"
        elif _NEUTRAL_HEADER.search(folded_line):
            section = "neutral"

        mandatory = bool(_REQUIRED_HINT.search(folded_line))
        for skill in _skills_in(line):
            target_required = section == "required" or (
                section == "neutral" and mandatory
            )
            bucket = required if target_required else preferred
            if skill not in required and skill not in bucket:
                bucket.append(skill)

    preferred = [skill for skill in preferred if skill not in required]
    return tuple(required), tuple(preferred)


def _detect_family(title: str, skills: Iterable[str]) -> str:
    folded = fold(title)
    for family, pattern in _FAMILY_TITLE_RULES:
        if pattern.search(folded):
            return family

    skill_set = set(skills)
    if skill_set & _MOBILE_SKILLS:
        return "mobile"
    if skill_set & _DATA_SKILLS:
        return "data"
    if skill_set & _DEVOPS_SKILLS:
        return "devops"
    frontend = bool(skill_set & _FRONTEND_SKILLS)
    backend = bool(skill_set & _BACKEND_SKILLS)
    if frontend and backend:
        return "fullstack"
    if frontend:
        return "frontend"
    if backend:
        return "backend"
    return "other"


_SENIORITY_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("intern", re.compile(r"\b(estagi\w*|estagio|intern|internship|trainee|aprendiz|apprentice)\b")),
    ("junior", re.compile(r"\b(junior|jr|entry[\s-]?level)\b")),
    (
        "lead",
        re.compile(
            r"\b(lead|lider|staff|principal|head of|manager|gerente|coordenador|"
            r"architect|arquitet\w*|especialista|specialist)\b"
        ),
    ),
    ("senior", re.compile(r"\b(senior|sr)\b")),
)

# In the body, "lead" is usually a verb ("lead code reviews").  Only explicit
# leadership compounds promote a role to lead; the title rules above are the
# primary signal.
_BODY_SENIORITY_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("intern", _SENIORITY_RULES[0][1]),
    ("junior", _SENIORITY_RULES[1][1]),
    (
        "lead",
        re.compile(
            r"\b(tech lead|lead engineer|lead developer|team lead|staff engineer|"
            r"principal engineer|engineering manager|arquiteto de software)\b"
        ),
    ),
    ("senior", _SENIORITY_RULES[3][1]),
)


def _detect_seniority(title: str, text: str) -> str:
    title_source = title or _first_line(text)
    folded_title = fold(title_source)
    for seniority, pattern in _SENIORITY_RULES:
        if pattern.search(folded_title):
            return seniority

    folded_body = fold(text)
    for seniority, pattern in _BODY_SENIORITY_RULES:
        if pattern.search(folded_body):
            return seniority

    years = [
        int(match)
        for match in re.findall(r"(\d+)\s*\+?\s*(?:anos|years)", folded_body)
    ]
    if years:
        maximum = max(years)
        if maximum >= 5:
            return "senior"
        if maximum >= 3:
            return "mid"
        return "junior"
    return "unspecified"
