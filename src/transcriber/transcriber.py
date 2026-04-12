import numpy as np

from config import Config
from domain.transcription_result import TranscriptionResult

SAMPLE_RATE = 16000
INT16_MAX = 32768


class Transcriber:
    def __init__(self, config: Config):
        self._config = config

    @staticmethod
    def audio_to_float32(audio_data: bytes) -> np.ndarray:
        return np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / INT16_MAX

    def transcribe(self, audio_data: bytes) -> TranscriptionResult:
        raise NotImplementedError(f"{type(self).__name__} must implement transcribe()")
