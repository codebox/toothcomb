from abc import ABC, abstractmethod
from typing import Optional

from domain.analysed_text import Annotation, AnalysedPart, AnalysedText
from domain.job import Job
from domain.llm_usage import LLMUsage
from domain.transcript import Utterance
from domain.types import JobId, UtteranceId, AnnotationId, AnalysisResultId, JobStatus


class Database(ABC):

    # -- Jobs --

    @abstractmethod
    def create_job(self, job: Job) -> None:
        """Insert a new job in 'init' status."""

    @abstractmethod
    def update_job_config(self, job_id: JobId, config_json: str) -> None:
        """Update a job's config JSON."""

    @abstractmethod
    def update_job_status(self, job_id: JobId, status: JobStatus) -> None:
        """Update job status."""

    @abstractmethod
    def set_job_started_at(self, job_id: JobId) -> None:
        """Record when the job started running."""

    @abstractmethod
    def advance_to_analysing(self, job_id: JobId) -> bool:
        """Atomically move a job from 'ingesting' to 'analysing' (source finished).
        Returns True if the transition happened."""

    @abstractmethod
    def try_advance_to_reviewing(self, job_id: JobId) -> bool:
        """Atomically move a job from 'analysing' to 'reviewing' if all analysis
        and fact checks are complete. Returns True if the transition happened."""

    @abstractmethod
    def start_early_review(self, job_id: JobId) -> bool:
        """Move a ingesting/analysing job directly to 'reviewing', skipping
        pending analysis and fact checks. In-flight (processing) fact checks
        are allowed to complete. Returns True if the transition happened."""

    @abstractmethod
    def try_advance_to_complete(self, job_id: JobId) -> bool:
        """Atomically move a job from 'reviewing' to 'complete' if the review
        is done and no processing fact checks remain. Returns True if the
        transition happened."""

    @abstractmethod
    def get_job(self, job_id: JobId) -> Optional[Job]:
        """Return a job, or None."""

    @abstractmethod
    def list_jobs(self) -> list[Job]:
        """Return all jobs, most recent first."""

    @abstractmethod
    def delete_job(self, job_id: JobId) -> bool:
        """Delete a job and all associated data. Returns True if the job existed."""

    # -- Utterances --

    @abstractmethod
    def create_utterance(self, utterance: Utterance) -> None:
        """Insert a new utterance with analysis_status='pending'."""

    @abstractmethod
    def next_utterance_seq(self, job_id: JobId) -> int:
        """Return the next sequence number for a job's utterances."""

    @abstractmethod
    def claim_utterance_for_analysis(self, job_id: JobId) -> Optional[Utterance]:
        """Find and claim the next utterance ready for analysis.
        Returns the Utterance or None if nothing is ready.
        An utterance is ready when all preceding utterances are complete/failed."""

    @abstractmethod
    def complete_utterance_analysis(self, utterance_id: UtteranceId, remainder: str) -> None:
        """Mark an utterance's analysis as complete and store remainder."""

    @abstractmethod
    def fail_utterance_analysis(self, utterance_id: UtteranceId) -> None:
        """Mark an utterance's analysis as failed."""

    @abstractmethod
    def get_utterance(self, utterance_id: UtteranceId) -> Optional[Utterance]:
        """Return a single utterance by ID."""

    @abstractmethod
    def get_utterances(self, job_id: JobId) -> list[Utterance]:
        """Return all utterances for a job, ordered by seq."""

    @abstractmethod
    def get_utterance_context(self, job_id: JobId, seq: int, context_count: int) -> list[Utterance]:
        """Return the utterance at seq plus up to context_count preceding utterances."""

    @abstractmethod
    def get_previous_remainder(self, job_id: JobId, seq: int) -> str:
        """Return the analysis_remainder from the most recent completed utterance before seq."""

    @abstractmethod
    def get_following_text(self, job_id: JobId, seq: int) -> str:
        """Return concatenated text from utterances after seq (any status). Best-effort lookahead."""

    @abstractmethod
    def flush_analysis_buffer(self, job_id: JobId, min_words: int) -> dict | None:
        """Flush buffered utterances if total word count >= min_words.
        Combines text into the last buffered utterance (marked 'pending'),
        deletes earlier ones.
        Returns {merged_ids: [...], target_id: str, combined_text: str} or None."""

    @abstractmethod
    def force_flush_analysis_buffer(self, job_id: JobId) -> dict | None:
        """Flush all buffered utterances regardless of word count.
        Same return format as flush_analysis_buffer."""

    # -- Analysis Results & Annotations --

    @abstractmethod
    def create_analysis_result(
        self, result_id: AnalysisResultId, utterance_id: UtteranceId, seq: int, corrected_text: str
    ) -> None:
        """Insert an analysis result (one analysed part)."""

    @abstractmethod
    def create_annotation(self, annotation: Annotation, analysis_result_id: AnalysisResultId) -> None:
        """Insert an annotation linked to an analysis result."""

    @abstractmethod
    def get_analysed_parts(self, utterance_id: UtteranceId) -> list[AnalysedPart]:
        """Return all analysis results for an utterance with their annotations loaded."""

    @abstractmethod
    def get_annotations(self, analysis_result_id: AnalysisResultId) -> list[Annotation]:
        """Return all annotations for an analysis result."""

    # -- Fact Checks --

    @abstractmethod
    def claim_fact_check(self) -> Optional[Annotation]:
        """Find and claim an annotation needing fact-checking.
        Only claims for jobs in ingesting/analysing/reviewing status.
        Returns the Annotation (with job_id populated) or None."""

    @abstractmethod
    def complete_fact_check(
        self, annotation_id: AnnotationId, verdict: str, note: str
    ) -> None:
        """Store the fact-check result on an annotation."""

    @abstractmethod
    def fail_fact_check(self, annotation_id: AnnotationId, note: str) -> None:
        """Mark a fact-check as failed."""

    @abstractmethod
    def reset_annotation_fact_check(self, annotation_id: AnnotationId) -> bool:
        """Reset an annotation's fact-check to pending, clearing any previous
        verdict, note and citations. Returns True if the annotation exists and
        was reset."""

    @abstractmethod
    def get_annotation(self, annotation_id: AnnotationId) -> Optional[Annotation]:
        """Return a single annotation by ID."""

    # -- Job Stats --

    @abstractmethod
    def record_llm_usage(self, job_id: JobId, usage: LLMUsage) -> None:
        """Accumulate token usage for a job+model pair."""

    @abstractmethod
    def get_job_stats(self, job_id: JobId) -> list[dict]:
        """Return accumulated stats per model for a job.
        Each dict: {model, input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens, request_count}."""

    # -- Transcript Review --

    @abstractmethod
    def claim_review(self) -> Optional['Job']:
        """Atomically find a job with status='reviewing' that has no processing
        fact checks remaining, and mark it as review-processing.
        Returns the Job or None."""

    @abstractmethod
    def complete_review(self, job_id: JobId, findings_json: str) -> None:
        """Store review findings."""

    @abstractmethod
    def get_review(self, job_id: JobId) -> dict | None:
        """Return parsed findings JSON, or None if no review exists."""

    @abstractmethod
    def get_all_analysed_texts(self, job_id: JobId) -> list[AnalysedText]:
        """Gather all utterances and their analysed parts into AnalysedText objects."""

    # -- Rate Limits --

    @abstractmethod
    def get_rate_limit(self, model: str) -> dict | None:
        """Return {retry_after: float, backoff_level: int} or None."""

    @abstractmethod
    def set_rate_limit(self, model: str, retry_after: float, backoff_level: int) -> None:
        """Record a rate-limit backoff for a model."""

    @abstractmethod
    def clear_rate_limit(self, model: str) -> None:
        """Clear rate-limit state for a model after a successful call."""

    # -- Work Item Reset --

    @abstractmethod
    def reset_utterance_to_pending(self, utterance_id: 'UtteranceId') -> None:
        """Reset an utterance from 'processing' back to 'pending' for retry."""

    @abstractmethod
    def reset_fact_check_to_pending(self, annotation_id: 'AnnotationId') -> None:
        """Reset a fact-check from 'processing' back to 'pending' for retry."""

    @abstractmethod
    def reset_review_claim(self, job_id: 'JobId') -> None:
        """Reset a review claim so it can be re-claimed."""

    # -- Recovery --

    @abstractmethod
    def recover_incomplete_work(self) -> None:
        """Reset any 'processing' items back to 'pending' after a restart."""
