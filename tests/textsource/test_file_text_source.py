from unittest.mock import patch, AsyncMock

import pytest

from textsource.file_text_source import FileTextSource


# ---------- helpers ----------


class _FakeConfig:
    def __init__(self, uploads_path="/tmp/uploads"):
        self._uploads = uploads_path

    def get(self, key, default=None):
        if key == "paths.uploads":
            return self._uploads
        return default


def _make_source(tmp_path, text, delay=0):
    """Create a FileTextSource backed by a real temp file."""
    f = tmp_path / "input.txt"
    f.write_text(text)
    config = _FakeConfig(uploads_path=str(tmp_path))
    return FileTextSource(config, "input.txt", delay_seconds=delay)


# ---------- sentence splitting ----------


class TestSentenceSplitting:

    def test_single_sentence(self, tmp_path):
        source = _make_source(tmp_path, "Hello world.")
        received = []
        source.on_text(received.append)
        source.start()
        assert received == ["Hello world."]

    def test_multiple_sentences(self, tmp_path):
        source = _make_source(tmp_path, "First. Second! Third?")
        received = []
        source.on_text(received.append)
        source.start()
        assert received == ["First.", "Second!", "Third?"]

    def test_multiple_spaces_between_sentences(self, tmp_path):
        source = _make_source(tmp_path, "One.   Two.   Three.")
        received = []
        source.on_text(received.append)
        source.start()
        assert received == ["One.", "Two.", "Three."]

    def test_newlines_between_sentences(self, tmp_path):
        source = _make_source(tmp_path, "First.\nSecond.\n\nThird.")
        received = []
        source.on_text(received.append)
        source.start()
        assert received == ["First.", "Second.", "Third."]

    def test_no_punctuation_single_chunk(self, tmp_path):
        source = _make_source(tmp_path, "no punctuation here")
        received = []
        source.on_text(received.append)
        source.start()
        assert received == ["no punctuation here"]

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

    def test_trailing_whitespace_stripped(self, tmp_path):
        source = _make_source(tmp_path, "  Hello.  ")
        received = []
        source.on_text(received.append)
        source.start()
        assert received == ["Hello."]

    def test_mixed_terminators(self, tmp_path):
        source = _make_source(tmp_path, "Really? Yes! Okay.")
        received = []
        source.on_text(received.append)
        source.start()
        assert received == ["Really?", "Yes!", "Okay."]

    def test_abbreviation_with_trailing_space_splits(self, tmp_path):
        """The simple regex splits on any period+whitespace, including abbreviations.
        This is a known limitation of the sentence-splitting approach."""
        source = _make_source(tmp_path, "The U.S.A. is large.")
        received = []
        source.on_text(received.append)
        source.start()
        # Splits on ". " after "A." — the regex can't distinguish abbreviations
        assert received == ["The U.S.A.", "is large."]

    def test_abbreviation_without_trailing_space_stays(self, tmp_path):
        """Dots NOT followed by whitespace don't split."""
        source = _make_source(tmp_path, "Visit U.S.A. today.")
        received = []
        source.on_text(received.append)
        source.start()
        # "A. today" splits, but internal dots in "U.S.A" don't
        assert received == ["Visit U.S.A.", "today."]


# ---------- immediate vs delayed ----------


class TestStartBranching:

    def test_immediate_when_no_delay(self, tmp_path):
        source = _make_source(tmp_path, "One. Two.", delay=0)
        received = []
        source.on_text(received.append)
        source.start()
        assert received == ["One.", "Two."]

    def test_delayed_calls_callback_for_each_sentence(self, tmp_path):
        source = _make_source(tmp_path, "One. Two. Three.", delay=0.5)
        received = []
        source.on_text(received.append)

        with patch("textsource.file_text_source.asyncio.sleep", new_callable=AsyncMock):
            source.start()

        assert received == ["One.", "Two.", "Three."]

    def test_delayed_sleeps_between_sentences(self, tmp_path):
        source = _make_source(tmp_path, "A. B.", delay=1.0)
        source.on_text(lambda _: None)

        with patch("textsource.file_text_source.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with patch("textsource.file_text_source.random.uniform", return_value=0.0):
                source.start()

        # Should sleep after each sentence (2 sentences = 2 sleeps)
        assert mock_sleep.call_count == 2
        # With jitter=0.0, delay should be exactly 1.0
        for call in mock_sleep.call_args_list:
            assert call[0][0] == 1.0

    def test_delayed_jitter_applied(self, tmp_path):
        source = _make_source(tmp_path, "A. B.", delay=2.0)
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
