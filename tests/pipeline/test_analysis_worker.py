import json
from unittest.mock import MagicMock, patch

import pytest

from db.sqlite_database import SQLiteDatabase
from domain.analysed_text import Annotation, AnnotationType, AnalysedPart, AnalysedText
from domain.job import Job
from domain.transcript import Utterance
from domain.types import (
    JobId, UtteranceId, AnnotationId, AnalysisResultId,
    JobStatus, AnalysisStatus,
)
from pipeline.workers.analysis_worker import AnalysisWorker


# ---------- helpers ----------


class _FakeConfig:
    def get(self, key, default=None):
        return {"llm.previous_utterance_count": 2}.get(key, default)


def _make_analyser(return_value=None, side_effect=None):
    analyser = MagicMock()
    if side_effect:
        analyser.analyse.side_effect = side_effect
    elif return_value:
        analyser.analyse.return_value = return_value
    else:
        analyser.analyse.return_value = AnalysedText(
            utterance_id=UtteranceId("u1"), text="t",
            analysed_parts=(AnalysedPart(corrected_text="corrected"),),
            remainder="left over",
        )
    return analyser


@pytest.fixture
def db():
    return SQLiteDatabase(":memory:")


@pytest.fixture
def updates():
    return MagicMock()


def _create_running_job(db, job_id="job-1", config_data=None):
    if config_data is None:
        config_data = {
            "context": {"speakers": "Alice", "date_and_time": "2025-03-04"},
            "is_transcribed": False,
        }
    job = Job(id=JobId(job_id), title="Test", config=json.dumps(config_data))
    db.create_job(job)
    db.update_job_status(JobId(job_id), JobStatus.INGESTING)
    return job


def _create_pending_utterance(db, utt_id="u1", job_id="job-1", seq=1, text="test text"):
    utt = Utterance(id=UtteranceId(utt_id), speaker="Alice", text=text,
                     seq=seq, job_id=JobId(job_id))
    db.create_utterance(utt)
    # Move from buffered to pending
    conn = db._get_conn()
    conn.execute("UPDATE utterances SET analysis_status = 'pending' WHERE id = ?", (utt_id,))
    conn.commit()
    return utt


def _make_worker(analyser, db, updates):
    return AnalysisWorker(
        text_analyser=analyser, database=db,
        update_service=updates, config=_FakeConfig(),
    )


# ---------- poll ----------


class TestPoll:

    def test_finds_work_in_running_job(self, db, updates):
        _create_running_job(db)
        _create_pending_utterance(db)
        analyser = _make_analyser()
        worker = _make_worker(analyser, db, updates)

        assert worker.poll() is True
        analyser.analyse.assert_called_once()

    def test_skips_non_running_jobs(self, db, updates):
        # Job is in INIT status
        job = Job(id=JobId("job-1"), title="Test", config="{}")
        db.create_job(job)
        _create_pending_utterance(db)
        analyser = _make_analyser()
        worker = _make_worker(analyser, db, updates)

        assert worker.poll() is False
        analyser.analyse.assert_not_called()

    def test_returns_false_when_no_work(self, db, updates):
        _create_running_job(db)
        # No utterances at all
        analyser = _make_analyser()
        worker = _make_worker(analyser, db, updates)

        assert worker.poll() is False

    def test_scans_multiple_jobs(self, db, updates):
        _create_running_job(db, "job-1")
        _create_running_job(db, "job-2")
        _create_pending_utterance(db, "u1", "job-2", seq=1)
        analyser = _make_analyser()
        worker = _make_worker(analyser, db, updates)

        assert worker.poll() is True
        analyser.analyse.assert_called_once()


# ---------- _process ----------


