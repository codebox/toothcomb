import logging

from config import Config
from db.sqlite_database import SQLiteDatabase
from job.job_builder import JobBuilder
from job.job_runner import JobRunner
from pipeline.pipeline import Pipeline
from web.web_server import WebServer

config = Config()

logging.basicConfig(
    level=config.get("log_level", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger(__name__)


if __name__ == "__main__":
    api_key = config.get("llm.anthropic.api_key")
    if not api_key:
        log.error("No Anthropic API key configured. "
                  "Set the LLM__ANTHROPIC__API_KEY environment variable, e.g.:\n"
                  "  docker run -e LLM__ANTHROPIC__API_KEY=sk-ant-... toothcomb")
        raise SystemExit(1)

    database = SQLiteDatabase(config.get("paths.db"))
    database.recover_incomplete_work()

    web_server = WebServer(config, database)

    pipeline = Pipeline(config, database, web_server.emitter)
    pipeline.start()

    job_builder = JobBuilder(config, database)
    job_runner = JobRunner(config, pipeline, database, pipeline.update_service)
    job_runner.resume_running_jobs()
    web_server.set_job_builder(job_builder)
    web_server.set_job_runner(job_runner)
    web_server.start()
