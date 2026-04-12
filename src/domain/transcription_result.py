from dataclasses import dataclass, field


@dataclass(frozen=True)
class TranscriptionSegment:
    text: str
    start: float  # seconds from start of chunk
    end: float


@dataclass(frozen=True)
class TranscriptionResult:
    speaker: str
    text: str
    segments: tuple[TranscriptionSegment, ...] = field(default_factory=tuple)
