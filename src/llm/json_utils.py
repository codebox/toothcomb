import json

from domain.llm_response_error import LLMResponseError


def parse_llm_json(llm_response: str, required_fields: list[str],
                    context: str = "", query: str = "") -> dict:
    """Parse an LLM response as JSON and validate required top-level fields.

    Returns the parsed dict. Raises LLMResponseError on any failure.
    """
    try:
        data = json.loads(extract_json(llm_response))
    except json.JSONDecodeError as e:
        raise LLMResponseError(f"{context}Response is not valid JSON: {e}", llm_response, query) from e

    if not isinstance(data, dict):
        raise LLMResponseError(f"{context}Response is not a JSON object", llm_response, query)

    for field in required_fields:
        if field not in data:
            raise LLMResponseError(
                f"{context}Response missing required '{field}' field", llm_response, query)

    return data


def extract_json(text: str) -> str:
    """Extract the last top-level JSON object from an LLM response.

    Handles responses with or without code fences, and cases where the LLM
    self-corrects by outputting multiple JSON blocks with reasoning in between.
    """
    # Strip backtick fence lines entirely
    lines = text.splitlines()
    cleaned = "\n".join(line for line in lines if not line.strip().startswith("```"))

    # Find all top-level JSON objects using raw_decode
    decoder = json.JSONDecoder()
    results = []
    i = 0
    while i < len(cleaned):
        if cleaned[i] == "{":
            try:
                obj, end = decoder.raw_decode(cleaned, i)
                results.append(json.dumps(obj))
                i = end
                continue
            except json.JSONDecodeError:
                pass
        i += 1

    if results:
        return results[-1]
    return text.strip()
