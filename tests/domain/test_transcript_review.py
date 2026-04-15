from domain.transcript_review import ReviewFinding, TranscriptReview
from domain.analysed_text import AnnotationType
from domain.types import JobId


def test_review_finding_to_dict():
    finding = ReviewFinding(
        id="f1", type=AnnotationType.FALLACY, technique="strawman",
        summary="Misrepresented argument", refs=("ann-1", "ann-2"),
    )
    d = finding.to_dict()
    assert d["id"] == "f1"
    assert d["type"] == "FALLACY"
    assert d["technique"] == "strawman"
    assert d["summary"] == "Misrepresented argument"
    assert d["refs"] == ["ann-1", "ann-2"]


def test_review_finding_auto_generates_id():
    a = ReviewFinding(type=AnnotationType.TACTIC, technique="t", summary="s")
    b = ReviewFinding(type=AnnotationType.TACTIC, technique="t", summary="s")
    assert a.id != b.id


def test_review_finding_empty_refs():
    finding = ReviewFinding(type=AnnotationType.RHETORIC, technique="t", summary="s")
    assert finding.to_dict()["refs"] == []


def test_review_finding_excerpt_in_dict():
    finding = ReviewFinding(type=AnnotationType.FALLACY, technique="t",
                            summary="s", excerpt="quoted text")
    assert finding.to_dict()["excerpt"] == "quoted text"


def test_review_finding_excerpt_defaults_to_none():
    finding = ReviewFinding(type=AnnotationType.FALLACY, technique="t", summary="s")
    assert finding.to_dict()["excerpt"] is None


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
