"""
FastAPI Inference & Telemetry Collection Server
Serves real-time bot detection inference using the trained Multi-Modal Ensemble
and provides endpoints for telemetry ingestion and operational analysis.
"""

import asyncio
import collections
import hashlib
import ipaddress
import json
import logging
import math
import os
import re
import secrets
import threading
import time
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urlsplit

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request
from fastapi import Path as PathParam
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from pydantic import BaseModel, Field, ValidationError, field_validator
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import Response as StarletteResponse

from api_service import auth, clicks, gateway, geoip, page_tokens, reference, sites
from api_service.capture import build_capture
from api_service.config import settings
from api_service.research_labels import (
    delete_research_data,
    delete_research_sessions,
    enrich_sessions,
    register_traffic,
    set_manual_label,
    traffic_page,
)
from api_service.spool import TelemetrySpool
from core_ml.features.env_features import FEATURE_NAMES as ENV_FEATURE_NAMES
from core_ml.features.mouse_features import STATISTICAL_FEATURE_NAMES
from core_ml.features.network import cloud_provider, crawler_operator
from core_ml.model_bundle import (
    ModelBundleError,
    release_evidence_valid,
    verify_model_bundle,
)
from core_ml.models.behavioral_lstm import MouseTrajectoryLSTM
from core_ml.models.ensemble import DECISION_POLICY_VERSION, EnsembleBotDetector
from core_ml.models.tabular_classifier import TabularBotClassifier

logger = logging.getLogger("bot_detection.api")


class RequestBodyTooLarge(Exception):
    pass


def _reject_non_finite_json(value: str):
    raise ValueError(f"Non-finite JSON number is not allowed: {value}")


class RequestBodyLimitMiddleware:
    """Reject oversized streamed bodies before FastAPI buffers them."""

    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") not in {"POST", "PUT", "PATCH"}:
            await self.app(scope, receive, send)
            return

        content_length = dict(scope.get("headers") or []).get(b"content-length")
        if content_length:
            try:
                if int(content_length) > self.max_bytes:
                    response = JSONResponse(status_code=413, content={"detail": "Request payload too large"})
                    await response(scope, receive, send)
                    return
            except ValueError:
                response = JSONResponse(status_code=400, content={"detail": "Invalid Content-Length header"})
                await response(scope, receive, send)
                return

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise RequestBodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except RequestBodyTooLarge:
            response = JSONResponse(status_code=413, content={"detail": "Request payload too large"})
            await response(scope, receive, send)

@asynccontextmanager
async def app_lifespan(_app):
    await run_in_threadpool(_restore_telemetry_spool)
    await run_in_threadpool(_reload_sites)
    await run_in_threadpool(_repair_site_attribution)
    try:
        await run_in_threadpool(auth.ensure_user_indexes)
    except Exception:
        logger.warning("Dashboard user index setup deferred", exc_info=True)
    maintenance_task = asyncio.create_task(_maintenance_loop())
    geoip_task = asyncio.create_task(_geoip_update_loop()) if settings.GEOIP_AUTO_UPDATE else None
    reference_task = asyncio.create_task(_reference_loop()) if reference.enabled() else None
    try:
        yield
    finally:
        if reference_task is not None:
            reference_task.cancel()
            with suppress(asyncio.CancelledError):
                await reference_task
        maintenance_task.cancel()
        with suppress(asyncio.CancelledError):
            await maintenance_task
        if geoip_task is not None:
            geoip_task.cancel()
            with suppress(asyncio.CancelledError):
                await geoip_task
        try:
            # Persist anything that arrived during a transient outage before a
            # rolling deployment removes this process.
            await run_in_threadpool(_flush_telemetry_buffer)
        finally:
            from api_service.database import close_database

            await run_in_threadpool(close_database)


auth.configure_secret(settings.SESSION_SECRET)

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Bot detection using browser heuristics, mouse dynamics, and tabular ML",
    version=settings.VERSION,
    lifespan=app_lifespan,
)

app.add_middleware(RequestBodyLimitMiddleware, max_bytes=settings.MAX_PAYLOAD_BYTES)

# A refused page's browser must be able to read the refusal, or the collector takes the failed
# preflight for a network error and keeps retrying every few seconds. Seconds it stops for:
STOP_UNREGISTERED_S = 86400
STOP_PAUSED_S = 3600
# Headers a refused collector must be able to read, on allowed and refused origins alike.
_STOP_EXPOSED = "X-Datacat-Stop, X-Datacat-Stop-Scope, Retry-After"


def _stop_headers(kind: str, origin) -> dict:
    """X-Datacat-Stop: how long the collector stays silent. X-Datacat-Stop-Scope: ``page`` when
    other pages of the website are still monitored (only this page goes silent), else ``origin``."""
    scope = "page" if origin and sites.registry.has_active(str(origin).strip().rstrip("/")) else "origin"
    seconds = STOP_PAUSED_S if kind == "paused" else STOP_UNREGISTERED_S
    return {"X-Datacat-Stop": str(seconds), "X-Datacat-Stop-Scope": scope}


def _early_refusal(request: Request) -> None:
    """Refuse telemetry from a website none of whose pages is monitored before the body is read
    or counted against the rate limit, so a refused page costs the API almost nothing and the
    collector always gets the stop signal (never a 400, 422 or 429 it would retry)."""
    origin = request.headers.get("origin")
    kind = sites.registry.refusal(origin, settings.TELEMETRY_ALLOWED_ORIGINS)
    if kind is None:
        return
    if kind == "unregistered":
        _log_refused_page(origin, None)
    raise HTTPException(status_code=403, headers=_stop_headers(kind, origin),
                        detail="Monitoring is paused for this site" if kind == "paused"
                        else "This page is not registered for monitoring")
_TELEMETRY_PATHS = ("/api/v1/telemetry", "/api/v1/visit")


class SiteAwareCORSMiddleware(CORSMiddleware):
    """CORS for the configured origins plus the active sites registered on the dashboard.

    Telemetry from any other page passes the preflight without credentials, so its POST reaches
    the API, is refused there (403, nothing stored) and the collector reads ``X-Datacat-Stop``.
    """

    def is_allowed_origin(self, origin: str) -> bool:
        return super().is_allowed_origin(origin) or sites.registry.allows_cors(origin)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path") in _TELEMETRY_PATHS:
            headers = Headers(scope=scope)
            origin = headers.get("origin")
            if origin and not self.is_allowed_origin(origin):
                if scope["method"] == "OPTIONS" and "access-control-request-method" in headers:
                    await StarletteResponse(status_code=204, headers={
                        "Access-Control-Allow-Origin": origin, "Access-Control-Allow-Methods": "POST",
                        "Access-Control-Allow-Headers": "content-type", "Access-Control-Max-Age": "86400",
                        "Vary": "Origin"})(scope, receive, send)
                    return

                async def send_readable(message):
                    if message["type"] == "http.response.start":
                        response_headers = MutableHeaders(scope=message)
                        response_headers["Access-Control-Allow-Origin"] = origin
                        response_headers["Access-Control-Expose-Headers"] = _STOP_EXPOSED
                        response_headers.add_vary_header("Origin")
                    await send(message)

                await self.app(scope, receive, send_readable)
                return
        await super().__call__(scope, receive, send)


# Enable CORS for local development and cloud deployments
app.add_middleware(
    SiteAwareCORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials="*" not in settings.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Retry-After", "X-Datacat-Stop", "X-Datacat-Stop-Scope"],
)

# Global model holders
weights_dir = settings.WEIGHTS_DIR
lstm_weights_path = os.path.join(weights_dir, "behavioral_lstm.pt")
tabular_weights_path = os.path.join(weights_dir, "tabular_model.joblib")
tabular_feature_names = list(ENV_FEATURE_NAMES) + list(STATISTICAL_FEATURE_NAMES)
try:
    model_manifest = verify_model_bundle(weights_dir, tabular_feature_names)
    model_bundle_valid = True
except ModelBundleError:
    logger.exception("Model bundle verification failed")
    model_manifest = {}
    model_bundle_valid = False

lstm_model = MouseTrajectoryLSTM()
lstm_loaded = model_bundle_valid and lstm_model.load_weights(lstm_weights_path)

tabular_model = TabularBotClassifier()
tabular_loaded = model_bundle_valid and tabular_model.load(
    tabular_weights_path,
    expected_feature_names=tabular_feature_names,
)

ensemble_detector = EnsembleBotDetector(
    lstm_model=lstm_model,
    tabular_model=tabular_model,
    threshold=settings.THRESHOLD,
    suspect_threshold=settings.SUSPECT_THRESHOLD,
    min_mouse_points_for_bot=settings.MIN_MOUSE_POINTS_FOR_BOT,
    lstm_available=lstm_loaded,
    tabular_available=tabular_loaded,
)
model_bundle_id = str(model_manifest.get("bundle_id") or "")
release_gate_evidence_present = release_evidence_valid(
    model_manifest,
    DECISION_POLICY_VERSION,
    settings.THRESHOLD,
    settings.SUSPECT_THRESHOLD,
    min_mouse_points_for_bot=settings.MIN_MOUSE_POINTS_FOR_BOT,
)

# The in-memory queue mirrors the durable spool while this process is running.
telemetry_buffer = collections.deque(maxlen=settings.MAX_BUFFER_SIZE)
_spool = TelemetrySpool(settings.TELEMETRY_SPOOL_PATH, settings.MAX_BUFFER_SIZE)
_telemetry_buffer_lock = threading.Lock()
_telemetry_buffer_stats = {"dropped_total": 0}
_telemetry_replay_inflight = 0
_telemetry_flush_lock = threading.Lock()
_health_cache_lock = threading.Lock()
_health_cache = {"checked_at": 0.0, "database": False, "inference_ready": False}

# Sliding-window rate limiter per client IP
# Recent live inference durations (telemetry + /detect) for the dashboard KPI.
# In-memory on purpose: it describes this process since start-up.
_latency_lock = threading.Lock()
_inference_latency_ms = collections.deque(maxlen=500)


def _record_inference_latency(started_at: float) -> float:
    elapsed = round((time.perf_counter() - started_at) * 1000, 2)
    with _latency_lock:
        _inference_latency_ms.append(elapsed)
    return elapsed


def _inference_latency_summary() -> Optional[Dict[str, Any]]:
    with _latency_lock:
        samples = sorted(_inference_latency_ms)
    if not samples:
        return None
    p95 = samples[min(len(samples) - 1, math.ceil(0.95 * len(samples)) - 1)]
    return {"avg_ms": round(sum(samples) / len(samples), 2), "p95_ms": p95, "samples": len(samples)}


_rate_limit_lock = threading.Lock()
_rate_limit_records = collections.defaultdict(list)


async def _geoip_update_loop():
    """Keep the offline GeoIP databases at most a month old (checked daily)."""
    from api_service import geoip

    while True:
        try:
            updated = await run_in_threadpool(geoip.refresh_if_stale)
            if updated:
                logger.info("GeoIP databases updated: %s", ", ".join(updated))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("GeoIP update failed")
        await asyncio.sleep(86400)


