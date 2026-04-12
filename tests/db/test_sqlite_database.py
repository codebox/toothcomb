import pytest

from db.sqlite_database import SQLiteDatabase
from domain.analysed_text import Annotation, AnnotationType
from domain.job import Job
from domain.llm_usage import LLMUsage
from domain.transcript import Utterance
from domain.types import (
    JobId, UtteranceId, AnnotationId, AnalysisResultId, ModelName,
    JobStatus, AnalysisStatus, FactCheckStatus,
)

# ---------- helpers ----------


@pytest.fixture
def db():
    """Fresh in-memory database for each test."""
    return SQLiteDatabase(":memory:")


def _job(job_id: str = "job-1", title: str = "Test Job") -> Job:
    return Job(id=JobId(job_id), title=title)


def _utterance(utt_id: str, job_id: str = "job-1", seq: int = 1,
               text: str = "some words here") -> Utterance:
    return Utterance(id=UtteranceId(utt_id), speaker="Speaker", text=text,
                     seq=seq, job_id=JobId(job_id))


def _annotation(ann_id: str = "ann-1", ann_type: AnnotationType = AnnotationType.CLAIM,
                fact_check_query: str | None = "Is this true?") -> Annotation:
    # If no fact_check_query and the type requires one, use PREDICTION instead
    if fact_check_query is None and ann_type.requires_fact_check:
        ann_type = AnnotationType.PREDICTION
    return Annotation(id=AnnotationId(ann_id), type=ann_type, notes="Some note",
                      fact_check_query=fact_check_query)


def _setup_analysis_chain(db, job_id: str = "job-1", utt_id: str = "utt-1",
                          result_id: str = "ar-1", ann_id: str = "ann-1",
                          fact_check_query: str | None = "Is this true?"):
    """Create job → utterance → analysis result → annotation chain."""
    db.create_job(_job(job_id))
    db.create_utterance(_utterance(utt_id, job_id))
    db.create_analysis_result(AnalysisResultId(result_id), UtteranceId(utt_id), seq=1,
                              corrected_text="Corrected text")
    ann = _annotation(ann_id, fact_check_query=fact_check_query)
    db.create_annotation(ann, AnalysisResultId(result_id))
    return ann


# ---------- Jobs ----------


def test_create_and_get_job(db):
    job = _job()
    db.create_job(job)
    result = db.get_job(JobId("job-1"))

    assert result is not None
    assert result.id == "job-1"
    assert result.title == "Test Job"
    assert result.status == JobStatus.INIT


def test_get_nonexistent_job(db):
    assert db.get_job(JobId("nope")) is None


def test_update_job_status(db):
    db.create_job(_job())
    db.update_job_status(JobId("job-1"), JobStatus.INGESTING)

    job = db.get_job(JobId("job-1"))
    assert job.status == JobStatus.INGESTING


def test_list_jobs_returns_all(db):
    db.create_job(_job("a", "First"))
    db.create_job(_job("b", "Second"))
    db.create_job(_job("c", "Third"))

    jobs = db.list_jobs()
    assert len(jobs) == 3
    titles = {j.title for j in jobs}
    assert titles == {"First", "Second", "Third"}


def test_delete_job_cascades(db):
    _setup_analysis_chain(db)
    db.record_llm_usage(JobId("job-1"), LLMUsage(model=ModelName("m"), input_tokens=10))

    assert db.delete_job(JobId("job-1")) is True
    assert db.get_job(JobId("job-1")) is None
    assert db.get_utterances(JobId("job-1")) == []
    assert db.get_job_stats(JobId("job-1")) == []
    assert db.get_annotation(AnnotationId("ann-1")) is None


def test_update_job_config(db):
    db.create_job(_job())
    db.update_job_config(JobId("job-1"), '{"source": {"type": "mp3"}}')

    job = db.get_job(JobId("job-1"))
    assert job.config_data == {"source": {"type": "mp3"}}


def test_set_job_started_at(db):
    db.create_job(_job())
    job_before = db.get_job(JobId("job-1"))
    assert job_before.started_at is None

    db.set_job_started_at(JobId("job-1"))
    job_after = db.get_job(JobId("job-1"))
    assert job_after.started_at is not None


def test_delete_nonexistent_job(db):
    assert db.delete_job(JobId("nope")) is False


