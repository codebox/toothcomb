from dataclasses import dataclass

from domain.types import JobId


@dataclass
class PromptContext:
    speakers: str = ""
    date_and_time: str = ""
    location: str = ""
    background: str = ""
    analysis_date: str = ""


class JobConfig:
    def __init__(self, id: JobId, title: str, context: PromptContext, is_transcribed: bool = False):
        self.id = id
        self.title = title
        self.context = context
        self.is_transcribed = is_transcribed
