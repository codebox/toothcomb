from config import Config
from llm.claude_client import ClaudeClient
from llm.json_utils import parse_llm_json
from llm.retrying_llm_caller import RetryingLLMCaller
from domain.analysed_text import AnalysedText, AnalysedPart, Annotation, AnnotationType
from domain.fact_check_result import Verdict
from domain.job_config import JobConfig
from domain.llm_response_error import LLMResponseError
from domain.llm_usage import LLMResponse
from domain.prompt import Prompt
from domain.transcript import Utterance, UtteranceWithContext
from llm.prompt_builder import PromptBuilder
from textanalyser.text_analyser import TextAnalyser


class LLMTextAnalyser(TextAnalyser, RetryingLLMCaller):
    def __init__(self, config: Config, prompt_builder: PromptBuilder,
                 claude_client: ClaudeClient):
        TextAnalyser.__init__(self, config)
        RetryingLLMCaller.__init__(self, max_retries=config.get("pipeline.analysis_parse_retries", 2))
        self.prompt_builder = prompt_builder
        self._claude_client = claude_client

    def send_prompt_to_llm(self, prompt: Prompt) -> LLMResponse:
        return self._claude_client.send(prompt)

    def analyse(self, utterance_with_context: UtteranceWithContext, job_config: JobConfig) -> AnalysedText:
        prompt = self.prompt_builder.build_analyser_prompt(
            job_config, utterance_with_context.utterance, utterance_with_context.previous,
            utterance_with_context.following_text)
        source = utterance_with_context.utterance
        response = self._call_with_retries(prompt, lambda text: self._parse_llm_analyse_response(text, source))
        response.result.usage = response.usage
        return response.result

    @staticmethod
    def _parse_llm_analyse_response(llm_response: str, source: Utterance) -> AnalysedText:
        data = parse_llm_json(llm_response, ["analysedParts"])

        if not isinstance(data["analysedParts"], list):
            raise LLMResponseError("'analysedParts' must be a list", llm_response)

        try:
            analysed_parts = tuple(
                AnalysedPart(
                    corrected_text=part["correctedText"],
                    annotations=tuple(
                        LLMTextAnalyser._parse_annotation(a)
                        for a in part["annotations"]
                    ),
                )
                for part in data["analysedParts"]
            )
        except KeyError as e:
            raise LLMResponseError(f"Response missing required field: {e}", llm_response) from e
        except ValueError as e:
            raise LLMResponseError(f"Invalid value in response: {e}", llm_response) from e

        return AnalysedText(
            utterance_id=source.id,
            text=source.text,
            analysed_parts=analysed_parts,
            remainder=data.get("remainder", ""),
        )

    @staticmethod
    def _parse_annotation(a: dict) -> Annotation:
        verdict_str = a.get("verdict")
        verdict_note = a.get("verdictNote")
        if verdict_str:
            Verdict(verdict_str)  # validate
        # If the LLM provided both a verdict and a query, the verdict wins —
        # no need to trigger a web search for something already resolved.
        fact_check_query = None if verdict_str else a.get("factCheckQuery")
        return Annotation(
            type=AnnotationType(a["type"]),
            notes=a["notes"],
            fact_check_query=fact_check_query,
            fact_check_verdict=verdict_str,
            fact_check_note=verdict_note,
        )
