"""Policy 26: a pointer that jumps between random points, and browser claims no browser makes.

Measured 2026-11-10 on an ad landing page ("Downloader", 3,283 sessions from pop and
redirect ad networks): the mouse models called 294 of its sessions HUMAN, and 265 of those
carried the evidence below.

* ``RANDOM_POINTER_JUMPS``: the pointer does not travel, it lands on random points. In a
  collector export of 10+ moves (25+ in policy 26), at least 40% of the steps cross more
  than 15% of the viewport, and of at least 5 pairs of consecutive jumps at least half turn back (the two
  steps more than 90 degrees apart). A hand that moves fast between targets, recorded
  sparsely, still keeps its direction from one step to the next. Balabit (10 people, 1,676
  Remote Desktop sessions sampled at about 10 Hz, replayed as 41,899 collector exports):
  no export matched; jumps alone (30% of steps) matched 15 sessions, which is why the turn
  is required. On the lander: 388 of 502 sessions with 25+ moves (turn share median 0.78;
  the people on the shop: 0.09, no jumps).
* ``UA_POINTER_MISMATCH``: the user agent claims Safari before 13 (or Chrome before 55),
  which has no Pointer Events, yet trusted pointer events arrived. The lander: 1,422
  sessions claiming Safari 9-12, 728 of them Safari 9 on macOS 10.13+, which never shipped.
* ``WEBDRIVER_TAMPERED``: ``navigator.webdriver`` was redefined on the navigator object,
  given a script getter, or deleted from a Chromium browser. Stealth plugins do this to
  hide automation; a browser never does. The lander: 2,555 sessions; people on the live
  site: none. An extension could do it too, so alone it only withholds a HUMAN verdict.
* ``SERVER_CPU``: a desktop reporting more than 64 logical cores. The lander: 371 sessions,
  all Linux x86_64 reporting 640. A 128-thread workstation is possible, hence not a BOT rule.

None of these convicts alone. ``synthetic_pointer_path_v1`` convicts a session whose
pointer jumps at random and whose browser also contradicts itself (one of the other codes
or any environment family except a cloud address).

Policy 27 (2026-11-10, measured on 11 sessions of real people moving a mouse on the lander
and the shop, against 1,358 lander sessions with two contradictions):

* The jump rule is judged from 10 moves. The lander's bots move a median of 20 times, so
  at 25 most of them were never judged. Balabit replayed as 51,863 exports of 10 moves or
  more: no export matched. The 11 people: none (largest step share 0.24, turn-back 0.09).
* ``forged_browser_v1`` convicts a session with two of the browser contradictions. Each
  comes from a different source (the user agent against the events, the navigator object,
  the hardware), and a genuine browser produces none of them: no person on the live site
  carried even one. On the lander, 1,621 sessions carried two.

Policy 28: a headless, GPU or permission contradiction (the anchor families of
``environment_tampering_v1``) counts as one more independent contradiction towards the two
that convict. Alone it changes nothing (since policy 12, environment evidence without input
leaves a session insufficient). On the lander, 371 sessions
reported 640 cores and rendered WebGL with SwiftShader behind home addresses: server hardware.
No person on the live site carried any environment family.

Policy 29: ``ZERO_TIME_TAPS`` (two or more taps released less than 1 ms after they landed) is
one more. A finger stays on glass for tens of milliseconds: the user's iPhone, tapping as fast
as it could, gave 47-80 ms (0 of 20 taps under 1 ms, 2026-11-10), two other iPhones on the shop
0 of 5; the lander's WebView bots 145 of 237 taps under 1 ms (median 0), Playwright's iPhone 8
of 8. Screen readers (TalkBack) may synthesize instant taps, so alone it only withholds HUMAN;
with ``navigator.webdriver`` tampered it convicts.

Policy 30 (2026-11-11, the lander's 225 live sessions; 22 SUSPECT, 30 insufficient):

* ``webview_webdriver_v1``: an Android WebView (``; wv)`` in the user agent) whose
  ``navigator.webdriver`` was redefined or deleted. On a desktop an extension could do that, which
  is why the flag alone only withholds HUMAN; a WebView runs no extensions, so the app hosting it
  hid its own automation flag. The lander: 59 such WebViews, all Chrome 156/157 on Android TV and
  phone names (Chromecast, MiTV-MOOQ3, FlowBox-Z3), all missing the Sec-Fetch headers a Chromium
  page sends. 39 tapped 12-20 times at 0 ms and were already BOT; the other 20 left before tapping
  twice and stayed SUSPECT. A desktop GPU behind a WebView user agent is not judged here.
* ``apple_synthetic_touch_v1``: an iPhone or iPad (including iPadOS Safari's desktop mode) on a
  current WebKit (18+) whose every touch point has contact radius exactly 1 and force exactly 1,
  release included: Chromium's CDP defaults. WebKit reports the finger's contact area (the user's
  and other iPhones on the shop: 24.3/36.4/48.6 px, force 0) and Playwright's WebKit none, so a
  browser that claims Safari and sends these touches is a Chromium driven through CDP. The lander:
  5 iPads (Safari 26-27, 2-19 taps), SUSPECT or insufficient before. Two gestures are enough.
"""

