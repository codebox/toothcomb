from config import Config
from domain.fact_check_result import FactCheckResult


class FactChecker:
    def __init__(self, config: Config):
        self.config = config

    def fact_check(self, query: str) -> FactCheckResult:
        raise NotImplementedError(f"{type(self).__name__} must implement fact_check()")
