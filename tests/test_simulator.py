import pytest

from simulator.run_simulation import benchmark_api


def test_benchmark_rejects_non_positive_sample_count():
    with pytest.raises(ValueError, match="greater than zero"):
        benchmark_api("http://127.0.0.1:8000/api/v1/detect", n_samples=0)


def test_benchmark_does_not_count_suspects_as_correct(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"verdict": "SUSPECT", "is_bot": False, "bot_probability": 0.5}

    monkeypatch.setattr("simulator.run_simulation.requests.post", lambda *args, **kwargs: Response())

    summary = benchmark_api("http://example.test/detect", n_samples=1)

    assert summary["human_correct"] == 0
    assert summary["bot_correct"] == 0
    assert summary["human_suspect"] == 1
    assert summary["bot_suspect"] == 1
