"""Policy 24: facts the API observed about a request, outside anything the page can change.

The API fills ``_server_headers`` before scoring (see ``api_service.gateway``):

* ``page_view``: whether the telemetry came with the cookie of a page the shop gateway
  served. ``missing``/``unknown`` mean a script posted it without loading the page (or with
  a made-up cookie); ``mismatched`` that another User-Agent loaded the page; ``reused``
  that one page's cookie was presented by many sessions.
  ``untracked`` (no gateway in front of the site) and ``unavailable`` are not judged.
* ``device_sessions``: sessions in the last hour from the same device fingerprint on the
  same address. A person opens a few tabs; a farm that clears storage between runs starts
  a new session every minute on one machine.

Each code only withholds a HUMAN verdict, like the other desktop and phone risk codes.
"""

DEVICE_VELOCITY_LIMIT = 30
_UNVERIFIED = ("missing", "unknown", "mismatched", "reused")


def _headers(payload):
    headers = payload.get("_server_headers") if isinstance(payload, dict) else None
    return headers if isinstance(headers, dict) else {}


def server_context_codes(payload) -> list:
    headers = _headers(payload)
    codes = []
    if headers.get("page_view") in _UNVERIFIED:
        codes.append("UNVERIFIED_PAGE_LOAD")
    sessions = headers.get("device_sessions")
    if isinstance(sessions, int) and not isinstance(sessions, bool) and sessions >= DEVICE_VELOCITY_LIMIT:
        codes.append("DEVICE_VELOCITY")
    return codes
