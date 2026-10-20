"""Deterministic quick filters that build the shortlist.

A candidate is shortlisted only after two cheap checks, both applied before any
JD is downloaded:

* the title must be a hands-on development role (not QA, security,
  infrastructure, leadership, internship or junior);
* the location must be remote or on-site in the Recife region; hybrid roles and
  on-site roles elsewhere are rejected.

Every rejection returns a stable ``reason`` code so the queue can explain why a
candidate never reached the JD stage.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Mapping


def fold(value: object) -> str:
    """Lowercase and strip accents so pt-BR and en-US spellings match."""
    text = unicodedata.normalize("NFD", str(value or ""))
    return "".join(char for char in text if unicodedata.category(char) != "Mn").lower()


@dataclass(frozen=True)
class FilterDecision:
    accepted: bool
    reason: str | None
    detail: Mapping[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "reason": self.reason,
            "detail": dict(self.detail),
        }


_TITLE_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "title_internship",
        re.compile(
            r"\b(estagi\w*|estagio|intern|internship|trainee|aprendiz|apprentice|entry[\s-]?level)\b"
        ),
    ),
    ("title_junior", re.compile(r"\b(junior|jr)\b")),
    (
        "title_qa",
        re.compile(
            r"\b(qa|quality assurance|quality engineer|q\.?a\.?|teste?s?|tester|testing|"
            r"test analyst|test engineer|sdet|automacao de teste|automation tester|"
            r"analista de teste)\b"
        ),
    ),
    (
        "title_security",
        re.compile(
            r"\b(seguranca|security|appsec|sec|pentest|penetration|soc analyst|ciso|"
            r"threat|vulnerab\w*|hacking|infosec|grc)\b"
        ),
    ),
    (
        "title_infra",
        re.compile(
            r"\b(devops|sre|site reliability|infraestrutura|infra|platform engineer|"
            r"cloud engineer|cloud architect|sysadmin|administrador de redes|"
            r"analista de redes|redes|suporte|support|service desk|help desk|noc|"
            r"observability|dba|banco de dados)\b"
        ),
    ),
    (
        "title_leadership",
        re.compile(
            r"\b(arquitet\w*|architect|tech lead|tecnico lead|lead developer|lead|lider|"
            r"gestor|gerente|manager|head of|coordenador|coordinator|diretor|director|"
            r"supervisor|staff engineer|principal engineer|engineering manager|"
            r"scrum master|product owner|product manager|gerencia|especialista|specialist)\b"
        ),
    ),
    (
        "title_non_dev",
        re.compile(
            r"\b(designer|ux|ui|vendas|sales|comercial|marketing|recrutad\w*|recruiter|"
            r"financeiro|contab\w*|customer success|suporte ao cliente|analista de negocios|"
            r"business analyst|business development|dados|data scien\w*|analytics|bi|power bi|"
            r"machine learning engineer|cientista)\b"
        ),
    ),
)

_DEV_SIGNAL = re.compile(
    r"\b(desenvolvedor\w*|desenvolvedora|desenvolvimento|development|developer|"
    r"programador\w*|engenheir\w* de software|software engineer|software developer|"
    r"full[\s-]?stack|front[\s-]?end|back[\s-]?end|frontend|backend|react|vue|"
    r"angular|next\.?js|node(\.js)?|javascript|typescript|php|laravel|python|django|"
    r"flask|fastapi|java|spring|\.net|c#|golang|ruby|rails|mobile|android|ios|flutter|"
    r"kotlin|swift|web dev\w*|dev web)\b"
)

_REMOTE = re.compile(r"\b(remot\w*|remote|home[\s-]?office|teletrabalho|anywhere)\b")
_HYBRID = re.compile(r"\b(hibrid\w*|hybrid)\b")
_ONSITE = re.compile(r"\b(on[\s-]?site|presencial|no local)\b")

# Recife and the municipalities that make up its immediate metropolitan region.
_RECIFE_REGION = (
    "recife",
    "olinda",
    "jaboatao",
    "jaboatao dos guararapes",
    "paulista",
    "camaragibe",
    "sao lourenco da mata",
    "igarassu",
    "abreu e lima",
    "cabo de santo agostinho",
    "moreno",
    "ilha de itamaraca",
    "aracoiaba",
    "itapissuma",
    "grande recife",
    "regiao metropolitana do recife",
    "rmr",
)


def filter_title(title: str) -> FilterDecision:
    """Reject titles that are clearly outside the target development role."""
    raw = (title or "").strip()
    if not raw:
        return FilterDecision(False, "title_missing", {"title": raw})

    folded = fold(raw)
    for reason, pattern in _TITLE_RULES:
        match = pattern.search(folded)
        if match:
            return FilterDecision(
                False,
                reason,
                {"title": raw, "match": match.group(0)},
            )

    if not _DEV_SIGNAL.search(folded):
        return FilterDecision(False, "title_non_dev", {"title": raw})

    return FilterDecision(True, None, {"title": raw})


def filter_location(
    location: str,
    *,
    workplace: str = "",
    is_remote: bool = False,
) -> FilterDecision:
    """Accept remote roles or on-site roles in the Recife region.

    Hybrid roles are rejected wherever they are; an on-site role outside the
    region is rejected too.  A missing workplace is treated as unspecified: it
    passes only when the location itself is inside the region, because that is
    the only place an on-site role could be acceptable.
    """
    location_raw = (location or "").strip()
    workplace_raw = (workplace or "").strip()
    combined = fold(f"{location_raw} {workplace_raw}")

    kind = _workplace_kind(combined, is_remote=is_remote)
    detail = {
        "location": location_raw,
        "workplace": kind,
        "is_remote": bool(is_remote),
    }

    if kind == "hybrid":
        return FilterDecision(False, "location_hybrid", detail)
    if kind == "remote":
        return FilterDecision(True, None, detail)
    if not location_raw:
        return FilterDecision(False, "location_missing", detail)
    if _in_recife_region(fold(location_raw)):
        return FilterDecision(True, None, detail)
    return FilterDecision(False, "location_outside_region", detail)


def _workplace_kind(combined: str, *, is_remote: bool) -> str:
    if _HYBRID.search(combined):
        return "hybrid"
    if is_remote or _REMOTE.search(combined):
        return "remote"
    if _ONSITE.search(combined):
        return "on_site"
    return "unspecified"


def _in_recife_region(folded_location: str) -> bool:
    return any(
        re.search(rf"\b{re.escape(token)}\b", folded_location)
        for token in _RECIFE_REGION
    )
