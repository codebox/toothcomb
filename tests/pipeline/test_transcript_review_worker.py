from unittest.mock import MagicMock

import pytest

from db.sqlite_database import SQLiteDatabase
from domain.analysed_text import Annotation, AnnotationType, AnalysedText, AnalysedPart
from domain.job import Job
from domain.llm_usage import LLMUsage
from domain.transcript import Utterance
from domain.transcript_review import TranscriptReview, ReviewFinding, FindingReference
from domain.types import (
    JobId, UtteranceId, AnnotationId, AnalysisResultId, ModelName,
    JobStatus,
)
from pipeline.workers.transcript_review_worker import TranscriptReviewWorker


# ---------- helpers ----------


@pytest.fixture
def db():
    return SQLiteDatabase(":memory:")


@pytest.fixture
def updates():
    return MagicMock()


class _FakeConfig:
    def get(self, key, default=None):
        return default


def _setup_reviewable_job(db, job_id="job-1"):
    """Create a job in reviewing status with a completed utterance and analysis."""
    db.create_job(Job(id=JobId(job_id), title="Test"))
    db.update_job_status(JobId(job_id), JobStatus.REVIEWING)

    utt = Utterance(id=UtteranceId("u1"), speaker="Alice", text="Hello world",
                    seq=1, job_id=JobId(job_id))
    db.create_utterance(utt)

    # Complete utterance analysis
    db.complete_utterance_analysis(UtteranceId("u1"), remainder="")
    db.create_analysis_result(AnalysisResultId("ar-1"), UtteranceId("u1"),
                              seq=1, corrected_text="Hello world")
    ann = Annotation(id=AnnotationId("ann-1"), type=AnnotationType.CLAIM,
                     notes="n", fact_check_query="q")
    db.create_annotation(ann, AnalysisResultId("ar-1"))
    # Complete the fact check so claim_review won't be blocked
    db.complete_fact_check(AnnotationId("ann-1"), verdict="true", note="ok")


def _make_reviewer(review=None, side_effect=None):
    reviewer = MagicMock()
    if side_effect:
        reviewer.review.side_effect = side_effect
    else:
        reviewer.review.return_value = review or TranscriptReview(job_id=JobId("job-1"))
    return reviewer


def _make_worker(reviewer, db, updates):
    return TranscriptReviewWorker(reviewer=reviewer, database=db,
                                  update_service=updates, config=_FakeConfig())


# ---------- poll ----------


class TestPoll:

    def test_finds_reviewing_job(self, db, updates):
        _setup_reviewable_job(db)
        reviewer = _make_reviewer()
        worker = _make_worker(reviewer, db, updates)

        assert worker.poll() is True
        reviewer.review.assert_called_once()

    def test_returns_false_when_no_work(self, db, updates):
        worker = _make_worker(_make_reviewer(), db, updates)
        assert worker.poll() is False

    def test_returns_false_when_no_reviewing_jobs(self, db, updates):
        db.create_job(Job(id=JobId("job-1"), title="T"))
        worker = _make_worker(_make_reviewer(), db, updates)
        assert worker.poll() is False


# ---------- _process: success ----------


class TestProcessSuccess:

    def test_calls_review_completed(self, db, updates):
        _setup_reviewable_job(db)
        finding = ReviewFinding(
            type=AnnotationType.TACTIC, technique="Self-Contradiction",
            summary="Contradicted",
            references=(
                FindingReference(excerpt="a", location="l1"),
                FindingReference(excerpt="b", location="l2"),
            ),
        )
        review = TranscriptReview(job_id=JobId("job-1"), findings=(finding,))
        reviewer = _make_reviewer(review=review)
        worker = _make_worker(reviewer, db, updates)

        job = db.claim_review()
        worker._process(job)

        updates.review_completed.assert_called_once()
        args = updates.review_completed.call_args[0]
        assert args[0] == JobId("job-1")
        assert len(args[1].findings) == 1

    def test_empty_findings_still_succeeds(self, db, updates):
        _setup_reviewable_job(db)
        review = TranscriptReview(job_id=JobId("job-1"), findings=())
        reviewer = _make_reviewer(review=review)
        worker = _make_worker(reviewer, db, updates)

        job = db.claim_review()
        worker._process(job)

        updates.review_completed.assert_called_once()

    def test_passes_analyses_to_reviewer(self, db, updates):
        _setup_reviewable_job(db)
        reviewer = _make_reviewer()
        worker = _make_worker(reviewer, db, updates)

        job = db.claim_review()
        worker._process(job)

        call_args = reviewer.review.call_args[0]
        analyses = call_args[1]
        assert len(analyses) == 1
        assert analyses[0].text == "Hello world"


# ---------- _process: failure ----------


class TestProcessFailure:

    def test_exception_calls_review_failed(self, db, updates):
        _setup_reviewable_job(db)
        reviewer = _make_reviewer(side_effect=RuntimeError("LLM down"))
        worker = _make_worker(reviewer, db, updates)

        job = db.claim_review()
        worker._process(job)

        updates.review_failed.assert_called_once_with(JobId("job-1"))
        updates.review_completed.assert_not_called()

    def test_failed_review_calls_review_failed(self, db, updates):
        _setup_reviewable_job(db)
        review = TranscriptReview(job_id=JobId("job-1"), failed=True)
        reviewer = _make_reviewer(review=review)
        worker = _make_worker(reviewer, db, updates)

        job = db.claim_review()
        worker._process(job)

        updates.review_failed.assert_called_once_with(JobId("job-1"))
        updates.review_completed.assert_not_called()
