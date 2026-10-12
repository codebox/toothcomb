class ClaudeCodeError(Exception):
    """A Claude Code run failed for a reason other than rate limiting or a refusal.

    `reason` is a short, user-readable explanation suitable for a failure note.
    """

    def __init__(self, message: str):
        super().__init__(message)
        self.reason = message
