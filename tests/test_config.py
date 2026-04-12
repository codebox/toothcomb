import os
from unittest.mock import patch

import pytest

from config import Config


# ---------- YAML file loading ----------


class TestFileLoading:

    def test_loads_yaml_file(self, tmp_path):
        f = tmp_path / "config.yaml"
        f.write_text("whisper:\n  model: tiny\n")
        cfg = Config(str(f))
        assert cfg.get("whisper.model") == "tiny"

    def test_missing_file_gives_empty_config(self, tmp_path):
        cfg = Config(str(tmp_path / "nope.yaml"))
        assert cfg.get("anything") is None

    def test_empty_file_gives_empty_config(self, tmp_path):
        f = tmp_path / "config.yaml"
        f.write_text("")
        cfg = Config(str(f))
        assert cfg.get("anything") is None


# ---------- dot-separated key lookup ----------


class TestGet:

    def _config(self, tmp_path, yaml_text):
        f = tmp_path / "config.yaml"
        f.write_text(yaml_text)
        return Config(str(f))

    def test_top_level_key(self, tmp_path):
        cfg = self._config(tmp_path, "log_level: DEBUG\n")
        assert cfg.get("log_level") == "DEBUG"

    def test_nested_key(self, tmp_path):
        cfg = self._config(tmp_path, "llm:\n  anthropic:\n    api_key: sk-123\n")
        assert cfg.get("llm.anthropic.api_key") == "sk-123"

    def test_missing_key_returns_default(self, tmp_path):
        cfg = self._config(tmp_path, "a: 1\n")
        assert cfg.get("b") is None
        assert cfg.get("b", 42) == 42

    def test_missing_nested_key_returns_default(self, tmp_path):
        cfg = self._config(tmp_path, "a:\n  b: 1\n")
        assert cfg.get("a.c") is None
        assert cfg.get("a.b.c") is None  # b is int, not dict

    def test_non_dict_intermediate_returns_default(self, tmp_path):
        cfg = self._config(tmp_path, "a: hello\n")
        assert cfg.get("a.b") is None

    def test_numeric_values_preserved(self, tmp_path):
        cfg = self._config(tmp_path, "port: 8080\nrate: 0.5\n")
        assert cfg.get("port") == 8080
        assert cfg.get("rate") == 0.5

    def test_boolean_values_preserved(self, tmp_path):
        cfg = self._config(tmp_path, "debug: true\n")
        assert cfg.get("debug") is True

    def test_list_value(self, tmp_path):
        cfg = self._config(tmp_path, "items:\n  - a\n  - b\n")
        assert cfg.get("items") == ["a", "b"]


# ---------- environment variable override ----------


class TestEnvOverride:

    def test_env_var_overrides_file(self, tmp_path):
        f = tmp_path / "config.yaml"
        f.write_text("whisper:\n  model: tiny\n")
        cfg = Config(str(f))

        with patch.dict(os.environ, {"WHISPER__MODEL": "large-v3"}):
            assert cfg.get("whisper.model") == "large-v3"

    def test_env_var_name_uppercased(self, tmp_path):
        cfg = Config(str(tmp_path / "nope.yaml"))

        with patch.dict(os.environ, {"MY__SETTING": "value"}):
            assert cfg.get("my.setting") == "value"

    def test_env_var_not_set_falls_through(self, tmp_path):
        f = tmp_path / "config.yaml"
        f.write_text("a: from_file\n")
        cfg = Config(str(f))

        # Make sure env var is not set
        with patch.dict(os.environ, {}, clear=True):
            assert cfg.get("a") == "from_file"

    def test_env_var_coerced_to_int(self, tmp_path):
        cfg = Config(str(tmp_path / "nope.yaml"))

        with patch.dict(os.environ, {"PORT": "8080"}):
            assert cfg.get("port") == 8080

    def test_env_var_coerced_to_bool(self, tmp_path):
        cfg = Config(str(tmp_path / "nope.yaml"))

        with patch.dict(os.environ, {"DEBUG": "true"}):
            assert cfg.get("debug") is True

    def test_top_level_env_var(self, tmp_path):
        cfg = Config(str(tmp_path / "nope.yaml"))

        with patch.dict(os.environ, {"LOG_LEVEL": "DEBUG"}):
            assert cfg.get("log_level") == "DEBUG"


# ---------- _coerce ----------


class TestCoerce:

    @pytest.mark.parametrize("value,expected", [
        ("true", True),
        ("True", True),
        ("TRUE", True),
        ("yes", True),
        ("YES", True),
        ("false", False),
        ("False", False),
        ("FALSE", False),
        ("no", False),
        ("NO", False),
    ])
    def test_boolean_coercion(self, value, expected):
        assert Config._coerce(value) is expected

    @pytest.mark.parametrize("value,expected", [
        ("0", 0),
        ("42", 42),
        ("-1", -1),
        ("999999", 999999),
    ])
    def test_int_coercion(self, value, expected):
        result = Config._coerce(value)
        assert result == expected
        assert isinstance(result, int)

    @pytest.mark.parametrize("value,expected", [
        ("3.14", 3.14),
        ("0.5", 0.5),
        ("-2.0", -2.0),
    ])
    def test_float_coercion(self, value, expected):
        result = Config._coerce(value)
        assert result == pytest.approx(expected)
        assert isinstance(result, float)

    def test_string_fallback(self):
        assert Config._coerce("hello") == "hello"
        assert Config._coerce("sk-abc123") == "sk-abc123"
        assert Config._coerce("") == ""
