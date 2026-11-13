"""Reference labels from Fingerprint Pro Plus bot detection, for measuring DATACAT on real traffic.

The collector loads the Fingerprint JS agent for a sampled share of sessions, calls
``get({linkedId: sessionId})`` and reports the returned ``event_id`` in ``collector.referenceEventId``.
The API stores it as ``reference.fingerprint`` (status ``pending``) and a background loop fetches
the event from the Fingerprint Server API with the secret key. A browser can send any event id, so
an event is accepted only when its ``linked_id`` is this session.

The result is an *observation of another detector*, never ground truth and never an input of
DATACAT's decision: ``bot == "bad"`` is a commercial bot verdict, ``not_detected`` does not prove a
human. ``report`` compares the two on the stored sessions (agreement and Cohen's kappa).
"""

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

import requests

from api_service.config import settings

logger = logging.getLogger(__name__)

EVENT_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
FIELD = "reference.fingerprint"
MAX_ATTEMPTS = 6
# The Server API allows 5 requests per second; the loop stays well below it.
REQUEST_INTERVAL_SECONDS = 0.3
BATCH = 40
# Fingerprint suspect score from which a session counts as flagged (with tampering or an anti-detect browser).
STRONG_SUSPECT_SCORE = 20


def enabled() -> bool:
    return bool(settings.FINGERPRINT_PUBLIC_KEY and settings.FINGERPRINT_SECRET_KEY
                and settings.FINGERPRINT_SAMPLE_RATE > 0)


def collector_config() -> tuple:
    """(public key, sample rate) written into the served collector; empty when disabled."""
    if not enabled():
        return "", 0.0
    return settings.FINGERPRINT_PUBLIC_KEY, settings.FINGERPRINT_SAMPLE_RATE


def ensure_indexes(db) -> None:
    collection = db["detection_results"]
    collection.create_index(
        [(FIELD + ".next_at", 1)], name="reference_fingerprint_pending",
        partialFilterExpression={FIELD + ".status": "pending"},
    )
    # Reports and the review list read only sessions that carry a reference.
    collection.create_index(
        [(FIELD + ".status", 1), ("created_at", -1)], name="reference_fingerprint_status",
        partialFilterExpression={FIELD + ".status": {"$exists": True}},
    )


def record_event(db, session_id: str, event_id: str, now: Optional[datetime] = None) -> bool:
    """Remember the first Fingerprint event a session reports; later ones are ignored."""
    if not session_id or not isinstance(event_id, str) or not EVENT_ID.match(event_id):
        return False
    now = now or datetime.now(timezone.utc)
    result = db["detection_results"].update_one(
        {"sessionId": session_id, FIELD: {"$exists": False}},
        {"$set": {FIELD: {"event_id": event_id, "status": "pending", "attempts": 0,
                          "received_at": now, "next_at": now + timedelta(seconds=10)}}},
    )
    return result.modified_count == 1


def fetch_event(event_id: str) -> tuple:
    """(HTTP status, JSON body or None) of GET /events/{event_id} on the Fingerprint Server API."""
    response = requests.get(
        f"{settings.FINGERPRINT_API_URL}/events/{event_id}",
        headers={"Authorization": f"Bearer {settings.FINGERPRINT_SECRET_KEY}"}, timeout=10,
    )
    try:
        body = response.json()
    except ValueError:
        body = None
    return response.status_code, body


def _bot_fields(body: dict) -> dict:
    """The bot verdict of a v4 event (v3 shape accepted as a fallback)."""
    bot = body.get("bot")
    if bot is None:
        bot = (((body.get("products") or {}).get("botd") or {}).get("data") or {}).get("bot", {}).get("result")
    if bot == "notDetected":
        bot = "not_detected"
    info = body.get("bot_info") if isinstance(body.get("bot_info"), dict) else {}
    linked = body.get("linked_id")
    if linked is None:
        linked = (((body.get("products") or {}).get("identification") or {}).get("data") or {}).get("linkedId")
    # The signals that separate bots from people on production (2026-11-13: 68% of DATACAT's
    # BOTs, 0.7% of its phone HUMANs) are tampering, an anti-detect browser and the suspect score;
    # the bot field alone barely fires. Kept so evaluation needs no second Server API read.
    details = body.get("tampering_details") if isinstance(body.get("tampering_details"), dict) else {}
    suspect = body.get("suspect_score")
    suspect = suspect if isinstance(suspect, (int, float)) and not isinstance(suspect, bool) else None
    ip_v4 = ((body.get("ip_info") or {}).get("v4") or {}) if isinstance(body.get("ip_info"), dict) else {}
    tampering = body.get("tampering") is True
    anti_detect = details.get("anti_detect_browser") is True
    return {
        "bot": bot if bot in ("bad", "good", "not_detected") else None,
        "bot_type": body.get("bot_type"),
        "bot_category": info.get("category"), "bot_name": info.get("name"),
        "bot_identity": info.get("identity"), "bot_confidence": info.get("confidence"),
        "tampering": tampering, "anti_detect": anti_detect, "suspect_score": suspect,
        "vpn": body.get("vpn") is True, "datacenter": ip_v4.get("datacenter_result") is True,
        "strong": tampering or anti_detect or (suspect is not None and suspect >= STRONG_SUSPECT_SCORE),
        "linked_id": linked,
    }


