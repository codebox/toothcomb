import logging
import threading

from audiosource.audio_source import AudioSource
from config import Config

log = logging.getLogger(__name__)


class StreamingAudioSource(AudioSource):
    """Receives audio chunks pushed from the browser via Socket.IO.
    Small fragments are buffered and emitted as properly-sized chunks
    split at silence boundaries, matching the MP3 source behaviour."""

    def __init__(self, config: Config) -> None:
        super().__init__(config)
        self._stopped = threading.Event()

    def start(self) -> None:
        """Block until stop() is called. Audio is pushed in via receive_audio()."""
        log.info("Streaming source waiting for audio")
        self._stopped.wait()
        log.info("Streaming source stopped")

    def receive_audio(self, audio_data: bytes) -> None:
        """Called by the web server when an audio chunk arrives from the browser."""
        self._feed(audio_data)

    def stop_stream(self) -> None:
        """Signal that the browser has stopped sending audio."""
        self._flush()
        self._stopped.set()
