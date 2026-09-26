"""
FastAPI Inference & Telemetry Collection Server
Serves real-time bot detection inference using the trained Multi-Modal Ensemble
and provides endpoints for telemetry ingestion and operational analysis.
"""

import asyncio
import collections
import ipaddress
import json
import logging
import math
import os
import secrets
import threading
import time
from contextlib import asynccontextmanager, suppress
from typing import Optional, Dict, Any
from fastapi import BackgroundTasks, Depends, FastAPI, Request, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from api_service.config import settings
from core_ml.models.behavioral_lstm import MouseTrajectoryLSTM
from core_ml.models.tabular_classifier import TabularBotClassifier
from core_ml.models.ensemble import DECISION_POLICY_VERSION, EnsembleBotDetector
from core_ml.model_bundle import ModelBundleError, release_evidence_valid, verify_model_bundle
from core_ml.features.env_features import FEATURE_NAMES as ENV_FEATURE_NAMES
from core_ml.features.mouse_features import STATISTICAL_FEATURE_NAMES


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
    maintenance_task = asyncio.create_task(_maintenance_loop())
    try:
        yield
    finally:
        maintenance_task.cancel()
        with suppress(asyncio.CancelledError):
            await maintenance_task
        try:
            # Persist anything that arrived during a transient outage before a
            # rolling deployment removes this process.
            await run_in_threadpool(_flush_telemetry_buffer)
        finally:
            from api_service.database import close_database

            await run_in_threadpool(close_database)


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Bot detection using browser heuristics, mouse dynamics, and tabular ML",
    version=settings.VERSION,
    lifespan=app_lifespan,
)

app.add_middleware(RequestBodyLimitMiddleware, max_bytes=settings.MAX_PAYLOAD_BYTES)

# Enable CORS for local development and cloud deployments
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials="*" not in settings.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
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
)

# Small best-effort cache for requests received while MongoDB is unavailable.
telemetry_buffer = collections.deque(maxlen=settings.MAX_BUFFER_SIZE)
_telemetry_buffer_lock = threading.Lock()
_telemetry_buffer_stats = {"dropped_total": 0}
_telemetry_replay_inflight = 0
_telemetry_flush_lock = threading.Lock()
_health_cache_lock = threading.Lock()
_health_cache = {"checked_at": 0.0, "database": False, "inference_ready": False}

# Sliding-window rate limiter per client IP
_rate_limit_lock = threading.Lock()
_rate_limit_records = collections.defaultdict(list)


async def _maintenance_loop():
    """Retry buffered persistence independently of incoming request traffic."""
    while True:
        await asyncio.sleep(settings.MAINTENANCE_INTERVAL_SECONDS)
        try:
            await run_in_threadpool(_flush_telemetry_buffer)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Telemetry maintenance iteration failed")


def _purge_session_from_memory(session_id: str) -> bool:
    """Remove a session from best-effort caches after an administrative delete."""
    with _telemetry_buffer_lock:
        retained = [event for event in telemetry_buffer if event.get("sessionId") != session_id]
        removed_from_buffer = len(retained) != len(telemetry_buffer)
        telemetry_buffer.clear()
        telemetry_buffer.extend(retained)
    return removed_from_buffer


def _clear_in_memory_sessions():
    with _telemetry_buffer_lock:
        telemetry_buffer.clear()


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
    """Buffer telemetry without evicting an event already acknowledged to a client."""
    buffered_data = dict(data)
    if analysis is not None:
        # Reuse the decision already returned for this event. Re-running the
        # model during database recovery wastes CPU and can change the verdict.
        buffered_data["_buffered_analysis"] = dict(analysis)
    with _telemetry_buffer_lock:
        if len(telemetry_buffer) + _telemetry_replay_inflight >= telemetry_buffer.maxlen:
            return False
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