def poll_pending(db, fetch: Callable[[str], tuple] = fetch_event, now: Optional[datetime] = None,
                 limit: int = BATCH, pause: float = REQUEST_INTERVAL_SECONDS) -> dict:
    """Fetch due pending events; returns counts by outcome."""
    collection = db["detection_results"]
    now = now or datetime.now(timezone.utc)
    outcome = {"done": 0, "mismatch": 0, "retry": 0, "failed": 0}
    due = collection.find(
        {FIELD + ".status": "pending", FIELD + ".next_at": {"$lte": now}},
        {"sessionId": 1, FIELD: 1},
    ).sort(FIELD + ".next_at", 1).limit(limit)
    for doc in list(due):
        ref = ((doc.get("reference") or {}).get("fingerprint")) or {}
        attempts = int(ref.get("attempts") or 0) + 1
        try:
            status, body = fetch(ref["event_id"])
        except Exception:
            logger.warning("Fingerprint event fetch failed", exc_info=True)
            status, body = None, None
        update = {FIELD + ".attempts": attempts, FIELD + ".fetched_at": now}
        if status == 200 and isinstance(body, dict):
            fields = _bot_fields(body)
            if fields["linked_id"] != doc.get("sessionId"):
                # An event of another page or visitor: never accepted as this session's label.
                update[FIELD + ".status"] = "mismatch"
                outcome["mismatch"] += 1
            else:
                update[FIELD + ".status"] = "done"
                update.update({f"{FIELD}.{key}": value for key, value in fields.items() if key != "linked_id"})
                outcome["done"] += 1
        elif attempts >= MAX_ATTEMPTS:
            update[FIELD + ".status"] = "not_found" if status == 404 else "error"
            update[FIELD + ".http_status"] = status
            outcome["failed"] += 1
        else:
            # 404 right after the visit (event not stored yet), 429 or a network error: back off.
            update[FIELD + ".next_at"] = now + timedelta(seconds=30 * 2 ** attempts)
            update[FIELD + ".http_status"] = status
            outcome["retry"] += 1
        collection.update_one({"_id": doc["_id"], FIELD + ".status": "pending"}, {"$set": update})
        if pause:
            time.sleep(pause)
    return outcome


def _datacat_class(doc: dict) -> str:
    verdict = str(doc.get("verdict") or "").upper()
    if verdict in ("BOT", "HUMAN"):
        return verdict
    return "PENDING" if doc.get("decision_state") == "INSUFFICIENT_EVIDENCE" else "SUSPECT"


def cohen_kappa(table: dict) -> Optional[float]:
    """Kappa of a 2x2 agreement table {(a, b): count} with a, b in {True, False}."""
    total = sum(table.values())
    if not total:
        return None
    observed = (table.get((True, True), 0) + table.get((False, False), 0)) / total
    a_yes = (table.get((True, True), 0) + table.get((True, False), 0)) / total
    b_yes = (table.get((True, True), 0) + table.get((False, True), 0)) / total
    expected = a_yes * b_yes + (1 - a_yes) * (1 - b_yes)
    if expected >= 1:
        return None
    return (observed - expected) / (1 - expected)


def _query(site_ids=None, site_filter=None, since=None, **extra) -> dict:
    query = {FIELD + ".status": {"$exists": True}, **extra}
    if site_ids:
        query["site_id"] = {"$in": list(site_ids)}
    if site_filter:
        query.update(site_filter)
    if since is not None:
        query["created_at"] = {"$gte": since}
    return query