# ---------- advance_to_analysing ----------


def test_advance_to_analysing(db):
    db.create_job(_job())
    db.update_job_status(JobId("job-1"), JobStatus.INGESTING)

    assert db.advance_to_analysing(JobId("job-1")) is True
    assert db.get_job(JobId("job-1")).status == JobStatus.ANALYSING


def test_advance_to_analysing_wrong_status(db):
    db.create_job(_job())
    # Job is in 'init' status, not 'ingesting'
    assert db.advance_to_analysing(JobId("job-1")) is False
    assert db.get_job(JobId("job-1")).status == JobStatus.INIT


# ---------- try_advance_to_reviewing ----------


def test_try_advance_to_reviewing_when_all_done(db):
    _setup_analysis_chain(db)
    db.update_job_status(JobId("job-1"), JobStatus.ANALYSING)
    db.complete_utterance_analysis(UtteranceId("utt-1"), remainder="")
    db.complete_fact_check(AnnotationId("ann-1"), verdict="true", note="Confirmed")

    assert db.try_advance_to_reviewing(JobId("job-1")) is True
    assert db.get_job(JobId("job-1")).status == JobStatus.REVIEWING


def test_try_advance_to_reviewing_blocked_by_pending_analysis(db):
    _setup_analysis_chain(db)
    db.update_job_status(JobId("job-1"), JobStatus.ANALYSING)
    # Utterance analysis still pending — should not advance
    db.complete_fact_check(AnnotationId("ann-1"), verdict="true", note="ok")

    assert db.try_advance_to_reviewing(JobId("job-1")) is False
    assert db.get_job(JobId("job-1")).status == JobStatus.ANALYSING


def test_try_advance_to_reviewing_blocked_by_pending_fact_check(db):
    _setup_analysis_chain(db)
    db.update_job_status(JobId("job-1"), JobStatus.ANALYSING)
    db.complete_utterance_analysis(UtteranceId("utt-1"), remainder="")
    # Fact check still pending — should not advance

    assert db.try_advance_to_reviewing(JobId("job-1")) is False
    assert db.get_job(JobId("job-1")).status == JobStatus.ANALYSING


def test_try_advance_to_reviewing_wrong_status(db):
    """A job in 'ingesting' status should not be advanceable to reviewing."""
    _setup_analysis_chain(db)
    db.update_job_status(JobId("job-1"), JobStatus.INGESTING)
    db.complete_utterance_analysis(UtteranceId("utt-1"), remainder="")
    db.complete_fact_check(AnnotationId("ann-1"), verdict="true", note="ok")

    assert db.try_advance_to_reviewing(JobId("job-1")) is False
    assert db.get_job(JobId("job-1")).status == JobStatus.INGESTING


# ---------- try_advance_to_complete ----------


def test_try_advance_to_complete(db):
    _setup_analysis_chain(db)
    db.update_job_status(JobId("job-1"), JobStatus.REVIEWING)
    db.complete_fact_check(AnnotationId("ann-1"), verdict="true", note="ok")

    assert db.try_advance_to_complete(JobId("job-1")) is True
    assert db.get_job(JobId("job-1")).status == JobStatus.COMPLETE


def test_try_advance_to_complete_blocked_by_processing_fact_check(db):
    _setup_analysis_chain(db)
    db.update_job_status(JobId("job-1"), JobStatus.REVIEWING)
    # Claim fact check to move it to 'processing'
    db.claim_fact_check()

    assert db.try_advance_to_complete(JobId("job-1")) is False
    assert db.get_job(JobId("job-1")).status == JobStatus.REVIEWING


def test_try_advance_to_complete_wrong_status(db):
    """A job in 'analysing' status should not be advanceable to complete."""
    _setup_analysis_chain(db)
    db.update_job_status(JobId("job-1"), JobStatus.ANALYSING)
    db.complete_fact_check(AnnotationId("ann-1"), verdict="true", note="ok")

    assert db.try_advance_to_complete(JobId("job-1")) is False
    assert db.get_job(JobId("job-1")).status == JobStatus.ANALYSING


# ---------- start_early_review ----------


def test_start_early_review_from_running(db):
    db.create_job(_job())
    db.update_job_status(JobId("job-1"), JobStatus.INGESTING)

    assert db.start_early_review(JobId("job-1")) is True
    assert db.get_job(JobId("job-1")).status == JobStatus.REVIEWING


