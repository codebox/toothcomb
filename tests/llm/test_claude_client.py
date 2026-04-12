from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

import anthropic
from domain.prompt import Prompt
from domain.types import ModelName
from llm.claude_client import ClaudeClient


# ---------- helpers ----------


class _FakeConfig:
    def get(self, key, default=None):
        return default


@dataclass
class _FakeTextBlock:
    type: str = "text"
    text: str = "response text"


@dataclass
class _FakeToolBlock:
    type: str = "tool_use"
    name: str = "web_search"


@dataclass
class _FakeUsage:
    input_tokens: int = 100
    output_tokens: int = 50
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    server_tool_use: object = None


def _fake_response(content=None, usage=None):
    resp = MagicMock()
    resp.content = content or [_FakeTextBlock()]
    resp.usage = usage or _FakeUsage()
    return resp


def _make_client(tools=None):
    mock_anthropic = MagicMock()
    client = ClaudeClient(
        _FakeConfig(), ModelName("claude-test"), max_tokens=1024,
        tools=tools, client=mock_anthropic,
    )
    return client, mock_anthropic


# ---------- Response parsing ----------


class TestResponseParsing:

    def test_single_text_block(self):
        client, mock_api = _make_client()
        mock_api.messages.create.return_value = _fake_response(
            content=[_FakeTextBlock(text="hello")])

        result = client.send(Prompt("sys", "user"))
        assert result.text == "hello"

    def test_multiple_blocks_returns_last_text(self):
        client, mock_api = _make_client()
        mock_api.messages.create.return_value = _fake_response(
            content=[_FakeTextBlock(text="first"), _FakeToolBlock(), _FakeTextBlock(text="last")])

        result = client.send(Prompt("sys", "user"))
        assert result.text == "last"

    def test_no_text_block_raises(self):
        client, mock_api = _make_client()
        mock_api.messages.create.return_value = _fake_response(
            content=[_FakeToolBlock()])

        with pytest.raises(ValueError, match="No text block"):
            client.send(Prompt("sys", "user"))

    def test_usage_fields_mapped(self):
        client, mock_api = _make_client()
        usage = _FakeUsage(input_tokens=200, output_tokens=80,
                           cache_read_input_tokens=30, cache_creation_input_tokens=10)
        mock_api.messages.create.return_value = _fake_response(usage=usage)

        result = client.send(Prompt("sys", "user"))
        assert result.usage.input_tokens == 200
        assert result.usage.output_tokens == 80
        assert result.usage.cache_read_tokens == 30
        assert result.usage.cache_creation_tokens == 10
        assert result.usage.model == "claude-test"

    def test_usage_missing_cache_fields_default_to_zero(self):
        """Older API responses may not have cache fields."""
        client, mock_api = _make_client()
        usage = MagicMock()
        usage.input_tokens = 100
        usage.output_tokens = 50
        del usage.cache_read_input_tokens
        del usage.cache_creation_input_tokens
        del usage.server_tool_use
        mock_api.messages.create.return_value = _fake_response(usage=usage)

        result = client.send(Prompt("sys", "user"))
        assert result.usage.cache_read_tokens == 0
        assert result.usage.cache_creation_tokens == 0


# ---------- Tools ----------


class TestTools:

    def test_tools_passed_to_api(self):
        tools = [{"name": "web_search", "type": "web_search_20250305"}]
        client, mock_api = _make_client(tools=tools)
        mock_api.messages.create.return_value = _fake_response()

        client.send(Prompt("sys", "user"))

        call_kwargs = mock_api.messages.create.call_args[1]
        assert call_kwargs["tools"] == tools

    def test_no_tools_omitted_from_api(self):
        client, mock_api = _make_client(tools=None)
        mock_api.messages.create.return_value = _fake_response()

        client.send(Prompt("sys", "user"))

        call_kwargs = mock_api.messages.create.call_args[1]
        assert "tools" not in call_kwargs


# ---------- Error handling ----------


class TestErrorHandling:

    def test_rate_limit_error_reraised(self):
        client, mock_api = _make_client()
        mock_api.messages.create.side_effect = anthropic.RateLimitError(
            message="rate limited",
            response=MagicMock(status_code=429, headers={}),
            body={"error": {"message": "rate limited"}},
        )

        with pytest.raises(anthropic.RateLimitError):
            client.send(Prompt("sys", "user"))


# ---------- Prompt formatting ----------


class TestPromptFormatting:

    def test_system_prompt_sent_with_cache_control(self):
        client, mock_api = _make_client()
        mock_api.messages.create.return_value = _fake_response()

        client.send(Prompt("my system prompt", "my user prompt"))

        call_kwargs = mock_api.messages.create.call_args[1]
        system_blocks = call_kwargs["system"]
        assert len(system_blocks) == 1
        assert system_blocks[0]["text"] == "my system prompt"
        assert system_blocks[0]["cache_control"] == {"type": "ephemeral"}

    def test_user_prompt_sent_as_message(self):
        client, mock_api = _make_client()
        mock_api.messages.create.return_value = _fake_response()

        client.send(Prompt("sys", "my user prompt"))

        call_kwargs = mock_api.messages.create.call_args[1]
        assert call_kwargs["messages"] == [{"role": "user", "content": "my user prompt"}]
