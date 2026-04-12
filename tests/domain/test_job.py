from domain.job import Job
from domain.types import JobId, JobStatus


def test_defaults():
    job = Job(id=JobId("j1"), title="Test")
    assert job.status == JobStatus.INIT
    assert job.started_at is None
    assert job.config == "{}"


def test_config_data_parses_json():
    job = Job(id=JobId("j1"), title="T", config='{"source": {"type": "mp3"}}')
    assert job.config_data == {"source": {"type": "mp3"}}


def test_config_data_empty_string():
    job = Job(id=JobId("j1"), title="T", config="")
    assert job.config_data == {}


def test_realtime_defaults_true():
    job = Job(id=JobId("j1"), title="T")
    assert job.realtime is True


def test_realtime_false_when_set():
    job = Job(id=JobId("j1"), title="T", config='{"realtime": false}')
    assert job.realtime is False


def test_to_dict():
    job = Job(id=JobId("j1"), title="My Job", config='{}',
              status=JobStatus.INGESTING,
              started_at="2025-01-01", created_at="2025-01-01")
    d = job.to_dict()
    assert d["id"] == "j1"
    assert d["title"] == "My Job"
    assert d["status"] == "ingesting"
    assert d["started_at"] == "2025-01-01"
    assert d["created_at"] == "2025-01-01"
