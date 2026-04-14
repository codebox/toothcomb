import asyncio
import random
from pathlib import Path

import pysbd

from config import Config
from textsource.text_source import TextSource

_JITTER = 0.5


class FileTextSource(TextSource):
    def __init__(self, config: Config, file_path: str, delay_seconds: float = 0) -> None:
        super().__init__(config)
        self.file_path = Path(config.get("paths.uploads")) / file_path
        self.delay_seconds = delay_seconds
        self._target_words = int(config.get("pipeline.analysis_buffer_words"))
        self._max_words = int(config.get("text.chunk_max_words"))
        self._segmenter = pysbd.Segmenter(language="en", clean=False)

    def start(self) -> None:
        if self.delay_seconds > 0:
            asyncio.run(self._start_with_delay())
        else:
            self._start_immediate()

    def _start_immediate(self) -> None:
        for chunk in self._iter_chunks():
            self._callback(chunk)

    async def _start_with_delay(self) -> None:
        for chunk in self._iter_chunks():
            self._callback(chunk)
            jitter = self.delay_seconds * random.uniform(-_JITTER, _JITTER)
            await asyncio.sleep(self.delay_seconds + jitter)

    def _iter_chunks(self):
        """Yield text chunks sized to target_words, force-splitting anything over max_words."""
        text = self.file_path.read_text()
        sentences = [s.strip() for s in self._segmenter.segment(text) if s.strip()]

        buffer_words: list[str] = []

        for sentence in sentences:
            words = sentence.split()

            # Force-split any single sentence that alone exceeds max_words
            if len(words) > self._max_words:
                if buffer_words:
                    yield " ".join(buffer_words)
                    buffer_words = []
                for i in range(0, len(words), self._max_words):
                    yield " ".join(words[i:i + self._max_words])
                continue

            # Emit buffer first if adding this sentence would exceed max
            if buffer_words and len(buffer_words) + len(words) > self._max_words:
                yield " ".join(buffer_words)
                buffer_words = []

            buffer_words.extend(words)

            # Once target reached, emit and reset
            if len(buffer_words) >= self._target_words:
                yield " ".join(buffer_words)
                buffer_words = []

        # Trailing remainder (may be below target)
        if buffer_words:
            yield " ".join(buffer_words)
