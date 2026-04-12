import logging

from config import Config
from llm.claude_client import ClaudeClient
from llm.json_utils import parse_llm_json
from llm.retrying_llm_caller import RetryingLLMCaller
from domain.fact_check_result import FactCheckResult, Verdict
from domain.llm_response_error import LLMResponseError
from domain.llm_usage import LLMResponse, Citation
from domain.prompt import Prompt
from factchecker.fact_checker import FactChecker
from llm.prompt_builder import PromptBuilder

log = logging.getLogger(__name__)


class LLMFactChecker(FactChecker, RetryingLLMCaller):
    def __init__(self, config: Config, prompt_builder: PromptBuilder,
                 claude_client: ClaudeClient):
        FactChecker.__init__(self, config)
        RetryingLLMCaller.__init__(self, max_retries=config.get("pipeline.fact_check_parse_retries", 2))
        self._prompt_builder = prompt_builder
        self._claude_client = claude_client

    def send_prompt_to_llm(self, prompt: Prompt) -> LLMResponse:
        return self._claude_client.send(prompt)

    def fact_check(self, query: str) -> FactCheckResult:
        prompt = self._prompt_builder.build_fact_checker_prompt(query)
        response = self._call_with_retries(prompt, lambda text: self._parse_llm_fact_check_response(text, query))
        response.result.usage = response.usage
        return response.result

    @staticmethod
    def _parse_llm_fact_check_response(llm_response: str, query: str) -> FactCheckResult:
        data = parse_llm_json(llm_response, ["verdict"], query=query)

        try:
            sources = data.get("sources", [])
            citations = tuple(
                Citation(url=s["url"], title=s.get("title", ""))
                for s in sources
                if isinstance(s, dict) and s.get("url")
            )
            return FactCheckResult(
                verdict=Verdict(data["verdict"]),
                note=data["note"],
                citations=citations,
            )
        except KeyError as e:
            raise LLMResponseError(f"Fact check response missing required field: {e}", llm_response, query) from e
        except ValueError as e:
            raise LLMResponseError(f"Invalid value in fact check response: {e}", llm_response, query) from e
