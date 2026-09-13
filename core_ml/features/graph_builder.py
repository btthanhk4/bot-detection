"""
Graph Construction Module for Click Fraud & Botnet Detection (Production-Ready v3)
Constructs Multi-relational / Heterogeneous Graphs connecting:
- Device (visitorId from FingerprintJS)
- IP Address (client IP / subnet)
- Session (user browsing session)
- Target (product / ad click target)

Edges represent behavioral and network interactions.
Features:
- Deterministic MD5 hashing (reproducible across processes)
- Single source of truth for session features (STATISTICAL_FEATURE_NAMES)
- Sliding window / bounded capacity to prevent production memory leaks
- Full None/malformed payload safety
"""

import hashlib
import threading
import numpy as np
import torch
from core_ml.features.env_features import extract_env_vector, FEATURE_NAMES as ENV_FEATURE_NAMES
from core_ml.features.mouse_features import (
    compute_statistical_features,
    extract_mouse_stat_vector,
    STATISTICAL_FEATURE_NAMES,
)


# ---- Node feature dimensions (single source of truth) ----
SESSION_FEATURE_KEYS = list(STATISTICAL_FEATURE_NAMES)
# +2 extra: heuristic_score, record_count
SESSION_FEATURE_DIM = len(SESSION_FEATURE_KEYS) + 2

IP_FEATURE_DIM = 3       # [ip_hash, is_private, request_count]
TARGET_FEATURE_DIM = 2    # [url_hash, visit_count]


def _deterministic_hash_feature(text: str, modulo: int = 1000) -> float:
    """Produces a deterministic float in [0.0, 1.0) for a given string across any process run."""
    if not text:
        return 0.0
    md5_int = int(hashlib.md5(str(text).encode("utf-8", errors="ignore")).hexdigest()[:8], 16)
    return float(md5_int % modulo) / float(modulo)


