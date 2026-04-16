import logging

from config import Config
from db.database import Database
from domain.analysed_text import Annotation
from domain.fact_check_result import FactCheckResult, Verdict
from domain.llm_response_error import LLMResponseError
from factchecker.fact_checker import FactChecker
from llm.rate_limit_tracker import RateLimitThrottled
from pipeline.update_service import UpdateService
from pipeline.workers.worker import PollingWorker

log = logging.getLogger(__name__)


class FactCheckWorker(PollingWorker):
    def __init__(
        self,
        fact_checker: FactChecker,
        database: Database,
        update_service: UpdateService,
        config: Config,
        num_workers: int = 2,
    ) -> None:
        super().__init__("fact-check", num_workers,
                         poll_interval=config.get("pipeline.poll_interval", 0.2))
        self._fact_checker = fact_checker
        self._database = database
        self._updates = update_service

    def poll(self) -> bool:
        annotation = self._database.claim_fact_check()
        if not annotation:
            return False
        self._process(annotation)
        return True

    def _process(self, annotation: Annotation) -> None:
        try:
            result = self._fact_checker.fact_check(annotation.fact_check_query)
        except RateLimitThrottled as e:
            log.info("[%s] Rate limited during fact check for annotation_id=%s — resetting to pending",
                     annotation.job_id, annotation.id)
            self._database.reset_fact_check_to_pending(annotation.id)
            self._updates.emit_rate_limited(annotation.job_id, e.retry_in_seconds)
            raise
        except LLMResponseError as e:
            log.exception("[%s] Fact check failed for annotation_id=%s", annotation.job_id, annotation.id)
            result = FactCheckResult(verdict=Verdict.FAILED, note=f"Fact check failed: {e.reason}")
        except Exception:
            log.exception("[%s] Fact check failed for annotation_id=%s", annotation.job_id, annotation.id)
            result = FactCheckResult(verdict=Verdict.FAILED, note=f"Fact check failed for annotation {annotation.id}")

        citations = [c.to_dict() for c in result.citations]
        if result.verdict == Verdict.FAILED:
            self._updates.fact_check_failed(annotation.job_id, annotation.id, result.note, usage=result.usage)
        else:
            self._updates.fact_check_completed(annotation.job_id, annotation.id, result.verdict.value, result.note,
                                               citations=citations, usage=result.usage)

        self._updates.check_job_progress(annotation.job_id)
