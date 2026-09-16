import pytest

from simulator.run_simulation import benchmark_api


def test_benchmark_rejects_non_positive_sample_count():
    with pytest.raises(ValueError, match="greater than zero"):
        benchmark_api("http://127.0.0.1:8000/api/v1/detect", n_samples=0)
