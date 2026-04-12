from domain.llm_response_error import LLMResponseError


def test_message_includes_response():
    err = LLMResponseError("Parse failed", llm_response="gibberish")
    assert "Parse failed" in str(err)
    assert "gibberish" in str(err)
    assert err.llm_response == "gibberish"


def test_message_includes_query_when_provided():
    err = LLMResponseError("Bad", llm_response="resp", query="my query")
    assert "my query" in str(err)


def test_message_without_query():
    err = LLMResponseError("Bad", llm_response="resp")
    assert "Query" not in str(err)


def test_is_exception():
    err = LLMResponseError("fail", llm_response="r")
    assert isinstance(err, Exception)
