import pytest

from domain.analysed_text import AnnotationType
from domain.llm_usage import LLMResponse, LLMUsage
from domain.prompt import Prompt
from domain.llm_response_error import LLMResponseError
from domain.types import JobId, ModelName
from reviewer.llm_transcript_reviewer import LLMTranscriptReviewer
from llm.prompt_builder import PromptBuilder


# ---------- helpers ----------


class _FakeConfig:
    def __init__(self, overrides=None):
        self._values = {"pipeline.review_parse_retries": 2}
        if overrides:
            self._values.update(overrides)

    def get(self, key, default=None):
        return self._values.get(key, default)


class _FakePromptBuilder:
    def build_transcript_review_prompt(self, job_config, analyses):
        return Prompt(system_prompt="system", user_prompt="transcript")


class _TestableLLMReviewer(LLMTranscriptReviewer):
    def __init__(self, responses: list[LLMResponse], config=None):
        super().__init__(config or _FakeConfig(), _FakePromptBuilder(), claude_client=None)
        self._responses = list(responses)
        self._call_count = 0

    def send_prompt_to_llm(self, prompt: Prompt) -> LLMResponse:
        resp = self._responses[self._call_count]
        self._call_count += 1
        return resp


class _FakeJobConfig:
    def __init__(self):
        self.id = JobId("job-1")
        self.title = "Test"
        self.context = None
        self.is_transcribed = False


def _ok_response(findings_json='[]', usage=None):
    text = f'{{"findings": {findings_json}}}'
    return LLMResponse(text=text, usage=usage)


def _bad_response(text, usage=None):
    return LLMResponse(text=text, usage=usage)


# ---------- _parse_llm_review_response ----------


class TestParseLLMReviewResponse:

    def test_empty_findings(self):
        result = LLMTranscriptReviewer._parse_llm_review_response(
            '{"findings": []}', JobId("j1"))
        assert result.findings == ()
        assert result.job_id == "j1"

    def test_valid_finding(self):
        json_str = '''{
            "findings": [{
                "type": "TACTIC",
                "technique": "Self-Contradiction",
                "summary": "Speaker contradicted themselves.",
                "refs": ["ann-1", "ann-2"]
            }]
        }'''
        result = LLMTranscriptReviewer._parse_llm_review_response(json_str, JobId("j1"))
        assert len(result.findings) == 1
        finding = result.findings[0]
        assert finding.type == AnnotationType.TACTIC
        assert finding.technique == "Self-Contradiction"
        assert finding.summary == "Speaker contradicted themselves."
        assert finding.refs == ("ann-1", "ann-2")

    def test_multiple_findings(self):
        json_str = '''{
            "findings": [
                {"type": "TACTIC", "technique": "Gish Gallop", "summary": "s1", "refs": []},
                {"type": "RHETORIC", "technique": "Moving Goalposts", "summary": "s2", "refs": []}
            ]
        }'''
        result = LLMTranscriptReviewer._parse_llm_review_response(json_str, JobId("j1"))
        assert len(result.findings) == 2

    def test_finding_without_refs(self):
        json_str = '{"findings": [{"type": "FALLACY", "technique": "t", "summary": "s"}]}'
        result = LLMTranscriptReviewer._parse_llm_review_response(json_str, JobId("j1"))
        assert result.findings[0].refs == ()

    def test_json_in_code_fence(self):
        text = '```json\n{"findings": []}\n```'
        result = LLMTranscriptReviewer._parse_llm_review_response(text, JobId("j1"))
        assert result.findings == ()

    def test_not_json_raises(self):
        with pytest.raises(LLMResponseError, match="not valid JSON"):
            LLMTranscriptReviewer._parse_llm_review_response("not json", JobId("j1"))

    def test_missing_findings_raises(self):
        with pytest.raises(LLMResponseError, match="missing required 'findings'"):
            LLMTranscriptReviewer._parse_llm_review_response('{"other": 1}', JobId("j1"))

    def test_findings_not_list_raises(self):
        with pytest.raises(LLMResponseError, match="must be a list"):
            LLMTranscriptReviewer._parse_llm_review_response('{"findings": "oops"}', JobId("j1"))

    def test_missing_type_raises(self):
        with pytest.raises(LLMResponseError, match="missing required field"):
            LLMTranscriptReviewer._parse_llm_review_response(
                '{"findings": [{"technique": "t", "summary": "s"}]}', JobId("j1"))

    def test_invalid_type_raises(self):
        with pytest.raises(LLMResponseError, match="Invalid value"):
            LLMTranscriptReviewer._parse_llm_review_response(
                '{"findings": [{"type": "BADTYPE", "technique": "t", "summary": "s"}]}', JobId("j1"))

    def test_missing_technique_raises(self):
        with pytest.raises(LLMResponseError, match="missing required field"):
            LLMTranscriptReviewer._parse_llm_review_response(
                '{"findings": [{"type": "TACTIC", "summary": "s"}]}', JobId("j1"))


# ---------- review retry loop ----------


class TestReviewRetries:

    def test_success_first_attempt(self):
        reviewer = _TestableLLMReviewer([_ok_response()])
        result = reviewer.review(_FakeJobConfig(), [])
        assert result.findings == ()
        assert reviewer._call_count == 1

    def test_retry_on_parse_failure(self):
        reviewer = _TestableLLMReviewer([
            _bad_response("not json"),
            _ok_response(),
        ])
        result = reviewer.review(_FakeJobConfig(), [])
        assert result.findings == ()
        assert reviewer._call_count == 2

    def test_all_retries_exhausted_raises(self):
        reviewer = _TestableLLMReviewer([
            _bad_response("bad1"),
            _bad_response("bad2"),
            _bad_response("bad3"),
        ], config=_FakeConfig({"pipeline.review_parse_retries": 2}))

        with pytest.raises(LLMResponseError):
            reviewer.review(_FakeJobConfig(), [])
        assert reviewer._call_count == 3

    def test_usage_accumulated_across_retries(self):
        usage1 = LLMUsage(model=ModelName("m"), input_tokens=100, output_tokens=50)
        usage2 = LLMUsage(model=ModelName("m"), input_tokens=200, output_tokens=75)
        reviewer = _TestableLLMReviewer([
            _bad_response("bad", usage=usage1),
            _ok_response(usage=usage2),
        ])
        result = reviewer.review(_FakeJobConfig(), [])
        assert result.usage.input_tokens == 300
        assert result.usage.output_tokens == 125

    def test_usage_none_when_no_usage_reported(self):
        reviewer = _TestableLLMReviewer([_ok_response()])
        result = reviewer.review(_FakeJobConfig(), [])
        assert result.usage is None