async def _reference_loop():
    """Fetch the Fingerprint verdicts of sampled sessions (api_service.reference)."""
    from api_service import database

    try:
        await run_in_threadpool(reference.ensure_indexes, database.get_db())
    except Exception:
        logger.warning("Reference index setup deferred", exc_info=True)
    while True:
        try:
            outcome = await run_in_threadpool(reference.poll_pending, database.get_db())
            if any(outcome.values()):
                logger.info("Fingerprint reference: %s", outcome)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Fingerprint reference iteration failed")
        await asyncio.sleep(20)


def _record_reference(data: dict) -> None:
    event_id = (data.get("collector") or {}).get("referenceEventId")
    if not event_id or not reference.enabled():
        return
    from api_service import database

    try:
        reference.record_event(database.get_db(), data.get("sessionId"), event_id)
    except Exception:
        logger.warning("Fingerprint reference event not recorded", exc_info=True)


async def _maintenance_loop():
    """Retry buffered persistence independently of incoming request traffic."""
    last_accounting = 0.0
    while True:
        await asyncio.sleep(settings.MAINTENANCE_INTERVAL_SECONDS)
        try:
            await run_in_threadpool(_flush_telemetry_buffer)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Telemetry maintenance iteration failed")
        try:
            await run_in_threadpool(_reload_sites)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Site registry refresh failed")
        if settings.GATEWAY_SECRET and time.monotonic() - last_accounting >= 60:
            last_accounting = time.monotonic()
            try:
                await run_in_threadpool(_account_unmonitored_page_views)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Page-view accounting failed")


_gateway_indexes_ready = False


def _gateway_db():
    """The database for gateway bookkeeping, with its indexes (best effort, never gating detection)."""
    global _gateway_indexes_ready
    from api_service.database import get_db
    db = get_db()
    if db is not None and not _gateway_indexes_ready:
        _gateway_indexes_ready = gateway.ensure_indexes(db)
    return db


def _account_unmonitored_page_views() -> int:
    return gateway.account_unmonitored(
        _gateway_db(), after_seconds=settings.NO_TELEMETRY_AFTER_SECONDS,
        policy_version=str(DECISION_POLICY_VERSION), site_for_host=_site_id_for_host,
    )


_site_indexes_ready = False


def _sites_db():
    """The database holding the site registry, with its indexes (best effort)."""
    global _site_indexes_ready
    from api_service.database import get_db
    db = get_db()
    if db is not None and not _site_indexes_ready:
        _site_indexes_ready = sites.ensure_indexes(db)
    return db


def _reload_sites() -> bool:
    return sites.registry.reload(_sites_db())


def _repair_site_attribution() -> None:
    db = _sites_db()
    if db is None:
        return
    try:
        moved = sites.attribute_unverified_history(db)
        if moved:
            logger.info("Attributed %d sessions without an Origin header to their site", moved)
    except Exception:
        logger.warning("Unverified site attribution repair deferred", exc_info=True)


def _site_id_for_host(host: str, path: str = "") -> Optional[str]:
    site = sites.registry.for_host(host, path)
    return site["site_id"] if site else None


def _request_host(request: Request) -> str:
    return (request.headers.get("host") or "").split(":")[0].lower()


def _attach_server_context(request: Request, data: dict, *, link: bool) -> None:
    """Facts only the server sees: was the page served by the gateway, how busy is this device."""
    page_view_id = request.cookies.get(gateway.PAGE_VIEW_COOKIE)
    tracked = bool(settings.PAGEVIEW_HOSTS) and _request_host(request) in settings.PAGEVIEW_HOSTS
    db = _gateway_db() if (tracked or data.get("visitorId") or gateway.valid_page_view_id(page_view_id)) else None
    headers = data.setdefault("_server_headers", {})
    headers["page_view"] = gateway.page_view_state(
        db, host=_request_host(request), tracked_hosts=settings.PAGEVIEW_HOSTS,
        page_view_id=page_view_id, session_id=data.get("sessionId"), link=link,
        user_agent=request.headers.get("user-agent") or "",
    )
    # Phones of one model share a fingerprint and carriers share addresses (CGNAT), so many
    # people would look like one busy device: the count is kept for desktops only.
    fingerprint = data.get("fingerprint") if isinstance(data.get("fingerprint"), dict) else {}
    phone = gateway.is_phone_user_agent(fingerprint.get("userAgent") or request.headers.get("user-agent") or "")
    headers["device_sessions"] = gateway.device_sessions(
        db, visitor_id=data.get("visitorId"), ip=data.get("client_ip") or get_client_ip(request),
        session_id=str(data.get("sessionId") or ""), device_token=data.get("deviceToken"),
    ) if data.get("visitorId") and not phone else None
    if gateway.valid_page_view_id(page_view_id):
        data["_page_view_id"] = page_view_id
    # A website without the gateway proves its page loads with a page-view token instead.
    if headers["page_view"] == "untracked" and data.get("_page_token"):
        headers["page_view"] = data["_page_token"]


def _page_token_state(data: dict, site: Optional[dict]) -> Optional[str]:
    from api_service.database import get_db

    db = get_db()
    if db is None or not site:
        return None
    try:
        required_from = datetime.fromisoformat(settings.PAGE_TOKEN_REQUIRED_FROM) if settings.PAGE_TOKEN_REQUIRED_FROM else None
    except ValueError:
        required_from = None
    try:
        return page_tokens.page_state(db, data, site.get("site_id"), required_from=required_from)
    except Exception:
        logger.warning("Page token check unavailable", exc_info=True)
        return None


def _purge_session_from_memory(session_id: str) -> bool:
    """Remove a session from best-effort caches after an administrative delete."""
    with _telemetry_buffer_lock:
        _spool.delete_session(session_id)
        retained = [event for event in telemetry_buffer if event.get("sessionId") != session_id]
        removed_from_buffer = len(retained) != len(telemetry_buffer)
        telemetry_buffer.clear()
        telemetry_buffer.extend(retained)
    return removed_from_buffer


def _purge_sessions_from_memory(session_ids) -> None:
    wanted = set(session_ids)
    with _telemetry_buffer_lock:
        _spool.delete_sessions(wanted)
        retained = [event for event in telemetry_buffer if event.get("sessionId") not in wanted]
        telemetry_buffer.clear()
        telemetry_buffer.extend(retained)


def _clear_in_memory_sessions():
    with _telemetry_buffer_lock:
        _spool.clear()
        telemetry_buffer.clear()


def _restore_telemetry_spool() -> None:
    """Recover committed events before accepting traffic after a restart."""
    with _telemetry_buffer_lock:
        events = _spool.load()
        known = {event.get("_spool_id") for event in telemetry_buffer}
        for event in events:
            if event["_spool_id"] not in known:
                if len(telemetry_buffer) >= telemetry_buffer.maxlen:
                    raise RuntimeError("Telemetry queue cannot hold all durable events")
                telemetry_buffer.append(event)


def _require_inference_models():
    """Reject inference when the complete, verified ensemble is unavailable."""
    if not (model_bundle_valid and tabular_loaded and lstm_loaded and release_gate_evidence_present):
        raise HTTPException(status_code=503, detail="Inference models are unavailable")


def _attach_model_metadata(result: dict) -> dict:
    """Make every decision traceable to the exact deployed model bundle."""
    result["model_bundle_id"] = model_bundle_id
    return result


def _record_telemetry_drop(reason: str):
    with _telemetry_buffer_lock:
        _telemetry_buffer_stats["dropped_total"] += 1
        dropped_total = _telemetry_buffer_stats["dropped_total"]
    logger.warning("Dropped telemetry event (%s); dropped_total=%d", reason, dropped_total)


def _buffer_telemetry(data: dict, analysis: Optional[dict] = None) -> bool:
    """Acknowledge only after the fallback event is committed to disk."""
    buffered_data = dict(data)
    if analysis is not None:
        # Reuse the decision already returned for this event. Re-running the
        # model during database recovery wastes CPU and can change the verdict.
        buffered_data["_buffered_analysis"] = dict(analysis)
    with _telemetry_buffer_lock:
        if len(telemetry_buffer) + _telemetry_replay_inflight >= telemetry_buffer.maxlen:
            return False
        try:
            identifier = _spool.enqueue(buffered_data)
        except (OSError, ValueError, TypeError) as exc:
            logger.error("Telemetry spool write failed: %s", exc)
            return False
        except Exception:
            logger.exception("Telemetry spool write failed")
            return False
        if identifier is None:
            return False
        buffered_data["_spool_id"] = identifier
        telemetry_buffer.append(buffered_data)
    return True


def _requeue_buffered_event(data: dict, *, front: bool = True):
    """Put a failed replay back only when doing so cannot evict newer data."""
    with _telemetry_buffer_lock:
        if len(telemetry_buffer) < telemetry_buffer.maxlen:
            if front:
                telemetry_buffer.appendleft(data)
            else:
                telemetry_buffer.append(data)
            return True
    _record_telemetry_drop("replay queue filled concurrently")
    return False


def _persist_capture(snapshot: dict, analysis: Optional[dict] = None) -> dict:
    """Persist research data without using inference as an ingestion gate."""
    from api_service.database import DatabaseIngestionPaused, save_telemetry_capture

    try:
        persisted = bool(save_telemetry_capture(snapshot, analysis))
    except DatabaseIngestionPaused as exc:
        raise HTTPException(status_code=503, detail="Telemetry ingestion is temporarily paused",
                            headers={"Retry-After": str(min(exc.retry_after_seconds, 300))}) from exc
    except Exception:
        logger.exception("Research capture persistence failed; attempting durable spool")
        buffered = _buffer_telemetry({
            "sessionId": snapshot["sessionId"], "_capture_snapshot": snapshot,
        }, analysis)
        if not buffered:
            raise HTTPException(status_code=503, detail="Research capture storage unavailable",
                                headers={"Retry-After": "10"})
        return {"capture_id": snapshot["event_id"], "persisted": False, "buffered": True}
    if not persisted:
        raise HTTPException(status_code=409, detail="Research capture expired or session deleted")
    return {"capture_id": snapshot["event_id"], "persisted": True, "buffered": False}


def _persist_touch_samples(data: dict, analysis: dict) -> None:
    """Best effort: training data must never fail or slow a telemetry request."""
    try:
        from api_service.database import save_touch_samples
        from api_service.touch_samples import build_touch_samples
        save_touch_samples(build_touch_samples(data, analysis))
    except Exception:
        logger.exception("Touch sample persistence failed")


