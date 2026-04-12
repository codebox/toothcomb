from enum import Enum
from typing import NewType

# ── ID types ──

JobId = NewType('JobId', str)
UtteranceId = NewType('UtteranceId', str)
AnnotationId = NewType('AnnotationId', str)
AnalysisResultId = NewType('AnalysisResultId', str)

# ── Model name ──

ModelName = NewType('ModelName', str)


# ── Enums ──

class JobStatus(Enum):
    INIT = "init"
    INGESTING = "ingesting"
    ANALYSING = "analysing"
    REVIEWING = "reviewing"
    COMPLETE = "complete"
    ABORTED = "aborted"


class AnalysisStatus(Enum):
    PENDING = "pending"
    BUFFERED = "buffered"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"


class FactCheckStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"


class SourceType(Enum):
    TEXT = "text"
    FILE = "file"
    MP3 = "mp3"
    STREAMING = "streaming"
