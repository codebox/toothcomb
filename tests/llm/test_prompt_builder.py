import os

import pytest

from domain.analysed_text import Annotation, AnnotationType, AnalysedPart, AnalysedText
from domain.job_config import JobConfig, PromptContext
from domain.prompt import Prompt
from domain.transcript import Utterance
from domain.types import JobId, UtteranceId
from llm.prompt_builder import PromptBuilder, _wrap_xml


# ---------- helpers ----------


@pytest.fixture
def builder():
    # PromptBuilder reads from resources/prompts/ — run from project root
    os.chdir(os.path.join(os.path.dirname(__file__), "..", ".."))
    return PromptBuilder()


def _ctx(**kwargs):
    return PromptContext(**kwargs)


def _job_config(context=None, is_transcribed=False):
    return JobConfig(
        id=JobId("j1"), title="Test",
        context=context or _ctx(),
        is_transcribed=is_transcribed,
    )


def _utterance(text="Hello world", speaker="Alice", utt_id="u1"):
    return Utterance(id=UtteranceId(utt_id), speaker=speaker, text=text)


# ---------- _wrap_xml ----------


def test_wrap_xml():
    assert _wrap_xml("tag", "content") == "<tag>\ncontent\n</tag>"


# ---------- _render_context ----------


class TestRenderContext:

    def test_empty_context_returns_empty(self):
        assert PromptBuilder._render_context(_ctx()) == ""

    def test_single_field(self):
        result = PromptBuilder._render_context(_ctx(speakers="Alice"))
        assert "<context>" in result
        assert "<speakers>\nAlice\n</speakers>" in result

    def test_all_fields(self):
        result = PromptBuilder._render_context(_ctx(
            speakers="Alice, Bob",
            date_and_time="2025-03-04",
            location="NYC",
            background="A debate",
            analysis_date="2025-03-15",
        ))
        assert "<speakers>" in result
        assert "<date_and_time>" in result
        assert "<location>" in result
        assert "<background>" in result
        assert "<analysis_date>" in result

    def test_skips_empty_fields(self):
        result = PromptBuilder._render_context(_ctx(speakers="Alice", location=""))
        assert "<speakers>" in result
        assert "<location>" not in result


# ---------- _render_previous_statements ----------


class TestRenderPreviousStatements:

    def test_empty_returns_empty(self):
        assert PromptBuilder._render_previous_statements(()) == ""

    def test_single_utterance(self):
        result = PromptBuilder._render_previous_statements((_utterance(text="Hi", speaker="Bob"),))
        assert "<previous_statements>" in result
        assert "Bob: Hi" in result

    def test_multiple_utterances(self):
        utts = (_utterance(text="One", speaker="A"), _utterance(text="Two", speaker="B"))
        result = PromptBuilder._render_previous_statements(utts)
        assert "A: One" in result
        assert "B: Two" in result


# ---------- _render_new_text ----------


def test_render_new_text():
    result = PromptBuilder._render_new_text("Hello world")
    assert result == "<new_text>\nHello world\n</new_text>"


# ---------- _render_annotated_transcript ----------


class TestRenderAnnotatedTranscript:

    def test_no_annotations(self):
        part = AnalysedPart(corrected_text="Plain text")
        analysis = AnalysedText(utterance_id=UtteranceId("u1"), text="t",
                                analysed_parts=(part,))
        result = PromptBuilder._render_annotated_transcript([analysis])
        assert result == "Plain text"

    def test_with_annotations(self):
        ann = Annotation(type=AnnotationType.PREDICTION, notes="GDP will rise")
        part = AnalysedPart(corrected_text="The economy will grow", annotations=(ann,))
        analysis = AnalysedText(utterance_id=UtteranceId("u1"), text="t",
                                analysed_parts=(part,))
        result = PromptBuilder._render_annotated_transcript([analysis])
        assert "The economy will grow [PREDICTION: GDP will rise]" in result

    def test_multiple_annotations_on_one_part(self):
        ann1 = Annotation(type=AnnotationType.CLAIM, notes="GDP claim",
                          fact_check_query="q")
        ann2 = Annotation(type=AnnotationType.COMMITMENT, notes="Tax pledge")
        part = AnalysedPart(corrected_text="Growth was 4%", annotations=(ann1, ann2))
        analysis = AnalysedText(utterance_id=UtteranceId("u1"), text="t",
                                analysed_parts=(part,))
        result = PromptBuilder._render_annotated_transcript([analysis])
        assert "CLAIM: GDP claim" in result
        assert "COMMITMENT: Tax pledge" in result

    def test_multiple_parts_separated_by_blank_lines(self):
        part1 = AnalysedPart(corrected_text="First paragraph")
        part2 = AnalysedPart(corrected_text="Second paragraph")
        analysis = AnalysedText(utterance_id=UtteranceId("u1"), text="t",
                                analysed_parts=(part1, part2))
        result = PromptBuilder._render_annotated_transcript([analysis])
        assert "First paragraph\n\nSecond paragraph" in result

    def test_multiple_analyses(self):
        a1 = AnalysedText(utterance_id=UtteranceId("u1"), text="t",
                          analysed_parts=(AnalysedPart(corrected_text="From u1"),))
        a2 = AnalysedText(utterance_id=UtteranceId("u2"), text="t",
                          analysed_parts=(AnalysedPart(corrected_text="From u2"),))
        result = PromptBuilder._render_annotated_transcript([a1, a2])
        assert "From u1" in result
        assert "From u2" in result

    def test_empty_analyses(self):
        assert PromptBuilder._render_annotated_transcript([]) == ""