class TestProcess:

    def test_success_calls_update_service(self, db, updates):
        _create_running_job(db)
        utt = _create_pending_utterance(db)
        job = db.get_job(JobId("job-1"))
        analyser = _make_analyser()
        worker = _make_worker(analyser, db, updates)

        worker._process(job, utt)

        updates.utterance_analysed.assert_called_once()
        args = updates.utterance_analysed.call_args[0]
        assert args[0] == "job-1"
        assert args[1] == "u1"

    def test_always_checks_job_complete(self, db, updates):
        _create_running_job(db)
        utt = _create_pending_utterance(db)
        job = db.get_job(JobId("job-1"))
        analyser = _make_analyser()
        worker = _make_worker(analyser, db, updates)

        worker._process(job, utt)

        updates.check_job_progress.assert_called_once_with(JobId("job-1"))

    def test_builds_context_from_previous_utterances(self, db, updates):
        _create_running_job(db)
        _create_pending_utterance(db, "u1", seq=1, text="first statement")
        db.complete_utterance_analysis(UtteranceId("u1"), remainder="")
        utt2 = _create_pending_utterance(db, "u2", seq=2, text="second statement")
        job = db.get_job(JobId("job-1"))
        analyser = _make_analyser()
        worker = _make_worker(analyser, db, updates)

        worker._process(job, utt2)

        call_args = analyser.analyse.call_args[0]
        utterance_with_context = call_args[0]
        assert len(utterance_with_context.previous) == 1
        assert utterance_with_context.previous[0].text == "first statement"

    def test_prepends_remainder_from_previous(self, db, updates):
        _create_running_job(db)
        _create_pending_utterance(db, "u1", seq=1, text="first")
        db.complete_utterance_analysis(UtteranceId("u1"), remainder="leftover")
        utt2 = _create_pending_utterance(db, "u2", seq=2, text="second")
        job = db.get_job(JobId("job-1"))
        analyser = _make_analyser()
        worker = _make_worker(analyser, db, updates)

        worker._process(job, utt2)

        call_args = analyser.analyse.call_args[0]
        assert call_args[0].utterance.text == "leftover second"

    def test_no_remainder_for_first_utterance(self, db, updates):
        _create_running_job(db)
        utt = _create_pending_utterance(db, "u1", seq=1, text="hello")
        job = db.get_job(JobId("job-1"))
        analyser = _make_analyser()
        worker = _make_worker(analyser, db, updates)

        worker._process(job, utt)

        call_args = analyser.analyse.call_args[0]
        assert call_args[0].utterance.text == "hello"

    def test_builds_job_config_from_job(self, db, updates):
        _create_running_job(db, config_data={
            "context": {"speakers": "Alice", "location": "NYC"},
            "is_transcribed": True,
        })
        utt = _create_pending_utterance(db)
        job = db.get_job(JobId("job-1"))
        analyser = _make_analyser()
        worker = _make_worker(analyser, db, updates)

        worker._process(job, utt)

        call_args = analyser.analyse.call_args[0]
        job_config = call_args[1]
        assert job_config.context.speakers == "Alice"
        assert job_config.context.location == "NYC"
        assert job_config.is_transcribed is True

    def test_analyser_exception_creates_failed_result(self, db, updates):
        _create_running_job(db)
        utt = _create_pending_utterance(db)
        job = db.get_job(JobId("job-1"))
        analyser = _make_analyser(side_effect=RuntimeError("LLM down"))
        worker = _make_worker(analyser, db, updates)

        worker._process(job, utt)

        # Should still call utterance_analysed with a failed AnalysedText
        updates.utterance_analysed.assert_called_once()
        analysed = updates.utterance_analysed.call_args[0][2]
        assert analysed.failed is True

    def test_analyser_exception_still_checks_complete(self, db, updates):
        _create_running_job(db)
        utt = _create_pending_utterance(db)
        job = db.get_job(JobId("job-1"))
        analyser = _make_analyser(side_effect=RuntimeError("boom"))
        worker = _make_worker(analyser, db, updates)

        worker._process(job, utt)

        updates.check_job_progress.assert_called_once()

    def test_outer_exception_fails_utterance_directly(self, db, updates):
        """If the outer try/except catches (e.g. DB error building context),
        the utterance is failed directly on the DB, not via update_service."""
        _create_running_job(db)
        utt = _create_pending_utterance(db)
        job = db.get_job(JobId("job-1"))
        analyser = _make_analyser()
        worker = _make_worker(analyser, db, updates)

        # Make get_utterance_context blow up to trigger the outer exception
        with patch.object(db, 'get_utterance_context', side_effect=RuntimeError("DB error")):
            worker._process(job, utt)

        # Should have failed the utterance directly
        u = db.get_utterance(UtteranceId("u1"))
        assert u.analysis_status == AnalysisStatus.FAILED
        # utterance_analysed should NOT have been called
        updates.utterance_analysed.assert_not_called()

    def test_outer_exception_still_checks_complete(self, db, updates):
        _create_running_job(db)
        utt = _create_pending_utterance(db)
        job = db.get_job(JobId("job-1"))
        analyser = _make_analyser()
        worker = _make_worker(analyser, db, updates)

        with patch.object(db, 'get_utterance_context', side_effect=RuntimeError("DB error")):
            worker._process(job, utt)

        updates.check_job_progress.assert_called_once()

    def test_empty_context_config(self, db, updates):
        """Job with no context in config_data should not crash."""
        _create_running_job(db, config_data={})
        utt = _create_pending_utterance(db)
        job = db.get_job(JobId("job-1"))
        analyser = _make_analyser()
        worker = _make_worker(analyser, db, updates)

        worker._process(job, utt)

        call_args = analyser.analyse.call_args[0]
        job_config = call_args[1]
        assert job_config.context.speakers == ""
        assert job_config.is_transcribed is False