def _flush_telemetry_buffer(max_events: Optional[int] = None):
    """Persist a bounded batch after MongoDB recovers without duplicate flushers."""
    global _telemetry_replay_inflight
    if not _telemetry_flush_lock.acquire(blocking=False):
        return
    try:
        _restore_telemetry_spool()
        from api_service.database import (
            DatabaseIngestionPaused,
            is_database_ready,
            save_detection_result,
            save_telemetry_capture,
        )

        with _telemetry_buffer_lock:
            # Retention must not be blocked by an earlier failed DB write.
            retained = []
            now_ms = int(time.time() * 1000)
            for event in telemetry_buffer:
                capture = event.get("_capture_snapshot")
                if capture is not None and capture["expires_at_ms"] <= now_ms:
                    if event.get("_spool_id") is not None:
                        _spool.delete(event["_spool_id"])
                else:
                    retained.append(event)
            telemetry_buffer.clear()
            telemetry_buffer.extend(retained)
            pending_count = len(telemetry_buffer)
        replay_count = pending_count if max_events is None else min(pending_count, max(0, max_events))

        for _ in range(replay_count):
            with _telemetry_buffer_lock:
                if not telemetry_buffer:
                    break
                data = telemetry_buffer.popleft()
                _telemetry_replay_inflight += 1

            try:
                analysis = data.get("_buffered_analysis")
                capture = data.get("_capture_snapshot")
                if capture is not None and capture["expires_at_ms"] <= int(time.time() * 1000):
                    # Enforce research retention even during a prolonged Mongo
                    # outage; expired raw data must not occupy the spool forever.
                    if data.get("_spool_id") is not None:
                        _spool.delete(data["_spool_id"])
                    continue
                register_traffic(capture if capture is not None else data)
                if capture is None and not isinstance(analysis, dict):
                    try:
                        analysis = ensemble_detector.predict(data)
                        _attach_model_metadata(analysis)
                    except Exception:
                        retry_count = int(data.get("_replay_attempts", 0)) + 1
                        if retry_count <= settings.MAX_TELEMETRY_RETRIES:
                            data["_replay_attempts"] = retry_count
                            _requeue_buffered_event(data, front=False)
                            logger.exception(
                                "Buffered telemetry inference failed (attempt %d/%d)",
                                retry_count,
                                settings.MAX_TELEMETRY_RETRIES,
                            )
                        else:
                            logger.exception(
                                "Dropping buffered telemetry after %d failed inference attempts",
                                retry_count,
                            )
                            _record_telemetry_drop("inference retry limit exceeded")
                            if data.get("_spool_id") is not None:
                                _spool.delete(data["_spool_id"])
                        continue
                data.pop("_replay_attempts", None)
                try:
                    if capture is not None:
                        persisted = bool(save_telemetry_capture(capture, analysis))
                    else:
                        persisted = bool(save_detection_result(data, analysis))
                except DatabaseIngestionPaused:
                    # An admin delete intentionally invalidates old replay data.
                    if data.get("_spool_id") is not None:
                        _spool.delete(data["_spool_id"])
                    continue
                except Exception:
                    logger.exception("Buffered telemetry persistence failed")
                    data["_buffered_analysis"] = analysis
                    _requeue_buffered_event(data)
                    break

                if persisted:
                    if data.get("_spool_id") is not None:
                        _spool.delete(data["_spool_id"])
                    continue

                # A live database can intentionally reject stale/tombstoned data;
                # discard it. On an outage, restore the event and retry later.
                try:
                    database_ready = is_database_ready()
                except Exception:
                    logger.exception("Database readiness check failed during replay")
                    database_ready = False
                if not database_ready:
                    data["_buffered_analysis"] = analysis
                    _requeue_buffered_event(data)
                    break
                if data.get("_spool_id") is not None:
                    _spool.delete(data["_spool_id"])
            finally:
                with _telemetry_buffer_lock:
                    _telemetry_replay_inflight -= 1
    finally:
        _telemetry_flush_lock.release()


def check_rate_limit(client_ip: str) -> bool:
    """Returns True if within rate limit, False if rate limit exceeded."""
    if settings.RATE_LIMIT_PER_MINUTE <= 0:
        return True
    # Sliding windows measure elapsed time; wall-clock changes must not reset
    # or indefinitely extend a client's limit window.
    now = time.monotonic()
    cutoff = now - 60.0
    with _rate_limit_lock:
        if client_ip not in _rate_limit_records and len(_rate_limit_records) >= 10000:
            stale_keys = [
                key for key, values in _rate_limit_records.items()
                if not values or values[-1] <= cutoff
            ]
            for key in stale_keys:
                del _rate_limit_records[key]
            if len(_rate_limit_records) >= 10000:
                return False

        timestamps = _rate_limit_records[client_ip]
        valid_ts = [t for t in timestamps if t > cutoff]
        if len(valid_ts) >= settings.RATE_LIMIT_PER_MINUTE:
            _rate_limit_records[client_ip] = valid_ts
            return False
        valid_ts.append(now)
        _rate_limit_records[client_ip] = valid_ts
        return True


class CollectorMetadata(BaseModel):
    schemaVersion: Literal[1]
    sdkVersion: str = Field(min_length=1, max_length=32)
    pageInstanceId: str = Field(min_length=1, max_length=128)
    # Collector 1.13: the page-view token GET /api/v1/visit issued for this session.
    pageToken: Optional[str] = Field(default=None, max_length=512)
    # Collector 1.15: event id of the Fingerprint agent for a sampled session (api_service.reference).
    referenceEventId: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9._-]{1,128}$")
    studyId: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")
    siteId: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")


class TelemetryPayload(BaseModel):
    sessionId: Optional[str] = Field(default=None, max_length=128)
    visitorId: Optional[str] = Field(default=None, max_length=128)
    # Collector 1.11: random id in the site's localStorage, shared by one browser's tabs.
    deviceToken: Optional[str] = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    action: Optional[str] = Field(default="telemetry", max_length=64)
    timestamp: Optional[int] = None
    sequence: Optional[int] = Field(default=None, ge=0, le=999999)
    pageUrl: Optional[str] = Field(default=None, max_length=2048)
    referrer: Optional[str] = Field(default=None, max_length=2048)
    fingerprint: Optional[Dict[str, Any]] = None
    botd: Optional[Dict[str, Any]] = None
    mouse: Optional[Dict[str, Any]] = None
    collector: Optional[CollectorMetadata] = None

    @field_validator("mouse")
    @classmethod
    def validate_mouse_records(cls, mouse):
        if mouse is not None:
            for key in ("records", "trajectory"):
                if key in mouse and not isinstance(mouse[key], list):
                    raise ValueError(f"mouse.{key} must be an array")
        return mouse


def _is_trusted_proxy(host: str) -> bool:
    if not settings.TRUST_PROXY_HEADERS:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    for value in settings.TRUSTED_PROXIES:
        try:
            if address in ipaddress.ip_network(value, strict=False):
                return True
        except ValueError:
            continue
    return False


def get_client_ip(request: Request) -> str:
    """
    Extract real client IP address, honoring reverse proxy headers
    (Cloudflare, Nginx, AWS ALB, Traefik, Docker).
    """
    peer_ip = request.client.host if request.client else "127.0.0.1"
    if not _is_trusted_proxy(peer_ip):
        return peer_ip

    forwarded = []
    for raw_value in (request.headers.get("X-Forwarded-For") or "").split(","):
        try:
            forwarded.append(str(ipaddress.ip_address(raw_value.strip())))
        except ValueError:
            continue
    # Walk from the proxy nearest to us towards the client, skipping only hops
    # explicitly configured as trusted.
    for candidate in reversed(forwarded):
        if not _is_trusted_proxy(candidate):
            return candidate

    candidates = [request.headers.get("CF-Connecting-IP"), request.headers.get("X-Real-IP")]
    for candidate in candidates:
        try:
            return str(ipaddress.ip_address((candidate or "").strip()))
        except ValueError:
            continue
    return peer_ip


def _cookie_user(request: Request) -> Optional[dict]:
    """Resolve the dashboard session cookie, enforcing a CSRF header on writes."""
    token = request.cookies.get(auth.SESSION_COOKIE, "")
    if not token:
        return None
    user = auth.session_user(token)
    if user and request.method not in ("GET", "HEAD", "OPTIONS"):
        if request.headers.get(auth.CSRF_HEADER, "").lower() != auth.CSRF_VALUE:
            raise HTTPException(status_code=403, detail="Missing CSRF header")
    return user


def _bearer(request: Request, header: str) -> str:
    supplied = request.headers.get(header, "")
    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    return supplied


def _session_site(session_id) -> Optional[dict]:
    """The site a session was attributed to on its landing page, if any."""
    from api_service.database import get_db
    db = get_db()
    if db is None or not session_id:
        return None
    try:
        doc = db["detection_results"].find_one({"sessionId": session_id}, {"site_id": 1})
    except Exception:
        return None
    return sites.registry.get(doc.get("site_id")) if doc and doc.get("site_id") else None


def _resolve_telemetry_site(request: Request, data: dict) -> tuple:
    """(site, verified) for a telemetry request, refusing pages that are not monitored.

    Telemetry is accepted only from registered pages (or the configured allowlist, or any
    origin on a local run without either). The Origin header decides; without one, or with
    "null", a matching Referer and page are accepted but marked unverified. A visitor who
    landed on a monitored page keeps that page's site on other pages of the same website.
    """
    origin = (request.headers.get("origin") or "").strip()
    lookup = lambda: _session_site(data.get("sessionId"))  # noqa: E731
    if origin and origin.lower() != "null":
        allowed, site = sites.registry.origin_decision(
            origin, settings.TELEMETRY_ALLOWED_ORIGINS, data.get("pageUrl"), session_site=lookup)
        verified = True
    else:
        allowed, site = sites.registry.unverified_decision(
            request.headers.get("referer"), data.get("pageUrl"), settings.TELEMETRY_ALLOWED_ORIGINS,
            session_site=lookup)
        verified = False
    if not allowed:
        stop_origin = origin if verified else request.headers.get("referer")
        if verified is False and stop_origin:
            try:
                stop_origin = sites.normalize_origin(str(stop_origin).split("?")[0])
            except ValueError:
                stop_origin = None
        if site is not None:
            raise HTTPException(status_code=403, detail="Monitoring is paused for this site",
                                headers=_stop_headers("paused", stop_origin))
        _log_refused_page(origin, data.get("pageUrl"))
        raise HTTPException(status_code=403, detail="This page is not registered for monitoring",
                            headers=_stop_headers("unregistered", stop_origin))
    return site, verified and site is not None


_refused_pages: set = set()
_REFUSED_PAGES_LOGGED = 500


def _log_refused_page(origin: str, page_url) -> None:
    """Log each refused origin + page path once per process, so an operator can see which
    pages carry the tag without being registered. Query strings are left out."""
    if len(_refused_pages) >= _REFUSED_PAGES_LOGGED:
        return
    key = (origin or "-")[:200], sites.page_path(page_url)[:300]
    if key in _refused_pages:
        return
    _refused_pages.add(key)
    logger.warning("Telemetry refused for an unregistered page: origin=%s path=%s", *key)


def _require_allowed_origin(request: Request, page_url=None) -> Optional[dict]:
    """Reject browsers posting from pages that are not monitored; return the page's site.

    The domain comes from the Origin header the browser sets, never from the tag's site id;
    the reported page URL only picks among the sites registered on that domain.
    """
    origin = request.headers.get("origin")
    allowed, site = sites.registry.origin_decision(origin, settings.TELEMETRY_ALLOWED_ORIGINS, page_url)
    if not allowed:
        if site is not None:
            raise HTTPException(status_code=403, detail="Monitoring is paused for this site",
                                headers=_stop_headers("paused", origin))
        raise HTTPException(status_code=403, detail="Origin is not allowed to submit telemetry",
                            headers=_stop_headers("unregistered", origin))
    return site


