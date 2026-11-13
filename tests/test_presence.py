"""Policy 33: page presence, first-touch reaction, motion summary, Client Hints, time zone vs IP country."""

from datetime import datetime, timezone

from core_ml.features.presence import analyze_presence, sanitize_presence
from core_ml.features.server_context import server_context_codes, timezone_mismatch

WINTER = datetime(2026, 1, 15, 12, tzinfo=timezone.utc)


def _payload(presence=None, hints=None, tz=None, country=None):
    payload = {"fingerprint": {}, "_server_headers": {}, "mouse": {}, "botd": {}}
    if presence is not None:
        payload["mouse"]["presence"] = presence
    if hints is not None:
        payload["botd"]["profile"] = {"main": {"clientHints": hints}}
    if tz:
        payload["fingerprint"]["timezone"] = tz
    if country:
        payload["_server_headers"]["ip_country"] = country
    return payload


def _seen(**extra):
    return {"prerendered": False, "initialVisibility": "visible", "firstVisibleMs": 0, "visibleMs": 9000,
            "hiddenCount": 0, "firstTouchMs": 800, "scrolls": 3, "maxScrollRatio": 0.5,
            "motion": {"status": "ok", "events": 300, "intervalMs": 16.7, "gravity": 9.8, "tiltDeg": 42.0,
                       "linearSd": 0.08, "gravitySd": 0.3, "rotationMean": 4.0, "rotationSd": 2.0}, **extra}


def test_older_collectors_report_nothing():
    report = analyze_presence(_payload(), android=True)
    assert report["reported"] is False and report["codes"] == [] and report["research_flags"] == []


def test_seen_page_held_phone():
    report = analyze_presence(_payload(_seen()), android=True)
    assert report["codes"] == [] and report["research_flags"] == ["HELD_IN_HAND"]
    assert report["first_touch_ms"] == 800 and report["motion"]["tilt_deg"] == 42.0


def test_prerendered_page_never_shown_is_not_viewed():
    presence = _seen(prerendered=True, initialVisibility="prerender", firstVisibleMs=None, visibleMs=0, firstTouchMs=None)
    assert analyze_presence(_payload(presence), android=True)["codes"] == ["NOT_VIEWED"]
    background = _seen(initialVisibility="hidden", firstVisibleMs=4000, visibleMs=200)
    assert analyze_presence(_payload(background), android=True)["codes"] == ["NOT_VIEWED"]


def test_instant_first_touch():
    assert analyze_presence(_payload(_seen(firstTouchMs=40)), android=True)["codes"] == ["INSTANT_TOUCH"]
    assert analyze_presence(_payload(_seen(firstTouchMs=120)), android=True)["codes"] == []


def test_still_device_and_missing_motion_are_research_only():
    still = _seen(motion={"status": "ok", "events": 300, "tiltDeg": 0.1, "linearSd": 0.0, "gravitySd": 0.0})
    report = analyze_presence(_payload(still), android=True)
    assert report["codes"] == [] and report["research_flags"] == ["STILL_DEVICE"]
    silent = _seen(motion={"status": "no_events"})
    assert analyze_presence(_payload(silent), android=True)["research_flags"] == ["NO_MOTION"]
    assert analyze_presence(_payload(silent), android=False)["research_flags"] == []


def test_client_hints_emulator_only_on_android():
    for hints in ({"model": "sdk_gphone64_x86_64", "architecture": ""}, {"model": "SM-A146B", "architecture": "x86"}):
        assert "CH_EMULATOR" in analyze_presence(_payload(_seen(), hints=hints), android=True)["codes"]
        assert "CH_EMULATOR" not in analyze_presence(_payload(_seen(), hints=hints), android=False)["codes"]
    real = {"model": "SM-A146B", "architecture": "", "platformVersion": "14.0.0", "mobile": True}
    assert analyze_presence(_payload(_seen(), hints=real), android=True)["codes"] == []


def test_sanitize_bounds_values():
    clean = sanitize_presence({"firstTouchMs": -5, "maxScrollRatio": 7, "initialVisibility": "x" * 99,
                               "motion": {"status": "streaming", "tiltDeg": float("nan")}})
    assert clean["first_touch_ms"] is None and clean["max_scroll_ratio"] is None
    assert len(clean["initial_visibility"]) == 16
    assert clean["motion"]["status"] is None and clean["motion"]["tilt_deg"] is None
    assert sanitize_presence("not a dict")["reported"] is False


def test_timezone_mismatch_needs_an_hour_from_every_zone_of_the_country():
    assert timezone_mismatch(_payload(tz="Asia/Ho_Chi_Minh", country="US"), WINTER) is True
    assert timezone_mismatch(_payload(tz="America/Los_Angeles", country="US"), WINTER) is False
    assert timezone_mismatch(_payload(tz="Asia/Calcutta", country="IN"), WINTER) is False, "legacy ICU name"
    assert timezone_mismatch(_payload(tz="Europe/Berlin", country="AT"), WINTER) is False, "neighbours, same offset"
    assert timezone_mismatch(_payload(tz="Asia/Bangkok", country="VN"), WINTER) is False
    assert timezone_mismatch(_payload(tz="UTC", country="US"), WINTER) is None, "zone in no country"
    assert timezone_mismatch(_payload(tz="Asia/Jakarta"), WINTER) is None, "no address country"
    assert timezone_mismatch(_payload(country="US"), WINTER) is None


def test_timezone_mismatch_is_a_server_context_code():
    assert "TIMEZONE_MISMATCH" in server_context_codes(_payload(tz="Asia/Jakarta", country="US"))
    assert "TIMEZONE_MISMATCH" not in server_context_codes(_payload(tz="Asia/Jakarta", country="ID"))
