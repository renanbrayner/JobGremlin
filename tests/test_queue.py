from __future__ import annotations

import json

import pytest

from career_ops.eligibility import EligibilityRules
from career_ops.job_description import JobDescription, JobDescriptionMissing
from career_ops.queue import (
    Candidate,
    JobQueue,
    QueueProcessor,
    load_candidates,
)
from conftest import DEVOPS_JD, FRONTEND_JD


class CountingFetcher:
    def __init__(self, descriptions: dict[str, str]) -> None:
        self.descriptions = descriptions
        self.calls: list[str] = []

    def fetch(self, job_id: str) -> JobDescription:
        self.calls.append(job_id)
        if job_id not in self.descriptions:
            raise JobDescriptionMissing(f"JD not found for job {job_id}")
        return JobDescription(job_id=job_id, text=self.descriptions[job_id])


def _candidate(
    job_id: str,
    *,
    title: str = "Desenvolvedor React",
    location: str = "Recife, PE",
    workplace: str = "Remote",
    applied: bool = False,
    closed: bool = False,
    discarded: bool = False,
) -> Candidate:
    return Candidate(
        id=job_id,
        title=title,
        company="Acme",
        location=location,
        workplace=workplace,
        applied=applied,
        closed=closed,
        discarded=discarded,
    )


def test_candidates_can_be_loaded_from_json_and_tsv(tmp_path):
    json_file = tmp_path / "candidates.json"
    json_file.write_text(
        json.dumps(
            [
                {
                    "id": 111,
                    "title": "React Developer",
                    "location": "Recife, PE",
                    "workplace": "Remote",
                }
            ]
        ),
        encoding="utf-8",
    )
    tsv_file = tmp_path / "candidates.tsv"
    tsv_file.write_text(
        "id\ttitle\tcompany\tlocation\tworkplace\tis_remote\n"
        "222\tBackend Developer\tAcme\tRecife, PE\tOn-site\tno\n",
        encoding="utf-8",
    )

    from_json = load_candidates(json_file)
    from_tsv = load_candidates(tsv_file)

    assert from_json[0].id == "111"
    assert from_json[0].title == "React Developer"
    assert from_tsv[0].id == "222"
    assert from_tsv[0].location == "Recife, PE"
    assert from_tsv[0].is_remote is False


def test_an_invalid_candidate_file_is_rejected(tmp_path):
    path = tmp_path / "candidates.json"
    path.write_text('{"not": "a list"}', encoding="utf-8")

    with pytest.raises(ValueError):
        load_candidates(path)


def test_the_queue_persists_and_deduplicates_by_id(paths):
    queue = JobQueue.load(paths)
    results = queue.ingest([_candidate("1"), _candidate("1")])

    assert [result.status for result in results] == ["enqueued", "skipped"]
    assert results[1].reason == "duplicate"

    reloaded = JobQueue.load(paths)
    assert list(reloaded.records) == ["1"]
    assert reloaded.records["1"].state == "new"


@pytest.mark.parametrize(
    ("flag", "reason"),
    [
        ("applied", "already_applied"),
        ("closed", "job_closed"),
        ("discarded", "discarded"),
    ],
)
def test_applied_closed_and_discarded_ids_do_not_come_back(paths, flag, reason):
    queue = JobQueue.load(paths)

    first = queue.ingest([_candidate("1", **{flag: True})])
    second = queue.ingest([_candidate("1")])

    assert first[0].status == "skipped"
    assert first[0].reason == reason
    assert second[0].status == "skipped"
    assert second[0].reason == "blocked:ineligible"
    assert queue.records["1"].state == "ineligible"


def test_a_blocked_id_can_return_only_with_an_explicit_reason(paths):
    queue = JobQueue.load(paths)
    queue.ingest([_candidate("1", applied=True)])

    result = queue.ingest([_candidate("1")], requeue_reason="manual retry")

    assert result[0].status == "requeued"
    assert queue.records["1"].state == "new"
    assert queue.records["1"].reason == "manual retry"


def test_a_candidate_that_becomes_applied_is_removed_from_the_queue(paths):
    queue = JobQueue.load(paths)
    queue.ingest([_candidate("1")])

    result = queue.ingest([_candidate("1", applied=True)])

    assert result[0].status == "skipped"
    assert result[0].reason == "already_applied"
    assert queue.records["1"].state == "ineligible"


