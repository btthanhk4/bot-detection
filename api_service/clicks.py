"""Ad-click attribution: the click id and traffic source an ad network appends to its landing page.

Asked for by the network running the "Downloader" lander (2026-11-10): every page view carries
the id of the click that brought the visitor and the source (zone) the click came from, e.g.
``index.html?clickid=dbpj8r797ugs73fe0jng&t1=28628-5fe41363``. The network needs to know, click
by click, whether a person or a bot came, and which sources send the bots.

The collector already sends the full page URL. The server keeps the two values of the first page
of a session as ``click_id`` and ``click_source``; parameter names come from
``BOT_CLICK_ID_PARAMS`` and ``BOT_CLICK_SOURCE_PARAMS`` (comma-separated, case-insensitive). A
value the network failed to fill in (``{clickid}``) or with characters outside a token is dropped.
"""

import logging
import os
import re
import threading
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

logger = logging.getLogger("bot_detection.clicks")


def _names(variable, default):
    return tuple(name.strip().lower() for name in os.getenv(variable, default).split(",") if name.strip())


CLICK_ID_PARAMS = _names("BOT_CLICK_ID_PARAMS", "clickid")
CLICK_SOURCE_PARAMS = _names("BOT_CLICK_SOURCE_PARAMS", "t1")
CLICK_VALUE_PATTERN = r"^[A-Za-z0-9._~:@+-]{1,128}$"
_VALUE = re.compile(CLICK_VALUE_PATTERN)
BACKFILL_MARKER = "click_attribution_backfill_v1"


def click_params(url) -> dict:
    """``{"click_id": ..., "click_source": ...}`` with the values the URL carries (possibly none)."""
    if not isinstance(url, str) or "?" not in url:
        return {}
    try:
        query = parse_qs(urlsplit(url[:2048]).query)
    except ValueError:
        return {}
    values = {name.lower(): found for name, found in query.items()}
    out = {}
    for field, names in (("click_id", CLICK_ID_PARAMS), ("click_source", CLICK_SOURCE_PARAMS)):
        for name in names:
            value = (values.get(name) or [""])[0].strip()
            if _VALUE.match(value):
                out[field] = value
                break
    return out


def record(collection, session_id, url) -> None:
    """Attribute a session to the click on its page URL, once: a later page never replaces it."""
    click = click_params(url)
    if click:
        collection.update_one({"sessionId": session_id, "click_id": None, "click_source": None}, {"$set": click})


def backfill(db) -> int:
    """Attribute the sessions stored before attribution existed, from their landing URL (once)."""
    control = db["service_control"]
    if control.find_one({"_id": BACKFILL_MARKER}):
        return 0
    names = "|".join(re.escape(name) for name in CLICK_ID_PARAMS + CLICK_SOURCE_PARAMS)
    attributed = 0
    cursor = db["detection_results"].find(
        {"click_id": {"$exists": False}, "click_source": {"$exists": False},
         "landing_url": {"$regex": f"[?&]({names})=", "$options": "i"}},
        {"sessionId": 1, "landing_url": 1},
    ).batch_size(200)
    for doc in cursor:
        click = click_params(doc.get("landing_url"))
        if click:
            db["detection_results"].update_one({"_id": doc["_id"]}, {"$set": click})
            attributed += 1
    control.update_one({"_id": BACKFILL_MARKER},
                       {"$set": {"done_at": datetime.now(timezone.utc), "sessions": attributed}}, upsert=True)
    return attributed


def backfill_in_background(db) -> None:
    def run():
        try:
            count = backfill(db)
            if count:
                logger.info("[DB] Click attribution backfilled on %d sessions", count)
        except Exception as exc:  # the next start retries
            logger.warning("[DB] Click attribution backfill failed: %s", exc)

    threading.Thread(target=run, name="click-backfill", daemon=True).start()
