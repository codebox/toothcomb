from domain.transcription_result import TranscriptionSegment, TranscriptionResult


def test_segment_fields():
    seg = TranscriptionSegment(text="hello", start=0.0, end=1.5)
    assert seg.text == "hello"
    assert seg.start == 0.0
    assert seg.end == 1.5


def test_result_fields():
    seg = TranscriptionSegment(text="hi", start=0.0, end=1.0)
    result = TranscriptionResult(speaker="Alice", text="hi", segments=(seg,))
    assert result.speaker == "Alice"
    assert result.text == "hi"
    assert len(result.segments) == 1


def test_result_default_segments():
    result = TranscriptionResult(speaker="Bob", text="hello")
    assert result.segments == ()
