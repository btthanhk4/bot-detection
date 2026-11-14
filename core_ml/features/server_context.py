"""Policy 24: facts the API observed about a request, outside anything the page can change.

The API fills ``_server_headers`` before scoring (see ``api_service.gateway``):

* ``page_view``: whether the telemetry came with the cookie of a page the shop gateway
  served. ``missing``/``unknown`` mean a script posted it without loading the page (or with
  a made-up cookie); ``mismatched`` that another User-Agent loaded the page; ``reused``
  that one page's cookie was presented by many sessions.
  ``untracked`` (no gateway in front of the site), ``gateway_idle`` (the gateway has not
  mirrored a page in ten minutes, so a missing cookie proves nothing) and ``unavailable``
  are not judged.
* ``device_sessions``: browsers that started sessions in the last hour from the same device
  fingerprint on the same address (policy 25: tabs sharing a storage token count once). A
  person opens many tabs in one browser; a farm that clears storage between runs starts a
  new browser every minute on one machine.

* ``ip_country`` (policy 33): the country of the address (GeoIP). A browser whose time zone
  is at least an hour away from every time zone of that country is reached through a proxy
  or VPN in another country: on production (12-13 Nov 2026) Fingerprint flagged 58% of the
  undecided phones and all undecided desktops showing it as tampered, anti-detect or
  suspect; 13 of 1,557 HUMAN phones showed it, 9 of the 11 checked behind a VPN.
  Neighbouring countries in one time zone, and time zones the tz database does not
  place in a country, are not judged.

* ``sensor_signature_models`` (policy 35): how many different claimed phone models showed, in the
  last 24 hours, the same calibration fingerprint as this phone lying still (gravity within
  0.01 m/s^2, tilt within 0.1 degree; see ``core_ml.features.presence``). Calibration offsets
  are unique to a physical device (SensorID, IEEE S&P 2019), so three or more models are one
  device or one emulator template behind spoofed identities. On production (13-14 Nov 2026,
  replayed in arrival order) 42 phones matched, all of one fleet that never touched the page
  and stayed about ten seconds (deviceMemory 4 behind Pixel 9 Pro and Galaxy S23 names);
  among the other phones lying still, no two models ever coincided.

* ``audio_hash_sessions`` (policy 36): how many other sessions of the last 24 hours reported this
  Android Chrome page's audio fingerprint. Real phones share it by the thousand (one value covered
  1,157 of 1,907 phones on 13-14 Nov 2026); anti-detect browsers add noise so that every profile
  gets its own. A value nobody else reported (``AUDIO_NOVEL``): Fingerprint flagged 29 of 34. Desktops
  are not judged: cloned server farms share one value, and there the new values were people. iOS
  Safari 26, Firefox, Samsung Internet and in-app browsers randomise or differ by design and are
  not judged either (the API leaves the count empty).

Each code only withholds a HUMAN verdict, like the other desktop and phone risk codes.
"""

from datetime import datetime, timezone

import pytz

DEVICE_VELOCITY_LIMIT = 30
SHARED_SIGNATURE_MODELS = 3
TIMEZONE_MISMATCH_MINUTES = 60
# Names browsers (ICU) still report for zones the tz database renamed.
_TZ_ALIASES = {
    "Asia/Calcutta": "Asia/Kolkata", "Asia/Saigon": "Asia/Ho_Chi_Minh", "Asia/Katmandu": "Asia/Kathmandu",
    "Asia/Rangoon": "Asia/Yangon", "Asia/Dacca": "Asia/Dhaka", "Asia/Thimbu": "Asia/Thimphu",
    "Europe/Kiev": "Europe/Kyiv", "Atlantic/Faeroe": "Atlantic/Faroe", "Asia/Ulan_Bator": "Asia/Ulaanbaatar",
    "America/Buenos_Aires": "America/Argentina/Buenos_Aires", "America/Indianapolis": "America/Indiana/Indianapolis",
    "America/Louisville": "America/Kentucky/Louisville", "Pacific/Truk": "Pacific/Chuuk",
    "Pacific/Ponape": "Pacific/Pohnpei", "Asia/Chongqing": "Asia/Shanghai", "Asia/Harbin": "Asia/Shanghai",
}
_ZONE_COUNTRY = {zone: code for code, zones in pytz.country_timezones.items() for zone in zones}
_UNVERIFIED = ("missing", "unknown", "mismatched", "reused")


def _headers(payload):
    headers = payload.get("_server_headers") if isinstance(payload, dict) else None
    return headers if isinstance(headers, dict) else {}


def _offset_minutes(zone_name, at):
    try:
        offset = pytz.timezone(zone_name).utcoffset(at.replace(tzinfo=None))
    except (pytz.UnknownTimeZoneError, pytz.AmbiguousTimeError, pytz.NonExistentTimeError, ValueError):
        return None
    return offset.total_seconds() / 60 if offset is not None else None


def timezone_mismatch(payload, at=None):
    """True: the browser's time zone is an hour or more from every zone of the IP's country.
    None when either side is unknown or the zone is not placed in a country."""
    headers = _headers(payload)
    country = headers.get("ip_country")
    fingerprint = payload.get("fingerprint") if isinstance(payload, dict) else None
    zone = fingerprint.get("timezone") if isinstance(fingerprint, dict) else None
    if not isinstance(country, str) or len(country) != 2 or not isinstance(zone, str) or not zone:
        return None
    zone = _TZ_ALIASES.get(zone, zone)
    country = country.upper()
    zones = pytz.country_timezones.get(country)
    if not zones or zone not in _ZONE_COUNTRY:
        return None
    if zone in zones:
        return False
    at = at or datetime.now(timezone.utc)
    browser = _offset_minutes(zone, at)
    offsets = [o for o in (_offset_minutes(z, at) for z in zones) if o is not None]
    if browser is None or not offsets:
        return None
    return min(abs(browser - o) for o in offsets) >= TIMEZONE_MISMATCH_MINUTES


def server_context_codes(payload) -> list:
    headers = _headers(payload)
    codes = []
    if headers.get("page_view") in _UNVERIFIED:
        codes.append("UNVERIFIED_PAGE_LOAD")
    sessions = headers.get("device_sessions")
    if isinstance(sessions, int) and not isinstance(sessions, bool) and sessions >= DEVICE_VELOCITY_LIMIT:
        codes.append("DEVICE_VELOCITY")
    if timezone_mismatch(payload):
        codes.append("TIMEZONE_MISMATCH")
    models = headers.get("sensor_signature_models")
    if isinstance(models, int) and not isinstance(models, bool) and models >= SHARED_SIGNATURE_MODELS:
        codes.append("SHARED_SENSOR_SIGNATURE")
    audio = headers.get("audio_hash_sessions")
    if isinstance(audio, int) and not isinstance(audio, bool) and audio == 0:
        codes.append("AUDIO_NOVEL")
    return codes
