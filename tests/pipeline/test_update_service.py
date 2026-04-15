from unittest.mock import MagicMock, call

import pytest

from db.sqlite_database import SQLiteDatabase
from domain.analysed_text import Annotation, AnnotationType, AnalysedPart, AnalysedText
from domain.job import Job
from domain.llm_usage import LLMUsage
from domain.transcript import Utterance
from domain.transcript_review import TranscriptReview
from domain.types import (
    JobId, UtteranceId, AnnotationId, AnalysisResultId, ModelName,
    JobStatus, AnalysisStatus, FactCheckStatus,
)
from pipeline.update_service import UpdateService


# ---------- helpers ----------


@pytest.fixture
def db():
    return SQLiteDatabase(":memory:")


@pytest.fixture
def emitter():
    return MagicMock()


@pytest.fixture
def svc(db, emitter):
    return UpdateService(db, emitter, buffer_words=5)


def _job(job_id="job-1"):
    return Job(id=JobId(job_id), title="Test")


def _utterance(utt_id="u1", job_id="job-1", seq=1, text="hello world foo bar baz qux"):
    return Utterance(id=UtteranceId(utt_id), speaker="Alice", text=text,
                     seq=seq, job_id=JobId(job_id))


# ---------- utterance_transcribed ----------


class TestUtteranceTranscribed:

    def test_stores_utterance_and_emits(self, db, emitter, svc):
        db.create_job(_job())
        utt = _utterance()
        svc.utterance_transcribed(utt)

        assert db.get_utterance(UtteranceId("u1")) is not None
        emitter.transcription.assert_called_once()

    def test_dropped_if_job_deleted(self, db, emitter, svc):
        utt = _utterance()  # job doesn't exist
        svc.utterance_transcribed(utt)

        assert db.get_utterance(UtteranceId("u1")) is None
        emitter.transcription.assert_not_called()

    def test_triggers_buffer_flush(self, db, emitter, svc):
        db.create_job(_job())
        # Buffer words is 5; send enough words to trigger flush
        svc.utterance_transcribed(_utterance("u1", seq=1, text="one two three"))
        svc.utterance_transcribed(_utterance("u2", seq=2, text="four five six seven"))

        # u2 should now be pending (flushed from buffer)
        utt = db.get_utterance(UtteranceId("u2"))
        assert utt.analysis_status == AnalysisStatus.PENDING

    def test_buffer_flush_emits_merge_event(self, db, emitter, svc):
        db.create_job(_job())
        svc.utterance_transcribed(_utterance("u1", seq=1, text="one two three"))
        svc.utterance_transcribed(_utterance("u2", seq=2, text="four five six seven"))

        emitter.utterances_merged.assert_called_once()


# ---------- flush_remaining_buffer ----------


class TestFlushRemainingBuffer:

    def test_flushes_buffered_utterances(self, db, emitter, svc):
        db.create_job(_job())
        db.create_utterance(_utterance("u1", text="short"))

        svc.flush_remaining_buffer(JobId("job-1"))

        utt = db.get_utterance(UtteranceId("u1"))
        assert utt.analysis_status == AnalysisStatus.PENDING

    def test_dropped_if_job_deleted(self, db, emitter, svc):
        svc.flush_remaining_buffer(JobId("nope"))
        emitter.utterances_merged.assert_not_called()

    def test_noop_if_no_buffered_utterances(self, db, emitter, svc):
        db.create_job(_job())
        svc.flush_remaining_buffer(JobId("job-1"))
        emitter.utterances_merged.assert_not_called()

    def test_emits_merge_when_multiple_utterances(self, db, emitter, svc):
        db.create_job(_job())
        db.create_utterance(_utterance("u1", seq=1, text="first"))
        db.create_utterance(_utterance("u2", seq=2, text="second"))

        svc.flush_remaining_buffer(JobId("job-1"))

        emitter.utterances_merged.assert_called_once()
        args = emitter.utterances_merged.call_args
        assert "u1" in args[0][1]  # merged_ids
        assert args[0][2] == "u2"  # target_id

    def test_no_merge_event_for_single_utterance(self, db, emitter, svc):
        db.create_job(_job())
        db.create_utterance(_utterance("u1", text="only one"))

        svc.flush_remaining_buffer(JobId("job-1"))

        emitter.utterances_merged.assert_not_called()


