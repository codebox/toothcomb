import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from db.sqlite_database import SQLiteDatabase
from domain.job import Job
from domain.transcription_result import TranscriptionResult, TranscriptionSegment
from domain.types import JobId, JobStatus
from pipeline.workers.transcription_worker import TranscriptionWorker


# ---------- helpers ----------


@pytest.fixture
def db():
    return SQLiteDatabase(":memory:")


@pytest.fixture
def updates():
    return MagicMock()


def _make_transcriber(text="Hello world", speaker="Alice", segments=None, side_effect=None):
    transcriber = MagicMock()
    if side_effect:
        transcriber.transcribe.side_effect = side_effect
    else:
        segs = segments or ()
        transcriber.transcribe.return_value = TranscriptionResult(
            speaker=speaker, text=text, segments=segs)
    return transcriber


def _make_worker(transcriber, db, updates):
    return TranscriptionWorker(
        transcriber=transcriber, database=db,
        update_service=updates, num_workers=1,
    )


def _create_running_job(db, job_id="job-1", realtime=False, set_started_at=False):
    config = f'{{"realtime": {str(realtime).lower()}}}'
    job = Job(id=JobId(job_id), title="T", config=config)
    db.create_job(job)
    db.update_job_status(JobId(job_id), JobStatus.INGESTING)
    if set_started_at:
        db.set_job_started_at(JobId(job_id))
    return job


def _create_running_job_with_started_at(db, job_id="job-1", started_at_str=None):
    """Create a running job with a specific started_at value for delay testing."""
    config = '{"realtime": true}'
    job = Job(id=JobId(job_id), title="T", config=config)
    db.create_job(job)
    db.update_job_status(JobId(job_id), JobStatus.INGESTING)
    if started_at_str:
        conn = db._get_conn()
        conn.execute("UPDATE jobs SET started_at = ? WHERE id = ?", (started_at_str, job_id))
        conn.commit()


# ---------- _process ----------


class TestProcess:

    def test_transcribes_and_emits_utterance(self, db, updates):
        _create_running_job(db)
        transcriber = _make_transcriber(text="Hello", speaker="Bob")
        worker = _make_worker(transcriber, db, updates)

        worker._process(JobId("job-1"), b"audio", 0.0, 2.0, seq=1)

        transcriber.transcribe.assert_called_once_with(b"audio")
        updates.utterance_transcribed.assert_called_once()
        utt = updates.utterance_transcribed.call_args[0][0]
        assert utt.text == "Hello"
        assert utt.speaker == "Bob"
        assert utt.job_id == "job-1"
        assert utt.seq == 1

    def test_seq_from_argument_used(self, db, updates):
        _create_running_job(db)
        transcriber = _make_transcriber()
        worker = _make_worker(transcriber, db, updates)

        worker._process(JobId("job-1"), b"audio", 0.0, 1.0, seq=42)

        utt = updates.utterance_transcribed.call_args[0][0]
        assert utt.seq == 42

    def test_offset_from_chunk_start(self, db, updates):
        _create_running_job(db)
        transcriber = _make_transcriber(segments=())
        worker = _make_worker(transcriber, db, updates)

        worker._process(JobId("job-1"), b"audio", 10.0, 12.0, seq=1)

        utt = updates.utterance_transcribed.call_args[0][0]
        assert utt.offset_seconds == 10.0

    def test_offset_includes_first_segment_start(self, db, updates):
        _create_running_job(db)
        seg = TranscriptionSegment(text="hi", start=0.5, end=1.0)
        transcriber = _make_transcriber(segments=(seg,))
        worker = _make_worker(transcriber, db, updates)

        worker._process(JobId("job-1"), b"audio", 10.0, 12.0, seq=1)

        utt = updates.utterance_transcribed.call_args[0][0]
        assert utt.offset_seconds == 10.5

    def test_no_transcriber_does_nothing(self, db, updates):
        _create_running_job(db)
        worker = TranscriptionWorker(
            transcriber=None, database=db,
            update_service=updates, num_workers=1,
        )

        worker._process(JobId("job-1"), b"audio", 0.0, 1.0, seq=1)

        updates.utterance_transcribed.assert_not_called()

    def test_transcriber_exception_swallowed(self, db, updates):
        _create_running_job(db)
        transcriber = _make_transcriber(side_effect=RuntimeError("whisper crashed"))
        worker = _make_worker(transcriber, db, updates)

        # Should not raise
        worker._process(JobId("job-1"), b"audio", 0.0, 1.0, seq=1)

        updates.utterance_transcribed.assert_not_called()

    def test_unique_ids_per_utterance(self, db, updates):
        """Each transcription should produce an utterance with a unique ID."""
        _create_running_job(db)
        transcriber = _make_transcriber()
        worker = _make_worker(transcriber, db, updates)

        worker._process(JobId("job-1"), b"a1", 0.0, 1.0, seq=1)
        worker._process(JobId("job-1"), b"a2", 1.0, 2.0, seq=2)

        calls = updates.utterance_transcribed.call_args_list
        id1 = calls[0][0][0].id
        id2 = calls[1][0][0].id
        assert id1 != id2


