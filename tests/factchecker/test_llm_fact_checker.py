import pytest

from domain.fact_check_result import Verdict
from domain.llm_usage import LLMResponse, LLMUsage
from domain.prompt import Prompt
from domain.llm_response_error import LLMResponseError
from domain.types import ModelName
from factchecker.llm_fact_checker import LLMFactChecker
from llm.prompt_builder import PromptBuilder


# ---------- helpers ----------


class _FakeConfig:
    def __init__(self, overrides=None):
        self._values = {"pipeline.fact_check_parse_retries": 2}
        if overrides:
            self._values.update(overrides)

    def get(self, key, default=None):
        return self._values.get(key, default)


class _FakePromptBuilder:
    """Minimal PromptBuilder stand-in that returns a fixed prompt."""
    def build_fact_checker_prompt(self, query: str) -> Prompt:
        return Prompt(system_prompt="system", user_prompt=query)


class _TestableLLMFactChecker(LLMFactChecker):
    """Concrete subclass that returns canned LLM responses."""
    def __init__(self, responses: list[LLMResponse], config=None):
        super().__init__(config or _FakeConfig(), _FakePromptBuilder())
        self._responses = list(responses)
        self._call_count = 0

    def send_prompt_to_llm(self, prompt: Prompt) -> LLMResponse:
        resp = self._responses[self._call_count]
        self._call_count += 1
        return resp


def _ok_response(verdict="established", note="Confirmed", usage=None):
    text = f'{{"verdict": "{verdict}", "note": "{note}"}}'
    return LLMResponse(text=text, usage=usage)


def _bad_response(text, usage=None):
    return LLMResponse(text=text, usage=usage)


# ---------- _parse_llm_fact_check_response ----------


class TestParseLLMResponse:

    def test_valid_json(self):
        result = LLMFactChecker._parse_llm_fact_check_response(
            '{"verdict": "established", "note": "Confirmed"}', "query")
        assert result.verdict == Verdict.ESTABLISHED
        assert result.note == "Confirmed"

    def test_all_verdicts(self):
        for v in Verdict:
            result = LLMFactChecker._parse_llm_fact_check_response(
                f'{{"verdict": "{v.value}", "note": "n"}}', "q")
            assert result.verdict == v

    def test_json_in_code_fence(self):
        text = '```json\n{"verdict": "false", "note": "Wrong"}\n```'
        result = LLMFactChecker._parse_llm_fact_check_response(text, "q")
        assert result.verdict == Verdict.FALSE

    def test_multiple_json_blocks_uses_last(self):
        text = ('{"verdict": "established", "note": "first"}\n'
                'Wait, let me reconsider.\n'
                '{"verdict": "misleading", "note": "corrected"}')
        result = LLMFactChecker._parse_llm_fact_check_response(text, "q")
        assert result.verdict == Verdict.MISLEADING
        assert result.note == "corrected"

    def test_not_json_raises(self):
        with pytest.raises(LLMResponseError, match="not valid JSON"):
            LLMFactChecker._parse_llm_fact_check_response("this is not json", "q")

    def test_json_array_raises(self):
        with pytest.raises(LLMResponseError, match="missing required 'verdict'"):
            LLMFactChecker._parse_llm_fact_check_response('[1, 2, 3]', "q")

    def test_missing_verdict_raises(self):
        with pytest.raises(LLMResponseError, match="missing required 'verdict'"):
            LLMFactChecker._parse_llm_fact_check_response('{"note": "n"}', "q")

    def test_missing_note_raises(self):
        with pytest.raises(LLMResponseError, match="missing required field"):
            LLMFactChecker._parse_llm_fact_check_response('{"verdict": "false"}', "q")

    def test_invalid_verdict_value_raises(self):
        with pytest.raises(LLMResponseError, match="Invalid value"):
            LLMFactChecker._parse_llm_fact_check_response(
                '{"verdict": "maybe", "note": "n"}', "q")

    def test_error_includes_llm_response(self):
        try:
            LLMFactChecker._parse_llm_fact_check_response("garbage", "my query")
            assert False, "Should have raised"
        except LLMResponseError as e:
            assert e.llm_response == "garbage"
            assert "my query" in str(e)


# ---------- fact_check retry loop ----------


class TestFactCheckRetries:

    def test_success_first_attempt(self):
        checker = _TestableLLMFactChecker([_ok_response()])
        result = checker.fact_check("Is the sky blue?")
        assert result.verdict == Verdict.ESTABLISHED
        assert checker._call_count == 1

    def test_retry_on_parse_failure(self):
        checker = _TestableLLMFactChecker([
            _bad_response("not json"),
            _ok_response(),
        ])
        result = checker.fact_check("query")
        assert result.verdict == Verdict.ESTABLISHED
        assert checker._call_count == 2

    def test_all_retries_exhausted_raises(self):
        checker = _TestableLLMFactChecker([
            _bad_response("bad1"),
            _bad_response("bad2"),
            _bad_response("bad3"),
        ], config=_FakeConfig({"pipeline.fact_check_parse_retries": 2}))

        with pytest.raises(LLMResponseError):
            checker.fact_check("query")
        assert checker._call_count == 3  # 1 initial + 2 retries

    def test_zero_retries_fails_immediately(self):
        checker = _TestableLLMFactChecker(
            [_bad_response("bad")],
            config=_FakeConfig({"pipeline.fact_check_parse_retries": 0}),
        )
        with pytest.raises(LLMResponseError):
            checker.fact_check("query")
        assert checker._call_count == 1

    def test_usage_accumulated_across_retries(self):
        usage1 = LLMUsage(model=ModelName("m"), input_tokens=100, output_tokens=50)
        usage2 = LLMUsage(model=ModelName("m"), input_tokens=200, output_tokens=75)
        checker = _TestableLLMFactChecker([
            _bad_response("bad", usage=usage1),
            _ok_response(usage=usage2),
        ])
        result = checker.fact_check("query")
        assert result.usage.input_tokens == 300
        assert result.usage.output_tokens == 125

    def test_usage_from_single_call(self):
        usage = LLMUsage(model=ModelName("m"), input_tokens=50)
        checker = _TestableLLMFactChecker([_ok_response(usage=usage)])
        result = checker.fact_check("query")
        assert result.usage.input_tokens == 50

    def test_usage_none_when_no_usage_reported(self):
        checker = _TestableLLMFactChecker([_ok_response()])
        result = checker.fact_check("query")
        assert result.usage is None

    def test_last_error_raised_on_exhaustion(self):
        """The error from the final attempt should be the one raised."""
        checker = _TestableLLMFactChecker([
            _bad_response('{"verdict": "bad_value", "note": "n"}'),  # ValueError
            _bad_response("totally not json"),  # JSONDecodeError
        ], config=_FakeConfig({"pipeline.fact_check_parse_retries": 1}))

        with pytest.raises(LLMResponseError, match="not valid JSON"):
            checker.fact_check("query")


# ---------- base class ----------


def test_send_prompt_to_llm_not_implemented():
    checker = LLMFactChecker(_FakeConfig(), _FakePromptBuilder())
    with pytest.raises(NotImplementedError):
        checker.send_prompt_to_llm(Prompt("s", "u"))