def test_an_interrupted_jd_fetch_is_resumed_without_a_requeue(paths):
    fetcher = CountingFetcher({"1": FRONTEND_JD})
    queue = JobQueue.load(paths)
    queue.ingest([_candidate("1")])
    queue.mark("1", "jd_fetched", None, {"jd_path": "data/jds/1.txt"})

    selection = QueueProcessor(queue, fetcher).next_eligible()

    assert selection is not None
    assert selection.job_id == "1"
    assert fetcher.calls == ["1"]
    assert queue.records["1"].state == "eligible"


def test_the_processor_shortlists_fetches_lazily_and_returns_the_first_eligible(paths):
    fetcher = CountingFetcher({"4": FRONTEND_JD, "5": FRONTEND_JD})
    queue = JobQueue.load(paths)
    queue.ingest(
        [
            _candidate("1", title="QA Automation Engineer"),
            _candidate("2", location="São Paulo, SP", workplace="On-site"),
            _candidate("3"),
            _candidate("4"),
            _candidate("5"),
        ]
    )

    selection = QueueProcessor(queue, fetcher).next_eligible()

    assert selection is not None
    assert selection.job_id == "4"
    assert fetcher.calls == ["3", "4"]
    assert queue.records["1"].state == "title_rejected"
    assert queue.records["1"].reason == "title_qa"
    assert queue.records["2"].state == "ineligible"
    assert queue.records["2"].reason == "location_outside_region"
    assert queue.records["3"].state == "failed"
    assert queue.records["3"].reason == "jd_missing"
    assert queue.records["4"].state == "eligible"
    assert queue.records["5"].state == "new"
    assert "jd_path" not in (queue.records["5"].detail or {})
    assert selection.profile["family"] == "frontend"
    assert selection.decision["reason"] == "eligible"
    assert selection.jd_path is not None
    assert selection.jd_path.is_file()


def test_an_ineligible_profile_is_recorded_and_processing_continues(paths):
    fetcher = CountingFetcher({"1": DEVOPS_JD, "2": FRONTEND_JD})
    queue = JobQueue.load(paths)
    queue.ingest([_candidate("1", title="Software Engineer"), _candidate("2")])

    selection = QueueProcessor(queue, fetcher).next_eligible()

    assert selection is not None
    assert selection.job_id == "2"
    assert queue.records["1"].state == "ineligible"
    assert queue.records["1"].reason == "family_not_targeted"
    assert queue.records["1"].profile["family"] == "devops"
    assert queue.records["1"].decision["reason"] == "family_not_targeted"


def test_an_existing_eligible_record_is_resumed_before_new_candidates(paths):
    fetcher = CountingFetcher({"1": FRONTEND_JD})
    queue = JobQueue.load(paths)
    queue.ingest([_candidate("1")])
    first = QueueProcessor(queue, fetcher).next_eligible()
    assert first is not None and first.job_id == "1"

    selection = QueueProcessor(queue, fetcher).next_eligible()

    assert selection is not None
    assert selection.job_id == "1"
    assert fetcher.calls == ["1"]


def test_rules_are_configurable_through_the_queue_processor(paths):
    fetcher = CountingFetcher({"1": FRONTEND_JD})
    queue = JobQueue.load(paths)
    queue.ingest([_candidate("1")])
    rules = EligibilityRules(languages=("en",))

    assert QueueProcessor(queue, fetcher, rules=rules).next_eligible() is None
    assert queue.records["1"].state == "ineligible"
    assert queue.records["1"].reason == "language_unsupported"


def test_begin_and_complete_record_the_application_outcome(paths):
    queue = JobQueue.load(paths)
    queue.ingest([_candidate("1")])
    queue.mark("1", "eligible", "eligible", {"eligible": True})

    queue.begin("1")
    queue.complete("1", "verified", "verified", {"run_id": "run-1"})

    record = JobQueue.load(paths).records["1"]
    assert record.state == "verified"
    assert record.attempts == 1
    assert record.reason == "verified"
    assert record.detail["run_id"] == "run-1"
