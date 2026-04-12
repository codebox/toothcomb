import threading

from pydub import AudioSegment
from pydub.generators import Sine

from audiosource.audio_source import PCM_SAMPLE_RATE, PCM_CHANNELS, PCM_SAMPLE_WIDTH
from audiosource.streaming_audio_source import StreamingAudioSource


def _make_config():
    values = {
        "audio.chunk_seconds": 2,
        "audio.chunk_max_seconds": 4,
        "audio.chunk_overlap_seconds": 1,
        "audio.silence_thresh_db": -40,
        "audio.min_silence_ms": 200,
        "audio.silence_search_window_ms": 2000,
    }

    class FakeConfig:
        def get(self, key, default=None):
            return values.get(key, default)

    return FakeConfig()


def _pcm_tone(duration_ms: int) -> bytes:
    return (Sine(440)
            .to_audio_segment(duration=duration_ms)
            .set_frame_rate(PCM_SAMPLE_RATE)
            .set_channels(PCM_CHANNELS)
            .set_sample_width(PCM_SAMPLE_WIDTH)
            .raw_data)


def test_start_blocks_until_stop_and_flush_emits_remainder():
    """start() should block until stop_stream() is called.
    stop_stream() should flush the buffer before unblocking."""
    source = StreamingAudioSource(_make_config())
    chunks = []
    source.on_audio(lambda data, start, end: chunks.append((data, start, end)))

    started = threading.Event()
    finished = threading.Event()

    def run_source():
        started.set()
        source.start()
        finished.set()

    t = threading.Thread(target=run_source, daemon=True)
    t.start()
    started.wait(timeout=1)

    # Feed 1s of audio — under target, so nothing should emit yet
    source.receive_audio(_pcm_tone(1000))
    assert len(chunks) == 0

    assert not finished.is_set(), "start() should still be blocking"

    # stop_stream should flush the buffered audio then unblock start()
    source.stop_stream()
    finished.wait(timeout=1)

    assert finished.is_set(), "start() should have returned after stop_stream()"
    assert len(chunks) == 1, f"Expected 1 flushed chunk, got {len(chunks)}"