# ---------- utterance_analysed ----------


class TestUtteranceAnalysed:

    def _setup(self, db):
        db.create_job(_job())
        db.create_utterance(_utterance("u1"))

    def test_success_stores_results_and_annotations(self, db, emitter, svc):
        self._setup(db)
        ann = Annotation(type=AnnotationType.PREDICTION, notes="will rise")
        part = AnalysedPart(corrected_text="corrected", annotations=(ann,))
        analysis = AnalysedText(
            utterance_id=UtteranceId("u1"), text="original",
            analysed_parts=(part,), remainder="leftover",
        )

        svc.utterance_analysed(JobId("job-1"), UtteranceId("u1"), analysis)

        utt = db.get_utterance(UtteranceId("u1"))
        assert utt.analysis_status == AnalysisStatus.COMPLETE
        assert utt.analysis_remainder == "leftover"

        parts = db.get_analysed_parts(UtteranceId("u1"))
        assert len(parts) == 1
        assert parts[0].corrected_text == "corrected"
        assert len(parts[0].annotations) == 1

    def test_success_emits_analysis(self, db, emitter, svc):
        self._setup(db)
        analysis = AnalysedText(utterance_id=UtteranceId("u1"), text="t")
        svc.utterance_analysed(JobId("job-1"), UtteranceId("u1"), analysis)
        emitter.analysis.assert_called_once()

    def test_failed_marks_utterance_failed(self, db, emitter, svc):
        self._setup(db)
        analysis = AnalysedText(
            utterance_id=UtteranceId("u1"), text="t", failed=True,
        )
        svc.utterance_analysed(JobId("job-1"), UtteranceId("u1"), analysis)

        utt = db.get_utterance(UtteranceId("u1"))
        assert utt.analysis_status == AnalysisStatus.FAILED
        emitter.analysis_failed.assert_called_once()
        emitter.analysis.assert_not_called()

    def test_records_usage(self, db, emitter, svc):
        self._setup(db)
        usage = LLMUsage(model=ModelName("m"), input_tokens=100)
        analysis = AnalysedText(
            utterance_id=UtteranceId("u1"), text="t", usage=usage,
        )
        svc.utterance_analysed(JobId("job-1"), UtteranceId("u1"), analysis)

        stats = db.get_job_stats(JobId("job-1"))
        assert len(stats) == 1
        assert stats[0]["input_tokens"] == 100

    def test_no_usage_is_fine(self, db, emitter, svc):
        self._setup(db)
        analysis = AnalysedText(
            utterance_id=UtteranceId("u1"), text="t", usage=None,
        )
        svc.utterance_analysed(JobId("job-1"), UtteranceId("u1"), analysis)
        assert db.get_job_stats(JobId("job-1")) == []

    def test_pre_verdicted_annotation_emits_fact_check(self, db, emitter, svc):
        self._setup(db)
        ann = Annotation(type=AnnotationType.CLAIM, notes="Known false",
                         fact_check_verdict="false",
                         fact_check_note="Well-established fact")
        part = AnalysedPart(corrected_text="text", annotations=(ann,))
        analysis = AnalysedText(
            utterance_id=UtteranceId("u1"), text="original",
            analysed_parts=(part,),
        )

        svc.utterance_analysed(JobId("job-1"), UtteranceId("u1"), analysis)

        emitter.analysis.assert_called_once()
        emitter.fact_check.assert_called_once()
        fc_args = emitter.fact_check.call_args[0]
        assert fc_args[0] == JobId("job-1")
        assert fc_args[2] == "false"
        assert fc_args[3] == "Well-established fact"

    def test_pre_verdicted_stored_as_complete(self, db, emitter, svc):
        self._setup(db)
        ann = Annotation(type=AnnotationType.PREDICTION, notes="Outcome known",
                         fact_check_verdict="established",
                         fact_check_note="It happened")
        part = AnalysedPart(corrected_text="text", annotations=(ann,))
        analysis = AnalysedText(
            utterance_id=UtteranceId("u1"), text="original",
            analysed_parts=(part,),
        )

        svc.utterance_analysed(JobId("job-1"), UtteranceId("u1"), analysis)

        parts = db.get_analysed_parts(UtteranceId("u1"))
        stored_ann = parts[0].annotations[0]
        assert stored_ann.fact_check_status == FactCheckStatus.COMPLETE
        assert stored_ann.fact_check_verdict == "established"

    def test_no_fact_check_event_for_normal_annotation(self, db, emitter, svc):
        self._setup(db)
        ann = Annotation(type=AnnotationType.PREDICTION, notes="future event")
        part = AnalysedPart(corrected_text="text", annotations=(ann,))
        analysis = AnalysedText(
            utterance_id=UtteranceId("u1"), text="original",
            analysed_parts=(part,),
        )

        svc.utterance_analysed(JobId("job-1"), UtteranceId("u1"), analysis)

        emitter.fact_check.assert_not_called()

    def test_dropped_if_job_deleted(self, db, emitter, svc):
        analysis = AnalysedText(utterance_id=UtteranceId("u1"), text="t")
        svc.utterance_analysed(JobId("nope"), UtteranceId("u1"), analysis)
        emitter.analysis.assert_not_called()
        emitter.analysis_failed.assert_not_called()


