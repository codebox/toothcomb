import pytest

from domain.prompt import Prompt
from textsource.text_source import TextSource


class _FakeConfig:
    def get(self, key, default=None):
        return default


class _ConcreteTextSource(TextSource):
    def start(self):
        self._callback("hello")


class TestTextSource:

    def test_no_callback_raises_runtime_error(self):
        source = _ConcreteTextSource(_FakeConfig())
        with pytest.raises(RuntimeError, match="No callback registered"):
            source.start()

    def test_on_text_registers_callback(self):
        source = _ConcreteTextSource(_FakeConfig())
        received = []
        source.on_text(received.append)
        source.start()
        assert received == ["hello"]

    def test_start_not_implemented_on_base(self):
        source = TextSource(_FakeConfig())
        with pytest.raises(NotImplementedError):
            source.start()

    def test_callback_can_be_replaced(self):
        source = _ConcreteTextSource(_FakeConfig())
        first = []
        second = []
        source.on_text(first.append)
        source.on_text(second.append)
        source.start()
        assert first == []
        assert second == ["hello"]