def _has_read_credentials(request: Request) -> bool:
    try:
        require_read_access(request)
        return True
    except HTTPException:
        return False


# Policy 24: anonymous callers learn that the snapshot was scored, not the verdict, so a bot
# cannot use /detect to tune itself. Site backends read verdicts with credentials.
_MINIMAL_DETECT_FIELDS = ("decision_state", "policy_version", "model_bundle_id", "sessionId", "visitorId")


def _observed_headers(request: Request) -> dict:
    """Header facts that a script cannot change from inside the page."""
    return {
        "observed": True,
        "accept_language": bool((request.headers.get("accept-language") or "").strip()),
        "sec_ch_ua": (request.headers.get("sec-ch-ua") or "")[:256],
        "sec_fetch_site": (request.headers.get("sec-fetch-site") or "")[:32],
        "sec_fetch_mode": (request.headers.get("sec-fetch-mode") or "")[:32],
        "forwarded_proto": (request.headers.get("x-forwarded-proto") or request.url.scheme or "")[:8],
        # Published cloud range of the client address (None for residential/mobile).
        "datacenter": cloud_provider(get_client_ip(request)),
        # Published crawler range of the client address (google, bing, ...), policy 25.
        "crawler_operator": crawler_operator(get_client_ip(request)),
        # Web Bot Auth (RFC 9421 message signatures for bots): the agent names itself.
        "signature_agent": bool(request.headers.get("signature-agent") or request.headers.get("signature-input")),
    }


def _require_password_changed(request: Request, user: Optional[dict]) -> None:
    """An account on a temporary password may only look itself up and change it."""
    if user and user.get("must_change_password") and request.url.path != "/api/v1/auth/me":
        raise HTTPException(status_code=403, detail="PASSWORD_CHANGE_REQUIRED")


def _allowed_sites(user: Optional[dict]) -> Optional[list]:
    """Websites a signed-in customer may read; None for staff, administrators and API tokens."""
    return list(user.get("sites") or []) if user and user.get("role") == "customer" else None


def _scope(user: Optional[dict], site: Optional[str]) -> dict:
    """Mongo condition for the sessions this account may read, narrowed to ``site`` if given."""
    allowed = _allowed_sites(user)
    if allowed is None:
        return sites.site_filter(site)
    if site:
        if site not in allowed:
            raise HTTPException(status_code=403, detail="This website is not in your account")
        return {"site_id": site}
    return {"site_id": {"$in": allowed}}


# The monitoring views (overview, Live View) filter by the visitor's country: one page often runs
# ads in many. "_none": sessions whose address has no known country.
COUNTRY_FILTER_PATTERN = r"^([A-Z]{2}|_none)$"


def _monitor_scope(user: Optional[dict], site: Optional[str], country: Optional[str]) -> dict:
    scope = dict(_scope(user, site))
    if country:
        scope["country_code"] = None if country == "_none" else country
    return scope


def _require_session_visible(user: Optional[dict], session_id: str) -> None:
    allowed = _allowed_sites(user)
    if allowed is None:
        return
    from api_service.database import get_db
    db = get_db()
    doc = db["detection_results"].find_one({"sessionId": session_id}, {"site_id": 1}) if db is not None else None
    # Another customer's session answers like a missing one.
    if not doc or doc.get("site_id") not in allowed:
        raise HTTPException(status_code=404, detail="Session not found")


def _require_staff(user: Optional[dict]) -> None:
    if _allowed_sites(user) is not None:
        raise HTTPException(status_code=403, detail="Not available to customer accounts")


def require_admin(request: Request):
    supplied = _bearer(request, "X-Admin-Token")
    if supplied and settings.ADMIN_TOKEN and secrets.compare_digest(supplied, settings.ADMIN_TOKEN):
        return {"username": "token", "role": "admin"}
    user = _cookie_user(request)
    _require_password_changed(request, user)
    if user and user["role"] == "admin":
        return user
    if not settings.ADMIN_TOKEN and not request.cookies.get(auth.SESSION_COOKIE):
        raise HTTPException(status_code=503, detail="Admin API is disabled until BOT_ADMIN_TOKEN is configured")
    raise HTTPException(status_code=401, detail="Invalid admin credentials")


def require_read_access(request: Request):
    supplied = _bearer(request, "X-Read-Token")
    if supplied:
        if settings.READ_TOKEN and secrets.compare_digest(supplied, settings.READ_TOKEN):
            return {"username": "token", "role": "viewer"}
        if settings.ADMIN_TOKEN and secrets.compare_digest(supplied, settings.ADMIN_TOKEN):
            return {"username": "token", "role": "admin"}
    user = _cookie_user(request)
    _require_password_changed(request, user)
    if user:
        return user
    if not settings.READ_TOKEN and not request.cookies.get(auth.SESSION_COOKIE):
        raise HTTPException(status_code=503, detail="Monitoring API is disabled until BOT_READ_TOKEN is configured")
    raise HTTPException(status_code=401, detail="Invalid read credentials")


@app.get("/")
def index():
    return {
        "status": "online",
        "service": "DATACAT Bot Detection API",
        "models": {
            "behavioral_lstm": "ready" if lstm_loaded else "unavailable",
            "tabular_xgboost": "ready" if tabular_loaded else "unavailable",
        },
    }


@app.get("/health")
@app.get("/healthz")
def health_check():
    """Standard health check endpoint for load balancers and container orchestrators."""
    now = time.monotonic()
    with _health_cache_lock:
        cache_fresh = now - _health_cache["checked_at"] <= settings.HEALTH_CACHE_SECONDS
        if cache_fresh:
            database_ready = _health_cache["database"]
            runtime_ready = _health_cache["inference_ready"]
        else:
            from api_service.database import is_database_ready

            database_ready = is_database_ready()
            runtime_ready = False
            if tabular_loaded and lstm_loaded and release_gate_evidence_present:
                try:
                    runtime_ready = True
                    for point_count in (25, 37):
                        probe_records = [
                            {"time": index * 16, "x": index / 100, "y": 0.2, "type": "move"}
                            for index in range(point_count)
                        ]
                        probe = ensemble_detector.predict({"mouse": {"records": probe_records}})
                        probability = float(probe.get("bot_probability"))
                        runtime_ready = runtime_ready and math.isfinite(probability) and 0.0 <= probability <= 1.0
                except Exception:
                    runtime_ready = False
                    logger.exception("Model inference health probe failed")
            _health_cache.update({
                "checked_at": now,
                "database": database_ready,
                "inference_ready": runtime_ready,
            })
    content = {
        "status": "healthy" if (runtime_ready and database_ready) else "degraded",
        "timestamp": int(time.time() * 1000),
        "models_loaded": {
            "tabular": tabular_loaded,
            "lstm": lstm_loaded,
        },
        "model_bundle_valid": model_bundle_valid,
        "model_bundle_id": model_bundle_id,
        "decision_policy_version": DECISION_POLICY_VERSION,
        "release_gate_evidence_present": release_gate_evidence_present,
        "inference_ready": runtime_ready,
        "database": database_ready,
        "research_capture": {
            "enabled": settings.CAPTURE_ENABLED,
            "retention_days": settings.CAPTURE_RETENTION_DAYS,
        },
        "geoip": geoip.status(),
        "gateway": {"configured": bool(settings.GATEWAY_SECRET), "page_view_hosts": settings.PAGEVIEW_HOSTS},
    }
    with _telemetry_buffer_lock:
        content["telemetry_buffer"] = {
            "queued": len(telemetry_buffer),
            "capacity": telemetry_buffer.maxlen,
            "dropped_total": _telemetry_buffer_stats["dropped_total"],
        }
    return JSONResponse(content=content, status_code=200 if content["status"] == "healthy" else 503)


@app.get("/health/live")
def liveness_check():
    return {"status": "alive", "timestamp": int(time.time() * 1000)}


@app.post("/api/v1/detect")
async def detect_bot(payload: TelemetryPayload, request: Request):
    """
    Real-time bot classification endpoint.
    Fuses mouse dynamics, environment fingerprint, and heuristic checks.
    """
    _early_refusal(request)
    client_ip = get_client_ip(request)
    if not check_rate_limit(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Too many requests from this IP.",
            headers={"Retry-After": "60"},
        )
    _require_allowed_origin(request, payload.pageUrl)
    _require_inference_models()
    data = payload.model_dump()
    data["_server_user_agent"] = (request.headers.get("user-agent") or "")[:512]
    data["_server_headers"] = _observed_headers(request)
    data["client_ip"] = client_ip
    await run_in_threadpool(_attach_server_context, request, data, link=False)

    start_t = time.perf_counter()
    try:
        result = await run_in_threadpool(ensemble_detector.predict, data)
    except Exception as exc:
        logger.exception("Detection inference failed")
        raise HTTPException(status_code=503, detail="Inference temporarily unavailable") from exc

    latency_ms = _record_inference_latency(start_t)

    _attach_model_metadata(result)
    # A rule verdict (phone, automation marker) has no meaningful fused score: a real iPhone
    # was HUMAN with risk_score 0.9989 from the out-of-domain tabular model. bot_probability
    # stays as it was for older clients; risk_score is null when it does not apply.
    if (result.get("breakdown") or {}).get("risk_score_in_domain") is False:
        result["risk_score"] = None
    result["latency_ms"] = latency_ms
    result["client_ip"] = client_ip
    result["sessionId"] = data.get("sessionId")
    result["visitorId"] = data.get("visitorId")

    if settings.DETECT_RESPONSE == "minimal" and not _has_read_credentials(request):
        return {key: result.get(key) for key in _MINIMAL_DETECT_FIELDS}
    return result


def _link_hello(request: Request, data: dict) -> None:
    gateway.page_view_state(
        _gateway_db(), host=_request_host(request), tracked_hosts=settings.PAGEVIEW_HOSTS,
        page_view_id=request.cookies.get(gateway.PAGE_VIEW_COOKIE), session_id=data.get("sessionId"), link=True,
        user_agent=request.headers.get("user-agent") or "",
    )


def _require_gateway(request: Request) -> None:
    if not settings.GATEWAY_SECRET:
        raise HTTPException(status_code=404, detail="Not Found")
    if not gateway.gateway_authorized(request.headers.get("x-datacat-gateway") or "", settings.GATEWAY_SECRET):
        raise HTTPException(status_code=403, detail="Gateway credentials required")


@app.api_route("/api/v1/pageview", methods=["GET", "POST", "HEAD"], include_in_schema=False)
async def record_page_view(request: Request):
    """Mirror of an HTML request made by the shop gateway (nginx ``mirror``)."""
    _require_gateway(request)
    page_view_id = (request.headers.get("x-datacat-pv") or "").strip()
    if not gateway.valid_page_view_id(page_view_id):
        raise HTTPException(status_code=422, detail="X-Datacat-PV must be a 32-character request id")
    await run_in_threadpool(
        gateway.record_page_view, _gateway_db(), page_view_id,
        ip=get_client_ip(request), user_agent=request.headers.get("user-agent") or "",
        host=_request_host(request), path=request.headers.get("x-original-uri") or "",
        purpose=request.headers.get("sec-purpose") or request.headers.get("purpose") or "",
        accept_language=bool((request.headers.get("accept-language") or "").strip()),
        fetch_dest=request.headers.get("sec-fetch-dest") or "",
    )
    return Response(status_code=204)


