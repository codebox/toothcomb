from unittest.mock import MagicMock, call

import pytest

from domain.analysed_text import AnalysedText, AnalysedPart, Annotation, AnnotationType
from domain.job import Job
from domain.transcript import Utterance
from domain.types import (
    JobId, UtteranceId, AnnotationId, JobStatus, FactCheckStatus,
)
from web.socket_emitter import SocketEmitter


# ---------- helpers ----------


def _emitter():
    sio = MagicMock()
    return SocketEmitter(sio), sio


def _job(job_id="j1", title="Test Job"):
    return Job(id=JobId(job_id), title=title)


def _utterance(utt_id="u1", speaker="Alice", text="hello"):
    return Utterance(id=UtteranceId(utt_id), speaker=speaker, text=text)


def _analysed_text(utt_id="u1", text="hello", failed=False):
    return AnalysedText(utterance_id=UtteranceId(utt_id), text=text, failed=failed)


# ---------- job_created ----------


class TestJobCreated:

    def test_emits_serialised_job(self):
        emitter, sio = _emitter()
        job = _job()
        emitter.job_created(job, room="lobby")

        sio.emit.assert_called_once_with("job_created", job.to_dict(), room="lobby")

    def test_kwargs_passed_through(self):
        emitter, sio = _emitter()
        emitter.job_created(_job(), to="sid123")

        assert sio.emit.call_args[1] == {"to": "sid123"}


# ---------- job_deleted ----------


class TestJobDeleted:

    def test_emits_job_id(self):
        emitter, sio = _emitter()
        emitter.job_deleted(JobId("j1"), room="lobby")

        sio.emit.assert_called_once_with(
            "job_deleted", {"job_id": "j1"}, room="lobby")


# ---------- job_status ----------


class TestJobStatus:

    def test_converts_enum_to_value(self):
        emitter, sio = _emitter()
        emitter.job_status(JobId("j1"), JobStatus.INGESTING, room="lobby")

        sio.emit.assert_called_once_with("job_status", {
            "job_id": "j1",
            "status": "ingesting",
        }, room="lobby")

    def test_all_statuses(self):
        for status in JobStatus:
            emitter, sio = _emitter()
            emitter.job_status(JobId("j1"), status)

            payload = sio.emit.call_args[0][1]
            assert payload["status"] == status.value


# ---------- transcription ----------


class TestTranscription:

    def test_injects_job_id_into_utterance_dict(self):
        emitter, sio = _emitter()
        utt = _utterance()
        emitter.transcription(JobId("j1"), utt, room="lobby")

        payload = sio.emit.call_args[0][1]
        assert payload["job_id"] == "j1"
        assert payload["utterance_id"] == "u1"
        assert payload["speaker"] == "Alice"
        assert payload["text"] == "hello"

    def test_event_name(self):
        emitter, sio = _emitter()
        emitter.transcription(JobId("j1"), _utterance())

        assert sio.emit.call_args[0][0] == "transcription"


# ---------- analysis ----------


class TestAnalysis:

    def test_injects_job_id_into_analysed_text_dict(self):
        emitter, sio = _emitter()
        at = _analysed_text()
        emitter.analysis(JobId("j1"), at, room="lobby")

        payload = sio.emit.call_args[0][1]
        assert payload["job_id"] == "j1"
        assert payload["utterance_id"] == "u1"
        assert payload["failed"] is False

    def test_event_name(self):
        emitter, sio = _emitter()
        emitter.analysis(JobId("j1"), _analysed_text())

        assert sio.emit.call_args[0][0] == "analysis"


# ---------- analysis_failed ----------


class TestAnalysisFailed:

    def test_emits_failed_analysis(self):
        emitter, sio = _emitter()
        emitter.analysis_failed(JobId("j1"), UtteranceId("u1"), room="lobby")

        payload = sio.emit.call_args[0][1]
        assert payload["job_id"] == "j1"
        assert payload["utterance_id"] == "u1"
        assert payload["failed"] is True

    def test_event_name_is_analysis(self):
        emitter, sio = _emitter()
        emitter.analysis_failed(JobId("j1"), UtteranceId("u1"))

        assert sio.emit.call_args[0][0] == "analysis"

    def test_kwargs_passed_through(self):
        emitter, sio = _emitter()
        emitter.analysis_failed(JobId("j1"), UtteranceId("u1"), to="sid")

        assert sio.emit.call_args[1] == {"to": "sid"}


# ---------- fact_check ----------


class TestFactCheck:

    def test_emits_all_fields(self):
        emitter, sio = _emitter()
        emitter.fact_check(
            JobId("j1"), AnnotationId("a1"),
            verdict="established", note="Confirmed",
            room="lobby",
        )

        sio.emit.assert_called_once_with("fact_check", {
            "annotation_id": "a1",
            "job_id": "j1",
            "verdict": "established",
            "note": "Confirmed",
            "citations": [],
        }, room="lobby")


# ---------- utterances_merged ----------


class TestUtterancesMerged:

    def test_emits_merge_payload(self):
        emitter, sio = _emitter()
        emitter.utterances_merged(
            JobId("j1"),
            merged_ids=[UtteranceId("u1"), UtteranceId("u2")],
            target_id=UtteranceId("u3"),
            room="lobby",
        )

        sio.emit.assert_called_once_with("utterances_merged", {
            "job_id": "j1",
            "merged_ids": ["u1", "u2"],
            "target_id": "u3",
        }, room="lobby")


# ---------- job_stats ----------


class TestJobStats:

    def test_emits_stats_list(self):
        emitter, sio = _emitter()
        stats = [{"model": "m", "input_tokens": 100}]
        emitter.job_stats(JobId("j1"), stats, room="lobby")

        sio.emit.assert_called_once_with("job_stats", {
            "job_id": "j1",
            "stats": stats,
        }, room="lobby")


# ---------- replay_complete ----------


class TestReplayComplete:

    def test_emits_job_id(self):
        emitter, sio = _emitter()
        emitter.replay_complete(JobId("j1"), to="sid")

        sio.emit.assert_called_once_with(
            "replay_complete", {"job_id": "j1"}, to="sid")
