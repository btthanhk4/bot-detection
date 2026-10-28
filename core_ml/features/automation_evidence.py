"""Group client automation probes into independent evidence families.

The collector (1.3.0+) sends ``botd.automation``; legacy ``botd.detectors`` and
the request headers seen by the API are folded in. Two decision rules sit on
top (policy 12):

* ``automation_marker_v1``: a framework artefact that a normal browser never
  has: ``navigator.webdriver`` true (page or worker), ChromeDriver ``cdc_``
  globals, Selenium/PhantomJS globals, Playwright exposed bindings, automation
  attributes on ``<html>``.
* ``environment_tampering_v1``: contradictions in at least three independent
  families, one of which must be headless, GPU or permission evidence. A user
  agent switcher extension typically touches client hints, worker context and
  native patching only, so it is held at SUSPECT-level evidence, not convicted.

Families were chosen from a probe matrix (2026-10-26): genuine Chrome and Edge
raised no signal; Puppeteer+stealth raised four families; headed patchright
raised none (it is a genuine browser, caught only by behaviour).

Policy 16: on a cloud address, a CPU rasteriser and a zero network RTT are what
any virtual machine shows, people on cloud desktops included, so they are folded
into the NETWORK family instead of counting as independent contradictions. An
unattended cloud browser is caught by ``idle_cloud_browser_v1`` instead: cloud
address, CPU rasteriser and no input at all for 10 s of page time. That verdict
is not locked; later human input may overturn it.
"""

import re

from core_ml.features.touch import sanitize_gestures

AUTOMATION_MARKER_RULE = "automation_marker_v1"
ENVIRONMENT_TAMPERING_RULE = "environment_tampering_v1"
IDLE_CLOUD_BROWSER_RULE = "idle_cloud_browser_v1"
MOBILE_EMULATION_RULE = "mobile_emulation_v1"
# Self-declared automation (policy 17): Web Bot Auth signatures (IETF draft,
# sent by ChatGPT Agent and verified by Cloudflare/AWS) and published crawler
# user agents. People never send either; the bot may be welcome, but it is a bot.
_DECLARED_BOT_UA = re.compile(
    r"\b(googlebot|google-inspectiontool|googleother|google-extended|storebot-google|adsbot-google|"
    r"mediapartners-google|google-read-aloud|feedfetcher-google|bingbot|"
    r"gptbot|chatgpt-user|oai-searchbot|claudebot|claude-user|claude-searchbot|anthropic-ai|"
    r"perplexitybot|perplexity-user|bytespider|amazonbot|applebot|ccbot|meta-externalagent|"
    r"facebookexternalhit|duckduckbot|yandexbot|baiduspider|petalbot|semrushbot|ahrefsbot|"
    r"mj12bot|dotbot|chrome-lighthouse)\b",
    re.I,
)
# Policy 25: operators that publish their crawlers' addresses (core_ml/refresh_crawler_ranges).
# A crawler from its operator's ranges is the real one, which a site should not block; the
# same name from anywhere else was copied. Either way it is a bot.
_CRAWLER_OPERATORS = {
    "google": ("googlebot", "google-inspectiontool", "googleother", "google-extended", "storebot-google",
               "adsbot-google", "mediapartners-google", "google-read-aloud", "feedfetcher-google", "chrome-lighthouse"),
    "bing": ("bingbot",),
    "apple": ("applebot",),
    "openai": ("gptbot", "chatgpt-user", "oai-searchbot"),
    "perplexity": ("perplexitybot", "perplexity-user"),
}
_CRAWLER_NAMES = {
    "googlebot": "Googlebot", "google-inspectiontool": "Google-InspectionTool", "googleother": "GoogleOther",
    "google-extended": "Google-Extended", "storebot-google": "Storebot-Google", "adsbot-google": "AdsBot-Google",
    "mediapartners-google": "Mediapartners-Google", "google-read-aloud": "Google-Read-Aloud",
    "feedfetcher-google": "FeedFetcher-Google", "chrome-lighthouse": "Chrome-Lighthouse", "bingbot": "Bingbot",
    "applebot": "Applebot", "gptbot": "GPTBot", "chatgpt-user": "ChatGPT-User", "oai-searchbot": "OAI-SearchBot",
    "perplexitybot": "PerplexityBot", "perplexity-user": "Perplexity-User", "claudebot": "ClaudeBot",
    "bytespider": "Bytespider", "facebookexternalhit": "facebookexternalhit", "meta-externalagent": "Meta-ExternalAgent",
}
IDLE_CLOUD_MIN_PAGE_MS = 10_000
# Evidence that a cloud virtual machine explains on its own.
_CLOUD_EXPLAINED = {"GPU": "server.software_renderer", "HEADLESS_ENV": "signals.rttZero"}
AUTOMATION_EVIDENCE_VERSION = "automation_evidence_v1"
TAMPERING_MIN_FAMILIES = 3
TAMPERING_ANCHOR_FAMILIES = ("HEADLESS_ENV", "GPU", "PERMISSION")