def _recently_resumed(site) -> bool:
    resumed = (site or {}).get("resumed_at")
    if not isinstance(resumed, datetime):
        return False
    if resumed.tzinfo is None:
        resumed = resumed.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - resumed).total_seconds() <= STOP_PAUSED_S


@app.api_route("/api/v1/gate", methods=["GET", "POST"], include_in_schema=False)
async def gate_request(request: Request):
    """``auth_request`` target: 204 lets a shop request through, 403 refuses it."""
    _require_gateway(request)
    path = request.headers.get("x-original-uri") or ""
    try:
        strict = bool(settings.GATE_STRICT_PATHS) and re.search(settings.GATE_STRICT_PATHS, path) is not None
    except re.error:
        strict = False
    # A shop whose monitoring is paused or removed has no collector to wait for: its writes pass.
    host = _request_host(request)
    monitored, site = sites.registry.origin_decision(
        f"https://{host}", settings.TELEMETRY_ALLOWED_ORIGINS, f"https://{host}{path.split('?')[0]}")         if host else (True, None)
    if not monitored:
        return Response(status_code=204, headers={"X-Datacat-Gate": "not_monitored"})
    allowed, reason = await run_in_threadpool(
        gateway.gate_decision, _gateway_db(),
        page_view_id=request.cookies.get(gateway.PAGE_VIEW_COOKIE),
        method=request.headers.get("x-original-method") or "GET",
        strict=strict, grace_seconds=settings.GATE_GRACE_SECONDS,
        user_agent=request.headers.get("user-agent") or "",
    )
    if not allowed and reason in ("no_collector", "no_telemetry") and _recently_resumed(site):
        # Browsers told to stay silent while the site was paused may not have asked again yet.
        allowed, reason = True, "resumed"
    if not allowed:
        logger.info("Gate refused %s %s: %s", request.headers.get("x-original-method"), path[:200], reason)
    return Response(status_code=204 if allowed else 403, headers={"X-Datacat-Gate": reason})


@app.get("/api/v1/visit")
def issue_page_token(
    request: Request,
    sid: str = Query(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_-]+$"),
    page: Optional[str] = Query(default=None, max_length=2048),
):
    """A page-view token for one session of a registered page (collector 1.13+, see page_tokens)."""
    from api_service.database import get_db

    _early_refusal(request)
    data = {"sessionId": sid, "pageUrl": page}
    site, _verified = _resolve_telemetry_site(request, data)
    if site is None:
        # An allowlisted origin outside the registry: nothing to bind a token to.
        return StarletteResponse(status_code=204)
    if not page_tokens.quota.allow(get_client_ip(request), site["site_id"]):
        raise HTTPException(status_code=429, detail="Too many sessions from this address", headers={"Retry-After": "600"})
    db = get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return {"token": page_tokens.issue(db, site["site_id"], sid), "expires_in": page_tokens.TOKEN_TTL_SECONDS}


@app.post("/api/v1/telemetry")
async def receive_telemetry(request: Request, background_tasks: BackgroundTasks):
    """
    Asynchronous telemetry ingestion endpoint (e.g. from navigator.sendBeacon).
    Accepts application/json, text/plain (beacons), and raw JSON payloads.
    """
    _early_refusal(request)
    client_ip = get_client_ip(request)
    if not check_rate_limit(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded.",
            headers={"Retry-After": "60"},
        )
    # Robust parsing supporting application/json, text/plain (sendBeacon), or raw bytes
    try:
        body_bytes = await request.body()
        if len(body_bytes) > settings.MAX_PAYLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Request payload too large")
        data = json.loads(
            body_bytes.decode("utf-8"),
            parse_constant=_reject_non_finite_json,
        ) if body_bytes else {}
    except HTTPException:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise HTTPException(status_code=400, detail="Telemetry body must be a valid JSON object")

    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Telemetry body must be a JSON object")

    try:
        data = TelemetryPayload.model_validate(data).model_dump(exclude_none=True)
    except ValidationError as exc:
        detail = [{"loc": error["loc"], "msg": error["msg"], "type": error["type"]} for error in exc.errors()]
        raise HTTPException(status_code=422, detail=detail)
    if not data.get("sessionId"):
        raise HTTPException(status_code=422, detail="sessionId is required")
    site, site_verified = _resolve_telemetry_site(request, data)
    if data.get("action") == "hello":
        # Collector >= 1.10 greets the API as soon as it loads, before fingerprinting,
        # so the gateway can tell a page that runs it from one that never does.
        await run_in_threadpool(_link_hello, request, data)
        return JSONResponse(status_code=202, content={"status": "linked"})
    if not data.get("visitorId"):
        raise HTTPException(status_code=422, detail="visitorId is required")

    data["client_ip"] = client_ip
    data["received_at"] = int(time.time() * 1000)
    data["_server_user_agent"] = (request.headers.get("user-agent") or "")[:512]
    data["_server_headers"] = _observed_headers(request)
    data["_page_token"] = await run_in_threadpool(_page_token_state, data, site)
    await run_in_threadpool(_attach_server_context, request, data, link=True)
    data.pop("_page_token", None)

    capture = None
    capture_status = None
    if settings.CAPTURE_ENABLED:
        try:
            capture = build_capture(
                {key: value for key, value in data.items()
                 if key not in {"client_ip", "received_at", "_server_user_agent", "_server_headers"}},
                received_at=data["received_at"], client_ip=client_ip,
                user_agent=data["_server_user_agent"], bundle_id=model_bundle_id,
                server_headers=data["_server_headers"],
                policy_version=str(DECISION_POLICY_VERSION),
                retention_days=settings.CAPTURE_RETENTION_DAYS,
            )
        except (ValueError, OverflowError, RecursionError) as exc:
            raise HTTPException(status_code=422, detail="Telemetry cannot be captured as finite JSON") from exc
    if site is not None:
        data["_site_id"] = site["site_id"]
        if not site_verified:
            data["_site_unverified"] = True
    traffic_number = await run_in_threadpool(register_traffic, data)
    if capture is not None:
        capture_status = await run_in_threadpool(_persist_capture, capture)

    try:
        _require_inference_models()
        started_at = time.perf_counter()
        analysis = await run_in_threadpool(ensemble_detector.predict, data)
        _record_inference_latency(started_at)
        _attach_model_metadata(analysis)
    except Exception as exc:
        logger.exception("Telemetry inference failed")
        if capture_status is not None:
            if capture_status["persisted"]:
                background_tasks.add_task(_flush_telemetry_buffer)
            return JSONResponse(status_code=202, content={
                "status": "captured", "recorded": True, "analysis_available": False,
                "traffic_number": traffic_number,
                **capture_status,
            })
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=503, detail="Inference temporarily unavailable") from exc

    if capture is not None:
        # Attach the decision actually made for this snapshot, never a later
        # replay under different weights. Raw capture already survived inference.
        capture_status = await run_in_threadpool(_persist_capture, capture, analysis)

    # Save the analyzed event to MongoDB.
    persisted = False
    persistence_failed = False
    try:
        from api_service.database import DatabaseIngestionPaused, save_detection_result
        persisted = bool(await run_in_threadpool(save_detection_result, data, analysis))
    except DatabaseIngestionPaused as exc:
        raise HTTPException(
            status_code=503,
            detail="Telemetry ingestion is temporarily paused",
            headers={"Retry-After": str(min(exc.retry_after_seconds, 300))},
        ) from exc
    except Exception:
        logger.exception("Telemetry persistence failed")
        persisted = False
        persistence_failed = True
    if persisted:
        await run_in_threadpool(_record_reference, data)

    # Keep a best-effort copy only during a real database outage. Rejected
    # tombstoned/stale events must not reappear from this fallback buffer.
    buffered = False
    if not persisted:
        database_ready = False
        if not persistence_failed:
            try:
                from api_service.database import is_database_ready
                database_ready = bool(await run_in_threadpool(is_database_ready))
            except Exception:
                database_ready = False
        if persistence_failed or not database_ready:
            buffered = _buffer_telemetry(data, analysis)
            if not buffered:
                raise HTTPException(
                    status_code=503,
                    detail="Telemetry buffer is full; retry later",
                    headers={"Retry-After": "10"},
                )

    if persisted:
        background_tasks.add_task(_flush_telemetry_buffer)
        if settings.TOUCH_CAPTURE_ENABLED and (
                not settings.TOUCH_CAPTURE_SITES or data.get("_site_id") in settings.TOUCH_CAPTURE_SITES):
            background_tasks.add_task(_persist_touch_samples, data, analysis)

    # An admin deleted this session while the tab stayed open: tell the collector
    # to continue under a new id instead of being refused until the tombstone expires.
    session_closed = False
    if not persisted and not buffered:
        from api_service.database import is_session_closed
        session_closed = bool(await run_in_threadpool(is_session_closed, data.get("sessionId")))

    return {
        "status": "success" if persisted else "degraded",
        **({"session_closed": True} if session_closed else {}),
        "recorded": persisted or buffered or capture_status is not None,
        "persisted": persisted,
        "buffered": buffered,
        "model_bundle_id": model_bundle_id,
        "traffic_number": traffic_number,
        **({"capture_id": capture_status["capture_id"], "analysis_available": True,
            "capture_persisted": capture_status["persisted"],
            "capture_buffered": capture_status["buffered"]} if capture_status else {}),
    }


@app.get("/api/v1/telemetry/recent")
def get_recent_telemetry(
    limit: int = Query(default=50, ge=1, le=200),
    site: Optional[str] = Query(default=None, pattern=sites.SITE_FILTER_PATTERN),
    user=Depends(require_read_access),
):
    """
    Returns the most recent detection sessions from MongoDB.
    Single source of truth — no fallback to in-memory buffer.
    """
    from api_service.database import get_db, get_recent_results, get_total_count
    if get_db() is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    scope = _scope(user, site)
    results = get_recent_results(limit=limit, site_filter=scope)
    total = get_total_count(site_filter=scope)
    if results is None or total is None:
        raise HTTPException(status_code=503, detail="Database query failed")
    try:
        results = enrich_sessions(results)
    except Exception:
        logger.warning("Research session metadata unavailable", exc_info=True)
    geoip.attach(results)

    return {
        "total": total,
        # Deprecated compatibility alias for dashboard clients deployed before
        # the endpoint switched from an in-memory buffer to MongoDB.
        "total_buffered": total,
        "returned": len(results),
        "sessions": results,
    }


