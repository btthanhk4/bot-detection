"""Opt-in offline policy for corroborated self-identifying automation."""


PROFILE_CANDIDATE_RULE = "profile_corroborated_v1"


def corroborated_profile_evidence(payload, report):
    """Return observed evidence, never infer BOT from missing APIs or OS mismatch.

    Page and worker observations are separate contexts, not statistically
    independent or trustworthy identities. This policy is experimental.
    """
    signals = {signal["code"] for signal in report["signals"]}
    headless = signals & {
        "PAGE_HEADLESS_UA", "PAGE_HEADLESS_CLIENT_HINTS",
        "WORKER_HEADLESS_UA", "WORKER_HEADLESS_CLIENT_HINTS",
    }
    if not headless:
        return []
    contexts = {code.split("_", 1)[0] for code in headless}
    botd = payload.get("botd")
    botd = botd if isinstance(botd, dict) else {}
    detectors = botd.get("detectors")
    detectors = detectors if isinstance(detectors, dict) else {}
    profile = botd.get("profile")
    profile = profile if isinstance(profile, dict) else {}
    main = profile.get("main") if profile.get("schema") == "browser-profile-v1" else None
    main = main if isinstance(main, dict) else {}
    markers = set()
    if main.get("webdriver") is True:
        markers.add("PAGE_WEBDRIVER")
    if "WORKER_WEBDRIVER" in signals:
        markers.add("WORKER_WEBDRIVER")
    if any(detectors.get(name) is True for name in
           ("webdriver", "distinctiveProperties", "chromeDriverGlobal")):
        markers.add("COLLECTOR_AUTOMATION_MARKER")
    if len(contexts) >= 2 or markers:
        return sorted(headless | markers)
    return []
