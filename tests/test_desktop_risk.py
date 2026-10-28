"""Policy 21: input provenance and environment evidence withhold a desktop HUMAN verdict."""

import copy

import numpy as np
import pytest

from core_ml.features.desktop_risk import analyze_desktop_risk
from core_ml.models.ensemble import EnsembleBotDetector
from core_ml.release_cases import DESKTOP_RISK_CASES, DESKTOP_RISK_RULE_GATE
from core_ml.train import validate_desktop_risk_rules

WINDOWS_CHROME = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/155.0.0.0 Safari/537.36")
MAC_CHROME = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/155.0.0.0 Safari/537.36")
WINDOWS_FIREFOX = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:158.0) Gecko/20100101 Firefox/158.0"
D3D = "ANGLE (Intel, Intel(R) Iris(R) Xe Graphics (0x00009A49) Direct3D11 vs_5_0 ps_5_0, D3D11)"
SWIFTSHADER = "ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) (0x0000C0DE)), SwiftShader driver)"


class FixedLSTM:
    def __init__(self, score=0.05):
        self.score = score

    def predict_session_scores(self, chunks):
        return self.score, self.score


class FixedTabular:
    def __init__(self, score=0.02):
        self.score = score

    def predict_proba(self, vector):
        return self.score


def moves(n=80, gap=16.7, burst=0):
    """A wandering path sampled every ``gap`` ms; ``burst`` moves per step land within 1 ms."""
    rng = np.random.default_rng(3)
    t, x, y, records = 0.0, 300.0, 200.0, []
    for _ in range(n):
        t += gap + float(rng.uniform(-0.4, 0.4))
        x += float(rng.normal(6, 3))
        y += float(rng.normal(2, 3))
        records.append({"time": round(t), "x": round(x, 1), "y": round(y, 1), "type": "move", "source": "mouse"})
        for k in range(burst):
            records.append({"time": round(t) + (k % 2), "x": round(x + k + 1, 1), "y": round(y, 1),
                            "type": "move", "source": "mouse"})
    return records


def stats(moves=500, coalesced=1.9, multi=0.8, secure=True, frame_ms=16.7, frames=60):
    return {"pointermove": moves, "coalescedTotal": round(moves * coalesced), "coalescedMax": 4,
            "coalescedMulti": round(moves * multi), "secureContext": secure,
            **({"frameMs": frame_ms, "frames": frames} if frame_ms else {})}


def payload(records=None, pointer=None, ua=WINDOWS_CHROME, renderer=D3D, signals=None, datacenter=None):
    return {
        "_server_user_agent": ua,
        "_server_headers": {"observed": True, "accept_language": True, "sec_ch_ua": "",
                            **({"datacenter": datacenter} if datacenter else {})},
        "fingerprint": {"userAgent": ua, "webglRenderer": renderer},
        "botd": {"detectors": {}, "automation": {"schema": "automation-v1", "signals": signals or {}, "worker": None}},
        "mouse": {"records": moves() if records is None else records,
                  **({"pointerStats": pointer} if pointer is not None else {})},
    }


def predict(body, lstm=0.05, tabular=0.02):
    return EnsembleBotDetector(lstm_model=FixedLSTM(lstm), tabular_model=FixedTabular(tabular)).predict(body)


def codes(body):
    return predict(body)["breakdown"]["desktop_risk"]["codes"]


def test_windows_mouse_with_coalesced_samples_is_human():
    result = predict(payload(pointer=stats()))
    assert result["verdict"] == "HUMAN"
    assert result["breakdown"]["desktop_risk"]["codes"] == []
    assert result["breakdown"]["desktop_risk"]["frame_judged"] is True


def test_cdp_frame_locked_pointer_is_final_suspect():
    result = predict(payload(pointer=stats(coalesced=1.0, multi=0.002)))
    breakdown = result["breakdown"]
    assert (result["verdict"], result["decision_state"]) == ("SUSPECT", "FINAL")
    assert breakdown["decision_basis"] == "desktop_risk"
    assert breakdown["desktop_risk"]["codes"] == ["FRAME_LOCKED_POINTER"]
    assert "DESKTOP_RISK" in breakdown["suspect_reason_codes"]
    assert breakdown["verdict_locked"] is False
    assert any("input or environment does not" in reason for reason in result["reasons"])


