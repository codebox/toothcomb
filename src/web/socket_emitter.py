from __future__ import annotations

from domain.analysed_text import AnalysedText
from domain.job import Job
from domain.transcript import Utterance
from domain.types import JobId, UtteranceId, AnnotationId, JobStatus
from flask_socketio import SocketIO


class SocketEmitter:
    """Encapsulates all WebSocket event shapes in one place.

    Domain objects serialise themselves via to_dict(). This class
    adds routing fields (job_id) and emits via Socket.IO.
    Callers pass either ``room=`` (broadcast) or ``to=`` (single client).
    """

    def __init__(self, socketio: SocketIO) -> None:
        self._sio = socketio

    def job_created(self, job: Job, **kwargs) -> None:
        self._sio.emit("job_created", job.to_dict(), **kwargs)

    def job_deleted(self, job_id: JobId, **kwargs) -> None:
        self._sio.emit("job_deleted", {"job_id": job_id}, **kwargs)

    def job_status(self, job_id: JobId, status: JobStatus, **kwargs) -> None:
        self._sio.emit("job_status", {
            "job_id": job_id,
            "status": status.value,
        }, **kwargs)

    def transcription(self, job_id: JobId, utterance: Utterance, **kwargs) -> None:
        data = utterance.to_dict()
        data["job_id"] = job_id
        self._sio.emit("transcription", data, **kwargs)

    def analysis(self, job_id: JobId, analysed_text: AnalysedText, **kwargs) -> None:
        data = analysed_text.to_dict()
        data["job_id"] = job_id
        self._sio.emit("analysis", data, **kwargs)

    def analysis_failed(self, job_id: JobId, utterance_id: UtteranceId, **kwargs) -> None:
        failed = AnalysedText(utterance_id=utterance_id, text="", failed=True)
        self.analysis(job_id, failed, **kwargs)

    def fact_check(
        self, job_id: JobId, annotation_id: AnnotationId, verdict: str, note: str,
        citations: list[dict] | None = None, **kwargs,
    ) -> None:
        self._sio.emit("fact_check", {
            "annotation_id": annotation_id,
            "job_id": job_id,
            "verdict": verdict,
            "note": note,
            "citations": citations or [],
        }, **kwargs)

    def fact_check_reset(self, job_id: JobId, annotation_id: AnnotationId, **kwargs) -> None:
        self._sio.emit("fact_check_reset", {
            "job_id": job_id,
            "annotation_id": annotation_id,
        }, **kwargs)

    def utterances_merged(self, job_id: JobId, merged_ids: list[UtteranceId], target_id: UtteranceId, **kwargs) -> None:
        self._sio.emit("utterances_merged", {
            "job_id": job_id,
            "merged_ids": merged_ids,
            "target_id": target_id,
        }, **kwargs)

    def rate_limited(self, job_id: JobId, retry_in_seconds: float, **kwargs) -> None:
        self._sio.emit("rate_limited", {
            "job_id": job_id,
            "retry_in_seconds": round(retry_in_seconds),
        }, **kwargs)

    def job_stats(self, job_id: JobId, stats: list[dict], **kwargs) -> None:
        self._sio.emit("job_stats", {
            "job_id": job_id,
            "stats": stats,
        }, **kwargs)

    def transcript_review(self, job_id: JobId, review_data: dict, **kwargs) -> None:
        data = dict(review_data)
        data["job_id"] = job_id
        self._sio.emit("transcript_review", data, **kwargs)

    def replay_complete(self, job_id: JobId, **kwargs) -> None:
        self._sio.emit("replay_complete", {"job_id": job_id}, **kwargs)
