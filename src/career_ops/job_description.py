"""Lazy job-description access for candidates that survived the quick filters.

Only shortlisted candidates ever reach a fetcher.  The production fetcher uses
LinkedIn's public guest posting endpoint (the same one ``career-ops-enrich``
uses); tests and offline runs can use a directory of ``<job-id>.txt`` files.
"""

from __future__ import annotations

import html
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

GUEST_POSTING_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
DEFAULT_TIMEOUT_SECONDS = 20.0

Transport = Callable[[str, float], "tuple[int, str]"]


class JobDescriptionError(RuntimeError):
    """A JD could not be fetched or parsed."""

    reason = "jd_fetch_failed"


JD_MISSING_REASON = "jd_missing"


class JobDescriptionMissing(JobDescriptionError):
    """The posting (or its description) is not available."""

    reason = JD_MISSING_REASON


@dataclass(frozen=True)
class JobDescription:
    job_id: str
    text: str
    url: str = ""
    title: str = ""
    company: str = ""
    location: str = ""
    workplace: str = ""
    path: Path | None = None


class JobDescriptionFetcher(Protocol):
    def fetch(self, job_id: str) -> JobDescription:
        """Return the JD for ``job_id`` or raise ``JobDescriptionError``."""


class DirectoryJobDescriptionFetcher:
    """Read JD text files from a directory (offline runs and tests)."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def fetch(self, job_id: str) -> JobDescription:
        path = self.root / f"{job_id}.txt"
        if not path.is_file():
            raise JobDescriptionMissing(
                f"JD not found for job {job_id}: {path}"
            )
        text = path.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            raise JobDescriptionMissing(f"JD for job {job_id} is empty: {path}")
        return JobDescription(job_id=job_id, text=text, path=path)


class HttpJobDescriptionFetcher:
    """Fetch the public guest posting card and extract title/location/JD text."""

    def __init__(
        self,
        *,
        transport: Transport | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        self._transport = transport or _urllib_transport
        self.timeout = timeout

    def fetch(self, job_id: str) -> JobDescription:
        url = GUEST_POSTING_URL.format(job_id=job_id)
        posting_url = f"https://www.linkedin.com/jobs/view/{job_id}/"
        try:
            status, body = self._transport(url, self.timeout)
        except OSError as exc:
            raise JobDescriptionError(f"could not fetch the JD for {job_id}: {exc}") from exc
        if status == 404:
            raise JobDescriptionMissing(f"LinkedIn has no posting for job {job_id}")
        if status < 200 or status >= 300:
            raise JobDescriptionError(f"LinkedIn returned HTTP {status} for job {job_id}")

        title = _first(body, r'class="[^"]*topcard__title[^"]*"[^>]*>([\s\S]*?)</h2>')
        company = _first(
            body,
            r'class="[^"]*topcard__org-name-link[^"]*"[^>]*>([\s\S]*?)</a>',
        )
        location = _first(
            body,
            r'class="[^"]*topcard__flavor topcard__flavor--bullet[^"]*"[^>]*>([\s\S]*?)</span>',
        )
        workplace = _first(
            body,
            r'class="[^"]*description__job-criteria-subheader[^"]*"[^>]*>\s*'
            r"(Remote|Remoto|Hybrid|Híbrido|On-site|Presencial)[\s\S]*?</span>",
        )
        description_html = (
            re.search(
                r'class="[^"]*show-more-less-html__markup[^"]*"[^>]*>([\s\S]*?)</div>',
                body,
            )
            or re.search(r"<body[^>]*>([\s\S]*?)</body>", body)
        )
        description = _strip_html(description_html.group(1) if description_html else "")
        if not description and not title:
            raise JobDescriptionMissing(f"job {job_id} has no description text")

        text = (
            f"# {title} @ {company}\n"
            f"# {location}\n"
            f"# {workplace}\n"
            f"# url: {posting_url}\n\n"
            f"{description}\n"
        )
        return JobDescription(
            job_id=job_id,
            text=text,
            url=posting_url,
            title=title,
            company=company,
            location=location,
            workplace=workplace,
        )


def _urllib_transport(url: str, timeout: float) -> tuple[int, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise OSError(str(exc)) from exc


def _first(source: str, pattern: str) -> str:
    match = re.search(pattern, source)
    return _strip_html(match.group(1)) if match else ""


def _strip_html(source: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", source or "", flags=re.IGNORECASE)
    text = re.sub(r"</(p|li|div|ul|ol|h\d)>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li[^>]*>", "- ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()
