from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class TextFromSource:
    text: str
    metadata: MappingProxyType[str, Any]

    def __init__(self, text: str, metadata: dict[str, Any] = {}) -> None:
        object.__setattr__(self, "text", text)
        object.__setattr__(self, "metadata", MappingProxyType(metadata))
