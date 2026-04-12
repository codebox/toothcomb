import logging

import numpy as np
from faster_whisper import WhisperModel

from config import Config
from domain.transcription_result import TranscriptionResult, TranscriptionSegment
from transcriber.transcriber import Transcriber, SAMPLE_RATE

log = logging.getLogger(__name__)

_MODEL_MAP = {
    "tiny": "tiny",
    "base": "base",
    "small": "small",
    "medium": "medium",
    "large-v3": "large-v3",
}


class FasterWhisperTranscriber(Transcriber):
    def __init__(self, config: Config) -> None:
        super().__init__(config)
        model_name = config.get("whisper.model")
        model_id = _MODEL_MAP.get(model_name, model_name)
        device = config.get("whisper.device") or "auto"
        log.info("Using faster-whisper model: %s (device=%s)", model_id, device)
        self._model = WhisperModel(model_id, device=device)
        self._warmup()

    def _warmup(self) -> None:
        log.info("Warming up faster-whisper model...")
        silence = np.zeros(SAMPLE_RATE, dtype=np.float32)
        self._model.transcribe(silence)
        log.info("Faster-whisper model ready")

    def transcribe(self, audio_data: bytes) -> TranscriptionResult:
        audio_array = self.audio_to_float32(audio_data)
        segments_iter, _ = self._model.transcribe(audio_array)
        segments = []
        text_parts = []
        for s in segments_iter:
            segments.append(TranscriptionSegment(text=s.text.strip(), start=s.start, end=s.end))
            text_parts.append(s.text.strip())
        return TranscriptionResult(speaker="", text=" ".join(text_parts), segments=tuple(segments))
