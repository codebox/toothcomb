from typing import Protocol

from domain.llm_usage import LLMResponse
from domain.prompt import Prompt


class LLMClient(Protocol):
    """Sends a single prompt to an LLM and returns its text response."""

    def send(self, prompt: Prompt) -> LLMResponse: ...
