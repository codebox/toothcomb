import logging
import threading

from audiosource.audio_source import AudioSource
from audiosource.mp3_audio_source import Mp3AudioSource
from audiosource.streaming_audio_source import StreamingAudioSource
from config import Config
from db.database import Database
from domain.job import Job
from domain.transcript import Utterance
from domain.types import JobId, UtteranceId, JobStatus, SourceType
from pipeline.pipeline import Pipeline
from pipeline.update_service import UpdateService
from textsource.file_text_source import FileTextSource

import uuid

log = logging.getLogger(__name__)


class JobRunner:
    def __init__(self, config: Config, pipeline: Pipeline, database: Database, update_service: UpdateService):
        self._config = config
        self._pipeline = pipeline
        self._database = database
        self._updates = update_service
        self._streaming_sources: dict[JobId, StreamingAudioSource] = {}
        self._audio_sources: dict[JobId, AudioSource] = {}

    def get_streaming_source(self, job_id: JobId) -> StreamingAudioSource | None:
        return self._streaming_sources.get(job_id)

    def start_job(self, job_id: JobId) -> None:
        """Start processing a job that's in 'init' status."""
        job = self._database.get_job(job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")

        self._database.update_job_status(job_id, JobStatus.INGESTING)
        self._database.set_job_started_at(job_id)
        self._run_source(job)

    def abort_job(self, job_id: JobId) -> None:
        """Permanently stop a running job. In-flight LLM calls complete but no new work is issued."""
        source = self._audio_sources.get(job_id)
        if source:
            source.pause()
        self._database.update_job_status(job_id, JobStatus.ABORTED)
        log.info("[%s] Job aborted", job_id)

    def resume_running_jobs(self) -> None:
        """Resume sources for any jobs that were running when the app last stopped."""
        jobs = self._database.list_jobs()
        for job in jobs:
            if job.status == JobStatus.INGESTING:
                source_type_str = job.config_data.get("source", {}).get("type")
                if source_type_str in (SourceType.MP3.value, SourceType.STREAMING.value):
                    existing = self._database.get_utterances(job.id)
                    if existing:
                        log.info("[%s] Streaming source cannot be resumed — advancing to analysing with %d utterances",
                                 job.id, len(existing))
                    else:
                        log.warning("[%s] Streaming source cannot be resumed and no utterances exist", job.id)
                    self._updates.flush_remaining_buffer(job.id)
                    self._database.advance_to_analysing(job.id)
                    self._emit_status(job.id, JobStatus.ANALYSING)
                    self._updates.check_job_progress(job.id)
                else:
                    log.info("[%s] Resuming job (restarting source)", job.id)
                    self._run_source(job)
            elif job.status == JobStatus.ANALYSING:
                log.info("[%s] Resuming analysing job", job.id)
                self._updates.check_job_progress(job.id)
            elif job.status == JobStatus.REVIEWING:
                log.info("[%s] Resuming reviewing job", job.id)
                self._updates.check_job_progress(job.id)

    def _emit_status(self, job_id: JobId, status: JobStatus) -> None:
        self._updates._emitter.job_status(job_id, status, room="lobby")

    def _run_source(self, job: Job) -> None:
        source_data = job.config_data.get("source", {})
        source_type = SourceType(source_data.get("type"))

        existing_count = len(self._database.get_utterances(job.id))
        source = self._build_source(job.id, source_type, source_data, skip=existing_count)
        self._audio_sources[job.id] = source

        updates = self._updates
        database = self._database
        job_id = job.id
        needs_drain = source_type in (SourceType.MP3, SourceType.STREAMING)
        transcription_worker = self._pipeline.transcription_worker if needs_drain else None

        def run_source():
            source.start()
            if transcription_worker:
                log.info("[%s] Waiting for transcription queue to drain", job_id)
                transcription_worker.wait_for_drain()
            if not database.get_job(job_id):
                log.info("[%s] Job deleted during source processing", job_id)
                return
            updates.flush_remaining_buffer(job_id)
            if database.advance_to_analysing(job_id):
                log.info("[%s] Source finished, advancing to analysing", job_id)
                self._emit_status(job_id, JobStatus.ANALYSING)
            updates.check_job_progress(job_id)

        threading.Thread(
            target=run_source,
            name=f"source-{job_id}",
            daemon=True,
        ).start()

    def _build_source(self, job_id: JobId, source_type: SourceType, source_data: dict, skip: int = 0):
        database = self._database

        match source_type:
            case SourceType.FILE:
                path = source_data["path"]
                delay = source_data.get("delay_seconds", 0)
                source = FileTextSource(self._config, path, delay_seconds=delay)
                skipped = 0
                updates = self._updates

                def on_text(text):
                    nonlocal skipped
                    if skipped < skip:
                        skipped += 1
                        return
                    utterance = Utterance(
                        id=UtteranceId(str(uuid.uuid4())),
                        speaker="",
                        text=text,
                        seq=database.next_utterance_seq(job_id),
                        job_id=job_id,
                    )
                    updates.utterance_transcribed(utterance)

                if skip > 0:
                    log.info("[%s] Resuming file source, skipping %d existing utterances", job_id, skip)
                source.on_text(on_text)
                return source

            case SourceType.MP3:
                source = Mp3AudioSource(self._config, source_data["path"])
                transcription_worker = self._pipeline.transcription_worker

                def on_mp3_audio(audio_data, chunk_offset_seconds, chunk_end_seconds):
                    transcription_worker.submit(job_id, audio_data, chunk_offset_seconds, chunk_end_seconds)

                source.on_audio(on_mp3_audio)
                return source

            case SourceType.STREAMING:
                source = StreamingAudioSource(self._config)
                transcription_worker = self._pipeline.transcription_worker

                def on_stream_audio(audio_data, chunk_offset_seconds, chunk_end_seconds):
                    transcription_worker.submit(job_id, audio_data, chunk_offset_seconds, chunk_end_seconds)

                source.on_audio(on_stream_audio)
                self._streaming_sources[job_id] = source
                return source

            case _:
                raise ValueError(f"Unknown source type: {source_type}")
