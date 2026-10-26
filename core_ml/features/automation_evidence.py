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
"""

import re

AUTOMATION_MARKER_RULE = "automation_marker_v1"
ENVIRONMENT_TAMPERING_RULE = "environment_tampering_v1"
AUTOMATION_EVIDENCE_VERSION = "automation_evidence_v1"
TAMPERING_MIN_FAMILIES = 3
TAMPERING_ANCHOR_FAMILIES = ("HEADLESS_ENV", "GPU", "PERMISSION")

_MARKER_SIGNALS = {
    "detectors": ("webdriver", "chromeDriverGlobal", "distinctiveProperties", "documentKeys"),
    "signals": ("playwrightGlobals", "seleniumGlobals"),
    "worker": ("webdriver",),
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
    "NATIVE_PATCH": {"signals": ("webdriverDeleted", "webdriverPatched", "navigatorGetterPatched", "toStringPatched")},
    "CLIENT_HINTS": {"signals": ("uaHintsMismatch", "malformedBrands"), "server": ("http_ua_mismatch",)},
    "HTTP": {"server": ("missing_accept_language", "missing_fetch_metadata")},
    # Corroboration only: VPN exits share these ranges, so NETWORK is never an anchor.
    "NETWORK": {"server": ("datacenter_ip",)},
}
_SOFTWARE_RENDERER = re.compile(r"swiftshader|llvmpipe|softpipe|mesa offscreen|microsoft basic render", re.I)


def _mapping(value):
    return value if isinstance(value, dict) else {}


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
        "software_renderer": bool(_SOFTWARE_RENDERER.search(renderer)),
        "datacenter_ip": bool(headers.get("datacenter")),
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


def analyze_automation_evidence(payload: dict) -> dict:
    payload = payload if isinstance(payload, dict) else {}
    sources, has_probes = _sources(payload)
    markers = _hits(sources, _MARKER_SIGNALS)
    families = {}
    for family, spec in _FAMILIES.items():
        hits = _hits(sources, spec)
        if hits:
            families[family] = hits
    tampering = (
        len(families) >= TAMPERING_MIN_FAMILIES
        and any(anchor in families for anchor in TAMPERING_ANCHOR_FAMILIES)
    )
    rule = AUTOMATION_MARKER_RULE if markers else ENVIRONMENT_TAMPERING_RULE if tampering else None
    return {
        "analysis_version": AUTOMATION_EVIDENCE_VERSION,
        "probes_present": has_probes,
        "markers": markers,
        "families": families,
        "family_count": len(families),
        "rule": rule,
    }
