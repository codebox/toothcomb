import pytest

from domain.analysed_text import Annotation, AnnotationType, AnalysedPart, AnalysedText
from domain.types import AnnotationId, UtteranceId, FactCheckStatus


# ---------- AnnotationType ----------


def test_claim_requires_fact_check():
    assert AnnotationType.CLAIM.requires_fact_check is True


def test_non_claim_types_do_not_require_fact_check():
    for t in [AnnotationType.PREDICTION, AnnotationType.COMMITMENT,
              AnnotationType.FALLACY, AnnotationType.RHETORIC, AnnotationType.TACTIC]:
        assert t.requires_fact_check is False, f"{t} should not require fact check"


# ---------- Annotation ----------


def test_claim_without_query_raises():
    with pytest.raises(ValueError, match="must include a fact_check_query"):
        Annotation(type=AnnotationType.CLAIM, notes="n")


def test_claim_with_query_ok():
    ann = Annotation(type=AnnotationType.CLAIM, notes="n", fact_check_query="Is it true?")
    assert ann.triggers_fact_check is True


def test_prediction_without_query_ok():
    ann = Annotation(type=AnnotationType.PREDICTION, notes="n")
    assert ann.triggers_fact_check is False


def test_triggers_fact_check_with_query():
    ann = Annotation(type=AnnotationType.PREDICTION, notes="n", fact_check_query="q")
    assert ann.triggers_fact_check is True


def test_annotation_auto_generates_id():
    a = Annotation(type=AnnotationType.PREDICTION, notes="n")
    b = Annotation(type=AnnotationType.PREDICTION, notes="n")
    assert a.id != b.id


def test_annotation_to_dict():
    ann = Annotation(
        id=AnnotationId("a1"), type=AnnotationType.CLAIM, notes="important",
        fact_check_query="Is this true?",
        fact_check_status=FactCheckStatus.COMPLETE,
    )
    d = ann.to_dict()
    assert d["annotation_id"] == "a1"
    assert d["type"] == "CLAIM"
    assert d["notes"] == "important"
    assert d["fact_check_query"] == "Is this true?"
    assert d["fact_check_status"] == "complete"


def test_annotation_to_dict_infers_pending_status():
    """When fact_check_query is set but fact_check_status is None,
    to_dict should report status as 'pending'."""
    ann = Annotation(
        type=AnnotationType.CLAIM, notes="n", fact_check_query="q",
        fact_check_status=None,
    )
    assert ann.to_dict()["fact_check_status"] == "pending"


def test_annotation_to_dict_no_query_no_status():
    ann = Annotation(type=AnnotationType.PREDICTION, notes="n")
    d = ann.to_dict()
    assert d["fact_check_query"] is None
    assert d["fact_check_status"] is None


# ---------- AnalysedPart ----------


def test_analysed_part_to_dict():
    ann = Annotation(type=AnnotationType.PREDICTION, notes="note")
    part = AnalysedPart(corrected_text="Hello world", annotations=(ann,))
    d = part.to_dict()
    assert d["corrected_text"] == "Hello world"
    assert len(d["annotations"]) == 1
    assert d["annotations"][0]["type"] == "PREDICTION"


def test_analysed_part_empty_annotations():
    part = AnalysedPart(corrected_text="text")
    d = part.to_dict()
    assert d["annotations"] == []


# ---------- AnalysedText ----------


def test_analysed_text_to_dict():
    part = AnalysedPart(corrected_text="text")
    at = AnalysedText(
        utterance_id=UtteranceId("u1"), text="original",
        analysed_parts=(part,), remainder="leftover", failed=False,
    )
    d = at.to_dict()
    assert d["utterance_id"] == "u1"
    assert len(d["parts"]) == 1
    assert d["remainder"] == "leftover"
    assert d["failed"] is False


def test_analysed_text_defaults():
    at = AnalysedText(utterance_id=UtteranceId("u1"), text="t")
    assert at.analysed_parts == ()
    assert at.remainder == ""
    assert at.failed is False
    assert at.usage is None