# ---------- fact_check_completed ----------


class TestFactCheckCompleted:

    def _setup(self, db):
        db.create_job(_job())
        db.create_utterance(_utterance("u1"))
        db.create_analysis_result(AnalysisResultId("ar-1"), UtteranceId("u1"),
                                  seq=1, corrected_text="text")
        ann = Annotation(id=AnnotationId("ann-1"), type=AnnotationType.CLAIM,
                         notes="n", fact_check_query="q")
        db.create_annotation(ann, AnalysisResultId("ar-1"))

    def test_stores_verdict_and_emits(self, db, emitter, svc):
        self._setup(db)
        svc.fact_check_completed(JobId("job-1"), AnnotationId("ann-1"),
                                 "established", "Confirmed")

        ann = db.get_annotation(AnnotationId("ann-1"))
        assert ann.fact_check_status == FactCheckStatus.COMPLETE
        assert ann.fact_check_verdict == "established"
        assert ann.fact_check_note == "Confirmed"
        emitter.fact_check.assert_called_once()

    def test_records_usage(self, db, emitter, svc):
        self._setup(db)
        usage = LLMUsage(model=ModelName("m"), input_tokens=50)
        svc.fact_check_completed(JobId("job-1"), AnnotationId("ann-1"),
                                 "false", "Wrong", usage=usage)

        stats = db.get_job_stats(JobId("job-1"))
        assert stats[0]["input_tokens"] == 50

    def test_dropped_if_job_deleted(self, db, emitter, svc):
        svc.fact_check_completed(JobId("nope"), AnnotationId("ann-1"),
                                 "true", "ok")
        emitter.fact_check.assert_not_called()


# ---------- fact_check_failed ----------


class TestFactCheckFailed:

    def _setup(self, db):
        db.create_job(_job())
        db.create_utterance(_utterance("u1"))
        db.create_analysis_result(AnalysisResultId("ar-1"), UtteranceId("u1"),
                                  seq=1, corrected_text="text")
        ann = Annotation(id=AnnotationId("ann-1"), type=AnnotationType.CLAIM,
                         notes="n", fact_check_query="q")
        db.create_annotation(ann, AnalysisResultId("ar-1"))

    def test_stores_failure_and_emits(self, db, emitter, svc):
        self._setup(db)
        svc.fact_check_failed(JobId("job-1"), AnnotationId("ann-1"), "API error")

        ann = db.get_annotation(AnnotationId("ann-1"))
        assert ann.fact_check_status == FactCheckStatus.FAILED
        assert ann.fact_check_note == "API error"
        emitter.fact_check.assert_called_once()
        # Should emit with "FAILED" verdict
        args = emitter.fact_check.call_args[0]
        assert args[2] == "FAILED"

    def test_records_usage(self, db, emitter, svc):
        self._setup(db)
        usage = LLMUsage(model=ModelName("m"), output_tokens=10)
        svc.fact_check_failed(JobId("job-1"), AnnotationId("ann-1"),
                              "error", usage=usage)

        stats = db.get_job_stats(JobId("job-1"))
        assert stats[0]["output_tokens"] == 10

    def test_dropped_if_job_deleted(self, db, emitter, svc):
        svc.fact_check_failed(JobId("nope"), AnnotationId("ann-1"), "err")
        emitter.fact_check.assert_not_called()


