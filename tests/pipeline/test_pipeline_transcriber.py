from unittest.mock import patch

from pipeline.pipeline import Pipeline


class _FakeConfig:
    def __init__(self, values=None):
        self._values = values or {}

    def get(self, key, default=None):
        return self._values.get(key, default)


class TestTranscriberSelection:

    @patch("transcriber.parakeet_transcriber.ParakeetTranscriber")
    def test_parakeet_is_default(self, parakeet):
        assert Pipeline._build_transcriber(_FakeConfig()) is parakeet.return_value

    @patch("transcriber.local_whisper_transcriber.LocalWhisperTranscriber")
    def test_whisper_engine_uses_whisper_backend(self, whisper):
        config = _FakeConfig({"transcription.engine": "whisper", "whisper.backend": "mlx"})
        assert Pipeline._build_transcriber(config) is whisper.return_value

    @patch("transcriber.parakeet_transcriber.ParakeetTranscriber")
    def test_unknown_engine_gives_no_transcriber(self, parakeet):
        assert Pipeline._build_transcriber(_FakeConfig({"transcription.engine": "parakeat"})) is None
        parakeet.assert_not_called()

    @patch("transcriber.parakeet_transcriber.ParakeetTranscriber", side_effect=RuntimeError("no model"))
    def test_load_failure_gives_no_transcriber(self, parakeet):
        assert Pipeline._build_transcriber(_FakeConfig()) is None

    @patch("transcriber.parakeet_transcriber.ParakeetTranscriber")
    def test_demo_mode_loads_nothing(self, parakeet):
        assert Pipeline._build_transcriber(_FakeConfig({"demo": True})) is None
        parakeet.assert_not_called()