_MARKER_SIGNALS = {
    "detectors": ("webdriver", "chromeDriverGlobal", "distinctiveProperties", "documentKeys"),
    "signals": ("playwrightGlobals", "seleniumGlobals"),
    "worker": ("webdriver",),
    "server": ("signature_agent", "declared_bot_ua", "declared_headless_ua"),
}
_FAMILIES = {
    "HEADLESS_ENV": {
        "detectors": ("headlessUa",),
        "signals": ("headlessScreen", "appVersionAutomation", "rttZero",
                    "pluginsPrototypeMismatch", "mimeTypesPrototypeMismatch", "sequentum"),
        "server": ("headless_client_hints_header",),
    },
    "GPU": {"signals": ("gpuOsMismatch",), "worker": ("rendererMismatch",),
            "server": ("legacy_angle_renderer", "software_renderer")},
    "PERMISSION": {"top": ("notificationPermissionMismatch",)},
    "CONTEXT": {"worker": ("cpuMismatch", "uaMismatch", "platformMismatch")},
    # Policy 25: toStringPatched left this family. Sentry and zone.js patch toString on
    # ordinary sites; collector 1.11 checks sources against a fresh realm's toString.
    "NATIVE_PATCH": {"signals": ("webdriverDeleted", "webdriverPatched", "navigatorGetterPatched", "inputApiPatched")},
    "CLIENT_HINTS": {"signals": ("uaHintsMismatch", "malformedBrands"), "server": ("http_ua_mismatch",)},
    "HTTP": {"server": ("missing_accept_language", "missing_fetch_metadata")},
    # Policy 24: a CDP client has Runtime enabled (Puppeteer, Playwright, Selenium; patchright
    # avoids it). On HTTPS Puppeteer-stealth loses its permission contradiction and kept only
    # GPU and CONTEXT, two families; this is its third. DevTools open in a person's browser
    # trips it too, alone, which only withholds a HUMAN verdict (desktop_risk CDP_ATTACHED).
    "CDP": {"signals": ("cdpRuntime",)},
    # Corroboration only: VPN exits share these ranges, so NETWORK is never an anchor.
    "NETWORK": {"server": ("datacenter_ip",)},
}
# Desktop graphics that no phone has (policy 19: Android emulators such as
# LDPlayer/BlueStacks expose the host GPU; Playwright/Puppeteer on Windows show
# Direct3D). Samsung's AMD-based phone GPU reports "Xclipse", not Radeon.
_DESKTOP_GPU = re.compile(r"Direct3D|D3D11|D3D9|GeForce|Quadro|Radeon|Intel\(R\)|Intel HD|UHD Graphics|Iris|PCIe|SSE2", re.I)
# Phones and tablets have at most 10 cores; a server or desktop shows through.
MOBILE_MAX_CORES = 16
_SOFTWARE_RENDERER = re.compile(r"swiftshader|llvmpipe|softpipe|mesa offscreen", re.I)
# Windows' own CPU renderer (WARP). Chrome uses it with hardware acceleration switched off
# and on machines without a working GPU driver, so on a Windows user agent it is ordinary
# (policy 25, measured 2026-10-29). Under another OS, or on a cloud address, it still counts.
_WARP_RENDERER = re.compile(r"microsoft basic render", re.I)


def _mapping(value):
    return value if isinstance(value, dict) else {}


def declared_crawler(user_agents, operator=None):
    """{name, operator, verified} for a crawler named in a User-Agent, else None.

    ``operator`` is whose published crawler ranges hold the client address. ``verified`` is
    None when the crawler's operator publishes no ranges this service tracks.
    """
    for ua in user_agents:
        match = _DECLARED_BOT_UA.search(str(ua or ""))
        if match:
            token = match.group(1).lower()
            owner = next((name for name, tokens in _CRAWLER_OPERATORS.items() if token in tokens), None)
            return {"name": _CRAWLER_NAMES.get(token, match.group(1)), "operator": owner,
                    "verified": (operator == owner) if owner else None}
    return None


