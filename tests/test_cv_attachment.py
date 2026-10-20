from __future__ import annotations

import pytest

from career_ops.cv_attachment import (
    WrongCvAttached,
    normalize_cv_name,
    verify_cv_attachment,
)


def test_the_expected_cv_matches_a_dom_basename_case_insensitively():
    check = verify_cv_attachment(
        "/workspace/output/cv-renan-react-2026-10-19.PDF",
        ["cv-renan-react-2026-10-19.pdf"],
    )

    assert check.ok is True
    assert check.reason == "attached"
    assert check.expected == "cv-renan-react-2026-10-19.PDF"
    assert check.selected == ("cv-renan-react-2026-10-19.pdf",)


def test_a_whitespace_difference_does_not_create_a_false_mismatch():
    check = verify_cv_attachment("cv-renan  react.pdf", ["cv-renan react.pdf"])

    assert check.ok is True
    assert normalize_cv_name("  /tmp/My CV.PDF ") == "my cv.pdf"


def test_linkedin_reusing_the_previous_pdf_is_a_wrong_cv():
    check = verify_cv_attachment(
        "cv-renan-react-2026-10-19.pdf",
        ["cv-renan-crossing-en-2026-10-06.pdf"],
    )

    assert check.ok is False
    assert check.reason == "wrong_cv"
    assert check.expected == "cv-renan-react-2026-10-19.pdf"
    assert check.selected == ("cv-renan-crossing-en-2026-10-06.pdf",)
    assert check.detail() == {
        "reason": "wrong_cv",
        "expected_cv": "cv-renan-react-2026-10-19.pdf",
        "selected_cvs": ["cv-renan-crossing-en-2026-10-06.pdf"],
    }


def test_no_selected_cv_is_reported_as_missing():
    check = verify_cv_attachment("cv-renan.pdf", [])

    assert check.ok is False
    assert check.reason == "missing"
    assert "no CV is selected" in str(WrongCvAttached(check))


def test_a_wrong_cv_error_never_suggests_a_fallback():
    check = verify_cv_attachment("expected.pdf", ["old.pdf"])

    with pytest.raises(WrongCvAttached, match="wrong CV selected"):
        raise WrongCvAttached(check)


def test_duplicate_selected_names_are_compared_once():
    check = verify_cv_attachment("A.pdf", ["A.pdf", "a.pdf"])

    assert check.ok is True
    assert check.selected == ("A.pdf",)
