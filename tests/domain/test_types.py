from domain.types import (
    JobId, UtteranceId, AnnotationId, AnalysisResultId, ModelName,
    JobStatus, AnalysisStatus, FactCheckStatus, SourceType,
)


def test_newtypes_are_strings():
    assert isinstance(JobId("j"), str)
    assert isinstance(UtteranceId("u"), str)
    assert isinstance(AnnotationId("a"), str)
    assert isinstance(AnalysisResultId("r"), str)
    assert isinstance(ModelName("m"), str)


def test_job_status_values():
    assert JobStatus.INIT.value == "init"
    assert JobStatus.INGESTING.value == "ingesting"
    assert JobStatus.ANALYSING.value == "analysing"
    assert JobStatus.REVIEWING.value == "reviewing"
    assert JobStatus.COMPLETE.value == "complete"
    assert JobStatus.ABORTED.value == "aborted"


def test_analysis_status_values():
    assert AnalysisStatus.PENDING.value == "pending"
    assert AnalysisStatus.BUFFERED.value == "buffered"
    assert AnalysisStatus.PROCESSING.value == "processing"
    assert AnalysisStatus.COMPLETE.value == "complete"
    assert AnalysisStatus.FAILED.value == "failed"


def test_fact_check_status_values():
    assert FactCheckStatus.PENDING.value == "pending"
    assert FactCheckStatus.PROCESSING.value == "processing"
    assert FactCheckStatus.COMPLETE.value == "complete"
    assert FactCheckStatus.FAILED.value == "failed"


def test_source_type_values():
    assert SourceType.TEXT.value == "text"
    assert SourceType.FILE.value == "file"
    assert SourceType.MP3.value == "mp3"
    assert SourceType.STREAMING.value == "streaming"