# Review lists: where the two detectors disagree on a decided session, the cases worth reading.
DISAGREEMENTS = {
    # Fingerprint saw a bad bot, DATACAT did not convict: a candidate for a new contradiction.
    "fingerprint_only": {"verdict": {"$ne": "BOT"}, FIELD + ".bot": "bad"},
    # DATACAT convicted, Fingerprint saw no bot: check the evidence of DATACAT's rule.
    "datacat_only": {"verdict": "BOT", FIELD + ".bot": "not_detected"},
    # Fingerprint names a known good bot (crawler, AI assistant) that DATACAT judged.
    "good_bot": {FIELD + ".bot": "good"},
}


def disagreements(db, kind: str, site_filter=None, since=None, limit: int = 50) -> list:
    """Sessions of one disagreement kind, newest first, with what a reviewer needs to compare."""
    query = _query(site_filter=site_filter, since=since, **{FIELD + ".status": "done"}, **DISAGREEMENTS[kind])
    rows = []
    for doc in (db["detection_results"].find(query, {
            "_id": 0, "sessionId": 1, "site_id": 1, "verdict": 1, "decision_state": 1, "created_at": 1,
            "client_ip": 1, "country_code": 1, "reasons": 1, "breakdown.automation_rule": 1,
            "breakdown.suspect_reason_codes": 1, FIELD: 1}).sort("created_at", -1).limit(limit)):
        ref = (doc.get("reference") or {}).get("fingerprint") or {}
        created = doc.get("created_at")
        rows.append({
            "sessionId": doc.get("sessionId"), "site_id": doc.get("site_id"),
            "datacat": _datacat_class(doc),
            "rule": (doc.get("breakdown") or {}).get("automation_rule"),
            "codes": (doc.get("breakdown") or {}).get("suspect_reason_codes") or [],
            "reason": (doc.get("reasons") or [None])[0],
            "fingerprint": ref.get("bot"), "bot_category": ref.get("bot_category"), "bot_name": ref.get("bot_name"),
            "country": doc.get("country_code"),
            "created_at": int(created.timestamp() * 1000) if hasattr(created, "timestamp") else created,
        })
    return rows


def report(db, site_ids=None, site_filter=None, since=None) -> dict:
    """DATACAT verdict versus the Fingerprint bot verdict on sessions with a fetched reference."""
    query = _query(site_ids, site_filter, since, **{FIELD + ".status": "done"})
    crosstab: dict = {}
    binary: dict = {}
    statuses: dict = {}
    for doc in db["detection_results"].find(_query(site_ids, site_filter, since), {FIELD + ".status": 1}):
        status = ((doc.get("reference") or {}).get("fingerprint") or {}).get("status")
        statuses[status] = statuses.get(status, 0) + 1
    strong: dict = {}
    for doc in db["detection_results"].find(query, {"verdict": 1, "decision_state": 1, FIELD + ".bot": 1,
                                                     FIELD + ".strong": 1}):
        ours = _datacat_class(doc)
        ref = (doc.get("reference") or {}).get("fingerprint") or {}
        theirs = ref.get("bot") or "unknown"
        crosstab.setdefault(ours, {}).setdefault(theirs, 0)
        crosstab[ours][theirs] += 1
        # Strong flags are stored from 2026-11-13 on; older labels have none.
        if isinstance(ref.get("strong"), bool):
            row = strong.setdefault(ours, {"labelled": 0, "flagged": 0})
            row["labelled"] += 1
            row["flagged"] += ref["strong"]
        # Binary view on decided sessions only: DATACAT BOT vs HUMAN, Fingerprint bad vs not bad.
        if ours in ("BOT", "HUMAN") and theirs in ("bad", "good", "not_detected"):
            key = (ours == "BOT", theirs == "bad")
            binary[key] = binary.get(key, 0) + 1
    decided = sum(binary.values())
    agree = binary.get((True, True), 0) + binary.get((False, False), 0)
    return {
        "statuses": statuses,
        "crosstab": crosstab,
        "decided_pairs": decided,
        "agreement": round(agree / decided, 4) if decided else None,
        "kappa": round(cohen_kappa(binary), 4) if cohen_kappa(binary) is not None else None,
        "both_bot": binary.get((True, True), 0),
        "datacat_bot_only": binary.get((True, False), 0),
        "fingerprint_bot_only": binary.get((False, True), 0),
        "neither": binary.get((False, False), 0),
        # Tampering, anti-detect browser or suspect score >= 20, by DATACAT verdict.
        "strong_by_verdict": strong,
    }