@app.get("/api/v1/traffic/timeline")
def get_traffic_timeline(
    window_minutes: int = Query(default=60, ge=30, le=43200),
    utc_offset_minutes: int = Query(default=0, ge=-720, le=840),
    site: Optional[str] = Query(default=None, pattern=sites.SITE_FILTER_PATTERN),
    country: Optional[str] = Query(default=None, pattern=COUNTRY_FILTER_PATTERN),
    user=Depends(require_read_access),
):
    """Return session counts using buckets sized for the requested window (up to 30 days,
    the data retention). Hour and day buckets start at the viewer's local midnight."""
    from api_service.database import get_traffic_timeline as query_traffic_timeline

    if window_minutes <= 60:
        bucket_minutes = 1
    elif window_minutes <= 120:
        bucket_minutes = 2
    elif window_minutes <= 360:
        bucket_minutes = 5
    elif window_minutes <= 720:
        bucket_minutes = 10
    elif window_minutes <= 1440:
        bucket_minutes = 15
    elif window_minutes <= 10080:
        bucket_minutes = 60
    else:
        bucket_minutes = 1440

    timeline = query_traffic_timeline(
        window_minutes=window_minutes,
        bucket_minutes=bucket_minutes,
        utc_offset_minutes=utc_offset_minutes,
        site_filter=_monitor_scope(user, site, country),
    )
    if timeline is None:
        raise HTTPException(status_code=503, detail="Traffic timeline query failed")
    return timeline


@app.get("/bot-collector.js")
def get_bot_collector_sdk(request: Request):
    """
    Serves the pre-compiled BotCollector standalone UMD bundle for proxy injection.
    """
    dist_path = os.path.join(os.path.dirname(__file__), "..", "collector", "dist", "bot-collector.js")
    dist_path = os.path.abspath(dist_path)
    bundle = _collector_bundle(dist_path)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Collector SDK bundle not found.")
    # The registry epoch is written into the script, so a browser told to stay silent asks
    # again as soon as a page is registered or resumed (see sites.SiteRegistry.epoch).
    epoch = sites.registry.epoch
    # Fingerprint reference sampling (api_service.reference): empty key and rate 0 turn it off.
    fp_key, fp_rate = reference.collector_config()
    variant = hashlib.sha256(f"{epoch}|{fp_key}|{fp_rate}".encode("utf-8")).hexdigest()[:8]
    etag = f'"{bundle[1]}-{epoch}-{variant}"'
    headers = {"Cache-Control": "public, no-cache", "ETag": etag}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    text = (bundle[0].replace(COLLECTOR_EPOCH_PLACEHOLDER, str(epoch))
            .replace(COLLECTOR_FP_KEY_PLACEHOLDER, fp_key)
            .replace(COLLECTOR_FP_RATE_PLACEHOLDER, repr(float(fp_rate))))
    return Response(text, media_type="application/javascript", headers=headers)


COLLECTOR_EPOCH_PLACEHOLDER = "__DATACAT_REGISTRY_EPOCH__"
COLLECTOR_FP_KEY_PLACEHOLDER = "__DATACAT_FP_KEY__"
COLLECTOR_FP_RATE_PLACEHOLDER = "__DATACAT_FP_RATE__"
_bundle_cache: dict = {}


def _collector_bundle(path: str):
    """(text, content hash) of the built collector, re-read when the file changes."""
    try:
        stat = os.stat(path)
    except OSError:
        return None
    key = (path, stat.st_mtime_ns, stat.st_size)
    if _bundle_cache.get("key") != key:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
        _bundle_cache.update(key=key, value=(text, hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]))
    return _bundle_cache["value"]


def _read_page(name: str) -> str:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"{name} not found.")
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


# Login and dashboard are never framed (clickjacking on admin actions).
_PAGE_HEADERS = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                 "Referrer-Policy": "same-origin", "X-Frame-Options": "DENY",
                 "Content-Security-Policy": "frame-ancestors 'none'"}


def _is_https(request: Request) -> bool:
    if request.url.scheme == "https":
        return True
    peer = request.client.host if request.client else ""
    return _is_trusted_proxy(peer) and request.headers.get("X-Forwarded-Proto", "").lower() == "https"


def _set_session_cookie(response, request: Request, token: str, max_age: int) -> None:
    response.set_cookie(
        auth.SESSION_COOKIE, token, max_age=max_age, httponly=True, samesite="strict",
        secure=_is_https(request), path="/",
    )


@app.get("/login", response_class=HTMLResponse)
def get_login_page(request: Request):
    """Serve the sign-in page; signed-in users go straight to the dashboard."""
    if auth.session_user(request.cookies.get(auth.SESSION_COOKIE, "")):
        return RedirectResponse("/dashboard", status_code=302)
    return HTMLResponse(content=_read_page("login.html"), headers=_PAGE_HEADERS)


@app.get("/dashboard", response_class=HTMLResponse)
def get_dashboard(request: Request):
    """Serve the monitoring dashboard to signed-in users only."""
    if not auth.session_user(request.cookies.get(auth.SESSION_COOKIE, "")):
        return RedirectResponse("/login", status_code=302)
    return HTMLResponse(content=_read_page("dashboard.html"), headers=_PAGE_HEADERS)


_PUBLIC_ASSETS = {"datacat-logo.png": "image/png"}


@app.get("/assets/{name}")
def get_public_asset(name: str):
    media_type = _PUBLIC_ASSETS.get(name)
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", name)
    if media_type is None or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Asset not found.")
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "public, max-age=86400"})


class LoginPayload(BaseModel):
    model_config = {"extra": "forbid"}
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=auth.MAX_PASSWORD_LENGTH)


class PasswordChangePayload(BaseModel):
    model_config = {"extra": "forbid"}
    current_password: str = Field(min_length=1, max_length=auth.MAX_PASSWORD_LENGTH)
    new_password: str = Field(min_length=1, max_length=auth.MAX_PASSWORD_LENGTH)


@app.post("/api/v1/auth/login")
async def auth_login(payload: LoginPayload, request: Request):
    client_ip = get_client_ip(request)
    if not check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Quá nhiều yêu cầu, thử lại sau.",
                            headers={"Retry-After": "60"})
    wait = auth.lockout_remaining(client_ip, payload.username)
    if wait:
        raise HTTPException(status_code=429, detail="Đăng nhập sai quá nhiều lần, hãy thử lại sau.",
                            headers={"Retry-After": str(wait)})
    try:
        user = await run_in_threadpool(auth.authenticate, payload.username, payload.password)
    except Exception as exc:
        logger.exception("Login lookup failed")
        raise HTTPException(status_code=503, detail="Dịch vụ tài khoản tạm thời không khả dụng") from exc
    if user is None:
        auth.record_failure(client_ip, payload.username)
        raise HTTPException(status_code=401, detail="Tên đăng nhập hoặc mật khẩu không đúng")
    auth.clear_failures(client_ip, payload.username)
    ttl = settings.SESSION_TTL_HOURS * 3600
    token = auth.issue_session(user["username"], user.get("role", "viewer"), user["password_hash"], ttl)
    try:
        users = auth.get_users_collection()
        if users is not None:
            users.update_one({"username_lower": user["username"].lower()},
                             {"$set": {"last_login_at": datetime.now(timezone.utc)}})
    except Exception:
        logger.warning("Could not record last login", exc_info=True)
    response = JSONResponse({"username": user["username"], "role": user.get("role", "viewer"),
                             "must_change_password": bool(user.get("must_change_password"))},
                            headers={"Cache-Control": "no-store"})
    _set_session_cookie(response, request, token, ttl)
    return response


@app.post("/api/v1/auth/logout")
def auth_logout(request: Request):
    response = JSONResponse({"status": "signed_out"}, headers={"Cache-Control": "no-store"})
    response.delete_cookie(auth.SESSION_COOKIE, path="/", samesite="strict", secure=_is_https(request))
    return response


@app.get("/api/v1/auth/me")
def auth_me(user=Depends(require_read_access)):
    allowed = _allowed_sites(user)
    return {"username": user["username"], "role": user["role"], "display_name": user.get("display_name") or "",
            "must_change_password": bool(user.get("must_change_password")),
            # None: every website.
            "sites": None if allowed is None else [
                {"site_id": site_id, "name": (sites.registry.get(site_id) or {}).get("name") or site_id}
                for site_id in allowed],
            "session_hours": settings.SESSION_TTL_HOURS}


@app.post("/api/v1/auth/password")
def auth_change_password(payload: PasswordChangePayload, request: Request):
    session = _cookie_user(request)
    if not session:
        raise HTTPException(status_code=401, detail="Cần đăng nhập")
    user = auth.find_user(session["username"], use_cache=False)
    if not user or not auth.verify_password(payload.current_password, user["password_hash"]):
        raise HTTPException(status_code=403, detail="Mật khẩu hiện tại không đúng")
    problem = auth.validate_new_password(payload.new_password, user["username"])
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    users = auth.get_users_collection()
    if users is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    new_hash = auth.hash_password(payload.new_password)
    users.update_one({"username_lower": user["username"].lower()},
                     {"$set": {"password_hash": new_hash, "must_change_password": False,
                               "password_changed_at": datetime.now(timezone.utc)}})
    auth.invalidate_user_cache(user["username"])
    ttl = settings.SESSION_TTL_HOURS * 3600
    response = JSONResponse({"status": "password_changed"}, headers={"Cache-Control": "no-store"})
    _set_session_cookie(response, request, auth.issue_session(user["username"], user.get("role", "viewer"), new_hash, ttl), ttl)
    return response


@app.get("/api/v1/telemetry/raw/{session_id}")
def get_raw_telemetry(session_id: str, user=Depends(require_read_access)):
    """
    Returns the raw telemetry data for a specific session, including mouse records.
    """
    _require_session_visible(user, session_id)
    from api_service.database import _sanitize_bson_value, get_db
    db = get_db()
    if db is not None:
        try:
            doc = db["detection_results"].find_one(
                {"sessionId": session_id},
                {"_id": 0, "sessionId": 1, "mouse_trajectory": 1, "fingerprint": 1, "botd": 1},
            )
        except Exception as exc:
            logger.warning("Raw telemetry query failed: %s", exc)
            raise HTTPException(status_code=503, detail="Database query failed")
        if doc:
            return {
                "sessionId": session_id,
                "mouse": {"records": doc.get("mouse_trajectory") or []},
                "fingerprint": _sanitize_bson_value(doc.get("fingerprint") or {}),
                "botd": _sanitize_bson_value(doc.get("botd") or {}),
                "raw_keys": list(doc.keys()),
            }
        raise HTTPException(status_code=404, detail="Session not found")

    with _telemetry_buffer_lock:
        buffered_events = list(telemetry_buffer)
    for ev in reversed(buffered_events):
        if ev.get("sessionId") == session_id:
            mouse = ev.get("mouse") or {}
            return {
                "sessionId": session_id,
                "mouse": mouse,
                "fingerprint": ev.get("fingerprint"),
                "botd": ev.get("botd"),
                "raw_keys": list(ev.keys()),
            }
    raise HTTPException(status_code=404, detail="Session not found")