def test_start_early_review_from_analysing(db):
    db.create_job(_job())
    db.update_job_status(JobId("job-1"), JobStatus.ANALYSING)

    assert db.start_early_review(JobId("job-1")) is True
    assert db.get_job(JobId("job-1")).status == JobStatus.REVIEWING


def test_start_early_review_wrong_status(db):
    """start_early_review should fail for jobs not in running/analysing."""
    db.create_job(_job())
    # Job is in 'init' status
    assert db.start_early_review(JobId("job-1")) is False
    assert db.get_job(JobId("job-1")).status == JobStatus.INIT


# ---------- Utterances ----------


def test_create_and_get_utterances(db):
    db.create_job(_job())
    db.create_utterance(_utterance("u1", seq=1, text="First"))
    db.create_utterance(_utterance("u2", seq=2, text="Second"))

    utts = db.get_utterances(JobId("job-1"))
    assert len(utts) == 2
    assert utts[0].text == "First"
    assert utts[1].text == "Second"


def test_next_utterance_seq(db):
    db.create_job(_job())
    assert db.next_utterance_seq(JobId("job-1")) == 1

    db.create_utterance(_utterance("u1", seq=1))
    assert db.next_utterance_seq(JobId("job-1")) == 2

    db.create_utterance(_utterance("u2", seq=2))
    assert db.next_utterance_seq(JobId("job-1")) == 3


def test_claim_utterance_first_is_claimable(db):
    db.create_job(_job())
    db.create_utterance(_utterance("u1", seq=1))
    # Change status from buffered to pending so it's claimable
    db._get_conn().execute(
        "UPDATE utterances SET analysis_status = 'pending' WHERE id = 'u1'")
    db._get_conn().commit()

    claimed = db.claim_utterance_for_analysis(JobId("job-1"))
    assert claimed is not None
    assert claimed.id == "u1"

    # Should now be processing
    utt = db.get_utterance(UtteranceId("u1"))
    assert utt.analysis_status == AnalysisStatus.PROCESSING


def test_claim_utterance_blocked_by_pending_predecessor(db):
    db.create_job(_job())
    db.create_utterance(_utterance("u1", seq=1))
    db.create_utterance(_utterance("u2", seq=2))
    # Set both to pending
    conn = db._get_conn()
    conn.execute("UPDATE utterances SET analysis_status = 'pending'")
    conn.commit()

    # Claim first
    claimed1 = db.claim_utterance_for_analysis(JobId("job-1"))
    assert claimed1.id == "u1"

    # Second should be blocked — first is now 'processing', not complete
    claimed2 = db.claim_utterance_for_analysis(JobId("job-1"))
    assert claimed2 is None


def test_claim_utterance_unblocked_after_predecessor_complete(db):
    db.create_job(_job())
    db.create_utterance(_utterance("u1", seq=1))
    db.create_utterance(_utterance("u2", seq=2))
    conn = db._get_conn()
    conn.execute("UPDATE utterances SET analysis_status = 'pending'")
    conn.commit()

    db.claim_utterance_for_analysis(JobId("job-1"))  # claims u1
    db.complete_utterance_analysis(UtteranceId("u1"), remainder="leftover")

    claimed = db.claim_utterance_for_analysis(JobId("job-1"))
    assert claimed is not None
    assert claimed.id == "u2"


def test_complete_and_fail_utterance_analysis(db):
    db.create_job(_job())
    db.create_utterance(_utterance("u1", seq=1))
    db.create_utterance(_utterance("u2", seq=2))

    db.complete_utterance_analysis(UtteranceId("u1"), remainder="leftover text")
    db.fail_utterance_analysis(UtteranceId("u2"))

    u1 = db.get_utterance(UtteranceId("u1"))
    assert u1.analysis_status == AnalysisStatus.COMPLETE
    assert u1.analysis_remainder == "leftover text"

    u2 = db.get_utterance(UtteranceId("u2"))
    assert u2.analysis_status == AnalysisStatus.FAILED