# ---------- check_job_progress ----------


class TestCheckJobProgress:

    def test_advances_analysing_to_reviewing(self, db, emitter, svc):
        db.create_job(_job())
        db.create_utterance(_utterance("u1"))
        db.update_job_status(JobId("job-1"), JobStatus.ANALYSING)
        db.complete_utterance_analysis(UtteranceId("u1"), remainder="")

        svc.check_job_progress(JobId("job-1"))

        assert db.get_job(JobId("job-1")).status == JobStatus.REVIEWING
        emitter.job_status.assert_called_once_with(
            JobId("job-1"), JobStatus.REVIEWING, room="lobby")

    def test_does_not_advance_when_analysis_pending(self, db, emitter, svc):
        db.create_job(_job())
        db.create_utterance(_utterance("u1"))
        db.update_job_status(JobId("job-1"), JobStatus.ANALYSING)
        # analysis still buffered

        svc.check_job_progress(JobId("job-1"))

        assert db.get_job(JobId("job-1")).status == JobStatus.ANALYSING
        emitter.job_status.assert_not_called()

    def test_noop_if_job_deleted(self, db, emitter, svc):
        svc.check_job_progress(JobId("nope"))
        emitter.job_status.assert_not_called()

    def test_noop_for_running_job(self, db, emitter, svc):
        """Running jobs don't advance via check_job_progress (source must finish first)."""
        db.create_job(_job())
        db.update_job_status(JobId("job-1"), JobStatus.INGESTING)

        svc.check_job_progress(JobId("job-1"))

        assert db.get_job(JobId("job-1")).status == JobStatus.INGESTING
        emitter.job_status.assert_not_called()


# ---------- review_completed ----------


class TestReviewCompleted:

    def test_stores_and_emits_review(self, db, emitter, svc):
        db.create_job(_job())
        db.update_job_status(JobId("job-1"), JobStatus.REVIEWING)
        review = TranscriptReview(job_id=JobId("job-1"))

        svc.review_completed(JobId("job-1"), review)

        assert db.get_review(JobId("job-1")) is not None
        emitter.transcript_review.assert_called_once()

    def test_advances_to_complete(self, db, emitter, svc):
        db.create_job(_job())
        db.update_job_status(JobId("job-1"), JobStatus.REVIEWING)
        review = TranscriptReview(job_id=JobId("job-1"))

        svc.review_completed(JobId("job-1"), review)

        assert db.get_job(JobId("job-1")).status == JobStatus.COMPLETE
        emitter.job_status.assert_called_once_with(
            JobId("job-1"), JobStatus.COMPLETE, room="lobby")

    def test_dropped_if_job_deleted(self, db, emitter, svc):
        review = TranscriptReview(job_id=JobId("nope"))
        svc.review_completed(JobId("nope"), review)
        emitter.transcript_review.assert_not_called()


# ---------- review_failed ----------


class TestReviewFailed:

    def test_leaves_job_in_reviewing_for_retry(self, db, emitter, svc):
        """Review failures don't mark the job as failed — job stays in reviewing
        so it gets retried on next restart."""
        db.create_job(_job())
        db.update_job_status(JobId("job-1"), JobStatus.REVIEWING)

        svc.review_failed(JobId("job-1"))

        assert db.get_job(JobId("job-1")).status == JobStatus.REVIEWING
        emitter.transcript_review.assert_not_called()
        emitter.job_status.assert_not_called()

    def test_dropped_if_job_deleted(self, db, emitter, svc):
        svc.review_failed(JobId("nope"))
        emitter.transcript_review.assert_not_called()


# ---------- _record_usage ----------


class TestRecordUsage:

    def test_emits_stats_after_recording(self, db, emitter, svc):
        db.create_job(_job())
        usage = LLMUsage(model=ModelName("m"), input_tokens=10)
        svc._record_usage(JobId("job-1"), usage)

        emitter.job_stats.assert_called_once()

    def test_noop_with_none_usage(self, db, emitter, svc):
        db.create_job(_job())
        svc._record_usage(JobId("job-1"), None)

        assert db.get_job_stats(JobId("job-1")) == []
        emitter.job_stats.assert_not_called()
