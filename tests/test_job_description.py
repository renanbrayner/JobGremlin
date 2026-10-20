from __future__ import annotations

import pytest

from career_ops.job_description import (
    DirectoryJobDescriptionFetcher,
    HttpJobDescriptionFetcher,
    JobDescriptionError,
    JobDescriptionMissing,
)


def test_the_directory_fetcher_reads_only_the_requested_job(tmp_path):
    (tmp_path / "111.txt").write_text("React JD", encoding="utf-8")
    (tmp_path / "222.txt").write_text("Backend JD", encoding="utf-8")
    fetcher = DirectoryJobDescriptionFetcher(tmp_path)

    jd = fetcher.fetch("222")

    assert jd.job_id == "222"
    assert jd.text == "Backend JD"
    assert jd.path == tmp_path / "222.txt"


def test_a_missing_directory_jd_raises_a_typed_missing_error(tmp_path):
    fetcher = DirectoryJobDescriptionFetcher(tmp_path)

    with pytest.raises(JobDescriptionMissing) as caught:
        fetcher.fetch("333")

    assert caught.value.reason == "jd_missing"
    assert "333" in str(caught.value)


def test_the_http_fetcher_parses_the_guest_job_card():
    def transport(url, timeout):
        assert "jobPosting/4411222" in url
        return (
            200,
            """
            <h2 class="topcard__title">Senior React Engineer</h2>
            <a class="topcard__org-name-link">Acme</a>
            <span class="topcard__flavor topcard__flavor--bullet">Recife, PE</span>
            <span class="description__job-criteria-subheader">Remote</span>
            <div class="show-more-less-html__markup">
              <p>Build React and TypeScript products.</p>
            </div>
            """,
        )

    fetcher = HttpJobDescriptionFetcher(transport=transport)

    jd = fetcher.fetch("4411222")

    assert jd.job_id == "4411222"
    assert jd.title == "Senior React Engineer"
    assert jd.company == "Acme"
    assert jd.location == "Recife, PE"
    assert "Build React and TypeScript" in jd.text
    assert "https://www.linkedin.com/jobs/view/4411222/" in jd.text


def test_an_http_404_is_a_missing_jd():
    fetcher = HttpJobDescriptionFetcher(transport=lambda url, timeout: (404, ""))

    with pytest.raises(JobDescriptionMissing):
        fetcher.fetch("4411222")


def test_a_transport_failure_is_a_typed_fetch_error():
    def transport(url, timeout):
        raise OSError("network down")

    fetcher = HttpJobDescriptionFetcher(transport=transport)

    with pytest.raises(JobDescriptionError) as caught:
        fetcher.fetch("4411222")

    assert caught.value.reason == "jd_fetch_failed"
    assert not isinstance(caught.value, JobDescriptionMissing)
