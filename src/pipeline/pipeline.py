import logging

from config import Config
from db.database import Database
from factchecker.llm_fact_checker import LLMFactChecker
from llm.claude_client import ClaudeClient
from llm.rate_limit_tracker import RateLimitTracker
from pipeline.update_service import UpdateService
from pipeline.workers.transcription_worker import TranscriptionWorker
from pipeline.workers.analysis_worker import AnalysisWorker
from pipeline.workers.fact_check_worker import FactCheckWorker
from pipeline.workers.transcript_review_worker import TranscriptReviewWorker
from reviewer.llm_transcript_reviewer import LLMTranscriptReviewer
from textanalyser.llm_text_analyser import LLMTextAnalyser
from llm.prompt_builder import PromptBuilder
from transcriber.transcriber import Transcriber
from web.socket_emitter import SocketEmitter

log = logging.getLogger(__name__)


class Pipeline:
    def __init__(
        self,
        config: Config,
        database: Database,
        emitter: SocketEmitter,
    ) -> None:
        buffer_words = config.get("pipeline.analysis_buffer_words", 50)
        self._update_service = UpdateService(database, emitter, buffer_words)
        update_service = self._update_service

        rate_tracker = RateLimitTracker(database)
        prompt_builder = PromptBuilder()
        text_analyser = self._build_text_analyser(config, prompt_builder, rate_tracker)
        fact_checker = self._build_fact_checker(config, prompt_builder, rate_tracker)
        reviewer = self._build_transcript_reviewer(config, prompt_builder, rate_tracker)
        transcriber = self._build_transcriber(config)

        self._transcription_worker = TranscriptionWorker(
            transcriber=transcriber,
            database=database,
            update_service=update_service,
            num_workers=config.get("pipeline.transcription_workers"),
        )
        self._analysis_worker = AnalysisWorker(
            text_analyser=text_analyser,
            database=database,
            update_service=update_service,
            config=config,
            num_workers=config.get("pipeline.analysis_workers"),
        )
        self._fact_check_worker = FactCheckWorker(
            fact_checker=fact_checker,
            database=database,
            update_service=update_service,
            config=config,
            num_workers=config.get("pipeline.fact_check_workers"),
        )
        self._review_worker = TranscriptReviewWorker(
            reviewer=reviewer,
            database=database,
            update_service=update_service,
            config=config,
            num_workers=config.get("pipeline.review_workers", 1),
        )

    @property
    def transcription_worker(self) -> TranscriptionWorker:
        return self._transcription_worker

    @property
    def update_service(self) -> UpdateService:
        return self._update_service

    def start(self) -> None:
        log.info("Starting pipeline")
        self._transcription_worker.start()
        self._analysis_worker.start()
        self._fact_check_worker.start()
        self._review_worker.start()

    def stop(self) -> None:
        log.info("Stopping pipeline")
        self._transcription_worker.stop()
        self._analysis_worker.stop()
        self._fact_check_worker.stop()
        self._review_worker.stop()
        log.info("Pipeline stopped")

    @staticmethod
    def _build_claude_client(config: Config, model_config_key: str, max_tokens: int,
                              tools: list | None = None,
                              prompt_caching: bool = True,
                              rate_limit_tracker: RateLimitTracker | None = None) -> ClaudeClient:
        model = config.get(model_config_key)
        return ClaudeClient(config, model, max_tokens, tools=tools,
                            prompt_caching=prompt_caching, rate_limit_tracker=rate_limit_tracker)

    @classmethod
    def _build_text_analyser(cls, config: Config, prompt_builder: PromptBuilder,
                              rate_tracker: RateLimitTracker | None = None) -> LLMTextAnalyser:
        max_tokens = config.get("llm.anthropic.analysis_max_tokens", 8192)
        client = cls._build_claude_client(config, "llm.anthropic.analysis_model", max_tokens=max_tokens,
                                           rate_limit_tracker=rate_tracker)
        return LLMTextAnalyser(config, prompt_builder, client)

    @classmethod
    def _build_fact_checker(cls, config: Config, prompt_builder: PromptBuilder,
                             rate_tracker: RateLimitTracker | None = None) -> LLMFactChecker:
        web_search_tool = config.get("llm.anthropic.web_search_tool")
        max_searches = config.get("llm.anthropic.web_search_max_uses", 3)
        tools = [
            {"type": web_search_tool, "name": "web_search", "max_uses": max_searches},
        ]
        max_tokens = config.get("llm.anthropic.fact_check_max_tokens", 1024)
        client = cls._build_claude_client(config, "llm.anthropic.fact_check_model", max_tokens=max_tokens,
                                           tools=tools, prompt_caching=False,
                                           rate_limit_tracker=rate_tracker)
        return LLMFactChecker(config, prompt_builder, client)

    @classmethod
    def _build_transcript_reviewer(cls, config: Config, prompt_builder: PromptBuilder,
                                    rate_tracker: RateLimitTracker | None = None) -> LLMTranscriptReviewer:
        model_key = "llm.anthropic.review_model"
        if not config.get(model_key):
            model_key = "llm.anthropic.analysis_model"
        max_tokens = config.get("llm.anthropic.review_max_tokens", 4096)
        client = cls._build_claude_client(config, model_key, max_tokens=max_tokens,
                                           rate_limit_tracker=rate_tracker)
        return LLMTranscriptReviewer(config, prompt_builder, client)

    @staticmethod
    def _build_transcriber(config: Config) -> Transcriber | None:
        backend = config.get("whisper.backend") or "mlx"
        try:
            if backend == "faster-whisper":
                from transcriber.faster_whisper_transcriber import FasterWhisperTranscriber
                return FasterWhisperTranscriber(config)
            else:
                from transcriber.local_whisper_transcriber import LocalWhisperTranscriber
                return LocalWhisperTranscriber(config)
        except Exception:
            log.warning("Could not initialise transcriber (backend=%s) — audio sources will not work", backend)
            return None
