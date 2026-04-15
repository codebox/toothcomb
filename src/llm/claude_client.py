import logging
from typing import Optional

import anthropic

from config import Config
from domain.llm_usage import LLMResponse, LLMUsage, Citation
from domain.prompt import Prompt
from domain.types import ModelName
from llm.rate_limit_tracker import RateLimitTracker, RateLimitThrottled

log = logging.getLogger(__name__)


class ClaudeClient:
    def __init__(self, config: Config, model: ModelName, max_tokens: int,
                 tools: Optional[list] = None,
                 client: Optional[anthropic.Anthropic] = None,
                 prompt_caching: bool = True,
                 rate_limit_tracker: Optional[RateLimitTracker] = None) -> None:
        if client is None:
            api_key = config.get("llm.anthropic.api_key") or None
            max_retries = config.get("llm.anthropic.max_retries")
            timeout = config.get("llm.anthropic.request_timeout")
            client = anthropic.Anthropic(
                api_key=api_key,
                max_retries=max_retries,
                timeout=timeout,
            )
        self._client = client
        self._model = model
        self._max_tokens = max_tokens
        self._tools = tools
        self._prompt_caching = prompt_caching
        self._rate_limit_tracker = rate_limit_tracker

    def send(self, prompt: Prompt) -> LLMResponse:
        # Check rate limit before making the call
        if self._rate_limit_tracker and self._rate_limit_tracker.is_throttled(self._model):
            wait = self._rate_limit_tracker.seconds_until_ready(self._model)
            raise RateLimitThrottled(f"Model {self._model} is rate-limited for {wait:.0f}s", retry_in_seconds=wait)

        return self._call_api(prompt)

    def _call_api(self, prompt: Prompt) -> LLMResponse:
        log.info("Anthropic request — model=%s", self._model)
        system_block = {"type": "text", "text": prompt.system_prompt}
        if self._prompt_caching:
            system_block["cache_control"] = {"type": "ephemeral"}
        kwargs = dict(
            model=self._model,
            max_tokens=self._max_tokens,
            system=[system_block],
            messages=[{"role": "user", "content": prompt.user_prompt}],
        )
        if self._tools:
            kwargs["tools"] = self._tools

        try:
            response = self._client.messages.create(**kwargs)
        except anthropic.RateLimitError as e:
            log.warning("Rate limited by Anthropic API — model=%s (retries exhausted)", self._model)
            retry_after = self._extract_retry_after(e)
            if self._rate_limit_tracker:
                self._rate_limit_tracker.record_rate_limit(self._model, retry_after)
            wait = self._rate_limit_tracker.seconds_until_ready(self._model) if self._rate_limit_tracker else 30
            raise RateLimitThrottled(f"Rate limited: {e}", retry_in_seconds=wait) from e

        # Clear any existing rate-limit backoff on success
        if self._rate_limit_tracker:
            self._rate_limit_tracker.clear_throttle(self._model)

        # When tools are used, the response contains multiple content blocks.
        # Extract the last text block and any citations.
        result = None
        seen_urls: set[str] = set()
        citations: list[Citation] = []
        for block in response.content:
            if block.type == "text":
                result = block.text
                # Extract citations from text blocks (natural language responses)
                for cite in getattr(block, "citations", None) or []:
                    url = getattr(cite, "url", None)
                    title = getattr(cite, "title", None)
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        citations.append(Citation(url=url, title=title or ""))
        if result is None:
            block_types = [getattr(b, "type", "?") for b in response.content]
            stop_reason = getattr(response, "stop_reason", "?")
            raise ValueError(
                f"No text block in response (stop_reason={stop_reason}, "
                f"block_types={block_types})"
            )

        api_usage = response.usage
        cache_read = getattr(api_usage, "cache_read_input_tokens", 0) or 0
        cache_creation = getattr(api_usage, "cache_creation_input_tokens", 0) or 0
        server_tool_use = getattr(api_usage, "server_tool_use", None)
        web_searches = getattr(server_tool_use, "web_search_requests", 0) if server_tool_use else 0
        log.info("Anthropic response — model=%s input=%d output=%d cache_read=%d cache_creation=%d web_searches=%d citations=%d",
                 self._model, api_usage.input_tokens, api_usage.output_tokens, cache_read, cache_creation, web_searches, len(citations))

        usage = LLMUsage(
            model=self._model,
            input_tokens=api_usage.input_tokens,
            output_tokens=api_usage.output_tokens,
            cache_read_tokens=cache_read,
            cache_creation_tokens=cache_creation,
        )
        return LLMResponse(text=result, usage=usage, citations=tuple(citations))

    @staticmethod
    def _extract_retry_after(e: anthropic.RateLimitError) -> float | None:
        """Try to extract retry-after seconds from the error response headers."""
        response = getattr(e, "response", None)
        if response:
            header = response.headers.get("retry-after")
            if header:
                try:
                    return float(header)
                except ValueError:
                    pass
        return None
