import json
from unittest.mock import MagicMock, patch, call

import pytest

from domain.analysed_text import (
    AnalysedText, AnalysedPart, Annotation, AnnotationType,
)
from domain.job import Job
from domain.transcript import Utterance
from domain.types import (
    JobId, UtteranceId, AnnotationId,
    JobStatus, AnalysisStatus, FactCheckStatus,
)
from web.web_server import WebServer


# ---------- helpers ----------


class _FakeConfig:
    def __init__(self, overrides=None):
        self._values = {"webserver.port": 5000, "paths.uploads": "/tmp/uploads"}
        if overrides:
            self._values.update(overrides)

    def get(self, key, default=None):
        return self._values.get(key, default)


def _make_server(db=None):
    db = db or MagicMock()
    server = WebServer(_FakeConfig(), db)
    server._emitter = MagicMock()
    return server, db


def _job(job_id="j1", title="Test", status=JobStatus.INIT):
    return Job(id=JobId(job_id), title=title, status=status)


def _utterance(utt_id="u1", text="hello", speaker="Alice",
               analysis_status=AnalysisStatus.PENDING,
               analysis_remainder=""):
    return Utterance(
        id=UtteranceId(utt_id), speaker=speaker, text=text,
        job_id=JobId("j1"), seq=1,
        analysis_status=analysis_status,
        analysis_remainder=analysis_remainder,
    )


def _annotation(ann_id="a1", ann_type=AnnotationType.CLAIM,
                fc_status=None, fc_verdict=None, fc_note=None):
    return Annotation(
        id=AnnotationId(ann_id),
        type=ann_type,
        notes="test note",
        fact_check_query="Is it true?" if ann_type == AnnotationType.CLAIM else None,
        fact_check_status=fc_status,
        fact_check_verdict=fc_verdict,
        fact_check_note=fc_note,
    )


# ---------- REST: list_jobs ----------


class TestListJobs:

    def test_returns_serialised_jobs(self):
        server, db = _make_server()
        db.list_jobs.return_value = [_job("j1"), _job("j2")]

        with server._app.test_client() as client:
            resp = client.get("/api/jobs")

        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 2
        assert data[0]["id"] == "j1"
        assert data[1]["id"] == "j2"

    def test_returns_empty_list(self):
        server, db = _make_server()
        db.list_jobs.return_value = []

        with server._app.test_client() as client:
            resp = client.get("/api/jobs")

        assert resp.get_json() == []


# ---------- REST: create_job ----------


class TestCreateJob:

    def test_json_payload(self):
        server, db = _make_server()
        builder = MagicMock()
        builder.build_from_dict.return_value = JobId("j1")
        db.get_job.return_value = _job("j1")
        server.set_job_builder(builder)

        with server._app.test_client() as client:
            resp = client.post("/jobs",
                               data=json.dumps({"title": "My Job"}),
                               content_type="application/json")

        assert resp.status_code == 201
        assert resp.get_json()["job_id"] == "j1"
        builder.build_from_dict.assert_called_once_with({"title": "My Job"})
        server._emitter.job_created.assert_called_once()

    def test_emits_to_lobby(self):
        server, db = _make_server()
        builder = MagicMock()
        builder.build_from_dict.return_value = JobId("j1")
        job = _job("j1")
        db.get_job.return_value = job
        server.set_job_builder(builder)

        with server._app.test_client() as client:
            client.post("/jobs",
                        data=json.dumps({"title": "T"}),
                        content_type="application/json")

        server._emitter.job_created.assert_called_once_with(job, room="lobby")


# ---------- REST: start_job ----------


class TestStartJob:

    def test_starts_existing_job(self):
        server, db = _make_server()
        builder = MagicMock()
        db.get_job.return_value = _job("j1")
        server.set_job_builder(builder)

        with server._app.test_client() as client:
            resp = client.post("/jobs/j1/start")

        assert resp.status_code == 200
        builder.start_job.assert_called_once_with(JobId("j1"))
        server._emitter.job_status.assert_called_once_with(
            JobId("j1"), JobStatus.INGESTING, room="lobby")

    def test_404_when_job_not_found(self):
        server, db = _make_server()
        db.get_job.return_value = None
        server.set_job_builder(MagicMock())

        with server._app.test_client() as client:
            resp = client.post("/jobs/nope/start")

        assert resp.status_code == 404
        assert "not found" in resp.get_json()["error"].lower()


