import pytest
from types import MappingProxyType

from domain.text_from_source import TextFromSource


def test_stores_text():
    t = TextFromSource(text="hello")
    assert t.text == "hello"


def test_metadata_is_immutable():
    t = TextFromSource(text="hi", metadata={"key": "value"})
    assert isinstance(t.metadata, MappingProxyType)
    assert t.metadata["key"] == "value"
    with pytest.raises(TypeError):
        t.metadata["key"] = "new"


def test_default_metadata_is_empty():
    t = TextFromSource(text="hi")
    assert len(t.metadata) == 0


def test_frozen():
    t = TextFromSource(text="hi")
    with pytest.raises(AttributeError):
        t.text = "changed"
