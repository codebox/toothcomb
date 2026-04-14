from unittest.mock import patch, AsyncMock

import pytest

from textsource.file_text_source import FileTextSource


# ---------- helpers ----------


class _FakeConfig:
    def __init__(self, uploads_path="/tmp/uploads", target_words=30, max_words=90):
        self._uploads = uploads_path
        self._target_words = target_words
        self._max_words = max_words

    def get(self, key, default=None):
        if key == "paths.uploads":
            return self._uploads
        if key == "pipeline.analysis_buffer_words":
            return self._target_words
        if key == "text.chunk_max_words":
            return self._max_words
        return default


def _make_source(tmp_path, text, delay=0, target_words=30, max_words=90):
    """Create a FileTextSource backed by a real temp file."""
    f = tmp_path / "input.txt"
    f.write_text(text)
    config = _FakeConfig(uploads_path=str(tmp_path),
                         target_words=target_words, max_words=max_words)
    return FileTextSource(config, "input.txt", delay_seconds=delay)


# ---------- chunking ----------


class TestChunking:

    def test_single_short_sentence_emitted_as_trailing(self, tmp_path):
        # Below target → emitted as trailing remainder
        source = _make_source(tmp_path, "Hello world.")
        received = []
        source.on_text(received.append)
        source.start()
        assert received == ["Hello world."]

    def test_short_sentences_accumulate_to_target(self, tmp_path):
        # Target=3: "One. Two. Three." = 3 words → one chunk
        source = _make_source(tmp_path, "One. Two. Three.", target_words=3)
        received = []
        source.on_text(received.append)
        source.start()
        assert received == ["One. Two. Three."]

    def test_accumulates_until_target_then_emits(self, tmp_path):
        # Target=4, each sentence is 2 words → pairs emitted
        text = "Alpha beta. Gamma delta. Epsilon zeta. Eta theta."
        source = _make_source(tmp_path, text, target_words=4)
        received = []
        source.on_text(received.append)
        source.start()
        assert received == ["Alpha beta. Gamma delta.", "Epsilon zeta. Eta theta."]

    def test_trailing_remainder_below_target(self, tmp_path):
        # Target=4, trailing sentence of 2 words emitted as short final chunk
        text = "Alpha beta. Gamma delta. Epsilon zeta."
        source = _make_source(tmp_path, text, target_words=4)
        received = []
        source.on_text(received.append)
        source.start()
        assert received == ["Alpha beta. Gamma delta.", "Epsilon zeta."]

    def test_force_split_oversize_sentence(self, tmp_path):
        # Single sentence exceeds max_words → force-split on word boundaries
        long_sentence = " ".join(f"w{i}" for i in range(10)) + "."
        source = _make_source(tmp_path, long_sentence, target_words=3, max_words=4)
        received = []
        source.on_text(received.append)
        source.start()
        # 10 words split into chunks of max 4: [4, 4, 2]
        assert received == [
            "w0 w1 w2 w3",
            "w4 w5 w6 w7",
            "w8 w9.",
        ]

    def test_buffer_flushed_before_oversize_sentence(self, tmp_path):
        # Accumulated buffer is emitted before an oversize sentence gets force-split
        long = " ".join(f"w{i}" for i in range(6)) + "."
        text = f"Alpha beta. {long}"
        source = _make_source(tmp_path, text, target_words=10, max_words=4)
        received = []
        source.on_text(received.append)
        source.start()
        assert received[0] == "Alpha beta."
        assert received[1:] == ["w0 w1 w2 w3", "w4 w5."]

    def test_buffer_emitted_if_adding_would_exceed_max(self, tmp_path):
        # Buffer near max; next sentence would overflow → buffer emitted first
        text = "one two three four. five six seven."
        source = _make_source(tmp_path, text, target_words=100, max_words=5)
        received = []
        source.on_text(received.append)
        source.start()
        # First sentence = 4 words, fits; second = 3 words, would push to 7 > max=5
        assert received == ["one two three four.", "five six seven."]


# ---------- sentence boundary detection (via pysbd) ----------


