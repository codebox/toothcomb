import logging

from config import Config
from db.database import Database
from domain.job import Job
from domain.job_config import JobConfig, PromptContext
from domain.transcript_review import TranscriptReview
from llm.rate_limit_tracker import RateLimitThrottled
from pipeline.update_service import UpdateService
from pipeline.workers.worker import PollingWorker
from reviewer.transcript_reviewer import TranscriptReviewer

log = logging.getLogger(__name__)


class TranscriptReviewWorker(PollingWorker):
    def __init__(
        self,
        reviewer: TranscriptReviewer,
        database: Database,
        update_service: UpdateService,
        config: Config,
        num_workers: int = 1,
    ) -> None:
        super().__init__("transcript-review", num_workers,
                         poll_interval=config.get("pipeline.poll_interval", 0.2))
        self._reviewer = reviewer
        self._database = database
        self._updates = update_service

    def poll(self) -> bool:
        job = self._database.claim_review()
        if not job:
            return False
        self._process(job)
        return True

    def _process(self, job: Job) -> None:
        try:
            context_data = job.config_data.get("context", {})
            job_config = JobConfig(
                id=job.id,
                title=job.title,
                context=PromptContext(**context_data),
                is_transcribed=job.config_data.get("is_transcribed", False),
            )

            analyses = self._database.get_all_analysed_texts(job.id)

            try:
                review = self._reviewer.review(job_config, analyses)
            except RateLimitThrottled as e:
                log.info("[%s] Rate limited during transcript review — resetting review claim", job.id)
                self._database.reset_review_claim(job.id)
                self._updates.emit_rate_limited(job.id, e.retry_in_seconds)
                raise
            except Exception:
                log.exception("[%s] Transcript review failed", job.id)
                review = TranscriptReview(job_id=job.id, failed=True)

            if review.failed:
                self._updates.review_failed(job.id)
            else:
                self._updates.review_completed(job.id, review)
        except RateLimitThrottled:
            raise
        except Exception:
            log.exception("[%s] Transcript review worker error", job.id)
            self._updates.review_failed(job.id)