def test_get_utterance_context(db):
    db.create_job(_job())
    for i in range(1, 6):
        db.create_utterance(_utterance(f"u{i}", seq=i, text=f"Sentence {i}"))

    context = db.get_utterance_context(JobId("job-1"), seq=4, context_count=2)
    texts = [u.text for u in context]
    # Should return utterances 2, 3, 4 (the target plus 2 preceding)
    assert texts == ["Sentence 2", "Sentence 3", "Sentence 4"]


def test_get_previous_remainder(db):
    db.create_job(_job())
    db.create_utterance(_utterance("u1", seq=1))
    db.create_utterance(_utterance("u2", seq=2))
    db.create_utterance(_utterance("u3", seq=3))

    db.complete_utterance_analysis(UtteranceId("u1"), remainder="remainder from u1")
    db.complete_utterance_analysis(UtteranceId("u2"), remainder="remainder from u2")

    assert db.get_previous_remainder(JobId("job-1"), seq=3) == "remainder from u2"
    assert db.get_previous_remainder(JobId("job-1"), seq=2) == "remainder from u1"
    assert db.get_previous_remainder(JobId("job-1"), seq=1) == ""


# ---------- Analysis buffer ----------


def test_flush_buffer_below_min_words(db):
    db.create_job(_job())
    db.create_utterance(_utterance("u1", seq=1, text="two words"))

    result = db.flush_analysis_buffer(JobId("job-1"), min_words=10)
    assert result is None


def test_flush_buffer_merges_utterances(db):
    db.create_job(_job())
    db.create_utterance(_utterance("u1", seq=1, text="hello world"))
    db.create_utterance(_utterance("u2", seq=2, text="foo bar baz"))
    db.create_utterance(_utterance("u3", seq=3, text="qux quux"))

    result = db.flush_analysis_buffer(JobId("job-1"), min_words=5)
    assert result is not None
    assert result["combined_text"] == "hello world foo bar baz qux quux"
    assert result["target_id"] == "u3"
    assert set(result["merged_ids"]) == {"u1", "u2"}

    # Merged utterances should be deleted, target should be pending
    utts = db.get_utterances(JobId("job-1"))
    assert len(utts) == 1
    assert utts[0].id == "u3"
    assert utts[0].analysis_status == AnalysisStatus.PENDING


def test_flush_buffer_single_utterance(db):
    db.create_job(_job())
    db.create_utterance(_utterance("u1", seq=1, text="enough words here for sure yes"))

    result = db.flush_analysis_buffer(JobId("job-1"), min_words=3)
    assert result is not None
    assert result["merged_ids"] == []
    assert result["target_id"] == "u1"

    utt = db.get_utterance(UtteranceId("u1"))
    assert utt.analysis_status == AnalysisStatus.PENDING


def test_force_flush_ignores_min_words(db):
    db.create_job(_job())
    db.create_utterance(_utterance("u1", seq=1, text="two words"))

    result = db.force_flush_analysis_buffer(JobId("job-1"))
    assert result is not None
    assert result["target_id"] == "u1"


def test_flush_empty_buffer(db):
    db.create_job(_job())
    assert db.flush_analysis_buffer(JobId("job-1"), min_words=1) is None
    assert db.force_flush_analysis_buffer(JobId("job-1")) is None


# ---------- Analysis results & Annotations ----------


def test_create_and_get_analysed_parts(db):
    _setup_analysis_chain(db)

    parts = db.get_analysed_parts(UtteranceId("utt-1"))
    assert len(parts) == 1
    assert parts[0].corrected_text == "Corrected text"
    assert len(parts[0].annotations) == 1
    assert parts[0].annotations[0].type == AnnotationType.CLAIM
    assert parts[0].annotations[0].notes == "Some note"


def test_annotation_without_fact_check_query(db):
    """A PREDICTION annotation with no fact_check_query should store and retrieve cleanly."""
    _setup_analysis_chain(db, ann_id="ann-nofc",
                          fact_check_query=None)
    ann = db.get_annotation(AnnotationId("ann-nofc"))
    assert ann is not None
    assert ann.fact_check_query is None
    assert ann.fact_check_status is None