# ---------- REST: delete_job ----------


class TestDeleteJob:

    def test_deletes_existing_job(self):
        server, db = _make_server()
        db.delete_job.return_value = True

        with server._app.test_client() as client:
            resp = client.delete("/jobs/j1")

        assert resp.status_code == 200
        db.delete_job.assert_called_once_with(JobId("j1"))
        server._emitter.job_deleted.assert_called_once_with(
            JobId("j1"), room="lobby")

    def test_404_when_job_not_found(self):
        server, db = _make_server()
        db.delete_job.return_value = False

        with server._app.test_client() as client:
            resp = client.delete("/jobs/j1")

        assert resp.status_code == 404
        server._emitter.job_deleted.assert_not_called()


# ---------- _replay_job_state ----------


class TestReplayJobState:

    def test_replays_status_and_complete(self):
        server, db = _make_server()
        job = _job("j1", status=JobStatus.INGESTING)
        db.get_job.return_value = job
        db.get_job_stats.return_value = None
        db.get_utterances.return_value = []

        server._replay_job_state(JobId("j1"), to="sid")

        emitter = server._emitter
        emitter.job_status.assert_called_once_with(
            JobId("j1"), JobStatus.INGESTING, to="sid")
        emitter.replay_complete.assert_called_once_with(
            JobId("j1"), to="sid")

    def test_replays_stats_when_present(self):
        server, db = _make_server()
        db.get_job.return_value = _job("j1")
        db.get_job_stats.return_value = [{"model": "m", "input_tokens": 100}]
        db.get_utterances.return_value = []

        server._replay_job_state(JobId("j1"), to="sid")

        server._emitter.job_stats.assert_called_once_with(
            JobId("j1"), [{"model": "m", "input_tokens": 100}], to="sid")

    def test_skips_stats_when_none(self):
        server, db = _make_server()
        db.get_job.return_value = _job("j1")
        db.get_job_stats.return_value = None
        db.get_utterances.return_value = []

        server._replay_job_state(JobId("j1"), to="sid")

        server._emitter.job_stats.assert_not_called()

    def test_skips_stats_when_empty(self):
        server, db = _make_server()
        db.get_job.return_value = _job("j1")
        db.get_job_stats.return_value = []
        db.get_utterances.return_value = []

        server._replay_job_state(JobId("j1"), to="sid")

        server._emitter.job_stats.assert_not_called()

    def test_returns_early_when_job_missing(self):
        server, db = _make_server()
        db.get_job.return_value = None

        server._replay_job_state(JobId("j1"), to="sid")

        server._emitter.job_status.assert_not_called()
        server._emitter.replay_complete.assert_not_called()

    def test_replays_transcription_and_analysis_per_utterance(self):
        server, db = _make_server()
        db.get_job.return_value = _job("j1")
        db.get_job_stats.return_value = None
        utt1 = _utterance("u1", analysis_status=AnalysisStatus.COMPLETE)
        utt2 = _utterance("u2", text="world", analysis_status=AnalysisStatus.PENDING)
        db.get_utterances.return_value = [utt1, utt2]
        db.get_analysed_parts.return_value = []

        server._replay_job_state(JobId("j1"), to="sid")

        emitter = server._emitter
        # Two transcription calls
        assert emitter.transcription.call_count == 2
        # Two analysis attempts (get_analysed_parts called for each non-failed)
        assert db.get_analysed_parts.call_count == 2

    def test_replay_complete_always_last(self):
        server, db = _make_server()
        db.get_job.return_value = _job("j1", status=JobStatus.INGESTING)
        db.get_job_stats.return_value = [{"x": 1}]
        utt = _utterance("u1")
        db.get_utterances.return_value = [utt]
        db.get_analysed_parts.return_value = []

        server._replay_job_state(JobId("j1"), to="sid")

        emitter = server._emitter
        last_call = emitter.method_calls[-1]
        assert last_call[0] == "replay_complete"


