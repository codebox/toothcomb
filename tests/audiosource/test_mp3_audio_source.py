import tempfile
from pathlib import Path

from pydub import AudioSegment
from pydub.generators import Sine

from audiosource.audio_source import PCM_SAMPLE_RATE, PCM_CHANNELS, PCM_SAMPLE_WIDTH
from audiosource.mp3_audio_source import Mp3AudioSource


def _make_config(uploads_dir: str):
    values = {
        "audio.chunk_seconds": 2,
        "audio.chunk_max_seconds": 4,
        "audio.chunk_overlap_seconds": 1,
        "audio.silence_thresh_db": -40,
        "audio.min_silence_ms": 200,
        "audio.silence_search_window_ms": 2000,
        "paths.uploads": uploads_dir,
    }

    class FakeConfig:
        def get(self, key, default=None):
            return values.get(key, default)

    return FakeConfig()


def test_loads_mp3_and_emits_chunks():
    """start() should read the MP3 file, convert to PCM, and emit chunks."""
    with tempfile.TemporaryDirectory() as tmp:
        # Create a 5s MP3 file
        audio = Sine(440).to_audio_segment(duration=5000)
        mp3_path = Path(tmp) / "test.mp3"
        audio.export(mp3_path, format="mp3")

        config = _make_config(tmp)
        source = Mp3AudioSource(config, "test.mp3")
        chunks = []
        source.on_audio(lambda data, start, end: chunks.append((data, start, end)))

        source.start()

        assert len(chunks) >= 2, f"Expected at least 2 chunks from 5s audio, got {len(chunks)}"

        _, first_start, _ = chunks[0]
        assert first_start == 0.0

        _, _, last_end = chunks[-1]
        assert abs(last_end - 5.0) < 0.1, f"Expected last chunk to end near 5s, got {last_end:.2f}s"
