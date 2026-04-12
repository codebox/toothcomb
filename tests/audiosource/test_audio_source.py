import pytest
from pydub import AudioSegment
from pydub.generators import Sine

from audiosource.audio_source import AudioSource, PCM_SAMPLE_RATE, PCM_CHANNELS, PCM_SAMPLE_WIDTH

# ---------- helpers ----------

# Use short chunk sizes so tests run fast and audio fixtures are small.
_TARGET_S = 2
_MAX_S = 4
_OVERLAP_S = 1

def _make_config():
    """Return a Config-like object with test-friendly chunk sizes."""
    values = {
        "audio.chunk_seconds": _TARGET_S,
        "audio.chunk_max_seconds": _MAX_S,
        "audio.chunk_overlap_seconds": _OVERLAP_S,
        "audio.silence_thresh_db": -40,
        "audio.min_silence_ms": 200,
        "audio.silence_search_window_ms": 2000,
    }

    class FakeConfig:
        def get(self, key, default=None):
            return values.get(key, default)

    return FakeConfig()


class _TestableAudioSource(AudioSource):
    """Concrete subclass so we can instantiate AudioSource for testing."""
    def start(self):
        pass


def _make_source():
    """Create a source with a callback that collects emitted chunks."""
    source = _TestableAudioSource(_make_config())
    chunks = []
    source.on_audio(lambda data, start, end: chunks.append((data, start, end)))
    return source, chunks


def _tone(duration_ms: int) -> AudioSegment:
    """Generate a sine-wave tone in the target PCM format."""
    return (Sine(440)
            .to_audio_segment(duration=duration_ms)
            .set_frame_rate(PCM_SAMPLE_RATE)
            .set_channels(PCM_CHANNELS)
            .set_sample_width(PCM_SAMPLE_WIDTH))


def _silence(duration_ms: int) -> AudioSegment:
    """Generate silence in the target PCM format."""
    return (AudioSegment.silent(duration=duration_ms)
            .set_frame_rate(PCM_SAMPLE_RATE)
            .set_channels(PCM_CHANNELS)
            .set_sample_width(PCM_SAMPLE_WIDTH))


def _pcm(segment: AudioSegment) -> bytes:
    return segment.raw_data


# ---------- tests ----------

def test_splits_at_silence():
    """Feed audio that has a silence near the target boundary.
    Expects a split at the silence rather than a hard cut, with no overlap."""
    source, chunks = _make_source()

    # 1.8s tone + 0.5s silence + 3s tone = 5.3s total
    # Target is 2s, silence midpoint is at ~2.05s, well within search window.
    audio = _tone(1800) + _silence(500) + _tone(3000)
    source._feed(_pcm(audio))
    source._flush()

    assert len(chunks) == 2, f"Expected 2 chunks, got {len(chunks)}"

    # First chunk should start at 0
    _, start1, end1 = chunks[0]
    assert start1 == 0.0

    # Split should land near the silence (~2.05s), not at the hard max (4s)
    assert 1.5 < end1 < 2.5, f"Expected split near silence (~2.05s), got {end1:.2f}s"

    # First chunk audio should NOT have overlap (silence split, not hard cut)
    first_chunk_bytes = chunks[0][0]
    first_chunk_ms = len(first_chunk_bytes) / (PCM_SAMPLE_RATE * PCM_SAMPLE_WIDTH * PCM_CHANNELS) * 1000
    split_ms = end1 * 1000
    assert first_chunk_ms < split_ms + 100, "Silence split should not include overlap"

    # Second chunk starts at the silence end (buffer advances past the whole
    # silence to avoid re-detection). The gap is the skipped silence tail.
    _, start2, end2 = chunks[1]
    assert start2 > end1, "Second chunk should start after first chunk ends"
    assert start2 - end1 < 0.5, f"Gap should be at most the silence duration, got {start2 - end1:.2f}s"


def test_hard_cut_with_overlap_when_no_silence():
    """Feed continuous tone with no silence at all.
    Expects a hard cut at max_ms with overlap appended."""
    source, chunks = _make_source()

    # 6s of uninterrupted tone — no silence anywhere
    audio = _tone(6000)
    source._feed(_pcm(audio))
    source._flush()

    assert len(chunks) == 2, f"Expected 2 chunks, got {len(chunks)}"

    # First chunk should hard-cut at max (4s)
    _, start1, end1 = chunks[0]
    assert start1 == 0.0
    assert abs(end1 - _MAX_S) < 0.01, f"Expected hard cut at {_MAX_S}s, got {end1:.2f}s"

    # First chunk audio should include overlap beyond the split point
    first_chunk_bytes = chunks[0][0]
    first_chunk_s = len(first_chunk_bytes) / (PCM_SAMPLE_RATE * PCM_SAMPLE_WIDTH * PCM_CHANNELS)
    assert first_chunk_s > _MAX_S, f"Hard cut chunk should include overlap, got {first_chunk_s:.2f}s"
    assert first_chunk_s <= _MAX_S + _OVERLAP_S + 0.01


def test_under_target_buffers_until_flush():
    """Feed audio shorter than the target. Nothing should emit until flush."""
    source, chunks = _make_source()

    # 1s of tone — well under the 2s target
    audio = _tone(1000)
    source._feed(_pcm(audio))

    assert len(chunks) == 0, "Should not emit anything before target is reached"

    source._flush()

    assert len(chunks) == 1, "Flush should emit the buffered audio"
    _, start, end = chunks[0]
    assert start == 0.0
    assert abs(end - 1.0) < 0.05


