import asyncio
import gc
import os
from unittest.mock import MagicMock

import anyio

import pytest

from claude_agent_sdk import AssistantMessage, ClaudeSDKError, ResultMessage, SystemMessage, TextBlock
from domain.llm_refusal_error import LLMRefusalError
from domain.prompt import Prompt
from domain.types import ModelName
from domain.claude_code_error import ClaudeCodeError
from llm.claude_code_client import ClaudeCodeClient
from llm.rate_limit_tracker import RateLimitThrottled


# ---------- helpers ----------


class _FakeConfig:
    def __init__(self, values=None):
        self._values = values or {}

    def get(self, key, default=None):
        return self._values.get(key, default)


def _init(api_key_source="none"):
    return SystemMessage(subtype="init", data={"apiKeySource": api_key_source})


def _result(text='{"ok": true}', is_error=False, subtype="success", stop_reason="end_turn",
            api_error_status=None, usage=None):
    return ResultMessage(
        subtype=subtype, duration_ms=10, duration_api_ms=10, is_error=is_error, num_turns=1,
        session_id="s", stop_reason=stop_reason, result=text, api_error_status=api_error_status,
        usage=usage if usage is not None else {"input_tokens": 12, "output_tokens": 34,
                                                "cache_read_input_tokens": 5,
                                                "cache_creation_input_tokens": 6},
    )


def _assistant(error=None):
    return AssistantMessage(content=[TextBlock(text="x")], model="m", error=error)


class _FakeQuery:
    """Stands in for claude_agent_sdk.query: yields canned messages, records options."""

    def __init__(self, messages, raise_after=None, delay=0.0):
        self._messages = messages
        self._raise_after = raise_after
        self._delay = delay
        self.calls = []

    def __call__(self, *, prompt, options):
        self.calls.append((prompt, options))
        return self._gen()

    async def _gen(self):
        if self._delay:
            await asyncio.sleep(self._delay)
        for m in self._messages:
            yield m
        if self._raise_after:
            raise self._raise_after


def _make_client(messages=None, *, query=None, tracker=None, **kwargs):
    query = query or _FakeQuery(messages or [_init(), _result()])
    client = ClaudeCodeClient(_FakeConfig(), ModelName("claude-test"), rate_limit_tracker=tracker,
                              query_fn=query, **kwargs)
    return client, query


# ---------- Successful calls ----------


class TestSuccessfulCall:

    def test_returns_result_text(self):
        client, _ = _make_client([_init(), _result(text="hello")])
        assert client.send(Prompt("sys", "user")).text == "hello"

    def test_maps_usage(self):
        client, _ = _make_client()
        usage = client.send(Prompt("sys", "user")).usage
        assert (usage.model, usage.input_tokens, usage.output_tokens,
                usage.cache_read_tokens, usage.cache_creation_tokens) == ("claude-test", 12, 34, 5, 6)

    def test_missing_usage_is_zero(self):
        client, _ = _make_client([_init(), _result(usage={})])
        assert client.send(Prompt("sys", "user")).usage.total_tokens == 0

    def test_sends_user_prompt_and_system_prompt_with_suffix(self):
        client, query = _make_client(system_prompt_suffix="EXTRA")
        client.send(Prompt("sys", "user text"))
        prompt, options = query.calls[0]
        assert prompt == "user text"
        assert options.system_prompt == "sys\n\nEXTRA"

    def test_no_suffix_leaves_system_prompt_unchanged(self):
        client, query = _make_client()
        client.send(Prompt("sys", "user text"))
        assert query.calls[0][1].system_prompt == "sys"

    def test_no_citations(self):
        client, _ = _make_client()
        assert client.send(Prompt("sys", "user")).citations == ()


# ---------- Options passed to Claude Code ----------


class TestOptions:

    def _options(self, **kwargs):
        client, query = _make_client(**kwargs)
        client.send(Prompt("sys", "user"))
        return query.calls[0][1]

    def test_no_tools_by_default(self):
        options = self._options()
        assert options.tools == []
        assert options.allowed_tools == []
        assert options.max_turns == 1

    def test_tools_are_enabled_and_pre_approved(self):
        options = self._options(tools=["WebSearch"], max_turns=8)
        assert options.tools == ["WebSearch"]
        assert options.allowed_tools == ["WebSearch"]
        assert options.max_turns == 8

    def test_isolated_from_user_settings_and_mcp(self):
        options = self._options()
        assert options.setting_sources == []
        assert options.strict_mcp_config is True

    def test_api_credentials_blanked_so_plan_is_used(self):
        env = self._options().env
        assert env["ANTHROPIC_API_KEY"] == ""
        assert env["ANTHROPIC_AUTH_TOKEN"] == ""
        assert env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"

    def test_sessions_not_saved_to_disk(self):
        assert "no-session-persistence" in self._options().extra_args

    def test_model_passed_through(self):
        assert self._options().model == "claude-test"

    def test_empty_working_directory_removed_when_client_discarded(self):
        client, query = _make_client()
        client.send(Prompt("sys", "user"))
        cwd = query.calls[0][1].cwd
        assert os.path.isdir(cwd) and os.listdir(cwd) == []
        del client
        gc.collect()
        assert not os.path.exists(cwd)