# ---------- _replay_analysis ----------


class TestReplayAnalysis:

    def test_failed_analysis_emits_failure(self):
        server, db = _make_server()
        utt = _utterance("u1", analysis_status=AnalysisStatus.FAILED)

        server._replay_analysis(JobId("j1"), utt, to="sid")

        server._emitter.analysis_failed.assert_called_once_with(
            JobId("j1"), UtteranceId("u1"), to="sid")
        # Should not query for analysed parts
        db.get_analysed_parts.assert_not_called()

    def test_no_parts_skips_emission(self):
        server, db = _make_server()
        utt = _utterance("u1", analysis_status=AnalysisStatus.COMPLETE)
        db.get_analysed_parts.return_value = []

        server._replay_analysis(JobId("j1"), utt, to="sid")

        server._emitter.analysis.assert_not_called()

    def test_with_parts_emits_analysis(self):
        server, db = _make_server()
        utt = _utterance("u1", text="hello", analysis_status=AnalysisStatus.COMPLETE,
                         analysis_remainder="leftover")
        part = AnalysedPart(corrected_text="Hello.", annotations=())
        db.get_analysed_parts.return_value = [part]

        server._replay_analysis(JobId("j1"), utt, to="sid")

        emitter = server._emitter
        emitter.analysis.assert_called_once()
        args = emitter.analysis.call_args
        analysed_text = args[0][1]
        assert analysed_text.utterance_id == "u1"
        assert analysed_text.text == "hello"
        assert analysed_text.analysed_parts == (part,)
        assert analysed_text.remainder == "leftover"

    def test_replays_complete_fact_checks(self):
        server, db = _make_server()
        utt = _utterance("u1", analysis_status=AnalysisStatus.COMPLETE)
        ann_complete = _annotation(
            "a1", fc_status=FactCheckStatus.COMPLETE,
            fc_verdict="established", fc_note="Confirmed",
        )
        ann_pending = _annotation(
            "a2", ann_type=AnnotationType.PREDICTION,
            fc_status=FactCheckStatus.PENDING,
        )
        part = AnalysedPart(
            corrected_text="text",
            annotations=(ann_complete, ann_pending),
        )
        db.get_analysed_parts.return_value = [part]

        server._replay_analysis(JobId("j1"), utt, to="sid")

        emitter = server._emitter
        # Only the complete fact check should be replayed
        emitter.fact_check.assert_called_once_with(
            JobId("j1"), AnnotationId("a1"),
            "established", "Confirmed",
            to="sid",
        )

    def test_no_fact_check_when_none_complete(self):
        server, db = _make_server()
        utt = _utterance("u1", analysis_status=AnalysisStatus.COMPLETE)
        ann = _annotation("a1", fc_status=FactCheckStatus.PENDING)
        part = AnalysedPart(corrected_text="t", annotations=(ann,))
        db.get_analysed_parts.return_value = [part]

        server._replay_analysis(JobId("j1"), utt, to="sid")

        server._emitter.fact_check.assert_not_called()

    def test_pending_analysis_with_no_parts(self):
        """Utterance still pending analysis — no parts exist yet."""
        server, db = _make_server()
        utt = _utterance("u1", analysis_status=AnalysisStatus.PENDING)
        db.get_analysed_parts.return_value = []

        server._replay_analysis(JobId("j1"), utt, to="sid")

        server._emitter.analysis.assert_not_called()
        server._emitter.analysis_failed.assert_not_called()


# ---------- _replay_fact_check ----------


