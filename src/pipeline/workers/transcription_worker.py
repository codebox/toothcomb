import logging
import queue
import threading
import time
import uuid
from datetime import datetime

from db.database import Database
from domain.transcript import Utterance
from domain.types import JobId, UtteranceId
from pipeline.update_service import UpdateService
from transcriber.transcriber import Transcriber

log = logging.getLogger(__name__)

_SENTINEL = object()


class TranscriptionWorker:
    """Consumes audio chunks from an in-memory queue, transcribes them,
    and writes results to the database via the update service.

    Audio data is transient and can't be stored in the DB, so this worker
    keeps a simple queue. All other workers poll the database instead.
    """

    def __init__(
        self,
        transcriber: Transcriber | None,
        database: Database,
        update_service: UpdateService,
        num_workers: int = 1,
    ) -> None:
        self._transcriber = transcriber
        self._database = database
        self._updates = update_service
        self._num_workers = num_workers
        self._queue: queue.Queue = queue.Queue()
        self._running = False
        self._threads: list[threading.Thread] = []
        self._seq_counters: dict[JobId, int] = {}
        self._pending_counts: dict[JobId, int] = {}
        self._pending_sems: dict[JobId, threading.Semaphore] = {}
        self._pending_lock = threading.Lock()

    def submit(self, job_id: JobId, audio_data: bytes, chunk_offset_seconds: float = 0.0,
               chunk_end_seconds: float = 0.0) -> None:
        """Submit audio data for transcription.

        Seq is assigned here (on the caller's thread) rather than during
        transcription so that ordering is preserved even with multiple workers.
        """
        seq = self._next_seq(job_id)
        self._queue.put((job_id, audio_data, chunk_offset_seconds, chunk_end_seconds, seq))

    def _next_seq(self, job_id: JobId) -> int:
        """Return the next sequence number for the given job.

        Uses an in-memory counter seeded from the DB on first call,
        so that seq values are monotonically increasing even before
        utterances are written back to the database.
        """
        if job_id not in self._seq_counters:
            self._seq_counters[job_id] = self._database.next_utterance_seq(job_id)
        else:
            self._seq_counters[job_id] += 1
        return self._seq_counters[job_id]

    def wait_for_drain(self, job_id: JobId) -> None:
        """Block until all currently queued items have been processed
        and all delayed (realtime-paced) emissions for this job have completed.

        The pending counter and semaphore are per-job so that concurrent jobs
        don't satisfy each other's drains - otherwise job A could advance past
        ingesting while one of its own Timer-scheduled emissions is still
        outstanding, leaving the late utterance stranded in 'buffered' state.
        """
        done = threading.Event()
        self._queue.put(("__drain__", done))
        done.wait()
        with self._pending_lock:
            remaining = self._pending_counts.get(job_id, 0)
            sem = self._pending_sems.get(job_id)
        if not sem:
            return
        for _ in range(remaining):
            sem.acquire()

    def start(self) -> None:
        self._running = True
        for i in range(self._num_workers):
            thread = threading.Thread(
                target=self._run,
                name=f"transcription-{i}",
                daemon=True,
            )
            self._threads.append(thread)
            thread.start()
        log.info("Started %d transcription worker(s)", self._num_workers)

    def stop(self) -> None:
        self._running = False
        self._queue.put(_SENTINEL)
        for thread in self._threads:
            thread.join()
        self._threads.clear()
        log.info("Stopped transcription workers")

    def _run(self) -> None:
        while self._running:
            try:
                item = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if item is _SENTINEL:
                self._queue.put(_SENTINEL)
                break
            if item[0] == "__drain__":
                item[1].set()
                continue
            job_id, audio_data, chunk_offset, chunk_end, seq = item
            self._process(job_id, audio_data, chunk_offset, chunk_end, seq)

    def _process(self, job_id: JobId, audio_data: bytes, chunk_offset_seconds: float,
                 chunk_end_seconds: float, seq: int) -> None:
        try:
            if self._transcriber is None:
                log.error("[%s] No transcriber configured", job_id)
                return

            result = self._transcriber.transcribe(audio_data)
            log.info("[%s] Transcribed: %s", job_id, result.text)

            # Compute offset: chunk start + first segment's start within the chunk
            offset = chunk_offset_seconds
            if result.segments:
                offset += result.segments[0].start

            utterance = Utterance(
                id=UtteranceId(str(uuid.uuid4())),
                speaker=result.speaker,
                text=result.text,
                seq=seq,
                job_id=job_id,
                offset_seconds=offset,
            )
            self._emit_utterance(job_id, utterance, chunk_end_seconds)
        except Exception:
            log.exception("[%s] Transcription failed", job_id)

    def _emit_utterance(self, job_id: JobId, utterance: Utterance, offset_seconds: float) -> None:
        """Write the utterance to the DB and notify clients, delaying if realtime pacing is enabled."""
        delay = self._compute_delay(job_id, offset_seconds)
        if delay > 0:
            log.info("[%s] Realtime pacing: emitting in %.1fs (offset %.1fs)", job_id, delay, offset_seconds)
            with self._pending_lock:
                if job_id not in self._pending_sems:
                    self._pending_sems[job_id] = threading.Semaphore(0)
                    self._pending_counts[job_id] = 0
                self._pending_counts[job_id] += 1
            timer = threading.Timer(delay, self._delayed_emit, args=(job_id, utterance))
            timer.daemon = True
            timer.start()
        else:
            self._updates.utterance_transcribed(utterance)

    def _delayed_emit(self, job_id: JobId, utterance: Utterance) -> None:
        """Emit a delayed utterance and signal that it has completed."""
        try:
            self._updates.utterance_transcribed(utterance)
        finally:
            with self._pending_lock:
                self._pending_counts[job_id] -= 1
                sem = self._pending_sems[job_id]
            sem.release()

    def _compute_delay(self, job_id: JobId, offset_seconds: float) -> float:
        """Return seconds to wait before emitting, or 0 if no delay needed."""
        job = self._database.get_job(job_id)
        if not job or not job.realtime or not job.started_at:
            return 0
        started = datetime.strptime(job.started_at, "%Y-%m-%d %H:%M:%S")
        target = started.timestamp() + offset_seconds
        return max(0.0, target - time.time())