def _sources(payload):
    botd = _mapping(payload.get("botd"))
    automation = _mapping(botd.get("automation"))
    if automation.get("schema") != "automation-v1":
        automation = {}
    fingerprint = _mapping(payload.get("fingerprint"))
    headers = _mapping(payload.get("_server_headers"))
    browser_ua = str(fingerprint.get("userAgent") or "")
    http_ua = str(payload.get("_server_user_agent") or "")
    chromium = "Chrome/" in browser_ua or "Chrome/" in http_ua
    # Firefox on plain HTTP legitimately reports Notification.permission "denied"
    # while the Permissions API says "prompt" (2 of 2 real Firefox sessions,
    # 2026-10-26); only a browser that claims Chromium is held to the check.
    claims_chromium = "Chrome/" in browser_ua and "Firefox/" not in browser_ua
    major = re.search(r"Chrome/(\d+)", browser_ua)
    renderer = str(fingerprint.get("webglRenderer") or "")
    server = {
        # Only meaningful when the browser reported a UA and the header was observed.
        "http_ua_mismatch": bool(browser_ua and http_ua and browser_ua != "mobile"
                                 and browser_ua[:512] != http_ua[:512]),
        "missing_accept_language": bool(chromium and headers.get("observed") is True
                                        and headers.get("accept_language") is False),
        # Over HTTPS, Chromium attaches Sec-Fetch-* to every fetch/beacon; their
        # absence means the request did not come from a browser page.
        "missing_fetch_metadata": bool(chromium and headers.get("observed") is True
                                       and headers.get("forwarded_proto") == "https"
                                       and not headers.get("sec_fetch_site")),
        "headless_client_hints_header": "headlesschrome" in str(headers.get("sec_ch_ua") or "").lower(),
        # Chromium >= 94 reports "ANGLE (Vendor, Device, Backend)". The comma-less
        # pre-2021 form is what spoofing kits paste in (seen on a Linux host
        # claiming Windows Chrome 155; 9 of 9 real Windows sessions use the new form).
        "legacy_angle_renderer": bool(major and int(major.group(1)) >= 100
                                      and renderer.startswith("ANGLE (") and ", " not in renderer),
        # CPU rasterisers used when no GPU exists (cloud VMs, containers). Hypervisor
        # adapters (VirtualBox, VMware) are excluded: people do browse from VMs.
        "software_renderer": bool(_SOFTWARE_RENDERER.search(renderer)) or bool(
            _WARP_RENDERER.search(renderer) and (headers.get("datacenter") or "Windows NT" not in browser_ua)),
        "datacenter_ip": bool(headers.get("datacenter")),
        "signature_agent": headers.get("signature_agent") is True,
        "declared_bot_ua": bool(_DECLARED_BOT_UA.search(http_ua) or _DECLARED_BOT_UA.search(browser_ua)),
        # Policy 20: only headless Chrome puts "HeadlessChrome/" in its UA, and nobody shops
        # with it. Both the request and the page must say so (a forged header alone is not
        # enough); the v10 rule also wanted a framework artefact, which stealth patches hide.
        "declared_headless_ua": "HeadlessChrome/" in http_ua and "HeadlessChrome/" in browser_ua,
    }
    permission = automation.get("notificationPermissionMismatch") if claims_chromium else None
    return {
        "detectors": _mapping(botd.get("detectors")),
        "signals": _mapping(automation.get("signals")),
        "worker": _mapping(automation.get("worker")),
        "top": {"notificationPermissionMismatch": permission},
        "server": server,
    }, bool(automation)


def _hits(sources, spec):
    found = []
    for source, names in spec.items():
        values = sources.get(source, {})
        for name in names:
            if values.get(name) is True:
                found.append(f"{source}.{name}")
    return found


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _mobile_emulation(fingerprint, worker=None, touch_data=None):
    """Contradictions of a desktop browser dressed up as a phone (policy 17).

    Measured 2026-10-26: Playwright (iPhone 13, Pixel 7, Galaxy S9+) and Puppeteer
    (iPhone 13) device emulation keep navigator.platform "Win32", a Direct3D
    (Windows-only) WebGL renderer and, on iOS profiles, navigator.deviceMemory,
    which WebKit (every iOS browser) does not implement. Real iPhones report
    platform "iPhone" and "Apple GPU"; Android phones "Linux arm*/aarch64".

    Policy 19 (measured 2026-10-27 with stealth scripts that patch
    navigator.platform, webdriver and maxTouchPoints): a dedicated worker keeps
    the real platform ("spoofed_platform"); desktop GPU vendors on Android; more
    cores than any phone has; and on iOS 18+ touches without a contact radius
    (Playwright WebKit reports none; real iPhones on the live site report
    24.3/36.4/48.6 px).
    """
    ua = str(fingerprint.get("userAgent") or "")
    platform = str(fingerprint.get("platform") or "")
    renderer = str(fingerprint.get("webglRenderer") or "")
    ios = bool(re.search(r"\((iPhone|iPod|iPad);", ua))
    android = "Android" in ua and not ios
    if not (ios or android) or not platform:
        return []
    found = []
    if (ios and platform not in ("iPhone", "iPod", "iPad")) or (
            android and platform in ("Win32", "Win64", "MacIntel", "Macintosh")):
        found.append("platform_mismatch")
    # JS spoofing patches the page's navigator, not a dedicated worker's.
    if _mapping(worker).get("platformMismatch") is True:
        found.append("spoofed_platform")
    if _DESKTOP_GPU.search(renderer) or (ios and renderer and "Apple" not in renderer):
        found.append("desktop_gpu")
    memory = fingerprint.get("deviceMemory")
    if ios and isinstance(memory, (int, float)) and not isinstance(memory, bool) and memory > 0:
        found.append("chromium_api_on_ios")
    touch_points = fingerprint.get("maxTouchPoints")
    if isinstance(touch_points, (int, float)) and not isinstance(touch_points, bool) and touch_points == 0:
        found.append("no_touch")
    cores = _number(fingerprint.get("hardwareConcurrency"))
    if cores is not None and cores > MOBILE_MAX_CORES:
        found.append("server_cpu")
    # WebKit reports a contact radius on current iOS (seen on iOS 18 and Safari 26,
    # whose UA freezes the OS at 18_6). Older versions are not judged.
    versions = [int(v) for v in re.findall(r"(?:OS |Version/)(\d+)", ua)]
    gestures = sanitize_gestures(touch_data)
    if (ios and versions and max(versions) >= 18 and len(gestures) >= 3
            and all(p[3] is None and p[4] is None for g in gestures for p in g["points"])):
        found.append("ios_touch_without_contact")
    return found


