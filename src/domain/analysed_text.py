from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from domain.types import AnnotationId, JobId, UtteranceId, FactCheckStatus


class AnnotationType(Enum):
    CLAIM = "CLAIM"
    PREDICTION = "PREDICTION"
    COMMITMENT = "COMMITMENT"
    FALLACY = "FALLACY"
    RHETORIC = "RHETORIC"
    TACTIC = "TACTIC"

    @property
    def requires_fact_check(self) -> bool:
        return self == AnnotationType.CLAIM


@dataclass(frozen=True)
class Annotation:
    type: AnnotationType
    notes: str
    fact_check_query: Optional[str] = None
    fact_check_status: Optional[FactCheckStatus] = None
    fact_check_verdict: Optional[str] = None
    fact_check_note: Optional[str] = None
    fact_check_citations: Optional[list[dict]] = None
    job_id: JobId = JobId("")
    id: AnnotationId = field(default_factory=lambda: AnnotationId(str(uuid.uuid4())))

    @property
    def triggers_fact_check(self) -> bool:
        return self.fact_check_query is not None

    def to_dict(self) -> dict:
        fc_status = self.fact_check_status
        if fc_status is None and self.fact_check_query:
            fc_status = FactCheckStatus.PENDING
        return {
            "annotation_id": self.id,
            "type": self.type.value,
            "notes": self.notes,
            "fact_check_query": self.fact_check_query,
            "fact_check_status": fc_status.value if fc_status else None,
        }

    def __post_init__(self):
        if self.type.requires_fact_check and not self.fact_check_query and not self.fact_check_verdict:
            raise ValueError(f"{self.type.value} annotations must include a fact_check_query or verdict")


@dataclass(frozen=True)
class AnalysedPart:
    corrected_text: str
    annotations: tuple[Annotation, ...] = ()

    def to_dict(self) -> dict:
        return {
            "corrected_text": self.corrected_text,
            "annotations": [a.to_dict() for a in self.annotations],
        }


@dataclass
class AnalysedText:
    utterance_id: UtteranceId
    text: str
    analysed_parts: tuple[AnalysedPart, ...] = ()
    remainder: str = ""
    failed: bool = False
    usage: object = None  # Optional LLMUsage, kept as object to avoid circular import

    def to_dict(self) -> dict:
        return {
            "utterance_id": self.utterance_id,
            "parts": [p.to_dict() for p in self.analysed_parts],
            "remainder": self.remainder,
            "failed": self.failed,
        }
