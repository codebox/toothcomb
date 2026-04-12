from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from domain.llm_usage import LLMUsage, Citation


class Verdict(Enum):
    ESTABLISHED = "established"
    MISLEADING = "misleading"
    UNSUPPORTED = "unsupported"
    FALSE = "false"
    FAILED = "failed"


@dataclass
class FactCheckResult:
    verdict: Verdict
    note: str
    usage: LLMUsage | None = None
    citations: tuple[Citation, ...] = ()

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict.value,
            "note": self.note,
            "citations": [c.to_dict() for c in self.citations],
        }
