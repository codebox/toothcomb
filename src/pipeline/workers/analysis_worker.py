import logging

from config import Config
from db.database import Database
from domain.analysed_text import AnalysedText
from domain.job import Job
from domain.job_config import JobConfig, PromptContext
from domain.transcript import Utterance, UtteranceWithContext
from domain.types import JobStatus, UtteranceId
from llm.rate_limit_tracker import RateLimitThrottled
from pipeline.update_service import UpdateService
from pipeline.workers.worker import PollingWorker
from textanalyser.text_analyser import TextAnalyser

log = logging.getLogger(__name__)


class AnalysisWorker(PollingWorker):
    def __init__(
        self,
        text_analyser: TextAnalyser,
        database: Database,
        update_service: UpdateService,
        config: Config,
        num_workers: int = 1,
    ) -> None:
        super().__init__("analysis", num_workers,
                         poll_interval=config.get("pipeline.poll_interval", 0.2))
        self._text_analyser = text_analyser
        self._database = database
        self._updates = update_service
        self._context_count = config.get("llm.previous_utterance_count")

    def poll(self) -> bool:
        # Look across running and analysing jobs for work
        jobs = self._database.list_jobs()
        for job in jobs:
            if job.status not in (JobStatus.INGESTING, JobStatus.ANALYSING):
                continue
            utterance = self._database.claim_utterance_for_analysis(job.id)
            if utterance:
                self._process(job, utterance)
                return True
        return False

    def _process(self, job: Job, utterance: Utterance) -> None:
        utterance_id = utterance.id
        seq = utterance.seq

        try:
            # Build context from DB
            context_rows = self._database.get_utterance_context(job.id, seq, self._context_count)
            previous = tuple(
                Utterance(id=r.id, speaker=r.speaker, text=r.text)
                for r in context_rows[:-1]
            )

            # Prepend remainder from the previous utterance
            remainder = self._database.get_previous_remainder(job.id, seq)
            text = remainder + " " + utterance.text if remainder else utterance.text

            # Peek at following text to help detect incomplete trailing sentences
            following_text = self._database.get_following_text(job.id, seq)

            target = Utterance(id=utterance_id, speaker=utterance.speaker, text=text)
            utterance_with_context = UtteranceWithContext(utterance=target, previous=previous,
                                                          following_text=following_text)

            # Build job config from Job
            context_data = job.config_data.get("context", {})
            job_config = JobConfig(
                id=job.id,
                title=job.title,
                context=PromptContext(**context_data),
                is_transcribed=job.config_data.get("is_transcribed", False),
            )

            try:
                analysed_text = self._text_analyser.analyse(utterance_with_context, job_config)
            except RateLimitThrottled as e:
                log.info("[%s] Rate limited during analysis for seq=%d — resetting to pending", job.id, seq)
                self._database.reset_utterance_to_pending(utterance_id)
                self._updates.emit_rate_limited(job.id, e.retry_in_seconds)
                raise
            except Exception:
                log.exception("[%s] Analysis failed for seq=%d", job.id, seq)
                analysed_text = AnalysedText(utterance_id=utterance_id, text=text, failed=True)

            self._updates.utterance_analysed(job.id, utterance_id, analysed_text)
        except RateLimitThrottled:
            raise
        except Exception:
            log.exception("[%s] Analysis worker error for seq=%d", job.id, seq)
            self._database.fail_utterance_analysis(utterance_id)

        self._updates.check_job_progress(job.id)
