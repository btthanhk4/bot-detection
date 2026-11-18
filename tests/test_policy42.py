"""Policy 42: on Android a worker disagreeing with the page about platform and GPU is one contradiction."""

from core_ml.features.client_forgery import (
    contradictions,
    forged_browser_fires,
    worker_only_android,
)

ANDROID = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/28.0 Chrome/130.0.0.0 Mobile Safari/537.36"
IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 Mobile/15E148 Safari/604.1"
WORKER = {"families": {"CONTEXT": ["worker.platformMismatch"], "GPU": ["worker.rendererMismatch"]}}


def test_worker_pair_counts_once_on_android():
    assert worker_only_android(["PLATFORM_SPOOFED"], WORKER, ANDROID)
    assert contradictions(["PLATFORM_SPOOFED"], WORKER, user_agent=ANDROID) == ["PLATFORM_SPOOFED"]
    assert not forged_browser_fires(["PLATFORM_SPOOFED"], WORKER, user_agent=ANDROID)


def test_iphones_keep_policy_32():
    assert not worker_only_android(["PLATFORM_SPOOFED"], WORKER, IPHONE)
    assert forged_browser_fires(["PLATFORM_SPOOFED"], WORKER, user_agent=IPHONE)


def test_other_anchors_and_contradictions_still_convict():
    page_gpu = {"families": {"CONTEXT": ["worker.platformMismatch"], "GPU": ["worker.rendererMismatch", "signals.gpuOsMismatch"]}}
    assert forged_browser_fires(["PLATFORM_SPOOFED"], page_gpu, user_agent=ANDROID)
    headless = {"families": {**WORKER["families"], "HEADLESS_ENV": ["signals.headlessScreen"]}}
    assert forged_browser_fires(["PLATFORM_SPOOFED"], headless, user_agent=ANDROID)
    assert forged_browser_fires(["PLATFORM_SPOOFED", "DESKTOP_FONTS"], WORKER, user_agent=ANDROID)
    assert forged_browser_fires(["PLATFORM_SPOOFED"], WORKER, ["ZERO_TIME_TAPS"], user_agent=ANDROID)


def test_without_a_user_agent_the_old_reading_holds():
    assert forged_browser_fires(["PLATFORM_SPOOFED"], WORKER)


def test_policy_version():
    from core_ml.models.ensemble import DECISION_POLICY_VERSION
    assert DECISION_POLICY_VERSION in ("42", "43", "44", "45", "46", "47", "48")
