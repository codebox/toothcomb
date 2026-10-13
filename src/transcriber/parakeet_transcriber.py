import logging

import numpy as np
import torch
from transformers import AutoModelForTDT, AutoProcessor

from config import Config
from domain.transcription_result import TranscriptionResult, TranscriptionSegment
from transcriber.transcriber import Transcriber, SAMPLE_RATE

log = logging.getLogger(__name__)

DEFAULT_MODEL = "nvidia/parakeet-tdt-0.6b-v3"
# The Apple GPU (MPS) backend recompiles its kernels for every new input length, and audio chunks
# vary in length, so on MPS each chunk is padded up to a whole number of these to limit the
# number of distinct lengths.
MPS_PAD_SECONDS = 2


def _pick_device(requested: str) -> str:
    if requested and requested != "auto":
        return requested
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class ParakeetTranscriber(Transcriber):
    """NVIDIA Parakeet TDT, run through Hugging Face transformers using NVIDIA's own published weights."""

    def __init__(self, config: Config) -> None:
        super().__init__(config)
        model_id = config.get("parakeet.model") or DEFAULT_MODEL
        self._device = _pick_device(config.get("parakeet.device") or "auto")
        log.info("Using Parakeet model: %s (device=%s)", model_id, self._device)
        self._processor = AutoProcessor.from_pretrained(model_id)
        self._model = AutoModelForTDT.from_pretrained(model_id).to(self._device).eval()
        self._warmup()

    def _warmup(self) -> None:
        log.info("Warming up Parakeet model...")
        self._run(np.zeros(SAMPLE_RATE, dtype=np.float32))
        log.info("Parakeet model ready")

    def _run(self, audio_array: np.ndarray) -> tuple[str, list[dict]]:
        padding = {}
        if self._device == "mps":
            pad_samples = MPS_PAD_SECONDS * SAMPLE_RATE
            padding = {"padding": "max_length", "max_length": -(-len(audio_array) // pad_samples) * pad_samples}
        inputs = self._processor([audio_array], sampling_rate=SAMPLE_RATE, **padding)
        inputs.to(self._device, dtype=self._model.dtype)
        with torch.inference_mode():
            output = self._model.generate(**inputs, return_dict_in_generate=True)
        # Timestamp decoding reads the tensors element by element, which is much slower on a GPU
        texts, timestamps = self._processor.decode(output.sequences.cpu(), durations=output.durations.cpu(),
                                                   skip_special_tokens=True)
        return texts[0], timestamps[0]

    def transcribe(self, audio_data: bytes) -> TranscriptionResult:
        text, tokens = self._run(self.audio_to_float32(audio_data))
        text = text.strip()
        # Parakeet times individual tokens; the pipeline only needs where the speech in this
        # chunk starts and ends, so the whole chunk becomes one segment.
        segments = ()
        if text and tokens:
            segments = (TranscriptionSegment(text=text, start=tokens[0]["start"], end=tokens[-1]["end"]),)
        return TranscriptionResult(speaker="", text=text, segments=segments)
