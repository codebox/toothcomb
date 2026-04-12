from config import Config
from domain.analysed_text import AnalysedText
from domain.job_config import JobConfig
from domain.transcript_review import TranscriptReview


class TranscriptReviewer:
    def __init__(self, config: Config):
        self.config = config

    def review(self, job_config: JobConfig, analyses: list[AnalysedText]) -> TranscriptReview:
        raise NotImplementedError(f"{type(self).__name__} must implement review()")