def _flush_telemetry_buffer(max_events: Optional[int] = None):
    """Persist a bounded batch after MongoDB recovers without duplicate flushers."""
    global _telemetry_replay_inflight
    if not _telemetry_flush_lock.acquire(blocking=False):
        return
    try:
        from api_service.database import (
            DatabaseIngestionPaused,
            is_database_ready,
            save_detection_result,
        )

        with _telemetry_buffer_lock:
            pending_count = len(telemetry_buffer)
        replay_count = pending_count if max_events is None else min(pending_count, max(0, max_events))

        for _ in range(replay_count):
            with _telemetry_buffer_lock:
                if not telemetry_buffer:
                    break
                data = telemetry_buffer.popleft()
                _telemetry_replay_inflight += 1

            try:
                analysis = data.pop("_buffered_analysis", None)
                if not isinstance(analysis, dict):
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
                        continue
                else:
                    _attach_model_metadata(analysis)

                data.pop("_replay_attempts", None)
                try:
                    persisted = bool(save_detection_result(data, analysis))
                except DatabaseIngestionPaused:
                    # An admin delete intentionally invalidates old replay data.
                    continue
                except Exception:
                    logger.exception("Buffered telemetry persistence failed")
                    data["_buffered_analysis"] = analysis
                    _requeue_buffered_event(data)
                    break

                if persisted:
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


class TelemetryPayload(BaseModel):
    sessionId: Optional[str] = Field(default=None, max_length=128)
    visitorId: Optional[str] = Field(default=None, max_length=128)
    action: Optional[str] = Field(default="telemetry", max_length=64)
    timestamp: Optional[int] = None
    sequence: Optional[int] = Field(default=None, ge=0, le=999999)
    pageUrl: Optional[str] = Field(default=None, max_length=2048)
    referrer: Optional[str] = Field(default=None, max_length=2048)
    fingerprint: Optional[Dict[str, Any]] = None
    botd: Optional[Dict[str, Any]] = None
    mouse: Optional[Dict[str, Any]] = None


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


def require_admin(request: Request):
    if not settings.ADMIN_TOKEN:
        raise HTTPException(status_code=503, detail="Admin API is disabled until BOT_ADMIN_TOKEN is configured")
    supplied = request.headers.get("X-Admin-Token", "")
    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    if not supplied or not secrets.compare_digest(supplied, settings.ADMIN_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid admin token")


def require_read_access(request: Request):
    if not settings.READ_TOKEN:
        raise HTTPException(status_code=503, detail="Monitoring API is disabled until BOT_READ_TOKEN is configured")
    supplied = request.headers.get("X-Read-Token", "")
    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    valid_read = bool(supplied) and secrets.compare_digest(supplied, settings.READ_TOKEN)
    valid_admin = bool(settings.ADMIN_TOKEN and supplied) and secrets.compare_digest(supplied, settings.ADMIN_TOKEN)
    if not valid_read and not valid_admin:
        raise HTTPException(status_code=401, detail="Invalid read token")


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
                    probe_records = [
                        {"time": index * 16, "x": index / 100, "y": 0.2, "type": "move"}
                        for index in range(25)
                    ]
                    probe = ensemble_detector.predict({"mouse": {"records": probe_records}})
                    probability = float(probe.get("bot_probability"))
                    runtime_ready = math.isfinite(probability) and 0.0 <= probability <= 1.0
                except Exception:
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
    client_ip = get_client_ip(request)
    if not check_rate_limit(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Too many requests from this IP.",
            headers={"Retry-After": "60"},
        )
    _require_inference_models()
    data = payload.model_dump()

    start_t = time.perf_counter()
    try:
        result = await run_in_threadpool(ensemble_detector.predict, data)
    except Exception as exc:
        logger.exception("Detection inference failed")
        raise HTTPException(status_code=503, detail="Inference temporarily unavailable") from exc

    latency_ms = round((time.perf_counter() - start_t) * 1000, 2)

    _attach_model_metadata(result)
    result["latency_ms"] = latency_ms
    result["client_ip"] = client_ip
    result["sessionId"] = data.get("sessionId")
    result["visitorId"] = data.get("visitorId")

    return result


@app.post("/api/v1/telemetry")
async def receive_telemetry(request: Request, background_tasks: BackgroundTasks):
    """
    Asynchronous telemetry ingestion endpoint (e.g. from navigator.sendBeacon).
    Accepts application/json, text/plain (beacons), and raw JSON payloads.
    """
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
    if not data.get("visitorId"):
        raise HTTPException(status_code=422, detail="visitorId is required")

    _require_inference_models()

    data["client_ip"] = client_ip
    data["received_at"] = int(time.time() * 1000)

    # Run AI analysis before persistence. Model failures are not database
    # outages and must not fill the persistence retry buffer with poison data.
    try:
        analysis = await run_in_threadpool(ensemble_detector.predict, data)
        _attach_model_metadata(analysis)
    except Exception as exc:
        logger.exception("Telemetry inference failed")
        raise HTTPException(status_code=503, detail="Inference temporarily unavailable") from exc

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

    return {
        "status": "success" if persisted else "degraded",
        "recorded": persisted or buffered,
        "persisted": persisted,
        "buffered": buffered,
        "model_bundle_id": model_bundle_id,
    }


@app.get("/api/v1/telemetry/recent")
def get_recent_telemetry(limit: int = Query(default=50, ge=1, le=200), _read=Depends(require_read_access)):
    """
    Returns the most recent detection sessions from MongoDB.
    Single source of truth — no fallback to in-memory buffer.
    """
    from api_service.database import get_db, get_recent_results, get_total_count
    if get_db() is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    results = get_recent_results(limit=limit)
    total = get_total_count()
    if results is None or total is None:
        raise HTTPException(status_code=503, detail="Database query failed")

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
    window_minutes: int = Query(default=60, ge=30, le=1440),
    _read=Depends(require_read_access),
):
    """Return session counts using buckets sized for the requested window."""
    from api_service.database import get_traffic_timeline as query_traffic_timeline

    if window_minutes <= 60:
        bucket_minutes = 1
    elif window_minutes <= 120:
        bucket_minutes = 2
    elif window_minutes <= 360:
        bucket_minutes = 5
    elif window_minutes <= 720:
        bucket_minutes = 10
    else:
        bucket_minutes = 15

    timeline = query_traffic_timeline(
        window_minutes=window_minutes,
        bucket_minutes=bucket_minutes,
    )
    if timeline is None:
        raise HTTPException(status_code=503, detail="Traffic timeline query failed")
    return timeline