# ---------- _compute_delay ----------


class TestComputeDelay:

    def test_no_delay_when_not_realtime(self, db):
        _create_running_job(db, realtime=False)
        worker = _make_worker(MagicMock(), db, MagicMock())

        assert worker._compute_delay(JobId("job-1"), 10.0) == 0

    def test_no_delay_when_no_started_at(self, db):
        _create_running_job(db, realtime=True, set_started_at=False)
        worker = _make_worker(MagicMock(), db, MagicMock())

        assert worker._compute_delay(JobId("job-1"), 10.0) == 0

    def test_no_delay_when_job_missing(self, db):
        worker = _make_worker(MagicMock(), db, MagicMock())
        assert worker._compute_delay(JobId("nope"), 10.0) == 0

    def test_positive_delay_when_ahead_of_realtime(self, db):
        # Set started_at to 5 seconds ago — offset 60s means we're ~55s ahead
        started = (datetime.now() - timedelta(seconds=5)).strftime("%Y-%m-%d %H:%M:%S")
        _create_running_job_with_started_at(db, started_at_str=started)
        worker = _make_worker(MagicMock(), db, MagicMock())

        delay = worker._compute_delay(JobId("job-1"), 60.0)
        assert delay > 50  # should be ~55s

    def test_zero_delay_when_behind_realtime(self, db):
        # Set started_at to 100 seconds ago — offset 5s means we're well behind
        started = (datetime.now() - timedelta(seconds=100)).strftime("%Y-%m-%d %H:%M:%S")
        _create_running_job_with_started_at(db, started_at_str=started)
        worker = _make_worker(MagicMock(), db, MagicMock())

        delay = worker._compute_delay(JobId("job-1"), 5.0)
        assert delay == 0.0

    def test_delay_never_negative(self, db):
        started = (datetime.now() - timedelta(seconds=1000)).strftime("%Y-%m-%d %H:%M:%S")
        _create_running_job_with_started_at(db, started_at_str=started)
        worker = _make_worker(MagicMock(), db, MagicMock())

        assert worker._compute_delay(JobId("job-1"), 0.0) == 0.0


# ---------- _emit_utterance ----------


class TestEmitUtterance:

    def test_no_delay_calls_update_service_directly(self, db, updates):
        _create_running_job(db, realtime=False)
        transcriber = _make_transcriber()
        worker = _make_worker(transcriber, db, updates)

        worker._process(JobId("job-1"), b"audio", 0.0, 1.0, seq=1)

        updates.utterance_transcribed.assert_called_once()

    def test_positive_delay_uses_timer(self, db, updates):
        # Started just now — offset 60s means ~60s delay
        started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _create_running_job_with_started_at(db, started_at_str=started)
        transcriber = _make_transcriber()
        worker = _make_worker(transcriber, db, updates)

        with patch("pipeline.workers.transcription_worker.threading.Timer") as mock_timer:
            mock_timer.return_value = MagicMock()
            worker._process(JobId("job-1"), b"audio", 0.0, 60.0, seq=1)

            mock_timer.assert_called_once()
            delay_arg = mock_timer.call_args[0][0]
            assert delay_arg > 50  # should be ~60s
            mock_timer.return_value.start.assert_called_once()

        # Should NOT have called update service directly
        updates.utterance_transcribed.assert_not_called()


# ---------- submit / queue ----------


class TestSubmit:

    def test_submit_enqueues(self, db, updates):
        _create_running_job(db)
        worker = _make_worker(MagicMock(), db, updates)
        worker.submit(JobId("job-1"), b"audio", 0.0, 1.0)
        assert worker._queue.qsize() == 1

    def test_submit_assigns_seq(self, db, updates):
        _create_running_job(db)
        worker = _make_worker(MagicMock(), db, updates)
        worker.submit(JobId("job-1"), b"audio", 0.0, 1.0)
        worker.submit(JobId("job-1"), b"audio", 1.0, 2.0)
        items = []
        while not worker._queue.empty():
            items.append(worker._queue.get_nowait())
        assert items[0][4] == 1  # first seq
        assert items[1][4] == 2  # second seq
