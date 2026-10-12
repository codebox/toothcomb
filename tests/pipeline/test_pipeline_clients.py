from llm.claude_client import ClaudeClient
from llm.claude_code_client import ClaudeCodeClient
from llm.prompt_builder import PromptBuilder
from pipeline.pipeline import Pipeline


class _FakeConfig:
    def __init__(self, values=None):
        self._values = {
            "llm.anthropic.api_key": "sk-test",
            "llm.anthropic.analysis_model": "claude-analysis",
            "llm.anthropic.fact_check_model": "claude-sonnet",
            "llm.anthropic.review_model": "claude-review",
            "llm.anthropic.web_search_tool": "web_search_20260209",
            "llm.anthropic.max_retries": 3,
            "llm.anthropic.request_timeout": 120,
            **(values or {}),
        }

    def get(self, key, default=None):
        return self._values.get(key, default)


_SUBSCRIPTION = {"llm.provider": "subscription"}


class TestProviderSelection:

    def test_api_is_default(self):
        analyser = Pipeline._build_text_analyser(_FakeConfig(), PromptBuilder())
        assert isinstance(analyser._claude_client, ClaudeClient)

    def test_subscription_uses_claude_code_for_all_roles(self):
        config = _FakeConfig(_SUBSCRIPTION)
        builder = PromptBuilder()
        clients = [
            Pipeline._build_text_analyser(config, builder)._claude_client,
            Pipeline._build_fact_checker(config, builder)._claude_client,
            Pipeline._build_transcript_reviewer(config, builder)._claude_client,
        ]
        assert all(isinstance(c, ClaudeCodeClient) for c in clients)

    def test_subscription_analysis_has_no_tools(self):
        client = Pipeline._build_text_analyser(_FakeConfig(_SUBSCRIPTION), PromptBuilder())._claude_client
        assert client._tools == []
        assert client._model == "claude-analysis"


class TestSubscriptionFactChecker:

    def _client(self, values=None):
        config = _FakeConfig({**_SUBSCRIPTION, **(values or {})})
        return Pipeline._build_fact_checker(config, PromptBuilder())._claude_client

    def test_uses_web_search_with_search_guidance(self):
        client = self._client()
        assert client._tools == ["WebSearch"]
        assert client._system_prompt_suffix.startswith("<search_requirement>")
        assert client._max_turns == 8

    def test_uses_claude_code_fact_check_model(self):
        assert self._client({"llm.claude_code.fact_check_model": "claude-opus"})._model == "claude-opus"

    def test_falls_back_to_anthropic_fact_check_model(self):
        assert self._client()._model == "claude-sonnet"

    def test_max_turns_configurable(self):
        assert self._client({"llm.claude_code.fact_check_max_turns": 3})._max_turns == 3
