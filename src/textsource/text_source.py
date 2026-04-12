from typing import Callable

from config import Config


class TextSource:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._callback: Callable[[str], None] = TextSource._no_callback

    @staticmethod
    def _no_callback(_: str) -> None:
        raise RuntimeError("No callback registered — call on_text() before start()")

    def on_text(self, callback: Callable[[str], None]) -> None:
        self._callback = callback

    def start(self) -> None:
        raise NotImplementedError(f"{type(self).__name__} must implement start()")
