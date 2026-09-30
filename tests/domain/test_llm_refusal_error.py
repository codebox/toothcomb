from domain.llm_refusal_error import LLMRefusalError


def test_reason_includes_category():
    err = LLMRefusalError("claude-opus-5-5", "cyber")
    assert err.reason == "Claude declined to answer (refusal category: cyber)"
    assert "claude-opus-5-5" in str(err)


def test_reason_without_category():
    err = LLMRefusalError("claude-opus-5-5")
    assert err.reason == "Claude declined to answer"
    assert "unspecified" in str(err)
