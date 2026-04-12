import logging
from typing import Callable, TypeVar

from config import Config
from domain.llm_response_error import LLMResponseError
from domain.llm_usage import LLMResponse, LLMUsage, ParsedLLMResponse
from domain.prompt import Prompt

log = logging.getLogger(__name__)

T = TypeVar("T")


class RetryingLLMCaller:
    """Mixin that provides retry logic for LLM calls.

    Subclasses must implement send_prompt_to_llm().
    """

    def __init__(self, max_retries: int = 2) -> None:
        self._max_retries = max_retries

    def send_prompt_to_llm(self, prompt: Prompt) -> LLMResponse:
        raise NotImplementedError(f"{type(self).__name__} must implement send_prompt_to_llm()")

    def _call_with_retries(self, prompt: Prompt, parse_fn: Callable[[str], T]) -> ParsedLLMResponse[T]:
        """Call the LLM and parse the response, retrying on LLMResponseError."""
        combined_usage: LLMUsage | None = None
        last_error = None
        for attempt in range(1 + self._max_retries):
            llm_response = self.send_prompt_to_llm(prompt)
            if llm_response.usage:
                combined_usage = llm_response.usage if combined_usage is None else combined_usage + llm_response.usage
            try:
                result = parse_fn(llm_response.text)
                return ParsedLLMResponse(result=result, usage=combined_usage, citations=llm_response.citations)
            except LLMResponseError as e:
                last_error = e
                if attempt < self._max_retries:
                    log.warning("LLM response parse failed (attempt %d/%d), retrying: %s",
                                attempt + 1, 1 + self._max_retries, e)

        raise last_error