def test_multiple_chunks_from_single_feed():
    """A large feed should produce multiple chunks in one _try_emit loop."""
    source, chunks = _make_source()

    # 5.6s: tone-silence-tone-silence-tone with silences near each target boundary
    # Split at ~2.05s, then ~4.1s, remainder ~1.5s flushed → 3 chunks
    audio = _tone(1800) + _silence(500) + _tone(1800) + _silence(500) + _tone(1000)
    source._feed(_pcm(audio))
    source._flush()

    assert len(chunks) == 3, f"Expected 3 chunks, got {len(chunks)}"

    # Chunks should be ordered with small gaps (skipped silence tails)
    for i in range(1, len(chunks)):
        _, prev_start, prev_end = chunks[i - 1]
        _, curr_start, curr_end = chunks[i]
        assert curr_start >= prev_end, (
            f"Chunk {i+1} overlaps chunk {i}: {prev_end:.3f} -> {curr_start:.3f}")
        assert curr_start - prev_end < 0.5, (
            f"Gap between chunk {i} and {i+1} too large: {prev_end:.3f} -> {curr_start:.3f}")


def test_incremental_feeding():
    """Many small feeds (simulating streaming) should accumulate and
    eventually emit a chunk once the buffer reaches target size."""
    source, chunks = _make_source()

    # Feed 3s of tone in 100ms increments — should not emit until target (2s)
    # but since there's no silence, should wait until max (4s) then hard cut.
    fragment = _pcm(_tone(100))
    for _ in range(30):
        source._feed(fragment)

    # Shouldn't have emitted yet — 3s is between target and max with no silence
    assert len(chunks) == 0, f"Expected 0 chunks at 3s, got {len(chunks)}"

    # Feed another 2s to push past max (5s total)
    for _ in range(20):
        source._feed(fragment)

    assert len(chunks) == 1, f"Expected 1 chunk after exceeding max, got {len(chunks)}"
    _, start, end = chunks[0]
    assert start == 0.0
    assert abs(end - _MAX_S) < 0.05

    source._flush()
    assert len(chunks) == 2


def test_waits_between_target_and_max_for_silence():
    """When the buffer is between target and max with no silence,
    _try_emit should not emit — it waits for more audio."""
    source, chunks = _make_source()

    # Feed 3s of continuous tone — past target (2s) but under max (4s)
    source._feed(_pcm(_tone(3000)))

    assert len(chunks) == 0, "Should wait for silence or max before emitting"

    # Now feed a silence followed by more tone — should trigger a split
    source._feed(_pcm(_silence(300) + _tone(1000)))
    assert len(chunks) == 1, f"Expected 1 chunk after silence arrived, got {len(chunks)}"

    # The split should be near the silence (~3.15s), not at target or max
    _, start, end = chunks[0]
    assert 2.5 < end < 3.5, f"Expected split near silence, got {end:.2f}s"


def test_flush_with_empty_buffer_is_noop():
    """Calling flush on an empty buffer should not emit anything."""
    source, chunks = _make_source()
    source._flush()
    assert len(chunks) == 0

    # Also: feed + emit + flush with nothing remaining
    source._feed(_pcm(_tone(5000)))
    source._flush()
    initial_count = len(chunks)

    # Extra flush should be a no-op
    source._flush()
    assert len(chunks) == initial_count


def test_no_callback_raises():
    """Feeding audio without registering a callback should raise RuntimeError."""
    source = _TestableAudioSource(_make_config())
    # Must exceed max (4s) with no silence to force emission and trigger the callback
    audio = _pcm(_tone(5000))
    with pytest.raises(RuntimeError, match="No callback registered"):
        source._feed(audio)


def test_chooses_silence_closest_to_target():
    """When multiple silences exist, the split should happen at the one
    closest to the target, not the first or last."""
    source, chunks = _make_source()

    # Silence at 1.0s (too early), 2.1s (close to target), 3.5s (further from target)
    audio = (_tone(800) + _silence(300) +
             _tone(800) + _silence(300) +
             _tone(1100) + _silence(300) +
             _tone(2400))
    source._feed(_pcm(audio))
    source._flush()

    assert len(chunks) >= 2

    # First split should be near 2.1s (the silence closest to target=2s),
    # not at the 1.0s silence
    _, _, end1 = chunks[0]
    assert 1.8 < end1 < 2.5, f"Expected split near 2.1s silence, got {end1:.2f}s"


def test_chunk_timestamps_span_full_audio():
    """The first chunk should start at 0 and the last should end at the
    total audio duration."""
    source, chunks = _make_source()

    audio = _tone(7000)
    source._feed(_pcm(audio))
    source._flush()

    assert len(chunks) >= 2

    _, first_start, _ = chunks[0]
    assert first_start == 0.0

    _, _, last_end = chunks[-1]
    assert abs(last_end - 7.0) < 0.05, f"Expected last chunk to end at ~7s, got {last_end:.2f}s"

    # All chunks should be contiguous
    for i in range(1, len(chunks)):
        _, _, prev_end = chunks[i - 1]
        _, curr_start, _ = chunks[i]
        assert abs(curr_start - prev_end) < 0.01
