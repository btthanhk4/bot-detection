"""Opt-in local stress benchmark for the FastAPI service.

Run directly with ``python -m tests.test_stress``. It intentionally does not
execute during pytest collection because that polluted shared rate-limit state.
"""

import statistics
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from api_service.config import settings
from api_service.main import app
from core_ml.dataset.loader import generate_synthetic_telemetry


NUM_REQUESTS = 400
CONCURRENCY = 8


def run_stress_test(num_requests=NUM_REQUESTS, concurrency=CONCURRENCY):
    client = TestClient(app)
    payloads = []
    for i in range(num_requests):
        is_bot = i % 2 == 1
        level = ["naive", "moderate", "advanced"][i % 3] if is_bot else None
        payloads.append(generate_synthetic_telemetry(is_bot=is_bot, bot_level=level))

    def send_request(payload):
        started = time.perf_counter()
        try:
            response = client.post("/api/v1/detect", json=payload)
            elapsed = (time.perf_counter() - started) * 1000.0
            verdict = response.json().get("verdict") if response.status_code == 200 else None
            return elapsed, verdict, None if response.status_code == 200 else f"HTTP_{response.status_code}"
        except Exception as exc:
            return (time.perf_counter() - started) * 1000.0, None, str(exc)

    original_limit = settings.RATE_LIMIT_PER_MINUTE
    settings.RATE_LIMIT_PER_MINUTE = 0
    started = time.perf_counter()
    try:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            results = list(executor.map(send_request, payloads))
    finally:
        settings.RATE_LIMIT_PER_MINUTE = original_limit

    total_time = time.perf_counter() - started
    latencies = sorted(result[0] for result in results)
    errors = [result[2] for result in results if result[2]]
    verdicts = {name: sum(result[1] == name for result in results) for name in ("HUMAN", "BOT", "SUSPECT")}

    return {
        "requests": num_requests,
        "errors": len(errors),
        "rps": num_requests / total_time,
        "p50_ms": statistics.median(latencies),
        "p95_ms": latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))],
        "p99_ms": latencies[min(len(latencies) - 1, int(len(latencies) * 0.99))],
        "verdicts": verdicts,
    }


if __name__ == "__main__":
    result = run_stress_test()
    print("Bot Detection Stress Benchmark")
    for key, value in result.items():
        print(f"{key}: {value}")
