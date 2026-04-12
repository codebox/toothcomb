import json
import logging
import uuid

from db.database import Database
from domain.analysed_text import AnalysedText
from domain.llm_usage import LLMUsage
from domain.transcript import Utterance
from domain.transcript_review import TranscriptReview
from domain.types import JobId, UtteranceId, AnnotationId, AnalysisResultId, JobStatus
from web.socket_emitter import SocketEmitter

log = logging.getLogger(__name__)


class UpdateService:
    """Persists work results to the database and notifies connected clients via Socket.IO."""

    def __init__(self, database: Database, emitter: SocketEmitter,
                 buffer_words: int = 50) -> None:
        self._db = database
        self._emitter = emitter
        self._buffer_words = buffer_words

    def utterance_transcribed(self, utterance: Utterance) -> None:
        if not self._db.get_job(utterance.job_id):
            log.info("[%s] Job deleted, dropping transcription", utterance.job_id)
            return
        self._db.create_utterance(utterance)
        log.info("[%s] transcription: %s seq=%d speaker=%s offset=%.1fs",
                 utterance.job_id, utterance.id, utterance.seq,
                 utterance.speaker, utterance.offset_seconds)
        self._emitter.transcription(utterance.job_id, utterance, room=utterance.job_id)
        self._check_buffer(utterance.job_id)

    def flush_remaining_buffer(self, job_id: JobId) -> None:
        """Force-flush any remaining buffered utterances (e.g. when source finishes)."""
        if not self._db.get_job(job_id):
            log.info("[%s] Job deleted, skipping buffer flush", job_id)
            return
        result = self._db.force_flush_analysis_buffer(job_id)
        if result and result["merged_ids"]:
            self._emitter.utterances_merged(job_id, result["merged_ids"], result["target_id"], room=job_id)

    def _check_buffer(self, job_id: JobId) -> None:
        result = self._db.flush_analysis_buffer(job_id, self._buffer_words)
        if result and result["merged_ids"]:
            self._emitter.utterances_merged(job_id, result["merged_ids"], result["target_id"], room=job_id)

    def utterance_analysed(
        self, job_id: JobId, utterance_id: UtteranceId, analysed_text: AnalysedText
    ) -> None:
        if not self._db.get_job(job_id):
            log.info("[%s] Job deleted, dropping analysis result", job_id)
            return

        self._record_usage(job_id, analysed_text.usage)

        if analysed_text.failed:
            self._db.fail_utterance_analysis(utterance_id)
            log.info("[%s] analysis failed: %s", job_id, utterance_id)
            self._emitter.analysis_failed(job_id, utterance_id, room=job_id)
            return

        self._db.complete_utterance_analysis(utterance_id, analysed_text.remainder)

        pre_verdicted = []
        for seq, part in enumerate(analysed_text.analysed_parts, start=1):
            result_id = AnalysisResultId(str(uuid.uuid4()))
            self._db.create_analysis_result(
                result_id=result_id,
                utterance_id=utterance_id,
                seq=seq,
                corrected_text=part.corrected_text,
            )
            for annotation in part.annotations:
                self._db.create_annotation(annotation, result_id)
                if annotation.fact_check_verdict:
                    pre_verdicted.append(annotation)

        annotation_count = sum(len(p.annotations) for p in analysed_text.analysed_parts)
        log.info("[%s] analysis: %s parts=%d annotations=%d",
                 job_id, utterance_id, len(analysed_text.analysed_parts), annotation_count)

        self._emitter.analysis(job_id, analysed_text, room=job_id)

        for annotation in pre_verdicted:
            self._emitter.fact_check(
                job_id, annotation.id,
                annotation.fact_check_verdict, annotation.fact_check_note or "",
                room=job_id,
            )

    def fact_check_completed(
        self, job_id: JobId, annotation_id: AnnotationId, verdict: str, note: str,
        citations: list[dict] | None = None, usage: LLMUsage | None = None,
    ) -> None:
        if not self._db.get_job(job_id):
            log.info("[%s] Job deleted, dropping fact check result", job_id)
            return
        self._record_usage(job_id, usage)
        self._db.complete_fact_check(annotation_id, verdict, note, citations=citations)
        log.info("[%s] fact_check: %s verdict=%s", job_id, annotation_id, verdict)
        self._emitter.fact_check(job_id, annotation_id, verdict, note, citations=citations, room=job_id)

    def fact_check_failed(
        self, job_id: JobId, annotation_id: AnnotationId, note: str,
        usage: LLMUsage | None = None,
    ) -> None:
        if not self._db.get_job(job_id):
            log.info("[%s] Job deleted, dropping fact check result", job_id)
            return
        self._record_usage(job_id, usage)
        self._db.fail_fact_check(annotation_id, note)
        log.info("[%s] fact_check failed: %s", job_id, annotation_id)
        self._emitter.fact_check(job_id, annotation_id, "FAILED", note, room=job_id)

    def check_job_progress(self, job_id: JobId) -> None:
        """Check if a job can advance to the next pipeline stage."""
        job = self._db.get_job(job_id)
        if not job:
            return

        if job.status == JobStatus.ANALYSING:
            if self._db.try_advance_to_reviewing(job_id):
                log.info("[%s] Job advancing to reviewing", job_id)
                self._emitter.job_status(job_id, JobStatus.REVIEWING, room="lobby")
        elif job.status == JobStatus.REVIEWING:
            if self._db.try_advance_to_complete(job_id):
                log.info("[%s] Job complete", job_id)
                self._emitter.job_status(job_id, JobStatus.COMPLETE, room="lobby")

    def review_completed(self, job_id: JobId, review: TranscriptReview) -> None:
        if not self._db.get_job(job_id):
            log.info("[%s] Job deleted, dropping review result", job_id)
            return
        self._record_usage(job_id, review.usage)
        findings_json = json.dumps(review.to_dict())
        self._db.complete_review(job_id, findings_json)
        log.info("[%s] Transcript review complete: %d findings", job_id, len(review.findings))
        self._emitter.transcript_review(job_id, review.to_dict(), room=job_id)

        # Advance to complete now that review is done
        if self._db.try_advance_to_complete(job_id):
            log.info("[%s] Job complete", job_id)
            self._emitter.job_status(job_id, JobStatus.COMPLETE, room="lobby")

    def review_failed(self, job_id: JobId) -> None:
        if not self._db.get_job(job_id):
            log.info("[%s] Job deleted, dropping review failure", job_id)
            return
        log.info("[%s] Transcript review failed — will retry on next restart", job_id)

    def _record_usage(self, job_id: JobId, usage: LLMUsage | None) -> None:
        """Record a single LLMUsage if present, then emit updated stats."""
        if not usage:
            return
        self._db.record_llm_usage(job_id, usage)
        self._emit_stats(job_id)

    def emit_rate_limited(self, job_id: JobId, retry_in_seconds: float) -> None:
        self._emitter.rate_limited(job_id, retry_in_seconds, room=job_id)

    def _emit_stats(self, job_id: JobId) -> None:
        stats = self._db.get_job_stats(job_id)
        self._emitter.job_stats(job_id, stats, room=job_id)
