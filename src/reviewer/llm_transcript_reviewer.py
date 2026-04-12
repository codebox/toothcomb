import logging

from config import Config
from domain.analysed_text import AnalysedText, AnnotationType
from domain.job_config import JobConfig
from domain.llm_response_error import LLMResponseError
from domain.transcript_review import TranscriptReview, ReviewFinding
from domain.types import JobId
from llm.claude_client import ClaudeClient
from llm.json_utils import parse_llm_json
from llm.prompt_builder import PromptBuilder
from llm.retrying_llm_caller import RetryingLLMCaller
from domain.llm_usage import LLMResponse
from domain.prompt import Prompt
from reviewer.transcript_reviewer import TranscriptReviewer

log = logging.getLogger(__name__)


class LLMTranscriptReviewer(TranscriptReviewer, RetryingLLMCaller):
    def __init__(self, config: Config, prompt_builder: PromptBuilder,
                 claude_client: ClaudeClient):
        TranscriptReviewer.__init__(self, config)
        RetryingLLMCaller.__init__(self, max_retries=config.get("pipeline.review_parse_retries", 2))
        self._prompt_builder = prompt_builder
        self._claude_client = claude_client

    def send_prompt_to_llm(self, prompt: Prompt) -> LLMResponse:
        return self._claude_client.send(prompt)

    def review(self, job_config: JobConfig, analyses: list[AnalysedText]) -> TranscriptReview:
        prompt = self._prompt_builder.build_transcript_review_prompt(job_config, analyses)
        response = self._call_with_retries(
            prompt, lambda text: self._parse_llm_review_response(text, job_config.id))
        response.result.usage = response.usage
        return response.result

    @staticmethod
    def _parse_llm_review_response(llm_response: str, job_id: JobId) -> TranscriptReview:
        data = parse_llm_json(llm_response, ["findings"])

        if not isinstance(data["findings"], list):
            raise LLMResponseError("'findings' must be a list", llm_response)

        try:
            findings = tuple(
                ReviewFinding(
                    type=AnnotationType(f["type"]),
                    technique=f["technique"],
                    summary=f["summary"],
                    refs=tuple(str(r) for r in f.get("refs", [])),
                    excerpt=f.get("excerpt"),
                )
                for f in data["findings"]
            )
        except KeyError as e:
            raise LLMResponseError(f"Review response missing required field: {e}", llm_response) from e
        except ValueError as e:
            raise LLMResponseError(f"Invalid value in review response: {e}", llm_response) from e

        return TranscriptReview(job_id=job_id, findings=findings)