class ClickFraudGraphBuilder:
    def __init__(self, max_sessions: int = 10000):
        self.max_sessions = max_sessions
        self._lock = threading.Lock()

        self.device_map = {}   # visitorId -> node_idx
        self.ip_map = {}       # ip_address -> node_idx
        self.session_map = {}  # sessionId -> node_idx
        self.target_map = {}   # target_url -> node_idx

        self.device_features = []
        self.ip_features = []
        self.session_features = []
        self.target_features = []

        # Edges (src, dst)
        self.edges_device_session = []
        self.edges_session_ip = []
        self.edges_session_target = []
        self.session_labels = []  # 0=Human, 1=Bot

    def _build_session_feature(self, mouse_stats: dict, botd: dict, record_count: int) -> np.ndarray:
        """Build session feature vector from mouse stats + metadata using canonical vector extractor."""
        mouse_vec = extract_mouse_stat_vector(mouse_stats)
        bd = botd if isinstance(botd, dict) else {}
        h_score = float(bd.get("heuristicScore") or 0.0)
        r_count = float(record_count or 0)
        return np.append(mouse_vec, [h_score, r_count]).astype(np.float32)

    def add_telemetry_event(self, telemetry: dict, ip_address: str = "127.0.0.1", is_bot_ground_truth: int = None):
        """
        Ingest a single telemetry event into the evolving graph structure.
        Safe against None payloads, malformed structures, and memory overflow.
        Thread-safe under concurrent requests.
        """
        with self._lock:
            if not isinstance(telemetry, dict):
                telemetry = {}

            session_id = str(telemetry.get("sessionId") or f"sess_{len(self.session_map)}")
            visitor_id = str(telemetry.get("visitorId") or f"dev_{len(self.device_map)}")
            page_url = str(telemetry.get("pageUrl") or "/")
            fingerprint = telemetry.get("fingerprint") or {}
            botd = telemetry.get("botd") or {}
            mouse = telemetry.get("mouse") or {}
            records = mouse.get("records") or [] if isinstance(mouse, dict) else []

            # Memory control: If session capacity exceeded, reset or prune oldest
            if len(self.session_map) >= self.max_sessions and session_id not in self.session_map:
                # Clear graph cache for long-running service to prevent memory leak
                self.device_map.clear()
                self.device_features.clear()
                self.ip_map.clear()
                self.ip_features.clear()
                self.target_map.clear()
                self.target_features.clear()
                self.session_map.clear()
                self.session_features.clear()
                self.session_labels.clear()
                self.edges_device_session.clear()
                self.edges_session_ip.clear()
                self.edges_session_target.clear()

            # 1. Device Node
            if visitor_id not in self.device_map:
                dev_idx = len(self.device_map)
                self.device_map[visitor_id] = dev_idx
                dev_feat = extract_env_vector(fingerprint, botd)
                self.device_features.append(dev_feat)
            else:
                dev_idx = self.device_map[visitor_id]

            # 2. IP Node (with deterministic hashing)
            ip_str = str(ip_address or "127.0.0.1")
            if ip_str not in self.ip_map:
                ip_idx = len(self.ip_map)
                self.ip_map[ip_str] = ip_idx
                is_private = 1.0 if ip_str.startswith(("127.", "192.168.", "10.")) else 0.0
                ip_feat = np.array([_deterministic_hash_feature(ip_str), is_private, 1.0], dtype=np.float32)
                self.ip_features.append(ip_feat)
            else:
                ip_idx = self.ip_map[ip_str]
                self.ip_features[ip_idx][2] += 1.0  # increment request count

            # 3. Target Node (URL / Ad, deterministic hashing)
            if page_url not in self.target_map:
                tgt_idx = len(self.target_map)
                self.target_map[page_url] = tgt_idx
                tgt_feat = np.array([_deterministic_hash_feature(page_url), 1.0], dtype=np.float32)
                self.target_features.append(tgt_feat)
            else:
                tgt_idx = self.target_map[page_url]
                self.target_features[tgt_idx][1] += 1.0

            # 4. Session Node
            if session_id not in self.session_map:
                sess_idx = len(self.session_map)
                self.session_map[session_id] = sess_idx
                m_stats = compute_statistical_features(records)
                sess_feat = self._build_session_feature(m_stats, botd, len(records))
                self.session_features.append(sess_feat)
                self.session_labels.append(is_bot_ground_truth if is_bot_ground_truth is not None else -1)
            else:
                sess_idx = self.session_map[session_id]
                # Update session features with new mouse data
                if records:
                    m_stats = compute_statistical_features(records)
                    prev_count = self.session_features[sess_idx][-1] if self.session_features[sess_idx].size > 0 else 0
                    sess_feat = self._build_session_feature(m_stats, botd, prev_count + len(records))
                    self.session_features[sess_idx] = sess_feat

            # 5. Connect Edges
            self.edges_device_session.append((dev_idx, sess_idx))
            self.edges_session_ip.append((ip_idx, sess_idx))
            self.edges_session_target.append((tgt_idx, sess_idx))

            return sess_idx

    def to_torch_tensors(self):
        """
        Exports graph data as pure PyTorch tensors for GNN training/inference.
        Works independently even without torch_geometric installed.
        Thread-safe.
        """
        with self._lock:
            x_device = torch.tensor(np.array(self.device_features, dtype=np.float32)) if self.device_features else torch.empty((0, len(ENV_FEATURE_NAMES)))
            x_ip = torch.tensor(np.array(self.ip_features, dtype=np.float32)) if self.ip_features else torch.empty((0, IP_FEATURE_DIM))
            x_session = torch.tensor(np.array(self.session_features, dtype=np.float32)) if self.session_features else torch.empty((0, SESSION_FEATURE_DIM))
            x_target = torch.tensor(np.array(self.target_features, dtype=np.float32)) if self.target_features else torch.empty((0, TARGET_FEATURE_DIM))

            edge_dev_sess = torch.tensor(self.edges_device_session, dtype=torch.long).t().contiguous() if self.edges_device_session else torch.empty((2, 0), dtype=torch.long)
            edge_ip_sess = torch.tensor(self.edges_session_ip, dtype=torch.long).t().contiguous() if self.edges_session_ip else torch.empty((2, 0), dtype=torch.long)
            edge_tgt_sess = torch.tensor(self.edges_session_target, dtype=torch.long).t().contiguous() if self.edges_session_target else torch.empty((2, 0), dtype=torch.long)

            y_session = torch.tensor(self.session_labels, dtype=torch.long) if self.session_labels else torch.empty(0, dtype=torch.long)

            return {
                "x_dict": {
                    "device": x_device,
                    "ip": x_ip,
                    "session": x_session,
                    "target": x_target,
                },
                "edge_index_dict": {
                    ("device", "operates", "session"): edge_dev_sess,
                    ("ip", "originates", "session"): edge_ip_sess,
                    ("target", "targeted_by", "session"): edge_tgt_sess,
                },
                "y_session": y_session,
                "node_counts": {
                    "device": len(self.device_map),
                    "ip": len(self.ip_map),
                    "session": len(self.session_map),
                    "target": len(self.target_map),
                },
            }

    def to_pyg_hetero_data(self):
        """Exports directly to torch_geometric.data.HeteroData if PyG is available."""
        try:
            from torch_geometric.data import HeteroData
            data = HeteroData()
            tensors = self.to_torch_tensors()
            for node_type, feat in tensors["x_dict"].items():
                data[node_type].x = feat
            for edge_type, edge_idx in tensors["edge_index_dict"].items():
                data[edge_type].edge_index = edge_idx
            data["session"].y = tensors["y_session"]
            return data
        except ImportError:
            return self.to_torch_tensors()

    def get_stats(self) -> dict:
        """Thread-safe snapshot of graph topology statistics."""
        with self._lock:
            device_cnt = len(self.device_map)
            ip_cnt = len(self.ip_map)
            session_cnt = len(self.session_map)
            edges_cnt = len(self.edges_device_session) + len(self.edges_session_ip) + len(self.edges_session_target)
            return {
                "device_count": device_cnt,
                "ip_count": ip_cnt,
                "session_count": session_cnt,
                "edges_count": edges_cnt,
                "suspected_coordinated_rings": 1 if (session_cnt > 10 and device_cnt < session_cnt * 0.3) else 0,
            }
