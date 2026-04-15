import json
from unittest.mock import MagicMock

import pytest

from domain.analysed_text import AnnotationType
from domain.job_config import JobConfig, PromptContext
from domain.llm_response_error import LLMResponseError
from domain.llm_usage import LLMResponse, LLMUsage
from domain.prompt import Prompt
from domain.transcript import Utterance, UtteranceWithContext
from domain.types import JobId, UtteranceId, ModelName
from textanalyser.llm_text_analyser import LLMTextAnalyser


# ---------- helpers ----------


_SOURCE = Utterance(id=UtteranceId("u1"), speaker="Alice", text="original text")


def _valid_response(parts=None, remainder=""):
    if parts is None:
        parts = [
            {
                "correctedText": "Corrected statement",
                "annotations": [
                    {"type": "CLAIM", "notes": "GDP claim", "factCheckQuery": "Is GDP up?"},
                ],
            }
        ]
    data = {"analysedParts": parts, "remainder": remainder}
    return json.dumps(data)


class _FakeConfig:
    def __init__(self, overrides=None):
        self._values = {"pipeline.analysis_parse_retries": 2}
        if overrides:
            self._values.update(overrides)

    def get(self, key, default=None):
        return self._values.get(key, default)


class _FakePromptBuilder:
    def build_analyser_prompt(self, job_config, utterance, previous, following_text=""):
        return Prompt(system_prompt="sys", user_prompt=utterance.text)


class _TestableLLMTextAnalyser(LLMTextAnalyser):
    def __init__(self, responses, config=None):
        super().__init__(config or _FakeConfig(), _FakePromptBuilder(), claude_client=None)
        self._responses = list(responses)
        self._call_count = 0

    def send_prompt_to_llm(self, prompt):
        resp = self._responses[self._call_count]
        self._call_count += 1
        return resp


# ---------- _parse_llm_analyse_response ----------


