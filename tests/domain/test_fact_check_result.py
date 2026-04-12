from domain.fact_check_result import FactCheckResult, Verdict


def test_verdict_values():
    assert Verdict.ESTABLISHED.value == "established"
    assert Verdict.MISLEADING.value == "misleading"
    assert Verdict.UNSUPPORTED.value == "unsupported"
    assert Verdict.FALSE.value == "false"
    assert Verdict.FAILED.value == "failed"


def test_to_dict():
    result = FactCheckResult(verdict=Verdict.ESTABLISHED, note="Confirmed by sources")
    d = result.to_dict()
    assert d == {"verdict": "established", "note": "Confirmed by sources"}


def test_to_dict_excludes_usage():
    result = FactCheckResult(verdict=Verdict.FALSE, note="Incorrect", usage=None)
    d = result.to_dict()
    assert "usage" not in d


def test_defaults():
    result = FactCheckResult(verdict=Verdict.MISLEADING, note="n")
    assert result.usage is None
