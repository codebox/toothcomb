import logging
import time

from db.database import Database
from domain.types import ModelName

log = logging.getLogger(__name__)

# Backoff levels in seconds
_BACKOFF_STEPS = [30, 60, 120, 240, 300]


class RateLimitThrottled(Exception):
    """Raised when an API call is blocked because the model is rate-limited."""
    def __init__(self, message: str, retry_in_seconds: float = 0):
        super().__init__(message)
        self.retry_in_seconds = retry_in_seconds


class RateLimitTracker:
    """Tracks rate-limit state per model using the database.

    All workers share the same tracker instance, and the state is persisted
    so it survives application restarts.
    """

    def __init__(self, database: Database) -> None:
        self._db = database

    def is_throttled(self, model: ModelName) -> bool:
        """Check if a model is currently rate-limited."""
        state = self._db.get_rate_limit(model)
        if not state:
            return False
        return time.time() < state["retry_after"]

    def seconds_until_ready(self, model: ModelName) -> float:
        """Return seconds until the model is available, or 0 if ready now."""
        state = self._db.get_rate_limit(model)
        if not state:
            return 0
        remaining = state["retry_after"] - time.time()
        return max(0, remaining)

    def record_rate_limit(self, model: ModelName, retry_after_seconds: float | None = None) -> None:
        """Record that a model has been rate-limited.

        Uses the retry_after_seconds hint if provided (from the API response header),
        otherwise escalates through exponential backoff steps.
        """
        if retry_after_seconds and retry_after_seconds > 0:
            backoff = retry_after_seconds
            backoff_level = 0
        else:
            state = self._db.get_rate_limit(model)
            current_level = state["backoff_level"] if state else -1
            backoff_level = min(current_level + 1, len(_BACKOFF_STEPS) - 1)
            backoff = _BACKOFF_STEPS[backoff_level]

        retry_after = time.time() + backoff
        self._db.set_rate_limit(model, retry_after, backoff_level)
        log.warning("Rate limit recorded for %s — backing off %.0fs (level %d)", model, backoff, backoff_level)

    def clear_throttle(self, model: ModelName) -> None:
        """Clear rate-limit state after a successful call."""
        self._db.clear_rate_limit(model)