class TestParseResponse:

    def test_valid_single_part_with_annotation(self):
        result = LLMTextAnalyser._parse_llm_analyse_response(
            _valid_response(), _SOURCE)
        assert result.utterance_id == "u1"
        assert result.text == "original text"
        assert len(result.analysed_parts) == 1
        assert result.analysed_parts[0].corrected_text == "Corrected statement"
        assert len(result.analysed_parts[0].annotations) == 1
        ann = result.analysed_parts[0].annotations[0]
        assert ann.type == AnnotationType.CLAIM
        assert ann.notes == "GDP claim"
        assert ann.fact_check_query == "Is GDP up?"

    def test_multiple_parts(self):
        parts = [
            {"correctedText": "Part one", "annotations": []},
            {"correctedText": "Part two", "annotations": []},
        ]
        result = LLMTextAnalyser._parse_llm_analyse_response(
            _valid_response(parts), _SOURCE)
        assert len(result.analysed_parts) == 2
        assert result.analysed_parts[0].corrected_text == "Part one"
        assert result.analysed_parts[1].corrected_text == "Part two"

    def test_multiple_annotations_on_one_part(self):
        parts = [{
            "correctedText": "text",
            "annotations": [
                {"type": "CLAIM", "notes": "n1", "factCheckQuery": "q"},
                {"type": "PREDICTION", "notes": "n2"},
                {"type": "COMMITMENT", "notes": "n3"},
            ],
        }]
        result = LLMTextAnalyser._parse_llm_analyse_response(
            _valid_response(parts), _SOURCE)
        annotations = result.analysed_parts[0].annotations
        assert len(annotations) == 3
        types = [a.type for a in annotations]
        assert types == [AnnotationType.CLAIM, AnnotationType.PREDICTION, AnnotationType.COMMITMENT]

    def test_empty_annotations(self):
        parts = [{"correctedText": "text", "annotations": []}]
        result = LLMTextAnalyser._parse_llm_analyse_response(
            _valid_response(parts), _SOURCE)
        assert result.analysed_parts[0].annotations == ()

    def test_empty_parts_list(self):
        result = LLMTextAnalyser._parse_llm_analyse_response(
            _valid_response([]), _SOURCE)
        assert result.analysed_parts == ()

    def test_remainder_extracted(self):
        result = LLMTextAnalyser._parse_llm_analyse_response(
            _valid_response([], remainder="leftover text"), _SOURCE)
        assert result.remainder == "leftover text"

    def test_remainder_defaults_empty(self):
        data = json.dumps({"analysedParts": []})
        result = LLMTextAnalyser._parse_llm_analyse_response(data, _SOURCE)
        assert result.remainder == ""

    def test_fact_check_query_optional(self):
        parts = [{
            "correctedText": "text",
            "annotations": [{"type": "PREDICTION", "notes": "will rise"}],
        }]
        result = LLMTextAnalyser._parse_llm_analyse_response(
            _valid_response(parts), _SOURCE)
        assert result.analysed_parts[0].annotations[0].fact_check_query is None

    def test_all_annotation_types(self):
        for ann_type in ["CLAIM", "PREDICTION", "COMMITMENT", "FALLACY", "RHETORIC", "TACTIC"]:
            ann_data = {"type": ann_type, "notes": "n"}
            if ann_type == "CLAIM":
                ann_data["factCheckQuery"] = "q"
            parts = [{"correctedText": "t", "annotations": [ann_data]}]
            result = LLMTextAnalyser._parse_llm_analyse_response(
                _valid_response(parts), _SOURCE)
            assert result.analysed_parts[0].annotations[0].type == AnnotationType(ann_type)

    def test_json_in_code_fence(self):
        text = "```json\n" + _valid_response([]) + "\n```"
        result = LLMTextAnalyser._parse_llm_analyse_response(text, _SOURCE)
        assert result.analysed_parts == ()

    def test_self_correction_uses_last_json(self):
        first = json.dumps({"analysedParts": [
            {"correctedText": "wrong", "annotations": []}]})
        second = json.dumps({"analysedParts": [
            {"correctedText": "correct", "annotations": []}]})
        text = f"{first}\nActually let me fix that.\n{second}"
        result = LLMTextAnalyser._parse_llm_analyse_response(text, _SOURCE)
        assert result.analysed_parts[0].corrected_text == "correct"

    # --- error cases ---

    def test_not_json_raises(self):
        with pytest.raises(LLMResponseError, match="not valid JSON"):
            LLMTextAnalyser._parse_llm_analyse_response("not json at all", _SOURCE)

    def test_json_array_raises(self):
        with pytest.raises(LLMResponseError, match="not a JSON object"):
            LLMTextAnalyser._parse_llm_analyse_response("[1, 2]", _SOURCE)

    def test_missing_analysed_parts_raises(self):
        with pytest.raises(LLMResponseError, match="missing required 'analysedParts'"):
            LLMTextAnalyser._parse_llm_analyse_response('{"other": 1}', _SOURCE)

    def test_missing_corrected_text_raises(self):
        data = json.dumps({"analysedParts": [{"annotations": []}]})
        with pytest.raises(LLMResponseError, match="missing required field"):
            LLMTextAnalyser._parse_llm_analyse_response(data, _SOURCE)

    def test_missing_annotations_key_raises(self):
        data = json.dumps({"analysedParts": [{"correctedText": "t"}]})
        with pytest.raises(LLMResponseError, match="missing required field"):
            LLMTextAnalyser._parse_llm_analyse_response(data, _SOURCE)

    def test_missing_annotation_type_raises(self):
        data = json.dumps({"analysedParts": [
            {"correctedText": "t", "annotations": [{"notes": "n"}]}]})
        with pytest.raises(LLMResponseError, match="missing required field"):
            LLMTextAnalyser._parse_llm_analyse_response(data, _SOURCE)

    def test_missing_annotation_notes_raises(self):
        data = json.dumps({"analysedParts": [
            {"correctedText": "t", "annotations": [{"type": "PREDICTION"}]}]})
        with pytest.raises(LLMResponseError, match="missing required field"):
            LLMTextAnalyser._parse_llm_analyse_response(data, _SOURCE)

    def test_invalid_annotation_type_raises(self):
        data = json.dumps({"analysedParts": [
            {"correctedText": "t", "annotations": [{"type": "INVALID", "notes": "n"}]}]})
        with pytest.raises(LLMResponseError, match="Invalid value"):
            LLMTextAnalyser._parse_llm_analyse_response(data, _SOURCE)

    def test_claim_without_fact_check_query_or_verdict_raises(self):
        data = json.dumps({"analysedParts": [
            {"correctedText": "t", "annotations": [{"type": "CLAIM", "notes": "n"}]}]})
        with pytest.raises(LLMResponseError, match="Invalid value"):
            LLMTextAnalyser._parse_llm_analyse_response(data, _SOURCE)

    def test_claim_with_direct_verdict(self):
        parts = [{
            "correctedText": "The earth is flat.",
            "annotations": [{
                "type": "CLAIM",
                "notes": "Asserts the earth is flat.",
                "verdict": "false",
                "verdictNote": "The earth is an oblate spheroid.",
            }],
        }]
        result = LLMTextAnalyser._parse_llm_analyse_response(
            _valid_response(parts), _SOURCE)
        ann = result.analysed_parts[0].annotations[0]
        assert ann.type == AnnotationType.CLAIM
        assert ann.fact_check_query is None
        assert ann.fact_check_verdict == "false"
        assert ann.fact_check_note == "The earth is an oblate spheroid."

    def test_prediction_with_direct_verdict(self):
        parts = [{
            "correctedText": "Bitcoin will reach 100k by 2025.",
            "annotations": [{
                "type": "PREDICTION",
                "notes": "Price prediction.",
                "verdict": "established",
                "verdictNote": "Bitcoin surpassed 100k in late 2024.",
            }],
        }]
        result = LLMTextAnalyser._parse_llm_analyse_response(
            _valid_response(parts), _SOURCE)
        ann = result.analysed_parts[0].annotations[0]
        assert ann.type == AnnotationType.PREDICTION
        assert ann.fact_check_verdict == "established"
        assert ann.fact_check_note == "Bitcoin surpassed 100k in late 2024."

    def test_invalid_verdict_value_raises(self):
        parts = [{
            "correctedText": "t",
            "annotations": [{
                "type": "CLAIM",
                "notes": "n",
                "verdict": "maybe_true",
                "verdictNote": "note",
            }],
        }]
        data = json.dumps({"analysedParts": parts, "remainder": ""})
        with pytest.raises(LLMResponseError, match="Invalid value"):
            LLMTextAnalyser._parse_llm_analyse_response(data, _SOURCE)

    def test_annotation_without_verdict_has_none(self):
        parts = [{
            "correctedText": "t",
            "annotations": [{"type": "PREDICTION", "notes": "future event"}],
        }]
        result = LLMTextAnalyser._parse_llm_analyse_response(
            _valid_response(parts), _SOURCE)
        ann = result.analysed_parts[0].annotations[0]
        assert ann.fact_check_verdict is None
        assert ann.fact_check_note is None

    def test_analysed_parts_not_a_list_raises(self):
        data = json.dumps({"analysedParts": "not a list"})
        with pytest.raises(LLMResponseError, match="must be a list"):
            LLMTextAnalyser._parse_llm_analyse_response(data, _SOURCE)

    def test_error_contains_llm_response(self):
        try:
            LLMTextAnalyser._parse_llm_analyse_response("garbage", _SOURCE)
            assert False, "Should have raised"
        except LLMResponseError as e:
            assert e.llm_response == "garbage"


