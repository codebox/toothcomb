from pathlib import Path

from domain.analysed_text import AnalysedText
from domain.job_config import JobConfig, PromptContext
from domain.prompt import Prompt
from domain.transcript import Utterance

_PROMPTS_DIR = Path("resources/prompts")


def _wrap_xml(tag: str, content: str) -> str:
    return f"<{tag}>\n{content}\n</{tag}>"


class PromptBuilder:
    def __init__(self):
        self._utterance_analysis_prompt = (_PROMPTS_DIR / "utterance_analysis.txt").read_text()
        self._transcript_review_prompt = (_PROMPTS_DIR / "transcript_review.txt").read_text()
        self._fact_checker_prompt = (_PROMPTS_DIR / "fact_checking.txt").read_text()
        self._fix_transcription = (_PROMPTS_DIR / "fix_transcription.txt").read_text()

    def build_analyser_prompt(self, job_config: JobConfig, utterance: Utterance,
                              previous: tuple[Utterance, ...], following_text: str = "") -> Prompt:
        parts = [self._utterance_analysis_prompt]
        context = self._render_context(job_config.context)
        if context:
            parts.append(context)
        if job_config.is_transcribed:
            parts.append(self._fix_transcription)
        system_prompt = "\n\n".join(parts)
        previous_statements = self._render_previous_statements(previous)
        new_statements = self._render_new_text(utterance.text)
        user_parts = [previous_statements, new_statements]
        if following_text:
            user_parts.append(_wrap_xml("following_text", following_text))

        return Prompt(system_prompt, "\n".join(user_parts))

    def build_transcript_review_prompt(self, job_config: JobConfig, analyses: list[AnalysedText]) -> Prompt:
        parts = [self._transcript_review_prompt]
        context = self._render_context(job_config.context)
        if context:
            parts.append(context)
        system_prompt = "\n\n".join(parts)
        annotated_transcript = self._render_annotated_transcript(analyses)
        return Prompt(system_prompt, _wrap_xml("transcript", annotated_transcript))

    def build_fact_checker_prompt(self, fact_check_query: str) -> Prompt:
        return Prompt(self._fact_checker_prompt, fact_check_query)

    @staticmethod
    def _render_annotated_transcript(analyses: list[AnalysedText]) -> str:
        """Render the full transcript with annotation IDs as inline markers.

        Produces text like:
            The economy grew by 4.2 percent [abc-123 CLAIM: GDP growth of 4.2%]. We will
            cut taxes for everyone [def-456 COMMITMENT: tax cut pledge].
        """
        paragraphs = []
        for analysis in analyses:
            for part in analysis.analysed_parts:
                text = part.corrected_text
                if part.annotations:
                    markers = ", ".join(
                        f"{a.id} {a.type.value}: {a.notes}" for a in part.annotations
                    )
                    text = f"{text} [{markers}]"
                paragraphs.append(text)
        return "\n\n".join(paragraphs)

    @staticmethod
    def _render_previous_statements(previous: tuple[Utterance, ...]) -> str:
        if not previous:
            return ""
        return _wrap_xml("previous_statements", "\n".join(str(u) for u in previous))

    @staticmethod
    def _render_new_text(new_text: str) -> str:
        return _wrap_xml("new_text", new_text)

    @staticmethod
    def _render_context(ctx: PromptContext) -> str:
        sections = []
        if ctx.speakers:
            sections.append(_wrap_xml("speakers", ctx.speakers))
        if ctx.date_and_time:
            sections.append(_wrap_xml("date_and_time", ctx.date_and_time))
        if ctx.location:
            sections.append(_wrap_xml("location", ctx.location))
        if ctx.background:
            sections.append(_wrap_xml("background", ctx.background))
        if ctx.analysis_date:
            sections.append(_wrap_xml("analysis_date", ctx.analysis_date))
        if not sections:
            return ""
        return _wrap_xml("context", "\n".join(sections))
