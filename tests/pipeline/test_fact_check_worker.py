from unittest.mock import MagicMock

import pytest

from db.sqlite_database import SQLiteDatabase
from domain.analysed_text import Annotation, AnnotationType
from domain.fact_check_result import FactCheckResult, Verdict
from domain.job import Job
from domain.llm_usage import LLMUsage
from domain.transcript import Utterance
from domain.types import (
    JobId, UtteranceId, AnnotationId, AnalysisResultId, ModelName,
    JobStatus, FactCheckStatus,
)
from pipeline.workers.fact_check_worker import FactCheckWorker


# ---------- helpers ----------


@pytest.fixture
def db():
    return SQLiteDatabase(":memory:")


@pytest.fixture
def updates():
    return MagicMock()


def _setup_claimable_annotation(db, ann_id="ann-1", query="Is this true?"):
    db.create_job(Job(id=JobId("job-1"), title="T"))
    db.update_job_status(JobId("job-1"), JobStatus.INGESTING)
    utt = Utterance(id=UtteranceId("u1"), speaker="S", text="t", seq=1, job_id=JobId("job-1"))
    db.create_utterance(utt)
    db.create_analysis_result(AnalysisResultId("ar-1"), UtteranceId("u1"), seq=1, corrected_text="t")
    ann = Annotation(id=AnnotationId(ann_id), type=AnnotationType.CLAIM,
                     notes="n", fact_check_query=query)
    db.create_annotation(ann, AnalysisResultId("ar-1"))
    return ann


def _make_checker(verdict=Verdict.ESTABLISHED, note="Confirmed", usage=None, side_effect=None):
    checker = MagicMock()
    if side_effect:
        checker.fact_check.side_effect = side_effect
    else:
        checker.fact_check.return_value = FactCheckResult(verdict=verdict, note=note, usage=usage)
    return checker


class _FakeConfig:
    def get(self, key, default=None):
        return default


def _make_worker(checker, db, updates):
    return FactCheckWorker(fact_checker=checker, database=db,
                           update_service=updates, config=_FakeConfig())


# ---------- poll ----------


class TestPoll:

    def test_finds_pending_fact_check(self, db, updates):
        _setup_claimable_annotation(db)
        checker = _make_checker()
        worker = _make_worker(checker, db, updates)

        assert worker.poll() is True
        checker.fact_check.assert_called_once_with("Is this true?")

    def test_returns_false_when_no_work(self, db, updates):
        worker = _make_worker(_make_checker(), db, updates)
        assert worker.poll() is False

    def test_returns_false_when_no_annotations_with_query(self, db, updates):
        # Create annotation without fact_check_query (PREDICTION type via helper)
        db.create_job(Job(id=JobId("job-1"), title="T"))
        db.update_job_status(JobId("job-1"), JobStatus.INGESTING)
        utt = Utterance(id=UtteranceId("u1"), speaker="S", text="t", seq=1, job_id=JobId("job-1"))
        db.create_utterance(utt)
        db.create_analysis_result(AnalysisResultId("ar-1"), UtteranceId("u1"), seq=1, corrected_text="t")
        ann = Annotation(id=AnnotationId("ann-1"), type=AnnotationType.PREDICTION, notes="n")
        db.create_annotation(ann, AnalysisResultId("ar-1"))

        worker = _make_worker(_make_checker(), db, updates)
        assert worker.poll() is False


# ---------- _process: success verdicts ----------


class TestProcessSuccess:

    def test_established_calls_completed(self, db, updates):
        ann = _setup_claimable_annotation(db)
        checker = _make_checker(Verdict.ESTABLISHED, "Confirmed")
        worker = _make_worker(checker, db, updates)

        # Claim to get annotation with job_id populated
        claimed = db.claim_fact_check()
        worker._process(claimed)

        updates.fact_check_completed.assert_called_once()
        args = updates.fact_check_completed.call_args
        assert args[0][2] == "established"
        assert args[0][3] == "Confirmed"

    def test_misleading_calls_completed(self, db, updates):
        _setup_claimable_annotation(db)
        checker = _make_checker(Verdict.MISLEADING, "Partly wrong")
        worker = _make_worker(checker, db, updates)

        worker._process(db.claim_fact_check())

        updates.fact_check_completed.assert_called_once()
        assert updates.fact_check_completed.call_args[0][2] == "misleading"

    def test_unsupported_calls_completed(self, db, updates):
        _setup_claimable_annotation(db)
        checker = _make_checker(Verdict.UNSUPPORTED, "No evidence")
        worker = _make_worker(checker, db, updates)

        worker._process(db.claim_fact_check())

        updates.fact_check_completed.assert_called_once()
        assert updates.fact_check_completed.call_args[0][2] == "unsupported"

    def test_false_calls_completed(self, db, updates):
        _setup_claimable_annotation(db)
        checker = _make_checker(Verdict.FALSE, "Incorrect")
        worker = _make_worker(checker, db, updates)

        worker._process(db.claim_fact_check())

        updates.fact_check_completed.assert_called_once()
        assert updates.fact_check_completed.call_args[0][2] == "false"

    def test_usage_passed_through(self, db, updates):
        _setup_claimable_annotation(db)
        usage = LLMUsage(model=ModelName("m"), input_tokens=50)
        checker = _make_checker(usage=usage)
        worker = _make_worker(checker, db, updates)

        worker._process(db.claim_fact_check())

        assert updates.fact_check_completed.call_args[1]["usage"] == usage


# ---------- _process: FAILED verdict ----------


class TestProcessFailed:

    def test_failed_verdict_calls_fact_check_failed(self, db, updates):
        _setup_claimable_annotation(db)
        checker = _make_checker(Verdict.FAILED, "Could not determine")
        worker = _make_worker(checker, db, updates)

        worker._process(db.claim_fact_check())

        updates.fact_check_failed.assert_called_once()
        updates.fact_check_completed.assert_not_called()
        assert updates.fact_check_failed.call_args[0][2] == "Could not determine"

    def test_failed_verdict_passes_usage(self, db, updates):
        _setup_claimable_annotation(db)
        usage = LLMUsage(model=ModelName("m"), input_tokens=10)
        checker = _make_checker(Verdict.FAILED, "err", usage=usage)
        worker = _make_worker(checker, db, updates)

        worker._process(db.claim_fact_check())

        assert updates.fact_check_failed.call_args[1]["usage"] == usage


# ---------- _process: exceptions ----------


class TestProcessException:

    def test_exception_creates_failed_result(self, db, updates):
        _setup_claimable_annotation(db)
        checker = _make_checker(side_effect=RuntimeError("API down"))
        worker = _make_worker(checker, db, updates)

        worker._process(db.claim_fact_check())

        # Should route to fact_check_failed, not fact_check_completed
        updates.fact_check_failed.assert_called_once()
        updates.fact_check_completed.assert_not_called()
        note = updates.fact_check_failed.call_args[0][2]
        assert "ann-1" in note

    def test_exception_still_checks_complete(self, db, updates):
        _setup_claimable_annotation(db)
        checker = _make_checker(side_effect=RuntimeError("boom"))
        worker = _make_worker(checker, db, updates)

        worker._process(db.claim_fact_check())

        updates.check_job_progress.assert_called_once()

    def test_always_checks_complete_on_success(self, db, updates):
        _setup_claimable_annotation(db)
        checker = _make_checker()
        worker = _make_worker(checker, db, updates)

        worker._process(db.claim_fact_check())

        updates.check_job_progress.assert_called_once_with(JobId("job-1"))
