import logging
import threading
import time
from abc import ABC, abstractmethod

from llm.rate_limit_tracker import RateLimitThrottled

log = logging.getLogger(__name__)

_DEFAULT_POLL_INTERVAL = 0.2  # seconds


class PollingWorker(ABC):
    def __init__(self, name: str, num_workers: int = 1,
                 poll_interval: float = _DEFAULT_POLL_INTERVAL) -> None:
        self._name = name
        self._num_workers = num_workers
        self._poll_interval = poll_interval
        self._running = False
        self._threads: list[threading.Thread] = []

    @abstractmethod
    def poll(self) -> bool:
        """Check for work and process one item. Return True if work was found."""
        raise NotImplementedError

    def start(self) -> None:
        self._running = True
        for i in range(self._num_workers):
            thread = threading.Thread(
                target=self._run,
                name=f"{self._name}-{i}",
                daemon=True,
            )
            self._threads.append(thread)
            thread.start()
        log.info("Started %d %s worker(s)", self._num_workers, self._name)

    def stop(self) -> None:
        self._running = False
        for thread in self._threads:
            thread.join()
        self._threads.clear()
        log.info("Stopped %s workers", self._name)

    def _run(self) -> None:
        while self._running:
            try:
                if not self.poll():
                    time.sleep(self._poll_interval)
            except RateLimitThrottled as e:
                wait = max(e.retry_in_seconds, self._poll_interval)
                log.info("[%s] Rate limited — sleeping %.0fs", self._name, wait)
                time.sleep(wait)
            except Exception:
                log.exception("[%s] Error in poll cycle", self._name)
                time.sleep(self._poll_interval)
