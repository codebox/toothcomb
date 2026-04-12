import logging
import threading
from typing import Protocol

from pydub import AudioSegment
from pydub.silence import detect_silence

from config import Config

log = logging.getLogger(__name__)

# PCM output format matching what the Whisper transcriber expects.
# Both Mp3AudioSource and StreamingAudioSource must produce audio in this
# format. Changing these without updating the transcriber will break recognition.
PCM_SAMPLE_RATE = 16000
PCM_CHANNELS = 1
PCM_SAMPLE_WIDTH = 2  # bytes (16-bit)

_BYTES_PER_MS = PCM_SAMPLE_RATE * PCM_SAMPLE_WIDTH * PCM_CHANNELS // 1000


class AudioCallback(Protocol):
    def __call__(self, audio_data: bytes, chunk_offset_seconds: float, chunk_end_seconds: float) -> None: ...


class AudioSource:
    """Base class for audio sources. Buffers incoming PCM audio and emits
    chunks split at silence boundaries for optimal transcription quality."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._callback: AudioCallback = AudioSource._no_callback

        # Chunking parameters
        self._target_ms = int(config.get("audio.chunk_seconds")) * 1000
        self._max_ms = int(config.get("audio.chunk_max_seconds")) * 1000
        self._overlap_ms = int(config.get("audio.chunk_overlap_seconds")) * 1000
        self._silence_thresh_db = config.get("audio.silence_thresh_db")
        self._min_silence_ms = config.get("audio.min_silence_ms")
        self._silence_search_window_ms = config.get("audio.silence_search_window_ms")

        # Buffer state
        self._lock = threading.Lock()
        self._buffer = b""
        self._buffer_offset_ms = 0
        self._chunk_count = 0

        # Pause support — when cleared, _feed() blocks until set again
        self._running = threading.Event()
        self._running.set()

    @staticmethod
    def _no_callback(audio_data: bytes, chunk_offset_seconds: float, chunk_end_seconds: float) -> None:
        raise RuntimeError("No callback registered — call on_audio() before start()")

    def on_audio(self, callback: AudioCallback) -> None:
        self._callback = callback

    def start(self) -> None:
        raise NotImplementedError(f"{type(self).__name__} must implement start()")

    def pause(self) -> None:
        """Pause audio feeding — blocks _feed() until resume() is called."""
        self._running.clear()

    def resume(self) -> None:
        """Resume audio feeding after a pause."""
        self._running.set()

    def _feed(self, audio_data: bytes) -> None:
        """Feed PCM audio into the buffer. Emits chunks when enough audio has accumulated."""
        self._running.wait()
        with self._lock:
            self._buffer += audio_data
            self._try_emit()

    def _flush(self) -> None:
        """Emit any remaining audio in the buffer as a final chunk."""
        with self._lock:
            if not self._buffer:
                return
            duration_ms = self._pcm_duration_ms(self._buffer)
            if duration_ms == 0:
                return
            self._chunk_count += 1
            chunk_start_s = self._buffer_offset_ms / 1000.0
            chunk_end_s = chunk_start_s + duration_ms / 1000.0
            log.info("Chunk %d (final): %.1fs-%.1fs (%.1fs)",
                     self._chunk_count, chunk_start_s, chunk_end_s, duration_ms / 1000.0)
            self._callback(self._buffer, chunk_start_s, chunk_end_s)
            self._buffer_offset_ms += duration_ms
            self._buffer = b""

    def _try_emit(self) -> None:
        """Check if the buffer has enough audio to emit one or more chunks."""
        while True:
            buffer_ms = self._pcm_duration_ms(self._buffer)
            if buffer_ms < self._target_ms:
                break

            segment = AudioSegment(
                data=self._buffer,
                sample_width=PCM_SAMPLE_WIDTH,
                frame_rate=PCM_SAMPLE_RATE,
                channels=PCM_CHANNELS,
            )

            # Only run silence detection on the region where we'd actually split,
            # not the entire buffer. This avoids re-scanning audio we've already seen.
            search_start = max(0, self._target_ms - self._silence_search_window_ms)
            search_end = min(self._max_ms, len(segment))
            search_region = segment[search_start:search_end]

            silences = detect_silence(
                search_region,
                min_silence_len=self._min_silence_ms,
                silence_thresh=self._silence_thresh_db,
            )
            # Shift silence regions back to buffer-relative offsets
            silence_regions = [(search_start + s, search_start + e) for s, e in silences]

            best = self._best_silence_in(
                silence_regions, self._target_ms, search_end, self._silence_search_window_ms,
            )

            if best is not None:
                midpoint, silence_end = best
                self._emit_chunk(segment, midpoint, hard_cut=False, advance_to=silence_end)
            elif buffer_ms >= self._max_ms:
                self._emit_chunk(segment, self._max_ms, hard_cut=True)
            else:
                # Between target and max, no silence found — wait for more audio
                break

    def _emit_chunk(self, segment: AudioSegment, split_ms: int, hard_cut: bool,
                    advance_to: int | None = None) -> None:
        """Emit a single chunk from the buffer and advance past the split point.
        When splitting at a silence, advance_to should be the silence end so the
        remaining silence tail doesn't get re-detected on the next iteration."""
        advance_ms = advance_to if advance_to is not None else split_ms
        overlap_ms = self._overlap_ms if hard_cut else 0
        chunk_end_ms = min(split_ms + overlap_ms, len(segment))
        chunk = segment[:chunk_end_ms]

        self._chunk_count += 1
        chunk_start_s = self._buffer_offset_ms / 1000.0
        chunk_end_s = (self._buffer_offset_ms + split_ms) / 1000.0
        overlap_s = (chunk_end_ms - split_ms) / 1000.0

        log.info("Chunk %d: %.1fs-%.1fs (%.1fs%s%s)",
                 self._chunk_count, chunk_start_s, chunk_end_s, len(chunk) / 1000.0,
                 f", +{overlap_s:.1f}s overlap" if overlap_ms else "",
                 ", hard cut" if hard_cut else "")

        self._callback(chunk.raw_data, chunk_start_s, chunk_end_s)

        # Advance buffer past the silence end (not just the midpoint) to avoid
        # re-detecting the tail of the same silence region on the next iteration.
        remainder = segment[advance_ms:]
        self._buffer = remainder.raw_data
        self._buffer_offset_ms += advance_ms

    @staticmethod
    def _best_silence_in(silence_regions: list[tuple[int, int]], target_ms: int,
                         hard_limit_ms: int, search_window_ms: int) -> tuple[int, int] | None:
        """Find the silence region whose midpoint is closest to target_ms,
        but not beyond hard_limit_ms. Returns (midpoint, silence_end) or None."""
        best: tuple[int, int] | None = None
        best_dist = search_window_ms
        for start, end in silence_regions:
            mid = (start + end) // 2
            if mid > hard_limit_ms:
                continue
            dist = abs(mid - target_ms)
            if dist < best_dist:
                best = (mid, end)
                best_dist = dist
        return best

    @staticmethod
    def _pcm_duration_ms(pcm_data: bytes) -> int:
        return len(pcm_data) // _BYTES_PER_MS
