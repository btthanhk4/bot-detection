"""
Commercial Production Stress & Concurrency Test
Simulates concurrent production traffic against the FastAPI API service.
Measures latency percentiles (P50, P95, P99), error rate, and throughput.
"""

import time
import statistics
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from api_service.main import app
from core_ml.dataset.loader import generate_synthetic_telemetry

client = TestClient(app)

NUM_REQUESTS = 400
CONCURRENCY = 8

print("=" * 60)
print(f"  STARTING STRESS TEST: {NUM_REQUESTS} requests across {CONCURRENCY} threads")
print("=" * 60)

# Pre-generate diverse payloads
payloads = []
for i in range(NUM_REQUESTS):
    is_bot = (i % 2 == 1)
    b_level = ["naive", "moderate", "advanced"][i % 3] if is_bot else None
    t = generate_synthetic_telemetry(is_bot=is_bot, bot_level=b_level)
    payloads.append((f"ip_{i % 50}", t))  # rotate through 50 distinct IPs to test graph & limiter

latencies = []
errors = 0
verdicts = {"HUMAN": 0, "BOT": 0, "SUSPECT": 0}

def send_request(idx):
    ip, payload = payloads[idx]
    t0 = time.perf_counter()
    try:
        res = client.post(
            "/api/v1/detect",
            json=payload,
            headers={"X-Forwarded-For": ip},
        )
        dt = (time.perf_counter() - t0) * 1000.0  # ms
        if res.status_code == 200:
            data = res.json()
            return dt, data.get("verdict", "UNKNOWN"), None
        else:
            return dt, None, f"HTTP_{res.status_code}"
    except Exception as e:
        dt = (time.perf_counter() - t0) * 1000.0
        return dt, None, str(e)

start_time = time.perf_counter()
with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
    results = list(executor.map(send_request, range(NUM_REQUESTS)))
total_time = time.perf_counter() - start_time

for dt, verdict, err in results:
    latencies.append(dt)
    if err:
        errors += 1
    elif verdict in verdicts:
        verdicts[verdict] += 1

latencies.sort()
p50 = statistics.median(latencies)
p90 = latencies[int(len(latencies) * 0.90)]
p95 = latencies[int(len(latencies) * 0.95)]
p99 = latencies[int(len(latencies) * 0.99)]
rps = NUM_REQUESTS / total_time

print(f"Total Requests:      {NUM_REQUESTS}")
print(f"Successful:          {NUM_REQUESTS - errors} ({(NUM_REQUESTS - errors)/NUM_REQUESTS*100:.1f}%)")
print(f"Failed / Errors:     {errors}")
print(f"Total Elapsed Time:  {total_time:.2f}s")
print(f"Throughput (RPS):    {rps:.1f} req/sec")
print("-" * 60)
print(f"Latency P50 (median): {p50:.2f} ms")
print(f"Latency P90:          {p90:.2f} ms")
print(f"Latency P95:          {p95:.2f} ms")
print(f"Latency P99:          {p99:.2f} ms")
print(f"Min / Max:            {min(latencies):.2f} ms / {max(latencies):.2f} ms")
print("-" * 60)
print(f"Verdicts distributed: {verdicts}")
print("=" * 60)
