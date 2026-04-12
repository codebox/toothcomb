from domain.llm_usage import LLMUsage, LLMResponse
from domain.types import ModelName


def test_total_tokens():
    usage = LLMUsage(model=ModelName("m"), input_tokens=100, output_tokens=50)
    assert usage.total_tokens == 150


def test_add():
    a = LLMUsage(model=ModelName("m"), input_tokens=10, output_tokens=5,
                 cache_read_tokens=3, cache_creation_tokens=1)
    b = LLMUsage(model=ModelName("m"), input_tokens=20, output_tokens=10,
                 cache_read_tokens=7, cache_creation_tokens=2)
    result = a + b
    assert result.input_tokens == 30
    assert result.output_tokens == 15
    assert result.cache_read_tokens == 10
    assert result.cache_creation_tokens == 3
    assert result.model == "m"


def test_add_takes_first_non_empty_model():
    a = LLMUsage(model=ModelName(""), input_tokens=1)
    b = LLMUsage(model=ModelName("claude"), input_tokens=2)
    assert (a + b).model == "claude"


def test_to_dict():
    usage = LLMUsage(model=ModelName("claude"), input_tokens=100, output_tokens=50,
                     cache_read_tokens=10, cache_creation_tokens=5)
    d = usage.to_dict()
    assert d == {
        "model": "claude",
        "input_tokens": 100,
        "output_tokens": 50,
        "cache_read_tokens": 10,
        "cache_creation_tokens": 5,
    }


def test_defaults():
    usage = LLMUsage()
    assert usage.model == ""
    assert usage.input_tokens == 0
    assert usage.output_tokens == 0
    assert usage.cache_read_tokens == 0
    assert usage.cache_creation_tokens == 0
    assert usage.total_tokens == 0


def test_llm_response():
    usage = LLMUsage(model=ModelName("m"), input_tokens=10)
    resp = LLMResponse(text="hello", usage=usage)
    assert resp.text == "hello"
    assert resp.usage.input_tokens == 10


def test_llm_response_no_usage():
    resp = LLMResponse(text="hello")
    assert resp.usage is None