# ---------- analyse ----------


class TestAnalyse:

    def _job_config(self):
        return JobConfig(id=JobId("j1"), title="T", context=PromptContext())

    def _utterance_with_context(self):
        utt = Utterance(id=UtteranceId("u1"), speaker="Alice", text="test")
        return UtteranceWithContext(utterance=utt, previous=())

    def test_success_returns_analysed_text(self):
        usage = LLMUsage(model=ModelName("m"), input_tokens=100)
        analyser = _TestableLLMTextAnalyser([
            LLMResponse(text=_valid_response(), usage=usage),
        ])
        result = analyser.analyse(self._utterance_with_context(), self._job_config())
        assert result.utterance_id == "u1"
        assert len(result.analysed_parts) == 1
        assert result.usage.input_tokens == 100

    def test_usage_attached_to_result(self):
        usage = LLMUsage(model=ModelName("m"), input_tokens=50, output_tokens=25)
        analyser = _TestableLLMTextAnalyser([
            LLMResponse(text=_valid_response([]), usage=usage),
        ])
        result = analyser.analyse(self._utterance_with_context(), self._job_config())
        assert result.usage == usage

    def test_none_usage_when_not_reported(self):
        analyser = _TestableLLMTextAnalyser([
            LLMResponse(text=_valid_response([]), usage=None),
        ])
        result = analyser.analyse(self._utterance_with_context(), self._job_config())
        assert result.usage is None

    def test_parse_failure_raises_after_retries(self):
        analyser = _TestableLLMTextAnalyser([
            LLMResponse(text="not json", usage=None),
            LLMResponse(text="still not json", usage=None),
            LLMResponse(text="nope", usage=None),
        ])
        with pytest.raises(LLMResponseError):
            analyser.analyse(self._utterance_with_context(), self._job_config())


