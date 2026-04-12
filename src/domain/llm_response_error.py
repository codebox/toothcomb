class LLMResponseError(Exception):
    def __init__(self, message: str, llm_response: str, query: str = None):
        detail = f"{message}\n\nLLM response:\n{llm_response}"
        if query:
            detail += f"\n\nQuery:\n{query}"
        super().__init__(detail)
        self.llm_response = llm_response
