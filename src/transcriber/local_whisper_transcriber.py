import logging

import mlx_whisper
import numpy as np

from config import Config
from domain.transcription_result import TranscriptionResult, TranscriptionSegment
from transcriber.transcriber import Transcriber, SAMPLE_RATE

log = logging.getLogger(__name__)

_MODEL_MAP = {
    "tiny": "mlx-community/whisper-tiny",
    "base": "mlx-community/whisper-base",
    "small": "mlx-community/whisper-small",
    "medium": "mlx-community/whisper-medium",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
}


class LocalWhisperTranscriber(Transcriber):
    def __init__(self, config: Config) -> None:
        super().__init__(config)
        model_name = config.get("whisper.model")
        self._model_repo = _MODEL_MAP.get(model_name, model_name)
        log.info("Using mlx-whisper model: %s", self._model_repo)
        self._warmup()

    def _warmup(self) -> None:
        """Run a tiny transcription to force model loading at startup."""
        log.info("Warming up whisper model...")
        silence = np.zeros(SAMPLE_RATE, dtype=np.float32)  # 1 second of silence at 16kHz
        mlx_whisper.transcribe(silence, path_or_hf_repo=self._model_repo)
        log.info("Whisper model ready")

    def transcribe(self, audio_data: bytes) -> TranscriptionResult:
        audio_array = self.audio_to_float32(audio_data)
        result = mlx_whisper.transcribe(audio_array, path_or_hf_repo=self._model_repo)
        text = result.get("text", "").strip()
        segments = tuple(
            TranscriptionSegment(text=s["text"].strip(), start=s["start"], end=s["end"])
            for s in result.get("segments", [])
        )
        return TranscriptionResult(speaker="", text=text, segments=segments)