# ---------- retry logic ----------


class TestAnalyseRetries:

    def _job_config(self):
        return JobConfig(id=JobId("j1"), title="T", context=PromptContext())

    def _utterance_with_context(self):
        utt = Utterance(id=UtteranceId("u1"), speaker="Alice", text="test")
        return UtteranceWithContext(utterance=utt, previous=())

    def test_retry_on_parse_failure(self):
        analyser = _TestableLLMTextAnalyser([
            LLMResponse(text="not json", usage=None),
            LLMResponse(text=_valid_response(), usage=None),
        ])
        result = analyser.analyse(self._utterance_with_context(), self._job_config())
        assert result.utterance_id == "u1"
        assert analyser._call_count == 2

    def test_all_retries_exhausted_raises(self):
        analyser = _TestableLLMTextAnalyser([
            LLMResponse(text="bad1", usage=None),
            LLMResponse(text="bad2", usage=None),
            LLMResponse(text="bad3", usage=None),
        ], config=_FakeConfig({"pipeline.analysis_parse_retries": 2}))

        with pytest.raises(LLMResponseError):
            analyser.analyse(self._utterance_with_context(), self._job_config())
        assert analyser._call_count == 3  # 1 initial + 2 retries

    def test_zero_retries_fails_immediately(self):
        analyser = _TestableLLMTextAnalyser(
            [LLMResponse(text="bad", usage=None)],
            config=_FakeConfig({"pipeline.analysis_parse_retries": 0}),
        )
        with pytest.raises(LLMResponseError):
            analyser.analyse(self._utterance_with_context(), self._job_config())
        assert analyser._call_count == 1

    def test_usage_accumulated_across_retries(self):
        usage1 = LLMUsage(model=ModelName("m"), input_tokens=100, output_tokens=50)
        usage2 = LLMUsage(model=ModelName("m"), input_tokens=200, output_tokens=75)
        analyser = _TestableLLMTextAnalyser([
            LLMResponse(text="bad", usage=usage1),
            LLMResponse(text=_valid_response([]), usage=usage2),
        ])
        result = analyser.analyse(self._utterance_with_context(), self._job_config())
        assert result.usage.input_tokens == 300
        assert result.usage.output_tokens == 125

    def test_last_error_raised_on_exhaustion(self):
        """The error from the final attempt should be the one raised."""
        # First: valid JSON but missing analysedParts -> "missing required 'analysedParts'"
        # Second: not valid JSON -> "not valid JSON"
        analyser = _TestableLLMTextAnalyser([
            LLMResponse(text='{"other": 1}', usage=None),
            LLMResponse(text="totally not json", usage=None),
        ], config=_FakeConfig({"pipeline.analysis_parse_retries": 1}))

        with pytest.raises(LLMResponseError, match="not valid JSON"):
            analyser.analyse(self._utterance_with_context(), self._job_config())


