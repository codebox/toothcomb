from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

from domain.types import ModelName

T = TypeVar("T")


@dataclass(frozen=True)
class LLMUsage:
    """LLM-agnostic token usage from a single API call."""
    model: ModelName = ModelName("")
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def __add__(self, other: LLMUsage) -> LLMUsage:
        return LLMUsage(
            model=self.model or other.model,
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_creation_tokens=self.cache_creation_tokens + other.cache_creation_tokens,
        )

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
        }


@dataclass(frozen=True)
class Citation:
    """A web search citation with URL and title."""
    url: str
    title: str

    def to_dict(self) -> dict:
        return {"url": self.url, "title": self.title}


@dataclass(frozen=True)
class LLMResponse:
    """Response from an LLM call: the generated text plus optional usage stats."""
    text: str
    usage: LLMUsage | None = None
    citations: tuple[Citation, ...] = ()


@dataclass(frozen=True)
class ParsedLLMResponse(Generic[T]):
    """A parsed LLM result paired with accumulated usage from all attempts."""
    result: T
    usage: LLMUsage | None = None
    citations: tuple[Citation, ...] = ()