def test_annotation_with_direct_verdict(db):
    """An annotation with a pre-populated verdict should be stored as complete."""
    db.create_job(_job())
    db.create_utterance(_utterance("utt-1"))
    db.create_analysis_result(AnalysisResultId("ar-1"), UtteranceId("utt-1"),
                              seq=1, corrected_text="text")
    ann = Annotation(id=AnnotationId("ann-v"), type=AnnotationType.CLAIM,
                     notes="Known false claim",
                     fact_check_verdict="false",
                     fact_check_note="Well-established fact")
    db.create_annotation(ann, AnalysisResultId("ar-1"))

    stored = db.get_annotation(AnnotationId("ann-v"))
    assert stored.fact_check_status == FactCheckStatus.COMPLETE
    assert stored.fact_check_verdict == "false"
    assert stored.fact_check_note == "Well-established fact"
    assert stored.fact_check_query is None


def test_annotation_with_verdict_not_claimable_for_fact_check(db):
    """An annotation with a pre-populated verdict should not be picked up by claim_fact_check."""
    db.create_job(_job())
    db.create_utterance(_utterance("utt-1"))
    db.create_analysis_result(AnalysisResultId("ar-1"), UtteranceId("utt-1"),
                              seq=1, corrected_text="text")
    ann = Annotation(id=AnnotationId("ann-v"), type=AnnotationType.CLAIM,
                     notes="n", fact_check_verdict="established",
                     fact_check_note="Known true")
    db.create_annotation(ann, AnalysisResultId("ar-1"))

    assert db.claim_fact_check() is None


def test_get_annotations_for_result(db):
    db.create_job(_job())
    db.create_utterance(_utterance("utt-1"))
    db.create_analysis_result(AnalysisResultId("ar-1"), UtteranceId("utt-1"),
                              seq=1, corrected_text="text")
    ann1 = Annotation(id=AnnotationId("a1"), type=AnnotationType.CLAIM,
                      notes="n1", fact_check_query="q1")
    ann2 = Annotation(id=AnnotationId("a2"), type=AnnotationType.PREDICTION,
                      notes="n2")
    db.create_annotation(ann1, AnalysisResultId("ar-1"))
    db.create_annotation(ann2, AnalysisResultId("ar-1"))

    annotations = db.get_annotations(AnalysisResultId("ar-1"))
    assert len(annotations) == 2
    types = {a.type for a in annotations}
    assert types == {AnnotationType.CLAIM, AnnotationType.PREDICTION}


# ---------- Fact checks ----------


def test_claim_fact_check(db):
    _setup_analysis_chain(db)
    db.update_job_status(JobId("job-1"), JobStatus.INGESTING)

    claimed = db.claim_fact_check()
    assert claimed is not None
    assert claimed.id == "ann-1"
    assert claimed.job_id == "job-1"
    assert claimed.fact_check_status == FactCheckStatus.PENDING

    # Should now be processing — second claim returns None
    verified = db.get_annotation(AnnotationId("ann-1"))
    assert verified.fact_check_status == FactCheckStatus.PROCESSING

    assert db.claim_fact_check() is None


def test_claim_fact_check_skips_no_query(db):
    """Annotations without fact_check_query should not be claimable."""
    _setup_analysis_chain(db, fact_check_query=None)
    assert db.claim_fact_check() is None


def test_claim_fact_check_only_active_jobs(db):
    """Fact checks should only be claimed for jobs in running/analysing/reviewing status."""
    _setup_analysis_chain(db)
    # Job is in 'init' status — fact check should not be claimable
    assert db.claim_fact_check() is None

    # Move to running — should be claimable
    db.update_job_status(JobId("job-1"), JobStatus.INGESTING)
    claimed = db.claim_fact_check()
    assert claimed is not None
    # Reset for next check
    conn = db._get_conn()
    conn.execute("UPDATE annotations SET fact_check_status = 'pending' WHERE id = 'ann-1'")
    conn.commit()

    # Move to analysing — should be claimable
    db.update_job_status(JobId("job-1"), JobStatus.ANALYSING)
    claimed = db.claim_fact_check()
    assert claimed is not None
    conn.execute("UPDATE annotations SET fact_check_status = 'pending' WHERE id = 'ann-1'")
    conn.commit()

    # Move to reviewing — should be claimable
    db.update_job_status(JobId("job-1"), JobStatus.REVIEWING)
    claimed = db.claim_fact_check()
    assert claimed is not None
    conn.execute("UPDATE annotations SET fact_check_status = 'pending' WHERE id = 'ann-1'")
    conn.commit()

    # Move to complete — should NOT be claimable
    db.update_job_status(JobId("job-1"), JobStatus.COMPLETE)
    assert db.claim_fact_check() is None

    # Move to failed — should NOT be claimable
    db.update_job_status(JobId("job-1"), JobStatus.FAILED)
    assert db.claim_fact_check() is None