def test_frame_lock_is_judged_on_two_frame_cadence_and_spoofed_ua():
    # A bot that waits between moves lands every other frame; a Direct3D renderer is Windows.
    assert codes(payload(moves(gap=33.4), stats(coalesced=1.0, multi=0.0))) == ["FRAME_LOCKED_POINTER"]
    assert codes(payload(pointer=stats(coalesced=1.0, multi=0.0), ua=MAC_CHROME)) == ["FRAME_LOCKED_POINTER"]


@pytest.mark.parametrize("body", [
    # macOS and X11 coalesce before Chrome does; a measured Linux user had 1.02.
    payload(pointer=stats(coalesced=1.0, multi=0.0), ua=MAC_CHROME, renderer="ANGLE (Apple, ANGLE Metal Renderer: Apple M2)"),
    # 144 Hz display with a 125 Hz mouse: one sample per frame is normal.
    payload(moves(gap=6.9), stats(coalesced=1.0, multi=0.0, frame_ms=6.9)),
    # Old collector, no frame probe: the move spacing stands in for the frame interval.
    payload(moves(gap=6.9), stats(coalesced=1.0, multi=0.0, frame_ms=None)),
    # Plain HTTP: no coalesced samples at all.
    payload(pointer=stats(coalesced=0.0, multi=0.0, secure=False)),
    # Firefox is not judged.
    payload(pointer=stats(coalesced=1.0, multi=0.0), ua=WINDOWS_FIREFOX),
    # Too few moves.
    payload(pointer=stats(moves=20, coalesced=1.0, multi=0.0)),
    # A VPN exit with a real GPU.
    payload(pointer=stats(), datacenter="aws"),
    # One non-anchor family (a UA switcher touches client hints).
    payload(pointer=stats(), signals={"uaHintsMismatch": True}),
])
def test_human_lookalikes_are_not_flagged(body):
    result = predict(body)
    assert result["breakdown"]["desktop_risk"]["codes"] == []
    assert result["verdict"] == "HUMAN"


def test_cdp_moves_faster_than_frames_are_unaligned():
    # CDP moves fired every 2 ms without waiting arrive 4 ms apart on a 60 Hz display.
    body = payload(moves(n=90, gap=4.0), stats(coalesced=1.07, multi=0.07))
    assert codes(body) == ["UNALIGNED_POINTER"]
    # A 240 Hz display delivers real moves that often.
    assert codes(payload(moves(n=90, gap=4.2), stats(coalesced=1.07, multi=0.07, frame_ms=4.2))) == []
    # Chrome's 30 fps battery saver slows input with the frames.
    assert codes(payload(moves(n=90, gap=33.3), stats(frame_ms=33.3))) == []
    # Without a measured frame interval nothing is judged.
    assert "UNALIGNED_POINTER" not in codes(payload(moves(n=90, gap=4.0), stats(coalesced=1.07, frame_ms=None)))


def test_tampered_pointer_apis():
    # getCoalescedEvents patched to hand back the event itself (collector 1.9 counts these).
    assert codes(payload(pointer={**stats(coalesced=0.0, multi=0.0), "coalescedSelf": 900})) == ["POINTER_API_TAMPERED"]
    # getCoalescedEvents deleted: no samples at all in a secure Chromium page.
    assert codes(payload(pointer=stats(coalesced=0.0, multi=0.0))) == ["POINTER_API_TAMPERED"]
    # The collector saw a non-native getCoalescedEvents or requestAnimationFrame.
    assert codes(payload(pointer=stats(), signals={"inputApiPatched": True})) == ["POINTER_API_TAMPERED"]
    # Plain HTTP pages and Firefox have no samples to judge.
    assert codes(payload(pointer=stats(coalesced=0.0, multi=0.0, secure=False))) == []
    assert codes(payload(pointer=stats(coalesced=0.0, multi=0.0), ua=WINDOWS_FIREFOX)) == []


def test_requests_without_browser_headers():
    forged = payload(pointer=stats())
    forged["_server_headers"]["accept_language"] = False
    assert codes(forged) == ["NON_BROWSER_REQUEST"]
    https = payload(pointer=stats())
    https["_server_headers"]["forwarded_proto"] = "https"
    assert codes(https) == ["NON_BROWSER_REQUEST"]
    https["_server_headers"]["sec_fetch_site"] = "same-origin"
    assert codes(https) == []


