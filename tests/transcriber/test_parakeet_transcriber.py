import struct
from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from transcriber.parakeet_transcriber import (ParakeetTranscriber, DEFAULT_MODEL, MPS_PAD_SECONDS,
                                              _pick_device)


# ---------- helpers ----------


class _FakeConfig:
    def __init__(self, model=None, device="cpu"):
        self._values = {"parakeet.model": model, "parakeet.device": device}

    def get(self, key, default=None):
        return self._values.get(key, default)


def _audio_bytes(*samples):
    """Pack int16 samples into bytes."""
    return struct.pack(f"<{len(samples)}h", *samples)


def _tokens(*spans):
    return [{"token": "x", "start": start, "end": end} for start, end in spans]


@pytest.fixture
def hf():
    """Patches the transformers classes; decode() returns whatever `hf.decoded` holds."""
    with patch("transcriber.parakeet_transcriber.AutoProcessor") as processor_cls, \
            patch("transcriber.parakeet_transcriber.AutoModelForTDT") as model_cls:
        processor = processor_cls.from_pretrained.return_value
        model = model_cls.from_pretrained.return_value.to.return_value.eval.return_value
        state = MagicMock(processor_cls=processor_cls, model_cls=model_cls, processor=processor, model=model)
        state.decoded = ([""], [[]])
        processor.decode.side_effect = lambda *a, **k: state.decoded
        yield state


# ---------- construction ----------


class TestConstruction:

    def test_default_model(self, hf):
        ParakeetTranscriber(_FakeConfig())
        hf.processor_cls.from_pretrained.assert_called_once_with(DEFAULT_MODEL)
        hf.model_cls.from_pretrained.assert_called_once_with(DEFAULT_MODEL)

    def test_configured_model(self, hf):
        ParakeetTranscriber(_FakeConfig(model="nvidia/parakeet-tdt-0.6b-v2"))
        hf.model_cls.from_pretrained.assert_called_once_with("nvidia/parakeet-tdt-0.6b-v2")

    def test_model_moved_to_device(self, hf):
        ParakeetTranscriber(_FakeConfig(device="mps"))
        hf.model_cls.from_pretrained.return_value.to.assert_called_once_with("mps")

    def test_warms_up_on_construction(self, hf):
        ParakeetTranscriber(_FakeConfig())
        hf.model.generate.assert_called_once()


# ---------- device selection ----------


class TestPickDevice:

    def test_explicit_device_used(self):
        assert _pick_device("cpu") == "cpu"

    @patch("transcriber.parakeet_transcriber.torch")
    def test_auto_prefers_cuda(self, mock_torch):
        mock_torch.cuda.is_available.return_value = True
        assert _pick_device("auto") == "cuda"

    @patch("transcriber.parakeet_transcriber.torch")
    def test_auto_then_mps(self, mock_torch):
        mock_torch.cuda.is_available.return_value = False
        mock_torch.backends.mps.is_available.return_value = True
        assert _pick_device("auto") == "mps"

    @patch("transcriber.parakeet_transcriber.torch")
    def test_auto_falls_back_to_cpu(self, mock_torch):
        mock_torch.cuda.is_available.return_value = False
        mock_torch.backends.mps.is_available.return_value = False
        assert _pick_device("auto") == "cpu"


# ---------- transcribe ----------


class TestTranscribe:

    def test_text_stripped_and_one_segment_spanning_tokens(self, hf):
        t = ParakeetTranscriber(_FakeConfig())
        hf.decoded = (["  Hello world. "], [_tokens((0.24, 0.5), (0.5, 1.1))])

        result = t.transcribe(_audio_bytes(0, 0))

        assert result.text == "Hello world."
        assert result.speaker == ""
        assert len(result.segments) == 1
        assert result.segments[0].text == "Hello world."
        assert result.segments[0].start == 0.24
        assert result.segments[0].end == 1.1

    def test_silence_gives_empty_result(self, hf):
        t = ParakeetTranscriber(_FakeConfig())
        hf.decoded = ([""], [[]])

        result = t.transcribe(_audio_bytes(0))

        assert result.text == ""
        assert result.segments == ()

    def test_audio_normalised_to_float32(self, hf):
        t = ParakeetTranscriber(_FakeConfig())

        t.transcribe(_audio_bytes(32767, -32768, 0))

        audio_array = hf.processor.call_args[0][0][0]
        assert audio_array.dtype == np.float32
        assert audio_array[0] == pytest.approx(32767 / 32768.0)
        assert audio_array[1] == pytest.approx(-1.0)
        assert audio_array[2] == 0.0
        assert hf.processor.call_args[1]["sampling_rate"] == 16000

    def test_durations_passed_to_decode_for_timestamps(self, hf):
        t = ParakeetTranscriber(_FakeConfig())

        t.transcribe(_audio_bytes(0))

        output = hf.model.generate.return_value
        assert hf.processor.decode.call_args[0][0] is output.sequences.cpu.return_value
        assert hf.processor.decode.call_args[1]["durations"] is output.durations.cpu.return_value

    def test_mps_pads_to_whole_pad_length(self, hf):
        t = ParakeetTranscriber(_FakeConfig(device="mps"))

        t.transcribe(_audio_bytes(*([0] * (MPS_PAD_SECONDS * 16000 + 1))))

        kwargs = hf.processor.call_args[1]
        assert kwargs["padding"] == "max_length"
        assert kwargs["max_length"] == 2 * MPS_PAD_SECONDS * 16000

    def test_cpu_does_not_pad(self, hf):
        t = ParakeetTranscriber(_FakeConfig(device="cpu"))

        t.transcribe(_audio_bytes(0, 0, 0))

        assert "padding" not in hf.processor.call_args[1]
