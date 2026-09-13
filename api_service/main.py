"""
FastAPI Inference & Telemetry Collection Server
Serves real-time bot detection inference using the trained Multi-Modal Ensemble
and provides endpoints for telemetry ingestion & graph analysis.
"""

import json
import os
import time
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from api_service.config import settings
from core_ml.models.behavioral_lstm import MouseTrajectoryLSTM
from core_ml.models.tabular_classifier import TabularBotClassifier
from core_ml.models.ensemble import EnsembleBotDetector
from core_ml.features.graph_builder import ClickFraudGraphBuilder
from core_ml.models.gnn_detector import HeteroClickFraudGNN

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Multi-Modal Bot Detection combining FingerprintJS, BotD, DELBOT-Mouse, and Graph Neural Networks",
    version=settings.VERSION,
)

# Enable CORS for local development and cloud deployments
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global model holders
weights_dir = settings.WEIGHTS_DIR
lstm_weights_path = os.path.join(weights_dir, "behavioral_lstm.pt")
tabular_weights_path = os.path.join(weights_dir, "tabular_model.joblib")
gnn_weights_path = os.path.join(weights_dir, "gnn_model.pt")

lstm_model = MouseTrajectoryLSTM()
lstm_model.load_weights(lstm_weights_path)

tabular_model = TabularBotClassifier()
tabular_model.load(tabular_weights_path)

gnn_model = HeteroClickFraudGNN()
gnn_model.load_model(gnn_weights_path)

ensemble_detector = EnsembleBotDetector(
    lstm_model=lstm_model,
    tabular_model=tabular_model,
    threshold=settings.THRESHOLD,
)
graph_builder = ClickFraudGraphBuilder(max_sessions=settings.MAX_GRAPH_SESSIONS)

import collections
import threading

# Thread-safe in-memory ring buffer for recent telemetry events
telemetry_buffer = collections.deque(maxlen=settings.MAX_BUFFER_SIZE)

# Sliding-window rate limiter per client IP
_rate_limit_lock = threading.Lock()
_rate_limit_records = collections.defaultdict(list)


def check_rate_limit(client_ip: str) -> bool:
    """Returns True if within rate limit, False if rate limit exceeded."""
    if settings.RATE_LIMIT_PER_MINUTE <= 0:
        return True
    now = time.time()
    cutoff = now - 60.0
    with _rate_limit_lock:
        timestamps = _rate_limit_records[client_ip]
        valid_ts = [t for t in timestamps if t > cutoff]
        if len(valid_ts) >= settings.RATE_LIMIT_PER_MINUTE:
            _rate_limit_records[client_ip] = valid_ts
            return False
        valid_ts.append(now)
        _rate_limit_records[client_ip] = valid_ts
        if len(_rate_limit_records) > 10000:
            stale_keys = [k for k, v in _rate_limit_records.items() if not v or v[-1] <= cutoff]
            for k in stale_keys:
                del _rate_limit_records[k]
            if len(_rate_limit_records) > 10000:
                _rate_limit_records.clear()
        return True


class TelemetryPayload(BaseModel):
    sessionId: Optional[str] = None
    visitorId: Optional[str] = None
    action: Optional[str] = "telemetry"
    timestamp: Optional[int] = None
    pageUrl: Optional[str] = None
    referrer: Optional[str] = None
    fingerprint: Optional[Dict[str, Any]] = None
    botd: Optional[Dict[str, Any]] = None
    mouse: Optional[Dict[str, Any]] = None


def get_client_ip(request: Request) -> str:
    """
    Extract real client IP address, honoring reverse proxy headers
    (Cloudflare, Nginx, AWS ALB, Traefik, Docker).
    """
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip.strip()
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    x_real = request.headers.get("X-Real-IP")
    if x_real:
        return x_real.strip()
    return request.client.host if request.client else "127.0.0.1"


@app.get("/")
def index():
    stats = graph_builder.get_stats()
    return {
        "status": "online",
        "service": "Bot Detection Core",
        "models": {
            "behavioral_lstm": "ready",
            "tabular_xgboost": "ready" if tabular_model.is_fitted else "fallback_heuristic",
            "hetero_gnn": "ready",
        },
        "graph_node_counts": {
            "devices": stats["device_count"],
            "ips": stats["ip_count"],
            "sessions": stats["session_count"],
        },
    }


@app.get("/health")
@app.get("/healthz")
def health_check():
    """Standard health check endpoint for load balancers and container orchestrators."""
    return {
        "status": "healthy",
        "timestamp": int(time.time() * 1000),
        "models_loaded": {
            "tabular": tabular_model.is_fitted,
            "lstm": True,
            "gnn": True,
        }
    }


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
    data = payload.model_dump()

    start_t = time.perf_counter()
    try:
        result = ensemble_detector.predict(data)
    except Exception as e:
        result = {
            "is_bot": False,
            "verdict": "SUSPECT",
            "bot_probability": 0.50,
            "confidence": 0.0,
            "reasons": [f"Server processing fallback: {type(e).__name__}"],
            "breakdown": {
                "behavioral_lstm_score": 0.5,
                "tabular_score": 0.5,
                "heuristic_score": 0.0,
                "has_enough_mouse_data": False,
                "mouse_points": 0,
            },
        }

    latency_ms = round((time.perf_counter() - start_t) * 1000, 2)

    # Ingest into graph builder (label=-1 unknown, not the model's own prediction)
    try:
        graph_builder.add_telemetry_event(data, ip_address=client_ip, is_bot_ground_truth=None)
    except Exception:
        pass

    result["latency_ms"] = latency_ms
    result["client_ip"] = client_ip
    result["sessionId"] = data.get("sessionId")
    result["visitorId"] = data.get("visitorId")

    return result


@app.post("/api/v1/telemetry")
async def receive_telemetry(request: Request):
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
        data = await request.json()
    except Exception:
        try:
            body_bytes = await request.body()
            data = json.loads(body_bytes.decode("utf-8", errors="ignore")) if body_bytes else {}
        except Exception:
            data = {}

    if not isinstance(data, dict):
        data = {}

    data["client_ip"] = client_ip
    data["received_at"] = int(time.time() * 1000)

    # Thread-safe ring buffer auto-evicts oldest item when maxlen reached
    telemetry_buffer.append(data)

    # Auto-add to evolving graph
    try:
        graph_builder.add_telemetry_event(data, ip_address=client_ip)
    except Exception:
        pass

    return {"status": "success", "recorded": True}


@app.get("/api/v1/graph/stats")
def get_graph_stats():
    """
    Returns graph topology statistics and fraud ring indicators.
    """
    return graph_builder.get_stats()


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
            headers={"Cache-Control": "public, max-age=3600"},
        )
    raise HTTPException(status_code=404, detail="Collector SDK bundle not found.")