def test_complete_fact_check(db):
    _setup_analysis_chain(db)
    db.complete_fact_check(AnnotationId("ann-1"), verdict="true", note="Verified")

    ann = db.get_annotation(AnnotationId("ann-1"))
    assert ann.fact_check_status == FactCheckStatus.COMPLETE
    assert ann.fact_check_verdict == "true"
    assert ann.fact_check_note == "Verified"


def test_fail_fact_check(db):
    _setup_analysis_chain(db)
    db.fail_fact_check(AnnotationId("ann-1"), note="API error")

    ann = db.get_annotation(AnnotationId("ann-1"))
    assert ann.fact_check_status == FactCheckStatus.FAILED
    assert ann.fact_check_note == "API error"


# ---------- Stats ----------


def test_record_and_get_stats(db):
    db.create_job(_job())
    db.record_llm_usage(JobId("job-1"), LLMUsage(
        model=ModelName("claude"), input_tokens=100, output_tokens=50))
    db.record_llm_usage(JobId("job-1"), LLMUsage(
        model=ModelName("claude"), input_tokens=200, output_tokens=75))

    stats = db.get_job_stats(JobId("job-1"))
    assert len(stats) == 1
    assert stats[0]["model"] == "claude"
    assert stats[0]["input_tokens"] == 300
    assert stats[0]["output_tokens"] == 125
    assert stats[0]["request_count"] == 2


def test_stats_separate_models(db):
    db.create_job(_job())
    db.record_llm_usage(JobId("job-1"), LLMUsage(
        model=ModelName("model-a"), input_tokens=10))
    db.record_llm_usage(JobId("job-1"), LLMUsage(
        model=ModelName("model-b"), input_tokens=20))

    stats = db.get_job_stats(JobId("job-1"))
    assert len(stats) == 2
    models = {s["model"] for s in stats}
    assert models == {"model-a", "model-b"}


# ---------- Utterance edge cases ----------


def test_create_utterance_status_is_buffered(db):
    """create_utterance should set analysis_status to 'buffered', not the domain default 'pending'."""
    db.create_job(_job())
    db.create_utterance(_utterance("u1"))

    utt = db.get_utterance(UtteranceId("u1"))
    assert utt.analysis_status == AnalysisStatus.BUFFERED


def test_create_utterance_duplicate_is_ignored(db):
    """INSERT OR IGNORE means a second insert with the same ID is silently dropped."""
    db.create_job(_job())
    db.create_utterance(_utterance("u1", text="first"))
    db.create_utterance(_utterance("u1", text="second"))

    utt = db.get_utterance(UtteranceId("u1"))
    assert utt.text == "first"


def test_claim_utterance_nothing_pending(db):
    """claim_utterance_for_analysis returns None when no pending utterances exist."""
    db.create_job(_job())
    db.create_utterance(_utterance("u1"))
    # u1 is 'buffered', not 'pending'
    assert db.claim_utterance_for_analysis(JobId("job-1")) is None


def test_claim_utterance_unblocked_by_failed_predecessor(db):
    """A failed predecessor should unblock the next utterance (failed counts as 'done')."""
    db.create_job(_job())
    db.create_utterance(_utterance("u1", seq=1))
    db.create_utterance(_utterance("u2", seq=2))
    conn = db._get_conn()
    conn.execute("UPDATE utterances SET analysis_status = 'pending'")
    conn.commit()

    # Claim and fail u1
    db.claim_utterance_for_analysis(JobId("job-1"))
    db.fail_utterance_analysis(UtteranceId("u1"))

    # u2 should now be claimable
    claimed = db.claim_utterance_for_analysis(JobId("job-1"))
    assert claimed is not None
    assert claimed.id == "u2"


def test_get_utterance_nonexistent(db):
    assert db.get_utterance(UtteranceId("nope")) is None