class TestReplayFactCheck:

    def test_complete_fact_check_emitted(self):
        server, _ = _make_server()
        ann = _annotation(
            "a1", fc_status=FactCheckStatus.COMPLETE,
            fc_verdict="false", fc_note="Debunked",
        )

        server._replay_fact_check(JobId("j1"), ann, to="sid")

        server._emitter.fact_check.assert_called_once_with(
            JobId("j1"), AnnotationId("a1"),
            "false", "Debunked", to="sid",
        )

    def test_pending_fact_check_not_emitted(self):
        server, _ = _make_server()
        ann = _annotation("a1", fc_status=FactCheckStatus.PENDING)

        server._replay_fact_check(JobId("j1"), ann, to="sid")

        server._emitter.fact_check.assert_not_called()

    def test_failed_fact_check_not_emitted(self):
        server, _ = _make_server()
        ann = _annotation("a1", fc_status=FactCheckStatus.FAILED)

        server._replay_fact_check(JobId("j1"), ann, to="sid")

        server._emitter.fact_check.assert_not_called()

    def test_processing_fact_check_not_emitted(self):
        server, _ = _make_server()
        ann = _annotation("a1", fc_status=FactCheckStatus.PROCESSING)

        server._replay_fact_check(JobId("j1"), ann, to="sid")

        server._emitter.fact_check.assert_not_called()


# ---------- REST: request_review ----------


class TestRequestReview:

    def test_returns_202_for_running_job_with_analyses(self):
        server, db = _make_server()
        db.get_job.return_value = _job("j1", status=JobStatus.INGESTING)
        db.get_all_analysed_texts.return_value = [MagicMock()]
        db.start_early_review.return_value = True

        with server._app.test_client() as client:
            resp = client.post("/jobs/j1/review")

        assert resp.status_code == 202
        assert resp.get_json()["status"] == "reviewing"
        db.start_early_review.assert_called_once_with(JobId("j1"))
        server._emitter.job_status.assert_called_once_with(
            JobId("j1"), JobStatus.REVIEWING, room="lobby")

    def test_returns_202_for_analysing_job(self):
        server, db = _make_server()
        db.get_job.return_value = _job("j1", status=JobStatus.ANALYSING)
        db.get_all_analysed_texts.return_value = [MagicMock()]
        db.start_early_review.return_value = True

        with server._app.test_client() as client:
            resp = client.post("/jobs/j1/review")

        assert resp.status_code == 202
        db.start_early_review.assert_called_once_with(JobId("j1"))

    def test_404_when_job_not_found(self):
        server, db = _make_server()
        db.get_job.return_value = None

        with server._app.test_client() as client:
            resp = client.post("/jobs/j1/review")

        assert resp.status_code == 404

    def test_400_when_no_analyses(self):
        server, db = _make_server()
        db.get_job.return_value = _job("j1", status=JobStatus.INGESTING)
        db.get_all_analysed_texts.return_value = []

        with server._app.test_client() as client:
            resp = client.post("/jobs/j1/review")

        assert resp.status_code == 400
        assert "No analysed" in resp.get_json()["error"]

    def test_400_when_job_not_reviewable(self):
        server, db = _make_server()
        db.get_job.return_value = _job("j1", status=JobStatus.COMPLETE)

        with server._app.test_client() as client:
            resp = client.post("/jobs/j1/review")

        assert resp.status_code == 400
        assert "reviewable" in resp.get_json()["error"].lower()


# ---------- _replay_review ----------


class TestReplayReview:

    def test_replays_complete_review(self):
        server, db = _make_server()
        job = Job(id=JobId("j1"), title="T", status=JobStatus.COMPLETE)
        review_data = {"findings": [{"type": "TACTIC"}]}
        db.get_review.return_value = review_data

        server._replay_review(JobId("j1"), job, to="sid")

        server._emitter.transcript_review.assert_called_once_with(
            JobId("j1"), review_data, to="sid")

    def test_skips_when_not_complete(self):
        server, db = _make_server()
        job = Job(id=JobId("j1"), title="T", status=JobStatus.REVIEWING)

        server._replay_review(JobId("j1"), job, to="sid")

        server._emitter.transcript_review.assert_not_called()

    def test_skips_when_init(self):
        server, db = _make_server()
        job = Job(id=JobId("j1"), title="T")

        server._replay_review(JobId("j1"), job, to="sid")

        server._emitter.transcript_review.assert_not_called()

    def test_skips_when_review_data_missing(self):
        server, db = _make_server()
        job = Job(id=JobId("j1"), title="T", status=JobStatus.COMPLETE)
        db.get_review.return_value = None

        server._replay_review(JobId("j1"), job, to="sid")

        server._emitter.transcript_review.assert_not_called()
