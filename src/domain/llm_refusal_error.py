class LLMRefusalError(Exception):
    """The model declined to answer (stop_reason "refusal").

    Kept separate from LLMResponseError so the parse-retry loop doesn't resend a
    prompt that will most likely be refused again.
    """

    def __init__(self, model: str, category: str | None = None):
        self.model = model
        self.category = category
        self.reason = "Claude declined to answer"
        if category:
            self.reason += f" (refusal category: {category})"
        super().__init__(f"Model {model} refused the request (category={category or 'unspecified'})")