# ---------- build methods ----------


class TestBuildAnalyserPrompt:

    def test_includes_utterance_text(self, builder):
        prompt = builder.build_analyser_prompt(
            _job_config(), _utterance(text="Test statement"), ())
        assert "<new_text>\nTest statement\n</new_text>" in prompt.user_prompt

    def test_includes_previous_statements(self, builder):
        prev = (_utterance(text="Earlier", speaker="Bob"),)
        prompt = builder.build_analyser_prompt(
            _job_config(), _utterance(text="Now"), prev)
        assert "Bob: Earlier" in prompt.user_prompt
        assert "<previous_statements>" in prompt.user_prompt

    def test_no_previous_statements(self, builder):
        prompt = builder.build_analyser_prompt(
            _job_config(), _utterance(text="Solo"), ())
        assert "<previous_statements>" not in prompt.user_prompt

    def test_includes_context_when_set(self, builder):
        config = _job_config(context=_ctx(speakers="Alice"))
        prompt = builder.build_analyser_prompt(config, _utterance(), ())
        assert "<speakers>" in prompt.system_prompt

    def test_excludes_context_when_empty(self, builder):
        prompt = builder.build_analyser_prompt(_job_config(), _utterance(), ())
        assert "<context>" not in prompt.system_prompt

    def test_includes_fix_transcription_when_transcribed(self, builder):
        config = _job_config(is_transcribed=True)
        prompt = builder.build_analyser_prompt(config, _utterance(), ())
        # The fix_transcription prompt text should appear in system prompt
        assert len(prompt.system_prompt) > len(
            builder.build_analyser_prompt(_job_config(is_transcribed=False), _utterance(), ()).system_prompt
        )

    def test_excludes_fix_transcription_when_not_transcribed(self, builder):
        config = _job_config(is_transcribed=False)
        prompt_without = builder.build_analyser_prompt(config, _utterance(), ())
        config_with = _job_config(is_transcribed=True)
        prompt_with = builder.build_analyser_prompt(config_with, _utterance(), ())
        assert len(prompt_with.system_prompt) > len(prompt_without.system_prompt)


class TestBuildTranscriptReviewPrompt:

    def test_wraps_transcript_in_xml(self, builder):
        part = AnalysedPart(corrected_text="Some text")
        analysis = AnalysedText(utterance_id=UtteranceId("u1"), text="t",
                                analysed_parts=(part,))
        prompt = builder.build_transcript_review_prompt(_job_config(), [analysis])
        assert "<transcript>" in prompt.user_prompt
        assert "Some text" in prompt.user_prompt
        assert "</transcript>" in prompt.user_prompt

    def test_includes_context_when_set(self, builder):
        config = _job_config(context=_ctx(location="DC"))
        prompt = builder.build_transcript_review_prompt(config, [])
        assert "<location>" in prompt.system_prompt

    def test_excludes_context_when_empty(self, builder):
        prompt = builder.build_transcript_review_prompt(_job_config(), [])
        assert "<context>" not in prompt.system_prompt


class TestBuildFactCheckerPrompt:

    def test_uses_query_as_user_prompt(self, builder):
        prompt = builder.build_fact_checker_prompt("Is the sky blue?")
        assert prompt.user_prompt == "Is the sky blue?"

    def test_system_prompt_is_fact_checker_prompt(self, builder):
        prompt = builder.build_fact_checker_prompt("query")
        assert len(prompt.system_prompt) > 0
