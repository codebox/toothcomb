from domain.transcript_review import FindingReference, ReviewFinding, TranscriptReview
from domain.analysed_text import AnnotationType
from domain.types import JobId


def test_finding_reference_to_dict():
    ref = FindingReference(excerpt="some quote", location="para 3")
    assert ref.to_dict() == {"excerpt": "some quote", "location": "para 3"}


def test_review_finding_to_dict():
    ref = FindingReference(excerpt="quote", location="p1")
    finding = ReviewFinding(
        id="f1", type=AnnotationType.FALLACY, technique="strawman",
        summary="Misrepresented argument", references=(ref,),
    )
    d = finding.to_dict()
    assert d["id"] == "f1"
    assert d["type"] == "FALLACY"
    assert d["technique"] == "strawman"
    assert d["summary"] == "Misrepresented argument"
    assert len(d["references"]) == 1
    assert d["references"][0]["excerpt"] == "quote"


def test_review_finding_auto_generates_id():
    a = ReviewFinding(type=AnnotationType.TACTIC, technique="t", summary="s")
    b = ReviewFinding(type=AnnotationType.TACTIC, technique="t", summary="s")
    assert a.id != b.id


def test_review_finding_empty_references():
    finding = ReviewFinding(type=AnnotationType.RHETORIC, technique="t", summary="s")
    assert finding.to_dict()["references"] == []


def test_transcript_review_to_dict():
    finding = ReviewFinding(id="f1", type=AnnotationType.FALLACY,
                            technique="t", summary="s")
    review = TranscriptReview(job_id=JobId("j1"), findings=(finding,), failed=False)
    d = review.to_dict()
    assert d["job_id"] == "j1"
    assert len(d["findings"]) == 1
    assert d["failed"] is False


def test_transcript_review_defaults():
    review = TranscriptReview(job_id=JobId("j1"))
    assert review.findings == ()
    assert review.failed is False
    assert review.to_dict()["findings"] == []
