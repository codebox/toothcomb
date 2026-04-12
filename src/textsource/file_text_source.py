import asyncio
import random
import re
from pathlib import Path

from config import Config
from textsource.text_source import TextSource

_SENTENCE_RE = re.compile(r'(?<=[.!?])\s+')
_JITTER = 0.5


class FileTextSource(TextSource):
    def __init__(self, config: Config, file_path: str, delay_seconds: float = 0) -> None:
        super().__init__(config)
        self.file_path = Path(config.get("paths.uploads")) / file_path
        self.delay_seconds = delay_seconds

    def start(self) -> None:
        if self.delay_seconds > 0:
            asyncio.run(self._start_with_delay())
        else:
            self._start_immediate()

    def _start_immediate(self) -> None:
        text = self.file_path.read_text()
        for sentence in _SENTENCE_RE.split(text):
            sentence = sentence.strip()
            if sentence:
                self._callback(sentence)

    async def _start_with_delay(self) -> None:
        text = self.file_path.read_text()
        for sentence in _SENTENCE_RE.split(text):
            sentence = sentence.strip()
            if sentence:
                self._callback(sentence)
                jitter = self.delay_seconds * random.uniform(-_JITTER, _JITTER)
                await asyncio.sleep(self.delay_seconds + jitter)