import math
import re

from core_ml.features.automation_evidence import _DESKTOP_GPU, TAMPERING_ANCHOR_FAMILIES
from core_ml.features.mouse_features import normalize_move_coordinates

SYNTHETIC_PATH_RULE = "synthetic_pointer_path_v1"
FORGED_BROWSER_RULE = "forged_browser_v1"
WEBVIEW_WEBDRIVER_RULE = "webview_webdriver_v1"
APPLE_SYNTHETIC_TOUCH_RULE = "apple_synthetic_touch_v1"
APPLE_TOUCH_MIN_GESTURES = 2
# WebKit reports a contact radius on current iOS (seen on iOS 18 and Safari 26, whose UA
# freezes the OS at 18_6); older versions are not judged.
APPLE_CONTACT_MIN_VERSION = 18
FORGED_BROWSER_MIN_CODES = 2
CLIENT_FORGERY_VERSION = "client_forgery_v1"
JUMP_MIN_MOVES = 10
JUMP_STEP = 0.15
JUMP_MIN_SHARE = 0.40
JUMP_MIN_PAIRS = 5
JUMP_MIN_TURN_SHARE = 0.50
SERVER_MIN_CORES = 64
# Pointer Events shipped in Safari 13 and Chrome 55.
SAFARI_POINTER_EVENTS = 13
CHROME_POINTER_EVENTS = 55
_SAFARI = re.compile(r"Version/(\d+)[.\d]*(?: Mobile/\w+)? Safari/")
_CHROME = re.compile(r"(?:Chrome|CriOS)/(\d+)\.")
_OTHER_ENGINES = re.compile(r"Chrome/|CriOS/|FxiOS/|EdgiOS/|Edg/|OPR/|Firefox/")


def pointer_jump_profile(moves) -> dict:
    """Jump share and how often consecutive jumps turn back, over sanitized move records."""
    points = normalize_move_coordinates(moves) if len(moves) >= JUMP_MIN_MOVES else []
    steps = [(b[0] - a[0], b[1] - a[1]) for a, b in zip(points, points[1:])]
    jumps = [math.hypot(dx, dy) > JUMP_STEP for dx, dy in steps]
    pairs = turns = 0
    for i in range(1, len(steps)):
        if jumps[i] and jumps[i - 1]:
            pairs += 1
            (ax, ay), (bx, by) = steps[i - 1], steps[i]
            turns += ax * bx + ay * by < 0
    share = sum(jumps) / len(steps) if steps else 0.0
    turn_share = turns / pairs if pairs else 0.0
    return {
        "steps": len(steps),
        "jump_share": round(share, 3),
        "jump_pairs": pairs,
        "turn_share": round(turn_share, 3),
        "random_jumps": bool(
            steps and share >= JUMP_MIN_SHARE and pairs >= JUMP_MIN_PAIRS and turn_share >= JUMP_MIN_TURN_SHARE
        ),
    }


def _pointer_moves(payload) -> int:
    mouse = payload.get("mouse") if isinstance(payload.get("mouse"), dict) else {}
    stats = mouse.get("pointerStats") if isinstance(mouse.get("pointerStats"), dict) else {}
    value = stats.get("pointermove")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return 0
    return int(value)


def _claims_no_pointer_events(user_agent: str) -> bool:
    safari = _SAFARI.search(user_agent)
    if safari and not _OTHER_ENGINES.search(user_agent):
        return int(safari.group(1)) < SAFARI_POINTER_EVENTS
    chrome = _CHROME.search(user_agent)
    return bool(chrome) and int(chrome.group(1)) < CHROME_POINTER_EVENTS


