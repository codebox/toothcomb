from domain.job_config import JobConfig, PromptContext
from domain.types import JobId


def test_prompt_context_defaults():
    ctx = PromptContext()
    assert ctx.speakers == ""
    assert ctx.date_and_time == ""
    assert ctx.location == ""
    assert ctx.background == ""
    assert ctx.analysis_date == ""


def test_job_config_fields():
    ctx = PromptContext(speakers="Alice, Bob", location="NYC")
    config = JobConfig(id=JobId("j1"), title="Debate", context=ctx)
    assert config.id == "j1"
    assert config.title == "Debate"
    assert config.context.speakers == "Alice, Bob"
    assert config.is_transcribed is False


def test_job_config_is_transcribed():
    ctx = PromptContext()
    config = JobConfig(id=JobId("j1"), title="T", context=ctx, is_transcribed=True)
    assert config.is_transcribed is True
