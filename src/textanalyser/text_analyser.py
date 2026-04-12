from config import Config
from domain.analysed_text import AnalysedText
from domain.job_config import JobConfig
from domain.transcript import UtteranceWithContext


class TextAnalyser:
    def __init__(self, config: Config):
        self.config = config

    def analyse(self, utterance_with_context: UtteranceWithContext, job_config: JobConfig) -> AnalysedText:
        raise NotImplementedError(f"{type(self).__name__} must implement analyse()")
