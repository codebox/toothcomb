import json
import tempfile
from pathlib import Path

import pytest

from db.sqlite_database import SQLiteDatabase
from domain.job import Job
from domain.types import JobId, JobStatus, SourceType
from job.job_builder import JobBuilder


# ---------- helpers ----------


class _FakeConfig:
    def __init__(self, uploads_dir: str):
        self._values = {
            "paths.uploads": uploads_dir,
        }

    def get(self, key, default=None):
        return self._values.get(key, default)


@pytest.fixture
def env(tmp_path):
    """Provide a JobBuilder wired to an in-memory DB and tmp uploads dir."""
    uploads = str(tmp_path / "uploads")
    config = _FakeConfig(uploads)
    db = SQLiteDatabase(":memory:")
    builder = JobBuilder(config, db)
    return builder, db, tmp_path, uploads


def _file_source_data(path="transcript.txt"):
    return {"source": {"type": "file", "path": path}, "title": "Test Job"}


def _mp3_source_data(path="audio.mp3"):
    return {"source": {"type": "mp3", "path": path}, "title": "MP3 Job"}


def _streaming_source_data():
    return {"source": {"type": "streaming"}, "title": "Stream Job"}


def _text_source_data(text="Hello world this is some text"):
    return {"source": {"type": "text", "text": text}, "title": "Text Job"}


# ---------- build_from_dict ----------


class TestBuildFromDict:

    def test_creates_job_in_database(self, env):
        builder, db, _, _ = env
        job_id = builder.build_from_dict(_file_source_data())

        job = db.get_job(job_id)
        assert job is not None
        assert job.title == "Test Job"
        assert job.status == JobStatus.INIT

    def test_returns_unique_job_ids(self, env):
        builder, _, _, _ = env
        id1 = builder.build_from_dict(_file_source_data())
        id2 = builder.build_from_dict(_file_source_data())
        assert id1 != id2

    def test_config_json_contains_source(self, env):
        builder, db, _, _ = env
        job_id = builder.build_from_dict(_file_source_data("my_file.txt"))

        job = db.get_job(job_id)
        config = job.config_data
        assert config["source"]["type"] == "file"
        assert config["source"]["path"] == "my_file.txt"

    def test_config_json_contains_context(self, env):
        builder, db, _, _ = env
        data = _file_source_data()
        data["context"] = {
            "speakers": "Alice, Bob",
            "location": "NYC",
            "date_and_time": "2025-03-04",
            "background": "A debate",
        }
        job_id = builder.build_from_dict(data)

        config = db.get_job(job_id).config_data
        assert config["context"]["speakers"] == "Alice, Bob"
        assert config["context"]["location"] == "NYC"
        assert config["context"]["analysis_date"]  # auto-set to today

    def test_missing_context_uses_defaults(self, env):
        builder, db, _, _ = env
        job_id = builder.build_from_dict(_file_source_data())

        config = db.get_job(job_id).config_data
        assert config["context"]["speakers"] == ""
        assert config["context"]["location"] == ""

    def test_file_source_not_transcribed(self, env):
        builder, db, _, _ = env
        job_id = builder.build_from_dict(_file_source_data())
        assert db.get_job(job_id).config_data["is_transcribed"] is False

    def test_mp3_source_is_transcribed(self, env):
        builder, db, _, _ = env
        job_id = builder.build_from_dict(_mp3_source_data())
        assert db.get_job(job_id).config_data["is_transcribed"] is True

    def test_streaming_source_is_transcribed(self, env):
        builder, db, _, _ = env
        job_id = builder.build_from_dict(_streaming_source_data())
        assert db.get_job(job_id).config_data["is_transcribed"] is True

    def test_realtime_defaults_false_for_file(self, env):
        builder, db, _, _ = env
        job_id = builder.build_from_dict(_file_source_data())
        assert db.get_job(job_id).config_data["realtime"] is False

    def test_realtime_defaults_true_for_streaming(self, env):
        builder, db, _, _ = env
        job_id = builder.build_from_dict(_streaming_source_data())
        assert db.get_job(job_id).config_data["realtime"] is True

    def test_realtime_can_be_overridden(self, env):
        builder, db, _, _ = env
        data = _file_source_data()
        data["realtime"] = True
        job_id = builder.build_from_dict(data)
        assert db.get_job(job_id).config_data["realtime"] is True

    def test_title_falls_back_to_id_field(self, env):
        builder, db, _, _ = env
        data = {"source": {"type": "file", "path": "f.txt"}, "id": "my-id"}
        job_id = builder.build_from_dict(data)
        assert db.get_job(job_id).title == "my-id"

    def test_title_falls_back_to_job_id(self, env):
        builder, db, _, _ = env
        data = {"source": {"type": "file", "path": "f.txt"}}
        job_id = builder.build_from_dict(data)
        assert db.get_job(job_id).title == job_id

    def test_text_source_saves_file_and_converts_to_file_type(self, env):
        builder, db, _, uploads = env
        job_id = builder.build_from_dict(_text_source_data("My transcript text"))

        # Should have written a .txt file in uploads
        saved = Path(uploads) / f"{job_id}.txt"
        assert saved.exists()
        assert saved.read_text() == "My transcript text"

        # Config should now reference a file source, not text
        config = db.get_job(job_id).config_data
        assert config["source"]["type"] == "file"
        assert config["source"]["path"] == f"{job_id}.txt"

    def test_text_source_creates_uploads_dir(self, env):
        builder, _, tmp_path, _ = env
        # Use a nested path that doesn't exist yet
        nested_uploads = str(tmp_path / "deep" / "nested" / "uploads")
        builder._config._values["paths.uploads"] = nested_uploads

        builder.build_from_dict(_text_source_data("some text"))
        assert Path(nested_uploads).is_dir()

    def test_text_source_empty_raises(self, env):
        builder, _, _, _ = env
        with pytest.raises(ValueError, match="non-empty text"):
            builder.build_from_dict(_text_source_data(""))

    def test_text_source_whitespace_only_raises(self, env):
        builder, _, _, _ = env
        with pytest.raises(ValueError, match="non-empty text"):
            builder.build_from_dict(_text_source_data("   \n  "))

    def test_invalid_source_type_raises(self, env):
        builder, _, _, _ = env
        with pytest.raises(ValueError):
            builder.build_from_dict({"source": {"type": "unknown"}, "title": "T"})


# ---------- set_source_path ----------


class TestSetSourcePath:

    def test_updates_source_path(self, env):
        builder, db, _, _ = env
        job_id = builder.build_from_dict(_file_source_data("original.txt"))

        builder.set_source_path(job_id, "updated.txt")

        config = db.get_job(job_id).config_data
        assert config["source"]["path"] == "updated.txt"

    def test_nonexistent_job_raises(self, env):
        builder, _, _, _ = env
        with pytest.raises(ValueError, match="Job not found"):
            builder.set_source_path(JobId("nope"), "file.txt")