@app.delete("/api/v1/sessions/{session_id}")
def delete_session(session_id: str, _admin=Depends(require_admin)):
    """Delete a specific detection session by sessionId."""
    from api_service.database import delete_session as db_delete
    success = db_delete(session_id)
    if success is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        research_deleted = delete_research_data(session_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Dataset deletion incomplete; retry") from exc
    removed_from_memory = _purge_session_from_memory(session_id)
    if success or removed_from_memory or research_deleted:
        return {"status": "deleted", "sessionId": session_id}
    raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


@app.delete("/api/v1/sessions")
def delete_all_sessions(
    site: Optional[str] = Query(default=None, pattern=sites.SITE_FILTER_PATTERN),
    _admin=Depends(require_admin),
):
    """Delete the sessions of one website (``site``, as the dashboard's website picker names it),
    or every session when no website is given."""
    if site:
        from api_service.database import delete_site_sessions
        ids = delete_site_sessions(sites.site_filter(site))
        if ids is None:
            raise HTTPException(status_code=503, detail="Database unavailable")
        try:
            delete_research_sessions(ids)
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Dataset deletion incomplete; retry") from exc
        _purge_sessions_from_memory(ids)
        return {"status": "deleted", "site": site, "count": len(ids)}
    from api_service.database import delete_all_sessions as db_delete_all
    count = db_delete_all()
    if count is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        research_deleted = delete_research_data()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Dataset deletion incomplete; retry") from exc
    _clear_in_memory_sessions()
    return {"status": "deleted", "count": max(count, research_deleted or 0)}


@app.get("/api/v1/touch-samples/stats")
def get_touch_sample_stats(user=Depends(require_read_access)):
    """Counts of stored phone/tablet gestures by weak label, device and kind."""
    _require_staff(user)
    from api_service.database import get_touch_sample_stats as db_stats
    stats = db_stats()
    if stats is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return {"capture_enabled": settings.TOUCH_CAPTURE_ENABLED,
            "retention_days": settings.TOUCH_RETENTION_DAYS, **stats}


@app.get("/api/v1/touch-samples/export")
def export_touch_samples(
    after: Optional[str] = Query(default=None, pattern=r"^[0-9a-f]{32}$"),
    label: Optional[str] = Query(default=None, pattern=r"^(human_candidate|automation|unlabeled)$"),
    limit: int = Query(default=500, ge=1, le=2000),
    _admin=Depends(require_admin),
):
    """Page through gesture samples for training (python -m core_ml.train_touch --live)."""
    from api_service.database import export_touch_samples as db_export
    page = db_export(after=after, label=label, limit=limit)
    if page is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return page


@app.delete("/api/v1/touch-samples")
def delete_touch_samples(_admin=Depends(require_admin)):
    from api_service.database import delete_touch_samples as db_delete
    count = db_delete()
    if count is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return {"status": "deleted", "count": count}


@app.get("/api/v1/live")
def get_live_view(
    window_minutes: int = Query(default=1440, ge=5, le=10080),
    site: Optional[str] = Query(default=None, pattern=sites.SITE_FILTER_PATTERN),
    country: Optional[str] = Query(default=None, pattern=COUNTRY_FILTER_PATTERN),
    user=Depends(require_read_access),
):
    """Recent traffic by location for the Live View globe (offline GeoIP, no external calls)."""
    from datetime import datetime, timedelta, timezone

    from api_service.database import get_live_sessions
    from api_service.live import build_live_view

    now = datetime.now(timezone.utc)
    rows = get_live_sessions(now - timedelta(minutes=window_minutes), site_filter=_monitor_scope(user, site, country))
    if rows is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return build_live_view(rows, now=now, window_minutes=window_minutes)


@app.get("/api/v1/live/online")
def get_live_online(site: Optional[str] = Query(default=None, pattern=sites.SITE_FILTER_PATTERN),
                    country: Optional[str] = Query(default=None, pattern=COUNTRY_FILTER_PATTERN),
                    user=Depends(require_read_access)):
    """Visitors on the site now (polled every few seconds; one indexed query over two minutes)."""
    from datetime import datetime, timedelta, timezone

    from api_service.database import get_online_sessions
    from api_service.live import ONLINE_SECONDS, build_online_view

    now = datetime.now(timezone.utc)
    rows = get_online_sessions(now - timedelta(seconds=ONLINE_SECONDS), site_filter=_monitor_scope(user, site, country))
    if rows is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return build_online_view(rows, now=now)


@app.get("/api/v1/stats/summary")
def get_stats_summary(site: Optional[str] = Query(default=None, pattern=sites.SITE_FILTER_PATTERN),
                      country: Optional[str] = Query(default=None, pattern=COUNTRY_FILTER_PATTERN),
                      user=Depends(require_read_access)):
    """Get aggregated detection statistics from MongoDB."""
    from api_service.database import get_db, get_summary_stats
    if get_db() is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    stats = get_summary_stats(site_filter=_monitor_scope(user, site, country))
    if stats is None:
        raise HTTPException(status_code=503, detail="Database query failed")
    return {**stats, "inference_latency": _inference_latency_summary()}


@app.get("/api/v1/stats/countries")
def get_stats_countries(site: Optional[str] = Query(default=None, pattern=sites.SITE_FILTER_PATTERN),
                        user=Depends(require_read_access)):
    """Countries of the stored sessions of a website, most sessions first (the country picker)."""
    from api_service.database import get_db
    db = get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    scope = _scope(user, site)
    detections = db["detection_results"]
    try:
        # A few dozen countries, each counted from an index (no scan of the sessions themselves).
        rows = [{"code": code or "_none", "sessions": detections.count_documents({**scope, "country_code": code})}
                for code in detections.distinct("country_code", scope)]
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database query failed") from exc
    countries = sorted((row for row in rows if row["sessions"]), key=lambda row: (-row["sessions"], row["code"]))
    return {"countries": countries}


@app.get("/api/v1/sessions/{session_id}/detail")
def get_session_detail(session_id: str, user=Depends(require_read_access)):
    """
    Returns comprehensive analysis detail for a specific session.
    Includes AI breakdown, fingerprint, botd detectors, mouse stats, and reasons.
    """
    _require_session_visible(user, session_id)
    from api_service.database import _sanitize_bson_value, get_db
    db = get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        doc = db["detection_results"].find_one(
            {"sessionId": session_id},
            {"_id": 0}
        )
    except Exception as exc:
        logger.warning("Session detail query failed: %s", exc)
        raise HTTPException(status_code=503, detail="Database query failed")
    if not doc:
        raise HTTPException(status_code=404, detail="Session not found")

    # Convert datetime objects
    for key in ["created_at", "updated_at"]:
        if key in doc and doc[key] and hasattr(doc[key], "timestamp"):
            doc[key] = int(doc[key].timestamp() * 1000)

    doc["mouse_trajectory"] = (doc.get("mouse_trajectory") or [])[:200]
    try:
        doc = enrich_sessions([doc])[0]
    except Exception:
        logger.warning("Research session metadata unavailable", exc_info=True)
    geoip.attach([doc])
    return _sanitize_bson_value(doc)


@app.get("/api/v1/research/traffic")
def research_traffic(
    limit: int = Query(default=50, ge=1, le=200),
    before_number: Optional[int] = Query(default=None, ge=1),
    site: Optional[str] = Query(default=None, pattern=sites.SITE_FILTER_PATTERN),
    verdict: Optional[Literal["bot", "suspect", "pending", "human"]] = Query(default=None),
    country: Optional[str] = Query(default=None, pattern=COUNTRY_FILTER_PATTERN),
    user=Depends(require_read_access),
):
    scope = _scope(user, site)
    try:
        page = traffic_page(limit, before_number, site_filter=scope, verdict=verdict, country=country)
    except Exception as exc:
        logger.exception("Traffic registry query failed")
        raise HTTPException(status_code=503, detail="Traffic registry unavailable") from exc
    geoip.attach(page.get("sessions"))
    page["geoip_attribution"] = geoip.ATTRIBUTION
    return page


class ManualLabelPayload(BaseModel):
    model_config = {"extra": "forbid"}
    label: Literal["BOT", "HUMAN", "UNKNOWN"]
    source: Literal["manual_review", "controlled_bot", "known_human", "provider_claim", "commercial_tool"]
    group_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    reviewer: str = Field(min_length=1, max_length=128)
    notes: str = Field(min_length=1, max_length=2000)
    confirmed: bool = Field(strict=True, default=False)
    expected_revision: int = Field(strict=True, ge=0)


@app.put("/api/v1/sessions/{session_id}/label")
def label_session(session_id: str, payload: ManualLabelPayload, _admin=Depends(require_admin)):
    annotation = payload.model_dump(exclude={"expected_revision"})
    if not annotation["reviewer"].strip() or not annotation["notes"].strip():
        raise HTTPException(status_code=422, detail="Reviewer and evidence notes are required")
    if ((payload.source == "controlled_bot" and payload.label == "HUMAN")
            or (payload.source == "known_human" and payload.label == "BOT")):
        raise HTTPException(status_code=422, detail="Label conflicts with its source")
    try:
        return set_manual_label(session_id, annotation, payload.expected_revision)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Manual label persistence failed")
        raise HTTPException(status_code=503, detail="Label storage unavailable; nothing acknowledged") from exc


# ---- Websites: the sites DATACAT monitors ----

class SiteCreatePayload(BaseModel):
    model_config = {"extra": "forbid"}
    name: str = Field(min_length=1, max_length=120)
    site_id: Optional[str] = Field(default=None, pattern=sites.SITE_ID_PATTERN)
    origins: List[str] = Field(min_length=1, max_length=sites.MAX_ORIGINS)
    contact: Optional[str] = Field(default=None, max_length=200)
    notes: Optional[str] = Field(default=None, max_length=2000)
    status: Literal["active", "paused"] = "active"
    platform: Optional[Literal["gtm", "wordpress", "shopify", "haravan", "sapo", "wix", "code", "nginx"]] = None


class SiteUpdatePayload(BaseModel):
    model_config = {"extra": "forbid"}
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    origins: Optional[List[str]] = Field(default=None, min_length=1, max_length=sites.MAX_ORIGINS)
    contact: Optional[str] = Field(default=None, max_length=200)
    notes: Optional[str] = Field(default=None, max_length=2000)
    status: Optional[Literal["active", "paused"]] = None
    platform: Optional[Literal["gtm", "wordpress", "shopify", "haravan", "sapo", "wix", "code", "nginx"]] = None


def _require_sites_db():
    db = _sites_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return db


def _collector_base(request: Request) -> str:
    if settings.PUBLIC_API_URL:
        return settings.PUBLIC_API_URL
    scheme = "https" if _is_https(request) else request.url.scheme
    return f"{scheme}://{request.headers.get('host') or request.url.netloc}"


@app.get("/api/v1/sites")
def list_sites(request: Request, user=Depends(require_read_access)):
    """Registered websites with their install state and the last 24 hours of traffic."""
    db = _require_sites_db()
    try:
        collector_base = _collector_base(request)
        view = sites.overview(db, collector_base=collector_base,
                              own_hosts=(_request_host(request), urlsplit(collector_base).hostname))
        allowed = _allowed_sites(user)
        if allowed is not None:
            empty = {"sessions": 0, "last_seen": None, "sessions_24h": 0, "humans_24h": 0, "bots_24h": 0,
                     "suspects_24h": 0}
            view.update(sites=[site for site in view["sites"] if site["site_id"] in allowed],
                        removed_sites=[], unassigned=empty, unregistered_origins=[])
        return view
    except Exception as exc:
        logger.exception("Site overview failed")
        raise HTTPException(status_code=503, detail="Database query failed") from exc


@app.post("/api/v1/sites", status_code=201)
def create_site(payload: SiteCreatePayload, request: Request, _admin=Depends(require_admin)):
    db = _require_sites_db()
    try:
        site = sites.create_site(db, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {**site, "snippet": sites.install_snippet(_collector_base(request), site["site_id"])}


@app.patch("/api/v1/sites/{site_id}")
def update_site(site_id: str, payload: SiteUpdatePayload, request: Request, _admin=Depends(require_admin)):
    db = _require_sites_db()
    try:
        site = sites.update_site(db, site_id, payload.model_dump(exclude_unset=True))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Site not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {**site, "snippet": sites.install_snippet(_collector_base(request), site["site_id"])}


@app.delete("/api/v1/sites/{site_id}")
def delete_site(site_id: str, _admin=Depends(require_admin)):
    """Remove a site from the registry. Its sessions stay; its pages are no longer accepted
    unless their origin is also in the server's allowlist."""
    if not sites.delete_site(_require_sites_db(), site_id):
        raise HTTPException(status_code=404, detail="Site not found")
    return {"status": "deleted", "site_id": site_id}


# ---- Reports: one website (or all) over a period ----

def _report_scope(user: Optional[dict], site: Optional[str], days: int):
    from api_service import reports
    if days not in reports.PERIOD_DAYS:
        raise HTTPException(status_code=422, detail="days must be 1, 7 or 30")
    from api_service.database import get_db
    db = get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return reports, db, _scope(user, site)


@app.get("/api/v1/reports/summary")
def report_summary(
    days: int = Query(default=7),
    site: Optional[str] = Query(default=None, pattern=sites.SITE_FILTER_PATTERN),
    utc_offset_minutes: int = Query(default=420, ge=-720, le=840),
    user=Depends(require_read_access),
):
    """Totals, reasons and bot sources of the sessions that started in the period, the period
    before for comparison, and per-day (per-hour) counts in the reader's time zone."""
    reports, db, scope = _report_scope(user, site, days)
    try:
        report = reports.summary(db, site_filter=scope, days=days, utc_offset_minutes=utc_offset_minutes)
        # What the report was made with, for its document control block.
        report["generated_at"] = datetime.now(timezone.utc).isoformat()
        report["decision_policy_version"] = DECISION_POLICY_VERSION
        report["model_bundle_id"] = model_bundle_id
        return report
    except Exception as exc:
        logger.exception("Report summary failed")
        raise HTTPException(status_code=503, detail="Database query failed") from exc


@app.get("/api/v1/reports/sessions")
def report_sessions(
    days: int = Query(default=7),
    site: Optional[str] = Query(default=None, pattern=sites.SITE_FILTER_PATTERN),
    user=Depends(require_read_access),
):
    """Sessions of the period for the CSV export (the dashboard builds the file)."""
    reports, db, scope = _report_scope(user, site, days)
    try:
        return reports.sessions(db, site_filter=scope, days=days)
    except Exception as exc:
        logger.exception("Report export failed")
        raise HTTPException(status_code=503, detail="Database query failed") from exc


@app.get("/api/v1/reports/clicks")
def report_clicks(
    days: int = Query(default=7),
    site: Optional[str] = Query(default=None, pattern=sites.SITE_FILTER_PATTERN),
    verdict: Optional[Literal["bot", "suspect", "human", "insufficient"]] = Query(default=None),
    q: Optional[str] = Query(default=None, pattern=r"^[A-Za-z0-9._~:@+-]{1,128}$"),
    page: int = Query(default=1, ge=1, le=10000),
    user=Depends(require_read_access),
):
    """Every ad click of the period (Click ID, Token 1) with its verdict, 50 a page."""
    reports, db, scope = _report_scope(user, site, days)
    try:
        return reports.clicks_page(db, site_filter=scope, days=days, verdict=verdict, query=q, page=page)
    except Exception as exc:
        logger.exception("Click report failed")
        raise HTTPException(status_code=503, detail="Database query failed") from exc


@app.get("/api/v1/reference/fingerprint")
def fingerprint_reference(
    days: int = Query(default=30),
    site: Optional[str] = Query(default=None, pattern=sites.SITE_FILTER_PATTERN),
    user=Depends(require_read_access),
):
    """DATACAT versus Fingerprint bot detection on the sampled sessions of the period, and the
    sessions where they disagree (api_service.reference). A comparison, not an accuracy."""
    from datetime import timedelta

    _reports, db, scope = _report_scope(user, site, days)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        return {
            "enabled": reference.enabled(),
            "sample_rate": settings.FINGERPRINT_SAMPLE_RATE if reference.enabled() else 0,
            "days": days,
            **reference.report(db, site_filter=scope, since=since),
            "review": {kind: reference.disagreements(db, kind, site_filter=scope, since=since, limit=30)
                       for kind in reference.DISAGREEMENTS},
        }
    except Exception as exc:
        logger.exception("Fingerprint reference report failed")
        raise HTTPException(status_code=503, detail="Database query failed") from exc


@app.get("/api/v1/clicks/{click_id}")
def click_verdict(
    click_id: str = PathParam(pattern=clicks.CLICK_VALUE_PATTERN),
    user=Depends(require_read_access),
):
    """Person or bot for one ad click (the ``clickid`` of its landing URL), and the source it came from."""
    from api_service.database import get_db
    db = get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        rows = list(db["detection_results"].find(
            {**_scope(user, None), "click_id": click_id},
            {"_id": 0, "sessionId": 1, "site_id": 1, "click_source": 1, "verdict": 1, "decision_state": 1,
             "breakdown.decision_deferred": 1, "breakdown.decision_basis": 1, "breakdown.automation_rule": 1,
             "created_at": 1, "updated_at": 1},
        ).sort("created_at", -1).limit(20))
    except Exception as exc:
        logger.exception("Click lookup failed")
        raise HTTPException(status_code=503, detail="Database query failed") from exc
    if not rows:
        raise HTTPException(status_code=404, detail="Click not found")

    def outcome(row):
        deferred = row.get("decision_state") == "INSUFFICIENT_EVIDENCE" or (row.get("breakdown") or {}).get("decision_deferred")
        return "INSUFFICIENT_EVIDENCE" if deferred else str(row.get("verdict") or "SUSPECT")

    sessions = [{"sessionId": row.get("sessionId"), "site_id": row.get("site_id"), "verdict": outcome(row),
                 "decision_basis": (row.get("breakdown") or {}).get("decision_basis"),
                 "automation_rule": (row.get("breakdown") or {}).get("automation_rule"),
                 "created_at": _iso(row.get("created_at")), "updated_at": _iso(row.get("updated_at"))} for row in rows]
    # A click whose page was opened twice is a bot if any of its sessions is.
    verdicts = {session["verdict"] for session in sessions}
    verdict = next((v for v in ("BOT", "SUSPECT", "HUMAN") if v in verdicts), "INSUFFICIENT_EVIDENCE")
    return {"click_id": click_id, "click_source": rows[0].get("click_source"), "verdict": verdict, "sessions": sessions}


def _iso(value):
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()
    return None


# ---- Accounts: who may sign in to the dashboard, and what they see ----

class UserCreatePayload(BaseModel):
    model_config = {"extra": "forbid"}
    username: str = Field(min_length=3, max_length=64)
    role: Literal["admin", "viewer", "customer"]
    sites: List[str] = Field(default_factory=list, max_length=200)
    display_name: str = Field(default="", max_length=80)


class UserUpdatePayload(BaseModel):
    model_config = {"extra": "forbid"}
    role: Optional[Literal["admin", "viewer", "customer"]] = None
    sites: Optional[List[str]] = Field(default=None, max_length=200)
    display_name: Optional[str] = Field(default=None, max_length=80)
    disabled: Optional[bool] = None


def _user_out(user: dict) -> dict:
    out = {key: value for key, value in user.items() if key not in ("password_hash", "username_lower")}
    for key in ("created_at", "last_login_at", "password_changed_at"):
        value = out.get(key)
        if isinstance(value, datetime):
            out[key] = int((value if value.tzinfo else value.replace(tzinfo=timezone.utc)).timestamp() * 1000)
    out["sites"] = list(out.get("sites") or [])
    return out


def _check_sites(site_ids) -> None:
    unknown = [site_id for site_id in site_ids or [] if not sites.registry.get(site_id)]
    if unknown:
        raise HTTPException(status_code=422, detail="Website không tồn tại: " + ", ".join(unknown))


def _same_account(admin: dict, username: str) -> bool:
    return admin.get("username", "").lower() == username.lower()


def _account_call(fn, *args):
    try:
        return fn(*args)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc


@app.get("/api/v1/users")
def list_accounts(_admin=Depends(require_admin)):
    return {"users": [_user_out(user) for user in _account_call(auth.list_users)]}


@app.post("/api/v1/users", status_code=201)
def create_account(payload: UserCreatePayload, _admin=Depends(require_admin)):
    """New account with a temporary password, returned once; its owner must change it."""
    _check_sites(payload.sites)
    if auth.find_user(payload.username, use_cache=False):
        raise HTTPException(status_code=409, detail="Tên đăng nhập đã tồn tại")
    password = auth.generate_password()
    try:
        _account_call(lambda: auth.create_user(
            payload.username, password, payload.role, sites=payload.sites,
            display_name=payload.display_name, must_change_password=True))
    except HTTPException:
        raise
    except Exception as exc:
        # A concurrent request created the same name (unique index).
        raise HTTPException(status_code=409, detail="Tên đăng nhập đã tồn tại") from exc
    user = auth.find_user(payload.username, use_cache=False)
    return {"user": _user_out(user), "password": password}


@app.patch("/api/v1/users/{username}")
def update_account(username: str, payload: UserUpdatePayload, admin=Depends(require_admin)):
    target = auth.find_user(username, use_cache=False)
    if not target:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản")
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("sites") is not None:
        _check_sites(changes["sites"])
    leaves_admin = target.get("role") == "admin" and (
        changes.get("role") not in (None, "admin") or changes.get("disabled") is True)
    if leaves_admin and _same_account(admin, username):
        raise HTTPException(status_code=409, detail="Không thể tự hạ quyền hoặc khóa chính mình")
    if leaves_admin and _account_call(auth.active_admins, username) == 0:
        raise HTTPException(status_code=409, detail="Phải còn ít nhất một quản trị viên đang hoạt động")
    return {"user": _user_out(_account_call(auth.update_user, username, changes))}


@app.post("/api/v1/users/{username}/reset-password")
def reset_account_password(username: str, admin=Depends(require_admin)):
    """New temporary password (shown once); the account's open sessions end."""
    if _same_account(admin, username):
        raise HTTPException(status_code=409, detail="Đổi mật khẩu của chính mình ở trang Tài khoản")
    return {"username": username, "password": _account_call(auth.reset_password, username)}


@app.delete("/api/v1/users/{username}")
def delete_account(username: str, admin=Depends(require_admin)):
    target = auth.find_user(username, use_cache=False)
    if not target:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản")
    if _same_account(admin, username):
        raise HTTPException(status_code=409, detail="Không thể xóa chính mình")
    if target.get("role") == "admin" and _account_call(auth.active_admins, username) == 0:
        raise HTTPException(status_code=409, detail="Phải còn ít nhất một quản trị viên đang hoạt động")
    _account_call(auth.delete_user, username)
    return {"status": "deleted", "username": username}
