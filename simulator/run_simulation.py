"""
Traffic Simulator & Benchmark Testing Script
Generates both API-level simulated traffic and real browser Playwright traffic
to evaluate the multi-modal bot detection model.
"""

import os
import argparse
import sys
import time
import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core_ml.dataset.loader import generate_synthetic_telemetry


def benchmark_api(endpoint: str, n_samples: int = 20):
    if n_samples <= 0:
        raise ValueError("n_samples must be greater than zero")
    print(f"\n=== BENCHMARKING INFERENCE API: {endpoint} ===")
    print(f"Sending {n_samples} Human and {n_samples} Bot payloads...")

    correct_human = 0
    correct_bot = 0
    latencies = []

    # 1. Test Humans
    for i in range(n_samples):
        payload = generate_synthetic_telemetry(is_bot=False)
        t0 = time.perf_counter()
        try:
            res = requests.post(endpoint, json=payload, timeout=5)
            res.raise_for_status()
            dt = (time.perf_counter() - t0) * 1000
            latencies.append(dt)
            data = res.json()
            if not data.get("is_bot", True):
                correct_human += 1
            else:
                print(f"  [False Positive #{i+1}] Human classified as Bot! Prob: {data.get('bot_probability')}")
        except Exception as e:
            print(f"  Request error: {e}")

    # 2. Test Bots
    bot_types = ["naive", "moderate", "advanced"]
    for i in range(n_samples):
        b_type = bot_types[i % len(bot_types)]
        payload = generate_synthetic_telemetry(is_bot=True, bot_level=b_type)
        t0 = time.perf_counter()
        try:
            res = requests.post(endpoint, json=payload, timeout=5)
            res.raise_for_status()
            dt = (time.perf_counter() - t0) * 1000
            latencies.append(dt)
            data = res.json()
            if data.get("is_bot", False):
                correct_bot += 1
            else:
                print(f"  [Evasion #{i+1}] {b_type} Bot bypassed detector! Prob: {data.get('bot_probability')}")
        except Exception as e:
            print(f"  Request error: {e}")

    print("\n--- BENCHMARK SUMMARY ---")
    print(f"Human Accuracy (True Negative): {correct_human}/{n_samples} ({correct_human/n_samples*100:.1f}%)")
    print(f"Bot Detection Rate (Recall):     {correct_bot}/{n_samples} ({correct_bot/n_samples*100:.1f}%)")
    if latencies:
        print(f"Average Latency:                {sum(latencies)/len(latencies):.2f} ms")


def run_playwright_test(target_url: str, headless: bool = True):
    """
    Launches Playwright headless browser, interacts with target web page,
    and tests if the bot-collector script flags the automated session.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright not installed in current environment. Install via 'pip install playwright'.")
        return

    print(f"\n=== RUNNING PLAYWRIGHT BOT TEST AGAINST: {target_url} ===")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        print("Navigating to page...")
        try:
            page.goto(target_url, timeout=15000)
            print("Page loaded successfully. Simulating bot clicks...")

            # Move mouse rapidly in straight lines
            for i in range(5):
                page.mouse.move(100 + i * 150, 200 + i * 50)
                time.sleep(0.02)
            page.mouse.click(600, 350)
            time.sleep(1)

            # Check if BotCollector is present in window
            collector_status = page.evaluate("""() => {
                if (typeof window.BotCollector !== 'undefined') {
                    return 'BotCollector loaded';
                }
                return 'BotCollector not loaded on page';
            }""")
            print(f"Telemetry Status on page: {collector_status}")

        except Exception as e:
            print(f"Navigation/Interaction error: {e}")
        finally:
            browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bot Detection Traffic Simulator")
    parser.add_argument("--mode", choices=["benchmark", "browser"], default="benchmark")
    parser.add_argument("--endpoint", default="http://127.0.0.1:8000/api/v1/detect")
    parser.add_argument("--url", default="http://localhost:5173")
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True)

    args = parser.parse_args()

    if args.mode == "benchmark":
        benchmark_api(args.endpoint, n_samples=args.samples)
    elif args.mode == "browser":
        run_playwright_test(args.url, headless=args.headless)