class TestSentenceBoundaries:

    def test_abbreviation_not_split(self, tmp_path):
        # pysbd correctly keeps the acronym intact
        source = _make_source(tmp_path, "The U.S.A. is large.", target_words=100)
        received = []
        source.on_text(received.append)
        source.start()
        assert received == ["The U.S.A. is large."]

    def test_decimal_not_split(self, tmp_path):
        source = _make_source(tmp_path, "Pi is 3.14 approximately.", target_words=100)
        received = []
        source.on_text(received.append)
        source.start()
        assert received == ["Pi is 3.14 approximately."]

    def test_title_abbreviation_not_split(self, tmp_path):
        source = _make_source(tmp_path, "Dr. Smith said hello.", target_words=100)
        received = []
        source.on_text(received.append)
        source.start()
        assert received == ["Dr. Smith said hello."]

    def test_question_and_exclamation_split(self, tmp_path):
        # Target=2: each 2-word sentence emits individually
        source = _make_source(tmp_path, "Really now? Yes indeed! Okay then.", target_words=2)
        received = []
        source.on_text(received.append)
        source.start()
        assert received == ["Really now?", "Yes indeed!", "Okay then."]


# ---------- edge cases ----------


class TestEdgeCases:

    def test_empty_file(self, tmp_path):
        source = _make_source(tmp_path, "")
        received = []
        source.on_text(received.append)
        source.start()
        assert received == []

    def test_whitespace_only_file(self, tmp_path):
        source = _make_source(tmp_path, "   \n\n  ")
        received = []
        source.on_text(received.append)
        source.start()
        assert received == []

    def test_no_punctuation_force_split_if_long(self, tmp_path):
        # No punctuation and text longer than max_words → force-split
        text = " ".join(f"w{i}" for i in range(8))
        source = _make_source(tmp_path, text, target_words=3, max_words=4)
        received = []
        source.on_text(received.append)
        source.start()
        assert received == ["w0 w1 w2 w3", "w4 w5 w6 w7"]

    def test_no_punctuation_short_stays_whole(self, tmp_path):
        source = _make_source(tmp_path, "no punctuation here", target_words=100, max_words=100)
        received = []
        source.on_text(received.append)
        source.start()
        assert received == ["no punctuation here"]


# ---------- immediate vs delayed ----------


class TestStartBranching:

    def test_immediate_when_no_delay(self, tmp_path):
        source = _make_source(tmp_path, "One two. Three four.", delay=0, target_words=2)
        received = []
        source.on_text(received.append)
        source.start()
        assert received == ["One two.", "Three four."]

    def test_delayed_calls_callback_for_each_chunk(self, tmp_path):
        source = _make_source(tmp_path, "One two. Three four. Five six.",
                              delay=0.5, target_words=2)
        received = []
        source.on_text(received.append)

        with patch("textsource.file_text_source.asyncio.sleep", new_callable=AsyncMock):
            source.start()

        assert received == ["One two.", "Three four.", "Five six."]

    def test_delayed_sleeps_between_chunks(self, tmp_path):
        source = _make_source(tmp_path, "One two. Three four.",
                              delay=1.0, target_words=2)
        source.on_text(lambda _: None)

        with patch("textsource.file_text_source.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with patch("textsource.file_text_source.random.uniform", return_value=0.0):
                source.start()

        # Should sleep after each chunk (2 chunks = 2 sleeps)
        assert mock_sleep.call_count == 2
        for call in mock_sleep.call_args_list:
            assert call[0][0] == 1.0

    def test_delayed_jitter_applied(self, tmp_path):
        source = _make_source(tmp_path, "One two. Three four.",
                              delay=2.0, target_words=2)
        source.on_text(lambda _: None)

        with patch("textsource.file_text_source.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            # uniform returns 0.25, so jitter = 2.0 * 0.25 = 0.5, total = 2.5
            with patch("textsource.file_text_source.random.uniform", return_value=0.25):
                source.start()

        for call in mock_sleep.call_args_list:
            assert call[0][0] == pytest.approx(2.5)


# ---------- path construction ----------


class TestPathConstruction:

    def test_path_joins_config_and_filename(self, tmp_path):
        config = _FakeConfig(uploads_path=str(tmp_path))
        source = FileTextSource(config, "my_file.txt")
        assert source.file_path == tmp_path / "my_file.txt"

    def test_file_not_found_raises(self, tmp_path):
        config = _FakeConfig(uploads_path=str(tmp_path))
        source = FileTextSource(config, "nonexistent.txt")
        source.on_text(lambda _: None)
        with pytest.raises(FileNotFoundError):
            source.start()
