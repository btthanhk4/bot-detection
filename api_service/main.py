"""
FastAPI Inference & Telemetry Collection Server
Serves real-time bot detection inference using the trained Multi-Modal Ensemble
and provides endpoints for telemetry ingestion & graph analysis.
"""

import os
import time
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core_ml.models.behavioral_lstm import MouseTrajectoryLSTM
from core_ml.models.tabular_classifier import TabularBotClassifier
from core_ml.models.ensemble import EnsembleBotDetector
from core_ml.features.graph_builder import ClickFraudGraphBuilder
from core_ml.models.gnn_detector import HeteroClickFraudGNN

app = FastAPI(
    title="Silkmoon Bot & Fraud Detection Core API",
    description="Multi-Modal Bot Detection combining FingerprintJS, BotD, DELBOT-Mouse, and Graph Neural Networks",
    version="1.0.0",
)

# Enable CORS for local development and cloud deployments
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global model holders
weights_dir = os.path.join(os.path.dirname(__file__), "..", "core_ml", "weights")
lstm_weights_path = os.path.join(weights_dir, "behavioral_lstm.pt")
tabular_weights_path = os.path.join(weights_dir, "tabular_model.joblib")
gnn_weights_path = os.path.join(weights_dir, "gnn_model.pt")

lstm_model = MouseTrajectoryLSTM()
lstm_model.load_weights(lstm_weights_path)

tabular_model = TabularBotClassifier()
tabular_model.load(tabular_weights_path)

gnn_model = HeteroClickFraudGNN()
gnn_model.load_model(gnn_weights_path)

ensemble_detector = EnsembleBotDetector(lstm_model=lstm_model, tabular_model=tabular_model)
graph_builder = ClickFraudGraphBuilder()

# In-memory telemetry log buffer (last 500 requests)
telemetry_buffer: List[Dict[str, Any]] = []


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


@app.get("/")
def index():
    return {
        "status": "online",
        "service": "Bot Detection Core",
        "models": {
            "behavioral_lstm": "ready",
            "tabular_xgboost": "ready" if tabular_model.is_fitted else "fallback_heuristic",
            "hetero_gnn": "ready",
        },
        "graph_node_counts": {
            "devices": len(graph_builder.device_map),
            "ips": len(graph_builder.ip_map),
            "sessions": len(graph_builder.session_map),
        },
    }


@app.post("/api/v1/detect")
async def detect_bot(payload: TelemetryPayload, request: Request):
    """
    Real-time bot classification endpoint.
    Fuses mouse dynamics, environment fingerprint, and heuristic checks.
    """
    client_ip = request.client.host if request.client else "127.0.0.1"
    data = payload.model_dump()

    start_t = time.perf_counter()
    result = ensemble_detector.predict(data)
    latency_ms = round((time.perf_counter() - start_t) * 1000, 2)

    # Ingest into graph builder (label=-1 unknown, not the model's own prediction)
    graph_builder.add_telemetry_event(data, ip_address=client_ip, is_bot_ground_truth=None)

    result["latency_ms"] = latency_ms
    result["client_ip"] = client_ip
    result["sessionId"] = data.get("sessionId")
    result["visitorId"] = data.get("visitorId")

    return result


@app.post("/api/v1/telemetry")
async def receive_telemetry(payload: TelemetryPayload, request: Request):
    """
    Asynchronous telemetry ingestion endpoint (e.g. from navigator.sendBeacon).
    """
    client_ip = request.client.host if request.client else "127.0.0.1"
    data = payload.model_dump()
    data["client_ip"] = client_ip
    data["received_at"] = int(time.time() * 1000)

    telemetry_buffer.append(data)
    if len(telemetry_buffer) > 1000:
        telemetry_buffer.pop(0)

    # Auto-add to evolving graph
    graph_builder.add_telemetry_event(data, ip_address=client_ip)

    return {"status": "success", "recorded": True}


@app.get("/api/v1/graph/stats")
def get_graph_stats():
    """
    Returns graph topology statistics and fraud ring indicators.
    """
    device_cnt = len(graph_builder.device_map)
    ip_cnt = len(graph_builder.ip_map)
    session_cnt = len(graph_builder.session_map)

    # Detect devices using multiple IPs (IP rotation / proxy anomaly)
    # or IPs hosting an unusually large number of distinct devices (device farm)
    return {
        "device_count": device_cnt,
        "ip_count": ip_cnt,
        "session_count": session_cnt,
        "edges_count": len(graph_builder.edges_device_session) + len(graph_builder.edges_session_ip),
        "suspected_coordinated_rings": 1 if (session_cnt > 10 and device_cnt < session_cnt * 0.3) else 0,
    }
