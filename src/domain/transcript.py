from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import List

from domain.types import UtteranceId, JobId, AnalysisStatus


@dataclass(frozen=True)
class Utterance:
    id: UtteranceId
    speaker: str
    text: str
    seq: int = 0
    job_id: JobId = JobId("")
    offset_seconds: float = 0.0
    analysis_status: AnalysisStatus = AnalysisStatus.PENDING
    analysis_remainder: str = ""

    def to_dict(self) -> dict:
        return {
            "utterance_id": self.id,
            "seq": self.seq,
            "speaker": self.speaker,
            "text": self.text,
            "offset_seconds": self.offset_seconds,
        }

    def __str__(self) -> str:
        if self.speaker:
            return f"{self.speaker}: {self.text}"
        return self.text


@dataclass(frozen=True)
class UtteranceWithContext:
    utterance: Utterance
    previous: tuple[Utterance, ...]
    following_text: str = ""


@dataclass
class Transcript:
    utterances: List[Utterance] = field(default_factory=list)
    _counter: int = field(default=0, repr=False)

    def add(self, speaker: str, text: str) -> Utterance:
        self._counter += 1
        utterance = Utterance(id=UtteranceId(str(uuid.uuid4())), speaker=speaker, text=text)
        self.utterances.append(utterance)
        return utterance

    def get_with_context(self, seq_id: int, context_count: int) -> UtteranceWithContext:
        """Return the utterance at seq_id (1-based) plus the preceding context_count utterances."""
        idx = seq_id - 1
        start = max(0, idx - context_count)
        return UtteranceWithContext(
            utterance=self.utterances[idx],
            previous=tuple(self.utterances[start:idx]),
        )
