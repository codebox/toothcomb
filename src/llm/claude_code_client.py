import asyncio
import logging
import tempfile

import anyio
from typing import Callable, Optional

from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ClaudeSDKError, ResultMessage,
                              SystemMessage, query)

from config import Config
from domain.claude_code_error import ClaudeCodeError
from domain.llm_refusal_error import LLMRefusalError
from domain.llm_usage import LLMResponse, LLMUsage
from domain.prompt import Prompt
from domain.types import ModelName
from llm.rate_limit_tracker import RateLimitTracker, RateLimitThrottled

log = logging.getLogger(__name__)

# Environment for the Claude Code process. Claude Code prefers ANTHROPIC_API_KEY and
# ANTHROPIC_AUTH_TOKEN over plan credentials, so blank them or calls would be silently
# billed to an API account.
_CHILD_ENV = {
    "ANTHROPIC_API_KEY": "",
    "ANTHROPIC_AUTH_TOKEN": "",
    "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
}

_SETUP_HINT = ("Claude Code is not logged in to a Claude plan. Run `claude setup-token` and set "
               "CLAUDE_CODE_OAUTH_TOKEN, or run `claude` once and log in.")


class ClaudeCodeClient:
    """Runs prompts through Claude Code (the Claude Agent SDK) so they are billed to the
    user's Claude Pro/Max plan rather than an API key.

    Each call starts a short-lived Claude Code process with no user settings, no MCP
    servers and only the tools named in `tools`.
    """

    def __init__(self, config: Config, model: ModelName,
                 tools: Optional[list[str]] = None,
                 max_turns: int = 1,
                 system_prompt_suffix: str = "",
                 rate_limit_tracker: Optional[RateLimitTracker] = None,
                 timeout: Optional[float] = None,
                 query_fn: Optional[Callable] = None) -> None:
        self._model = model
        self._tools = list(tools or [])
        self._max_turns = max_turns
        self._system_prompt_suffix = system_prompt_suffix
        self._rate_limit_tracker = rate_limit_tracker
        self._timeout = timeout or config.get("llm.claude_code.request_timeout", 300)
        self._query = query_fn or query
        # An empty working directory, so Claude Code finds no project files or CLAUDE.md.
        # Removed when the client is garbage collected.
        self._cwd = tempfile.TemporaryDirectory(prefix="toothcomb-claude-code-")

    def send(self, prompt: Prompt) -> LLMResponse:
        if self._rate_limit_tracker and self._rate_limit_tracker.is_throttled(self._model):
            wait = self._rate_limit_tracker.seconds_until_ready(self._model)
            raise RateLimitThrottled(f"Model {self._model} is rate-limited for {wait:.0f}s", retry_in_seconds=wait)

        # Claude Code hangs without output if given an empty prompt
        if not prompt.user_prompt or not prompt.user_prompt.strip():
            raise ValueError("Cannot send an empty user prompt to Claude Code")

        try:
            return asyncio.run(self._call_claude_code(prompt))
        except TimeoutError as e:
            raise ClaudeCodeError(f"Claude Code call timed out after {self._timeout}s - model={self._model}") from e

    async def _call_claude_code(self, prompt: Prompt) -> LLMResponse:
        # An anyio timeout rather than asyncio.wait_for: the SDK shuts the claude process
        # down inside an anyio shielded scope, which a raw asyncio cancellation would cut
        # short and leave the process running.
        with anyio.fail_after(self._timeout):
            return await self._run_query(prompt)

    async def _run_query(self, prompt: Prompt) -> LLMResponse:
        log.info("Claude Code request - model=%s tools=%s", self._model, self._tools or "none")
        system_prompt = prompt.system_prompt
        if self._system_prompt_suffix:
            system_prompt += "\n\n" + self._system_prompt_suffix
        options = ClaudeAgentOptions(
            system_prompt=system_prompt,
            tools=list(self._tools),
            allowed_tools=list(self._tools),
            setting_sources=[],
            strict_mcp_config=True,
            max_turns=self._max_turns,
            model=self._model,
            cwd=self._cwd.name,
            env=dict(_CHILD_ENV),
            extra_args={"no-session-persistence": None},
        )

        result: Optional[ResultMessage] = None
        error_category: Optional[str] = None
        try:
            async for message in self._query(prompt=prompt.user_prompt, options=options):
                if isinstance(message, SystemMessage) and message.subtype == "init":
                    source = message.data.get("apiKeySource")
                    if source not in (None, "none"):
                        log.warning("Claude Code is using %s rather than plan credentials", source)
                elif isinstance(message, AssistantMessage) and message.error:
                    error_category = message.error
                elif isinstance(message, ResultMessage):
                    result = message
        except ClaudeSDKError as e:
            # A failed run raises after yielding its error result, which is handled below
            if result is None:
                raise ClaudeCodeError(f"Claude Code failed: {e}") from e

        return self._to_response(result, error_category)

    def _to_response(self, result: Optional[ResultMessage], error_category: Optional[str]) -> LLMResponse:
        if result is None:
            raise ClaudeCodeError(f"Claude Code returned no result - model={self._model}")

        if error_category == "rate_limit" or result.api_error_status == 429:
            log.warning("Rate limited by Claude plan - model=%s", self._model)
            wait = 30
            if self._rate_limit_tracker:
                self._rate_limit_tracker.record_rate_limit(self._model, None)
                wait = self._rate_limit_tracker.seconds_until_ready(self._model)
            raise RateLimitThrottled(f"Rate limited: {result.result or 'usage limit reached'}",
                                     retry_in_seconds=wait)

        if error_category == "authentication_failed" or result.api_error_status == 401:
            raise ClaudeCodeError(f"{_SETUP_HINT} ({result.result})")

        if result.stop_reason == "refusal":
            raise LLMRefusalError(self._model)

        if result.subtype == "error_max_turns":
            raise ClaudeCodeError(f"Claude Code used all {self._max_turns} turns without reaching an answer")

        if result.is_error or not result.result:
            detail = result.result or "; ".join(result.errors or []) or "no output"
            raise ClaudeCodeError(f"Claude Code error ({result.subtype}): {detail}")

        if self._rate_limit_tracker:
            self._rate_limit_tracker.clear_throttle(self._model)

        raw = result.usage or {}
        usage = LLMUsage(
            model=self._model,
            input_tokens=raw.get("input_tokens", 0),
            output_tokens=raw.get("output_tokens", 0),
            cache_read_tokens=raw.get("cache_read_input_tokens", 0),
            cache_creation_tokens=raw.get("cache_creation_input_tokens", 0),
        )
        log.info("Claude Code response - model=%s input=%d output=%d cache_read=%d turns=%d duration_ms=%d",
                 self._model, usage.input_tokens, usage.output_tokens, usage.cache_read_tokens,
                 result.num_turns, result.duration_ms)
        return LLMResponse(text=result.result, usage=usage)