def test_get_utterance_context_less_than_requested(db):
    """When fewer preceding utterances exist than context_count, return what's available."""
    db.create_job(_job())
    db.create_utterance(_utterance("u1", seq=1, text="First"))
    db.create_utterance(_utterance("u2", seq=2, text="Second"))

    context = db.get_utterance_context(JobId("job-1"), seq=2, context_count=5)
    assert len(context) == 2
    assert [u.text for u in context] == ["First", "Second"]


def test_get_previous_remainder_no_completed_predecessors(db):
    """When seq > 1 but no predecessor is complete, return empty string."""
    db.create_job(_job())
    db.create_utterance(_utterance("u1", seq=1))
    db.create_utterance(_utterance("u2", seq=2))
    # u1 is 'buffered', not complete — no remainder available
    assert db.get_previous_remainder(JobId("job-1"), seq=2) == ""


# ---------- Analysis results edge cases ----------


def test_get_analysed_parts_no_results(db):
    """get_analysed_parts for an utterance with no analysis results returns empty list."""
    db.create_job(_job())
    db.create_utterance(_utterance("u1"))

    parts = db.get_analysed_parts(UtteranceId("u1"))
    assert parts == []


def test_get_annotation_nonexistent(db):
    assert db.get_annotation(AnnotationId("nope")) is None


# ---------- Stats edge cases ----------


def test_get_job_stats_empty(db):
    db.create_job(_job())
    assert db.get_job_stats(JobId("job-1")) == []


def test_record_llm_usage_cache_tokens_accumulate(db):
    """cache_read_tokens and cache_creation_tokens should accumulate via ON CONFLICT UPDATE."""
    db.create_job(_job())
    db.record_llm_usage(JobId("job-1"), LLMUsage(
        model=ModelName("claude"), input_tokens=10, cache_read_tokens=100, cache_creation_tokens=50))
    db.record_llm_usage(JobId("job-1"), LLMUsage(
        model=ModelName("claude"), input_tokens=20, cache_read_tokens=200, cache_creation_tokens=75))

    stats = db.get_job_stats(JobId("job-1"))
    assert len(stats) == 1
    assert stats[0]["cache_read_tokens"] == 300
    assert stats[0]["cache_creation_tokens"] == 125
    assert stats[0]["input_tokens"] == 30
    assert stats[0]["request_count"] == 2


# ---------- Recovery ----------


def test_recover_incomplete_work(db):
    _setup_analysis_chain(db)
    conn = db._get_conn()
    conn.execute("UPDATE utterances SET analysis_status = 'processing' WHERE id = 'utt-1'")
    conn.execute("UPDATE annotations SET fact_check_status = 'processing' WHERE id = 'ann-1'")
    conn.commit()

    db.recover_incomplete_work()

    utt = db.get_utterance(UtteranceId("utt-1"))
    assert utt.analysis_status == AnalysisStatus.PENDING

    ann = db.get_annotation(AnnotationId("ann-1"))
    assert ann.fact_check_status == FactCheckStatus.PENDING


def test_recover_leaves_complete_and_pending_untouched(db):
    """recover_incomplete_work resets 'processing' and 'failed' to 'pending', leaves 'complete' alone."""
    db.create_job(_job())
    db.create_utterance(_utterance("u1", seq=1))
    db.create_utterance(_utterance("u2", seq=2))
    db.create_utterance(_utterance("u3", seq=3))

    conn = db._get_conn()
    conn.execute("UPDATE utterances SET analysis_status = 'complete' WHERE id = 'u1'")
    conn.execute("UPDATE utterances SET analysis_status = 'pending' WHERE id = 'u2'")
    conn.execute("UPDATE utterances SET analysis_status = 'failed' WHERE id = 'u3'")
    conn.commit()

    db.recover_incomplete_work()

    assert db.get_utterance(UtteranceId("u1")).analysis_status == AnalysisStatus.COMPLETE
    assert db.get_utterance(UtteranceId("u2")).analysis_status == AnalysisStatus.PENDING
    assert db.get_utterance(UtteranceId("u3")).analysis_status == AnalysisStatus.PENDING


def test_recover_review_processing(db):
    """recover_incomplete_work should reset review_claimed for reviewing jobs."""
    db.create_job(_job())
    db.update_job_status(JobId("job-1"), JobStatus.REVIEWING)
    db.claim_review()  # sets review_claimed = 1

    db.recover_incomplete_work()

    # After recovery, the job should be claimable again
    job = db.claim_review()
    assert job is not None
    assert job.id == "job-1"