# ---------- Errors ----------


class TestErrors:

    def test_empty_user_prompt_rejected_without_calling_claude(self):
        client, query = _make_client()
        with pytest.raises(ValueError):
            client.send(Prompt("sys", "  "))
        assert query.calls == []

    def test_error_result_raises(self):
        msgs = [_init(), _result(text="boom", is_error=True, subtype="error_during_execution")]
        client, _ = _make_client(query=_FakeQuery(msgs, raise_after=ClaudeSDKError("exit 1")))
        with pytest.raises(ClaudeCodeError, match="boom"):
            client.send(Prompt("sys", "user"))

    def test_max_turns_reason_names_the_limit(self):
        msgs = [_init(), _result(text=None, is_error=True, subtype="error_max_turns")]
        client, _ = _make_client(query=_FakeQuery(msgs, raise_after=ClaudeSDKError("max turns")), max_turns=8)
        with pytest.raises(ClaudeCodeError) as exc:
            client.send(Prompt("sys", "user"))
        assert exc.value.reason == "Claude Code used all 8 turns without reaching an answer"

    def test_authentication_failure_explains_setup(self):
        msgs = [_init(), _assistant(error="authentication_failed"),
                _result(text="Failed to authenticate", is_error=True, api_error_status=401)]
        client, _ = _make_client(query=_FakeQuery(msgs, raise_after=ClaudeSDKError("exit 1")))
        with pytest.raises(ClaudeCodeError, match="setup-token"):
            client.send(Prompt("sys", "user"))

    def test_sdk_failure_without_result_raises(self):
        client, _ = _make_client(query=_FakeQuery([], raise_after=ClaudeSDKError("CLI not found")))
        with pytest.raises(ClaudeCodeError, match="CLI not found"):
            client.send(Prompt("sys", "user"))

    def test_no_result_message_raises(self):
        client, _ = _make_client([_init()])
        with pytest.raises(ClaudeCodeError):
            client.send(Prompt("sys", "user"))

    def test_refusal_raises_refusal_error(self):
        client, _ = _make_client([_init(), _result(text="", stop_reason="refusal")])
        with pytest.raises(LLMRefusalError):
            client.send(Prompt("sys", "user"))

    def test_timeout_raises(self):
        client, _ = _make_client(query=_FakeQuery([_init(), _result()], delay=1.0), timeout=0.05)
        with pytest.raises(ClaudeCodeError, match="timed out"):
            client.send(Prompt("sys", "user"))

    def test_timeout_lets_shielded_sdk_shutdown_finish(self):
        """The SDK shuts the claude process down inside an anyio shielded scope, which only
        holds off cancellation that comes from an anyio cancel scope. A raw asyncio timeout
        landing during that shutdown would cut it short and orphan the process."""
        shutdown_finished = []

        async def slow_shutdown_query(*, prompt, options):
            yield _init()
            with anyio.CancelScope(shield=True):
                await anyio.sleep(0.2)
                shutdown_finished.append(True)
            await anyio.sleep(10)
            yield _result()

        client = ClaudeCodeClient(_FakeConfig(), ModelName("claude-test"), query_fn=slow_shutdown_query,
                                  timeout=0.05)
        with pytest.raises(ClaudeCodeError, match="timed out"):
            client.send(Prompt("sys", "user"))
        assert shutdown_finished == [True]


# ---------- Rate limiting ----------


class TestRateLimiting:

    def test_throttled_model_not_called(self):
        tracker = MagicMock()
        tracker.is_throttled.return_value = True
        tracker.seconds_until_ready.return_value = 42
        client, query = _make_client(tracker=tracker)
        with pytest.raises(RateLimitThrottled) as exc:
            client.send(Prompt("sys", "user"))
        assert exc.value.retry_in_seconds == 42
        assert query.calls == []

    @pytest.mark.parametrize("msgs", [
        [_init(), _assistant(error="rate_limit"), _result(text="limit", is_error=True)],
        [_init(), _result(text="limit", is_error=True, api_error_status=429)],
    ])
    def test_rate_limit_recorded_and_raised(self, msgs):
        tracker = MagicMock()
        tracker.is_throttled.return_value = False
        tracker.seconds_until_ready.return_value = 30
        client, _ = _make_client(query=_FakeQuery(msgs, raise_after=ClaudeSDKError("exit 1")), tracker=tracker)
        with pytest.raises(RateLimitThrottled) as exc:
            client.send(Prompt("sys", "user"))
        tracker.record_rate_limit.assert_called_once_with("claude-test", None)
        assert exc.value.retry_in_seconds == 30

    def test_rate_limit_without_text_has_readable_message(self):
        msgs = [_init(), _result(text=None, is_error=True, api_error_status=429)]
        client, _ = _make_client(query=_FakeQuery(msgs, raise_after=ClaudeSDKError("exit 1")))
        with pytest.raises(RateLimitThrottled) as exc:
            client.send(Prompt("sys", "user"))
        assert "None" not in str(exc.value)

    def test_success_clears_throttle(self):
        tracker = MagicMock()
        tracker.is_throttled.return_value = False
        client, _ = _make_client(tracker=tracker)
        client.send(Prompt("sys", "user"))
        tracker.clear_throttle.assert_called_once_with("claude-test")
