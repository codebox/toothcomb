import logging
from pathlib import Path

from pydub import AudioSegment

from audiosource.audio_source import AudioSource, PCM_SAMPLE_RATE, PCM_CHANNELS, PCM_SAMPLE_WIDTH
from config import Config

log = logging.getLogger(__name__)


class Mp3AudioSource(AudioSource):
    def __init__(self, config: Config, file_path: str, start_offset_seconds: float = 0) -> None:
        super().__init__(config)
        self.file_path = Path(config.get("paths.uploads")) / file_path
        self._start_offset_seconds = start_offset_seconds

    def start(self) -> None:
        log.info("Loading MP3 from %s", self.file_path)
        audio = AudioSegment.from_mp3(self.file_path)
        audio = audio.set_frame_rate(PCM_SAMPLE_RATE).set_channels(PCM_CHANNELS).set_sample_width(PCM_SAMPLE_WIDTH)

        pos = int(self._start_offset_seconds * 1000)
        if pos > 0:
            log.info("Resuming from offset %.1fs (skipping %dms)", self._start_offset_seconds, pos)
        log.info("Loaded %.1fs of audio, feeding in %ds segments", len(audio) / 1000, self._max_ms / 1000)

        # Feed audio incrementally so the buffer never grows excessively large
        while pos < len(audio):
            end = min(pos + self._max_ms, len(audio))
            self._feed(audio[pos:end].raw_data)
            pos = end

        self._flush()