def mobile_emulation_fires(found) -> bool:
    """A platform contradiction plus at least one hardware contradiction."""
    platform = {"platform_mismatch", "spoofed_platform"}
    return bool(platform & set(found)) and bool(set(found) - platform)


def _idle_page_ms(payload):
    """Page time without any pointer, wheel or key input; None if not measurable."""
    mouse = _mapping(payload.get("mouse"))
    age = _number(mouse.get("pageAgeMs"))
    counters = _mapping(mouse.get("counters"))
    if age is None or not counters:
        return None
    keyboard = _mapping(mouse.get("keyboard"))
    activity = sum(_number(counters.get(name)) or 0 for name in ("mousemove", "mousedown", "click", "wheel"))
    activity += len(keyboard.get("keystrokes") or []) + len(mouse.get("records") or [])
    return age if activity == 0 else 0.0


def analyze_automation_evidence(payload: dict) -> dict:
    payload = payload if isinstance(payload, dict) else {}
    sources, has_probes = _sources(payload)
    markers = _hits(sources, _MARKER_SIGNALS)
    families = {}
    for family, spec in _FAMILIES.items():
        hits = _hits(sources, spec)
        if hits:
            families[family] = hits
    cloud = "NETWORK" in families
    if cloud:
        for family, hit in _CLOUD_EXPLAINED.items():
            if hit in families.get(family, []):
                families[family].remove(hit)
                families["NETWORK"].append(hit)
                if not families[family]:
                    del families[family]
    tampering = (
        len(families) >= TAMPERING_MIN_FAMILIES
        and any(anchor in families for anchor in TAMPERING_ANCHOR_FAMILIES)
    )
    idle_ms = _idle_page_ms(payload)
    # DevTools device mode sets the platform, so a platform contradiction is
    # required; automation emulation also leaves a GPU, API or touch one.
    emulation = _mobile_emulation(_mapping(payload.get("fingerprint")), sources.get("worker"),
                                  _mapping(payload.get("mouse")).get("touch"))
    mobile_emulation = mobile_emulation_fires(emulation)
    idle_cloud = (
        cloud and "server.software_renderer" in families["NETWORK"]
        and idle_ms is not None and idle_ms >= IDLE_CLOUD_MIN_PAGE_MS
    )
    rule = (
        AUTOMATION_MARKER_RULE if markers
        else ENVIRONMENT_TAMPERING_RULE if tampering
        else MOBILE_EMULATION_RULE if mobile_emulation
        else IDLE_CLOUD_BROWSER_RULE if idle_cloud
        else None
    )
    headers = _mapping(payload.get("_server_headers"))
    crawler = declared_crawler(
        (payload.get("_server_user_agent"), _mapping(payload.get("fingerprint")).get("userAgent")),
        headers.get("crawler_operator"),
    ) if "server.declared_bot_ua" in markers else None
    return {
        "analysis_version": AUTOMATION_EVIDENCE_VERSION,
        "probes_present": has_probes,
        "markers": markers,
        "crawler": crawler,
        "families": families,
        "family_count": len(families),
        "cloud_vm": cloud and len(families["NETWORK"]) > 1,
        "idle_page_ms": idle_ms,
        "mobile_emulation": emulation,
        "rule": rule,
    }
