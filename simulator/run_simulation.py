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
    suspect_human = 0
    suspect_bot = 0
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
            verdict = str(data.get("verdict") or "").upper()
            if verdict == "HUMAN":
                correct_human += 1
            elif verdict == "SUSPECT":
                suspect_human += 1
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
            verdict = str(data.get("verdict") or "").upper()
            if verdict == "BOT":
                correct_bot += 1
            elif verdict == "SUSPECT":
                suspect_bot += 1
            else:
                print(f"  [Evasion #{i+1}] {b_type} Bot bypassed detector! Prob: {data.get('bot_probability')}")
        except Exception as e:
            print(f"  Request error: {e}")

    print("\n--- BENCHMARK SUMMARY ---")
    print(f"Human Accuracy (True Negative): {correct_human}/{n_samples} ({correct_human/n_samples*100:.1f}%)")
    print(f"Bot Detection Rate (Recall):     {correct_bot}/{n_samples} ({correct_bot/n_samples*100:.1f}%)")
    print(f"Suspect Human / Bot:             {suspect_human} / {suspect_bot}")
    if latencies:
        print(f"Average Latency:                {sum(latencies)/len(latencies):.2f} ms")
    return {
        "human_correct": correct_human,
        "bot_correct": correct_bot,
        "human_suspect": suspect_human,
        "bot_suspect": suspect_bot,
        "successful_requests": len(latencies),
        "average_latency_ms": sum(latencies) / len(latencies) if latencies else None,
    }


def run_playwright_test(
    target_url: str,
    detect_endpoint: str = "http://127.0.0.1:8000/api/v1/detect",
    headless: bool = True,
):
    """
    Launches Playwright headless browser, interacts with target web page,
    and tests if the bot-collector script flags the automated session.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright not installed in current environment. Install via 'pip install playwright'.")
        return {
            "collector_loaded": False,
            "verdict": "ERROR",
            "bot_probability": None,
            "fallback": True,
            "error": "Playwright is not installed",
        }

    print(f"\n=== RUNNING PLAYWRIGHT BOT TEST AGAINST: {target_url} ===")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        print("Navigating to page...")
        try:
            page.goto(target_url, timeout=15000)
            collector_status = page.evaluate(
                r"""async (detectUrl) => {
                    if (typeof window.BotCollector === 'undefined') {
                        return { loaded: false };
                    }
                    const collector = new window.BotCollector({
                        detectUrl,
                        endpointUrl: detectUrl.replace(/\/detect$/, '/telemetry'),
                        autoSendInterval: 0,
                    });
                    await collector.start();
                    window.__botSimulationCollector = collector;
                    return { loaded: true };
                }""",
                detect_endpoint,
            )
            if not collector_status.get("loaded"):
                raise RuntimeError("BotCollector is not loaded on the target page")

            print("Page loaded successfully. Simulating bot clicks...")

            # Move mouse rapidly in straight lines
            for i in range(30):
                page.mouse.move(100 + (i % 12) * 80, 200 + (i % 8) * 35)
                time.sleep(0.02)
            page.mouse.click(600, 350)
            result = page.evaluate(
                """async () => window.__botSimulationCollector.checkBotStatus('playwright_test')"""
            )
            verdict = str(result.get("verdict") or "UNKNOWN").upper()
            print(
                "Detection result: "
                f"verdict={verdict}, probability={result.get('bot_probability')}"
            )
            return {
                "collector_loaded": True,
                "verdict": verdict,
                "bot_probability": result.get("bot_probability"),
                "fallback": bool(result.get("fallback", False)),
                "detected": verdict in {"BOT", "SUSPECT"},
            }

        except Exception as e:
            print(f"Navigation/Interaction error: {e}")
            return {
                "collector_loaded": False,
                "verdict": "ERROR",
                "bot_probability": None,
                "fallback": True,
                "error": str(e),
            }
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
        run_playwright_test(args.url, detect_endpoint=args.endpoint, headless=args.headless)