def test_sparse_moves_are_still_frame_locked():
    # A script stepping every 110-160 ms leaves no move spacing to measure; the measured
    # frame interval is enough to judge the coalesced samples.
    body = payload(moves(gap=130.0), stats(coalesced=1.004, multi=0.004))
    report = predict(body)["breakdown"]["desktop_risk"]
    assert report["move_interval_ms"] is None and report["codes"] == ["FRAME_LOCKED_POINTER"]
    # Another run of the same script: a stalled main thread merged a few injected moves.
    assert codes(payload(moves(gap=130.0), stats(coalesced=1.051, multi=0.048))) == ["FRAME_LOCKED_POINTER"]
    # A mouse reporting a little faster than the display is not frame-locked.
    assert codes(payload(pointer=stats(coalesced=1.12, multi=0.11))) == []


def test_subframe_burst():
    assert codes(payload(moves(n=40, burst=3), stats(coalesced=3.4, multi=0.8))) == ["SUBFRAME_POINTER_BURST"]
    # A payload without pointer statistics (training sets, other tools) is not timed.
    assert codes(payload(moves(n=40, burst=3))) == []


def test_cloud_software_gpu_and_environment_evidence():
    assert codes(payload(pointer=stats(), renderer=SWIFTSHADER, datacenter="gcp")) == ["CLOUD_SOFTWARE_GPU"]
    assert codes(payload(pointer=stats(), signals={"headlessScreen": True})) == ["ENVIRONMENT_EVIDENCE"]
    assert codes(payload(pointer=stats(), signals={"uaHintsMismatch": True, "navigatorGetterPatched": True})) == [
        "ENVIRONMENT_EVIDENCE"]


def test_risk_never_turns_a_verdict_into_bot_or_human():
    flagged = payload(pointer=stats(coalesced=1.0, multi=0.0))
    bot = predict(flagged, lstm=0.99, tabular=0.99)
    assert bot["verdict"] == "BOT" and bot["breakdown"]["decision_basis"] == "ensemble"
    suspect = predict(flagged, lstm=0.6, tabular=0.6)
    assert suspect["verdict"] == "SUSPECT" and suspect["breakdown"]["decision_basis"] == "ensemble"
    assert "DESKTOP_RISK" in suspect["breakdown"]["suspect_reason_codes"]


def test_insufficient_mouse_stays_insufficient():
    result = predict(payload(moves(n=10), stats(coalesced=1.0, multi=0.0)))
    assert (result["verdict"], result["decision_state"]) == ("SUSPECT", "INSUFFICIENT_EVIDENCE")
    assert "DESKTOP_RISK" not in result["breakdown"]["suspect_reason_codes"]


def test_phones_are_not_judged():
    report = analyze_desktop_risk({"fingerprint": {"userAgent": WINDOWS_CHROME}}, {"families": {"GPU": ["x"]}},
                                  [], {"pointer_moves": 100}, judged=False)
    assert report["codes"] == [] and report["judged"] is False


def test_malformed_pointer_statistics_are_ignored():
    body = payload(pointer={"pointermove": "x", "coalescedTotal": None, "secureContext": "yes"})
    assert codes(body) == []


@pytest.fixture(scope="module")
def production_detector():
    from api_service.main import ensemble_detector

    return ensemble_detector


@pytest.mark.parametrize("index", range(len(DESKTOP_RISK_CASES)))
def test_release_fixtures(production_detector, index):
    verdict, expected_codes, body = DESKTOP_RISK_CASES[index]
    result = production_detector.predict(copy.deepcopy(body))
    assert result["breakdown"]["desktop_risk"]["codes"] == expected_codes
    assert result["decision_state"] == "FINAL"
    assert (result["verdict"] == "HUMAN") == (verdict == "HUMAN")


def test_release_gate_counts(production_detector):
    gate = validate_desktop_risk_rules(production_detector)
    assert gate == DESKTOP_RISK_RULE_GATE
    assert (gate["human_cases"], gate["suspect_cases"]) == (11, 12)
