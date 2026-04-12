import os
from pathlib import Path
from typing import Any

import yaml


class Config:
    """Reads a YAML config file and supports dot-separated key lookup.

    Environment variables override file values. For a key like
    "whisper.model", the env var WHISPER__MODEL is checked first
    (dots become double underscores, uppercased).
    """

    def __init__(self, path: str = "resources/config.yaml") -> None:
        config_path = Path(path)
        if config_path.exists():
            with open(config_path) as f:
                self._data = yaml.safe_load(f) or {}
        else:
            self._data = {}

    def get(self, key: str, default: Any = None) -> Any:
        """Look up a dot-separated key, e.g. config.get("whisper.model").

        Checks for an environment variable first (dots → __, uppercased).
        Falls back to traversing the YAML dict.
        """
        env_name = key.replace(".", "__").upper()
        env_val = os.environ.get(env_name)
        if env_val is not None:
            return self._coerce(env_val)

        parts = key.split(".")
        node = self._data
        for part in parts:
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    @staticmethod
    def _coerce(value: str) -> Any:
        """Best-effort coercion of env var strings to Python types."""
        if value.lower() in ("true", "yes"):
            return True
        if value.lower() in ("false", "no"):
            return False
        try:
            return int(value)
        except ValueError:
            pass
        try:
            return float(value)
        except ValueError:
            pass
        return value