@app.get("/bot-collector.js")
def get_bot_collector_sdk():
    """
    Serves the pre-compiled BotCollector standalone UMD bundle for proxy injection.
    """
    dist_path = os.path.join(os.path.dirname(__file__), "..", "collector", "dist", "bot-collector.js")
    dist_path = os.path.abspath(dist_path)
    if os.path.exists(dist_path):
        return FileResponse(
            dist_path,
            media_type="application/javascript",
            headers={"Cache-Control": "public, no-cache"},
        )
    raise HTTPException(status_code=404, detail="Collector SDK bundle not found.")


@app.get("/dashboard", response_class=HTMLResponse)
def get_dashboard():
    """
    Serves the real-time SOC Monitoring Dashboard for Bot Detection.
    """
    dashboard_path = os.path.join(os.path.dirname(__file__), "dashboard.html")
    dashboard_path = os.path.abspath(dashboard_path)
    if os.path.exists(dashboard_path):
        with open(dashboard_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read(), status_code=200)
    raise HTTPException(status_code=404, detail="Dashboard not found.")


@app.get("/api/v1/telemetry/raw/{session_id}")
def get_raw_telemetry(session_id: str, _read=Depends(require_read_access)):
    """
    Returns the raw telemetry data for a specific session, including mouse records.
    """
    from api_service.database import get_db, _sanitize_bson_value
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
    removed_from_memory = _purge_session_from_memory(session_id)
    if success or removed_from_memory:
        return {"status": "deleted", "sessionId": session_id}
    raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


@app.delete("/api/v1/sessions")
def delete_all_sessions(_admin=Depends(require_admin)):
    """Delete all detection sessions from the database."""
    from api_service.database import delete_all_sessions as db_delete_all
    count = db_delete_all()
    if count is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    _clear_in_memory_sessions()
    return {"status": "deleted", "count": count}


@app.get("/api/v1/stats/summary")
def get_stats_summary(_read=Depends(require_read_access)):
    """Get aggregated detection statistics from MongoDB."""
    from api_service.database import get_db, get_summary_stats
    if get_db() is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    stats = get_summary_stats()
    if stats is None:
        raise HTTPException(status_code=503, detail="Database query failed")
    return stats


@app.get("/api/v1/sessions/{session_id}/detail")
def get_session_detail(session_id: str, _read=Depends(require_read_access)):
    """
    Returns comprehensive analysis detail for a specific session.
    Includes AI breakdown, fingerprint, botd detectors, mouse stats, and reasons.
    """
    from api_service.database import get_db, _sanitize_bson_value
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
    return _sanitize_bson_value(doc)
