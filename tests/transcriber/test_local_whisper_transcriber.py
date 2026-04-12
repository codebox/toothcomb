import struct
from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from transcriber.local_whisper_transcriber import LocalWhisperTranscriber, _MODEL_MAP


# ---------- helpers ----------


class _FakeConfig:
    def __init__(self, model="tiny"):
        self._model = model

    def get(self, key, default=None):
        if key == "whisper.model":
            return self._model
        return default


def _whisper_result(text=" Hello world ", segments=None):
    result = {"text": text}
    if segments is not None:
        result["segments"] = segments
    return result


def _audio_bytes(*samples):
    """Pack int16 samples into bytes."""
    return struct.pack(f"<{len(samples)}h", *samples)


# ---------- model mapping ----------


class TestModelMapping:

    @patch("transcriber.local_whisper_transcriber.mlx_whisper")
    def test_known_models_mapped(self, mock_whisper):
        mock_whisper.transcribe.return_value = {"text": ""}
        for name, repo in _MODEL_MAP.items():
            t = LocalWhisperTranscriber(_FakeConfig(model=name))
            assert t._model_repo == repo

    @patch("transcriber.local_whisper_transcriber.mlx_whisper")
    def test_unknown_model_passes_through(self, mock_whisper):
        mock_whisper.transcribe.return_value = {"text": ""}
        t = LocalWhisperTranscriber(_FakeConfig(model="my-custom/whisper-fork"))
        assert t._model_repo == "my-custom/whisper-fork"

    @patch("transcriber.local_whisper_transcriber.mlx_whisper")
    def test_none_model_passes_through(self, mock_whisper):
        mock_whisper.transcribe.return_value = {"text": ""}
        t = LocalWhisperTranscriber(_FakeConfig(model=None))
        assert t._model_repo is None


# ---------- transcribe ----------


class TestTranscribe:

    @patch("transcriber.local_whisper_transcriber.mlx_whisper")
    def test_text_extracted_and_stripped(self, mock_whisper):
        mock_whisper.transcribe.return_value = _whisper_result(text="  Hello  ")
        t = LocalWhisperTranscriber(_FakeConfig())

        result = t.transcribe(_audio_bytes(0, 0))

        assert result.text == "Hello"
        assert result.speaker == ""

    @patch("transcriber.local_whisper_transcriber.mlx_whisper")
    def test_segments_extracted(self, mock_whisper):
        mock_whisper.transcribe.return_value = _whisper_result(
            text="Hello world",
            segments=[
                {"text": " Hello ", "start": 0.0, "end": 1.0},
                {"text": " world ", "start": 1.0, "end": 2.0},
            ],
        )
        t = LocalWhisperTranscriber(_FakeConfig())

        result = t.transcribe(_audio_bytes(0))

        assert len(result.segments) == 2
        assert result.segments[0].text == "Hello"
        assert result.segments[0].start == 0.0
        assert result.segments[0].end == 1.0
        assert result.segments[1].text == "world"
        assert result.segments[1].start == 1.0
        assert result.segments[1].end == 2.0

    @patch("transcriber.local_whisper_transcriber.mlx_whisper")
    def test_missing_segments_defaults_to_empty(self, mock_whisper):
        mock_whisper.transcribe.return_value = {"text": "Hello"}
        t = LocalWhisperTranscriber(_FakeConfig())

        result = t.transcribe(_audio_bytes(0))

        assert result.segments == ()

    @patch("transcriber.local_whisper_transcriber.mlx_whisper")
    def test_missing_text_defaults_to_empty(self, mock_whisper):
        mock_whisper.transcribe.return_value = {}
        t = LocalWhisperTranscriber(_FakeConfig())

        result = t.transcribe(_audio_bytes(0))

        assert result.text == ""

    @patch("transcriber.local_whisper_transcriber.mlx_whisper")
    def test_audio_normalised_to_float32(self, mock_whisper):
        mock_whisper.transcribe.return_value = _whisper_result(text="ok")
        t = LocalWhisperTranscriber(_FakeConfig())

        # Max positive int16 = 32767, should normalise to ~1.0
        audio = _audio_bytes(32767, -32768, 0)
        t.transcribe(audio)

        call_args = mock_whisper.transcribe.call_args
        audio_array = call_args[0][0]
        assert audio_array.dtype == np.float32
        assert audio_array[0] == pytest.approx(32767 / 32768.0)
        assert audio_array[1] == pytest.approx(-1.0)
        assert audio_array[2] == 0.0

    @patch("transcriber.local_whisper_transcriber.mlx_whisper")
    def test_model_repo_passed_to_whisper(self, mock_whisper):
        mock_whisper.transcribe.return_value = _whisper_result(text="ok")
        t = LocalWhisperTranscriber(_FakeConfig(model="small"))

        t.transcribe(_audio_bytes(0))

        call_args = mock_whisper.transcribe.call_args
        assert call_args[1]["path_or_hf_repo"] == "mlx-community/whisper-small"

    @patch("transcriber.local_whisper_transcriber.mlx_whisper")
    def test_empty_segments_list(self, mock_whisper):
        mock_whisper.transcribe.return_value = _whisper_result(text="ok", segments=[])
        t = LocalWhisperTranscriber(_FakeConfig())

        result = t.transcribe(_audio_bytes(0))

        assert result.segments == ()


# ---------- base class ----------


def test_base_transcriber_not_implemented():
    from transcriber.transcriber import Transcriber
    t = Transcriber(_FakeConfig())
    with pytest.raises(NotImplementedError):
        t.transcribe(b"audio")
