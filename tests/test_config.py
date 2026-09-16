import pytest

from api_service.config import _env_float, _env_int


def test_integer_environment_value_is_range_checked(monkeypatch):
    monkeypatch.setenv("TEST_INTEGER_SETTING", "-1")

    with pytest.raises(ValueError, match="TEST_INTEGER_SETTING"):
        _env_int("TEST_INTEGER_SETTING", 10, 1)


def test_float_environment_value_rejects_non_finite_values(monkeypatch):
    monkeypatch.setenv("TEST_FLOAT_SETTING", "nan")

    with pytest.raises(ValueError, match="TEST_FLOAT_SETTING"):
        _env_float("TEST_FLOAT_SETTING", 0.5, 0.0, 1.0)
