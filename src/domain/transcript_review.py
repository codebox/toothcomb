from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional

from domain.analysed_text import AnnotationType
from domain.types import JobId


@dataclass(frozen=True)
class ReviewFinding:
    type: AnnotationType
    technique: str
    summary: str
    refs: tuple[str, ...] = ()
    excerpt: Optional[str] = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type.value,
            "technique": self.technique,
            "summary": self.summary,
            "refs": list(self.refs),
            "excerpt": self.excerpt,
        }


@dataclass
class TranscriptReview:
    job_id: JobId
    findings: tuple[ReviewFinding, ...] = ()
    failed: bool = False
    usage: object = None

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "findings": [f.to_dict() for f in self.findings],
            "failed": self.failed,
        }