def forgery_codes(payload: dict, automation_evidence: dict, *, desktop: bool) -> list:
    """Contradictions a genuine browser does not produce; each only withholds a HUMAN verdict."""
    payload = payload if isinstance(payload, dict) else {}
    fingerprint = payload.get("fingerprint") if isinstance(payload.get("fingerprint"), dict) else {}
    families = (automation_evidence or {}).get("families") or {}
    codes = []
    if _pointer_moves(payload) > 0 and _claims_no_pointer_events(str(fingerprint.get("userAgent") or "")):
        codes.append("UA_POINTER_MISMATCH")
    if any(hit in ("signals.webdriverPatched", "signals.webdriverDeleted") for hit in families.get("NATIVE_PATCH", [])):
        codes.append("WEBDRIVER_TAMPERED")
    cores = fingerprint.get("hardwareConcurrency")
    if (desktop and not isinstance(cores, bool) and isinstance(cores, (int, float))
            and math.isfinite(cores) and cores > SERVER_MIN_CORES):
        codes.append("SERVER_CPU")
    return codes


def synthetic_path_fires(jump_profile: dict, forgery: list, automation_evidence: dict) -> bool:
    """Random jumps and, independently, a browser that contradicts itself."""
    families = (automation_evidence or {}).get("families") or {}
    return bool(jump_profile.get("random_jumps")) and bool(
        forgery or any(family != "NETWORK" for family in families)
    )


def environment_anchor(automation_evidence: dict) -> bool:
    """A headless, GPU or permission contradiction (policy 28)."""
    families = (automation_evidence or {}).get("families") or {}
    return any(family in families for family in TAMPERING_ANCHOR_FAMILIES)


def contradictions(forgery: list, automation_evidence: dict = None, touch_flags=None) -> list:
    """Independent contradictions of the browser: the forgery codes, an environment anchor and
    (policy 29) taps released the moment they landed."""
    found = sorted(set(forgery or []))
    found += ["ENVIRONMENT_EVIDENCE"] if environment_anchor(automation_evidence) else []
    return found + (["ZERO_TIME_TAPS"] if "ZERO_TIME_TAPS" in (touch_flags or []) else [])


def forged_browser_fires(forgery: list, automation_evidence: dict = None, touch_flags=None) -> bool:
    """Policy 27: two independent claims no genuine browser makes (policy 28: or one and an
    environment anchor; policy 29: or one and taps of 0 ms)."""
    return len(contradictions(forgery, automation_evidence, touch_flags)) >= FORGED_BROWSER_MIN_CODES


def _fingerprint(payload) -> dict:
    payload = payload if isinstance(payload, dict) else {}
    return payload.get("fingerprint") if isinstance(payload.get("fingerprint"), dict) else {}


def webview_webdriver_fires(payload: dict, forgery: list) -> bool:
    """Policy 30: an Android WebView that hid ``navigator.webdriver`` (no extension runs there)."""
    fingerprint = _fingerprint(payload)
    user_agent = str(fingerprint.get("userAgent") or "")
    return bool("WEBDRIVER_TAMPERED" in (forgery or []) and "Android" in user_agent and "; wv)" in user_agent
                and not _DESKTOP_GPU.search(str(fingerprint.get("webglRenderer") or "")))


def apple_touch_device(fingerprint: dict) -> bool:
    """The user agent of an iPhone or iPad, or iPadOS Safari asking for desktop sites."""
    user_agent = str(fingerprint.get("userAgent") or "")
    if re.search(r"\((iPhone|iPod|iPad);", user_agent):
        return True
    touch = fingerprint.get("maxTouchPoints")
    return bool("Macintosh" in user_agent and not _OTHER_ENGINES.search(user_agent)
                and str(fingerprint.get("platform") or "") == "MacIntel"
                and isinstance(touch, (int, float)) and not isinstance(touch, bool) and touch > 1)


def apple_synthetic_touch_fires(payload: dict, touch_report: dict) -> bool:
    """Policy 30: an iPhone or iPad on WebKit 18+ whose touches carry CDP's contact defaults."""
    fingerprint = _fingerprint(payload)
    versions = [int(v) for v in re.findall(r"(?:OS |Version/)(\d+)", str(fingerprint.get("userAgent") or ""))]
    return bool(apple_touch_device(fingerprint) and versions and max(versions) >= APPLE_CONTACT_MIN_VERSION
                and int((touch_report or {}).get("gestures") or 0) >= APPLE_TOUCH_MIN_GESTURES
                and "SYNTHETIC_CONTACT" in ((touch_report or {}).get("research_flags") or []))
