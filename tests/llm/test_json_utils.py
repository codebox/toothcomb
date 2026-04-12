from llm.json_utils import extract_json


def test_plain_json():
    assert extract_json('{"key": "value"}') == '{"key": "value"}'


def test_json_in_code_fence():
    text = '```json\n{"key": "value"}\n```'
    assert extract_json(text) == '{"key": "value"}'


def test_code_fence_without_language():
    text = '```\n{"key": 1}\n```'
    assert extract_json(text) == '{"key": 1}'


def test_json_with_surrounding_text():
    text = 'Here is my analysis:\n{"verdict": "true"}\nThat is my answer.'
    assert extract_json(text) == '{"verdict": "true"}'


def test_multiple_json_objects_returns_last():
    text = '{"first": 1}\nSome reasoning\n{"second": 2}'
    result = extract_json(text)
    assert '"second"' in result
    assert '"first"' not in result


def test_nested_json():
    text = '{"outer": {"inner": "value"}}'
    assert extract_json(text) == '{"outer": {"inner": "value"}}'


def test_no_json_returns_stripped_text():
    assert extract_json("  no json here  ") == "no json here"


def test_malformed_json_returns_stripped_text():
    text = "{not valid json"
    assert extract_json(text) == text.strip()


def test_self_correction_pattern():
    """LLM outputs wrong answer, then corrects itself — should use the correction."""
    text = ('{"verdict": "established", "note": "Initially correct"}\n'
            'Actually, I made an error. Let me reconsider.\n'
            '{"verdict": "false", "note": "Corrected answer"}')
    result = extract_json(text)
    import json
    parsed = json.loads(result)
    assert parsed["verdict"] == "false"
    assert parsed["note"] == "Corrected answer"


def test_json_with_special_characters():
    text = '{"note": "The claim said \\"50%\\" increase"}'
    result = extract_json(text)
    import json
    parsed = json.loads(result)
    assert "50%" in parsed["note"]
