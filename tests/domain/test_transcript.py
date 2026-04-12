from domain.transcript import Utterance, Transcript, UtteranceWithContext
from domain.types import UtteranceId, JobId, AnalysisStatus


# ---------- Utterance ----------


def test_utterance_to_dict():
    u = Utterance(id=UtteranceId("u1"), speaker="Alice", text="Hello",
                  seq=3, job_id=JobId("j1"), offset_seconds=1.5)
    d = u.to_dict()
    assert d == {
        "utterance_id": "u1",
        "seq": 3,
        "speaker": "Alice",
        "text": "Hello",
        "offset_seconds": 1.5,
    }


def test_utterance_str_with_speaker():
    u = Utterance(id=UtteranceId("u1"), speaker="Bob", text="Hi there")
    assert str(u) == "Bob: Hi there"


def test_utterance_str_without_speaker():
    u = Utterance(id=UtteranceId("u1"), speaker="", text="Hi there")
    assert str(u) == "Hi there"


def test_utterance_defaults():
    u = Utterance(id=UtteranceId("u1"), speaker="S", text="T")
    assert u.seq == 0
    assert u.job_id == ""
    assert u.offset_seconds == 0.0
    assert u.analysis_status == AnalysisStatus.PENDING
    assert u.analysis_remainder == ""


# ---------- Transcript ----------


def test_transcript_add():
    t = Transcript()
    u1 = t.add("Alice", "First")
    u2 = t.add("Bob", "Second")

    assert len(t.utterances) == 2
    assert u1.speaker == "Alice"
    assert u2.speaker == "Bob"
    assert u1.id != u2.id


def test_transcript_get_with_context():
    t = Transcript()
    t.add("A", "One")
    t.add("B", "Two")
    t.add("C", "Three")
    t.add("D", "Four")

    ctx = t.get_with_context(seq_id=3, context_count=2)
    assert isinstance(ctx, UtteranceWithContext)
    assert ctx.utterance.text == "Three"
    assert len(ctx.previous) == 2
    assert ctx.previous[0].text == "One"
    assert ctx.previous[1].text == "Two"


def test_transcript_get_with_context_at_start():
    t = Transcript()
    t.add("A", "First")
    t.add("B", "Second")

    ctx = t.get_with_context(seq_id=1, context_count=5)
    assert ctx.utterance.text == "First"
    assert len(ctx.previous) == 0