# ---------- Transcript Review ----------


def test_claim_review(db):
    """claim_review finds jobs with status='reviewing' and review_claimed=0, no processing FCs."""
    _setup_analysis_chain(db)
    db.update_job_status(JobId("job-1"), JobStatus.REVIEWING)
    # Complete the fact check so it doesn't block
    db.complete_fact_check(AnnotationId("ann-1"), verdict="true", note="ok")

    job = db.claim_review()
    assert job is not None
    assert job.id == "job-1"

    # Second claim should return None (already claimed)
    assert db.claim_review() is None


def test_claim_review_blocked_by_processing_fact_check(db):
    """claim_review should not return a job that has processing fact checks."""
    _setup_analysis_chain(db)
    db.update_job_status(JobId("job-1"), JobStatus.REVIEWING)
    # Claim fact check to move it to 'processing'
    db.claim_fact_check()

    assert db.claim_review() is None


def test_claim_review_returns_none_when_no_reviewing_jobs(db):
    db.create_job(_job())
    # Job is in 'init' status, not 'reviewing'
    assert db.claim_review() is None


def test_complete_review(db):
    db.create_job(_job())
    db.update_job_status(JobId("job-1"), JobStatus.REVIEWING)

    findings = '{"job_id": "job-1", "findings": [{"type": "TACTIC"}]}'
    db.complete_review(JobId("job-1"), findings)

    review = db.get_review(JobId("job-1"))
    assert review is not None
    assert review["findings"] == [{"type": "TACTIC"}]


def test_get_review_returns_none_when_no_review(db):
    db.create_job(_job())
    assert db.get_review(JobId("job-1")) is None


def test_get_all_analysed_texts(db):
    _setup_analysis_chain(db)
    db.complete_utterance_analysis(UtteranceId("utt-1"), remainder="leftover")

    results = db.get_all_analysed_texts(JobId("job-1"))
    assert len(results) == 1
    assert results[0].utterance_id == "utt-1"
    assert len(results[0].analysed_parts) == 1
    assert results[0].remainder == "leftover"


def test_get_all_analysed_texts_skips_incomplete(db):
    db.create_job(_job())
    db.create_utterance(_utterance("u1", seq=1))
    db.create_utterance(_utterance("u2", seq=2))

    # Complete only u1
    db.complete_utterance_analysis(UtteranceId("u1"), remainder="")
    db.create_analysis_result(AnalysisResultId("ar-1"), UtteranceId("u1"),
                              seq=1, corrected_text="text")

    results = db.get_all_analysed_texts(JobId("job-1"))
    assert len(results) == 1
    assert results[0].utterance_id == "u1"


def test_get_all_analysed_texts_empty_when_no_parts(db):
    db.create_job(_job())
    db.create_utterance(_utterance("u1", seq=1))
    db.complete_utterance_analysis(UtteranceId("u1"), remainder="")
    # No analysis_result created

    results = db.get_all_analysed_texts(JobId("job-1"))
    assert results == []


def test_delete_job_cascades_review(db):
    db.create_job(_job())
    db.update_job_status(JobId("job-1"), JobStatus.REVIEWING)
    db.complete_review(JobId("job-1"), '{"findings": []}')

    assert db.get_review(JobId("job-1")) is not None
    db.delete_job(JobId("job-1"))
    assert db.get_review(JobId("job-1")) is None


def test_flush_buffer_only_picks_up_buffered(db):
    """flush_analysis_buffer should only pick up 'buffered' utterances, ignoring 'pending' and others."""
    db.create_job(_job())
    db.create_utterance(_utterance("u1", seq=1, text="buffered words here"))
    db.create_utterance(_utterance("u2", seq=2, text="also buffered words"))

    # Manually move u1 to 'pending' — it should NOT be included in flush
    conn = db._get_conn()
    conn.execute("UPDATE utterances SET analysis_status = 'pending' WHERE id = 'u1'")
    conn.commit()

    result = db.flush_analysis_buffer(JobId("job-1"), min_words=2)
    assert result is not None
    assert result["target_id"] == "u2"
    assert result["merged_ids"] == []
    assert result["combined_text"] == "also buffered words"
