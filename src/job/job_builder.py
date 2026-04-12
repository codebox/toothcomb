import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

from config import Config
from db.database import Database
from domain.job import Job
from domain.job_config import PromptContext
from domain.types import JobId, SourceType

log = logging.getLogger(__name__)


class JobBuilder:
    def __init__(self, config: Config, database: Database):
        self._config = config
        self._database = database

    def build_from_dict(self, data: dict) -> JobId:
        """Create a job from a dict (e.g. from the web UI). Returns the job_id."""
        job_id = JobId(str(uuid.uuid4()))

        source_data = data["source"]
        source_type = SourceType(source_data["type"])

        # For text submitted inline (from the UI), save it to a file
        if source_type == SourceType.TEXT:
            text = source_data.get("text", "")
            if not text.strip():
                raise ValueError("Text source requires non-empty text")
            uploads_dir = Path(self._config.get("paths.uploads"))
            uploads_dir.mkdir(parents=True, exist_ok=True)
            text_path = f"{job_id}.txt"
            (uploads_dir / text_path).write_text(text)
            log.info("[%s] Saved inline text to %s", job_id, uploads_dir / text_path)
            source_data = {"type": SourceType.FILE.value, "path": text_path}
            source_type = SourceType.FILE

        ctx = data.get("context", {})
        context = PromptContext(
            speakers=ctx.get("speakers", ""),
            date_and_time=ctx.get("date_and_time", ""),
            location=ctx.get("location", ""),
            background=ctx.get("background", ""),
            analysis_date=datetime.now().strftime("%Y-%m-%d"),
        )

        title = data.get("title", data.get("id", job_id))

        is_transcribed = source_type != SourceType.FILE
        realtime = data.get("realtime", source_type == SourceType.STREAMING)

        config_json = json.dumps({
            "id": job_id,
            "title": title,
            "context": context.__dict__,
            "source": source_data,
            "is_transcribed": is_transcribed,
            "realtime": realtime,
        }, default=str)

        job = Job(id=job_id, title=title, config=config_json)
        self._database.create_job(job)
        return job_id

    def set_source_path(self, job_id: JobId, path: str) -> None:
        """Update the source path in a job's config (e.g. after file upload)."""
        job = self._database.get_job(job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")
        config_data = job.config_data
        config_data["source"]["path"] = path
        self._database.update_job_config(job_id, json.dumps(config_data, default=str))
