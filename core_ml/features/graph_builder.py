"""
Graph Construction Module for Click Fraud & Botnet Detection
Constructs Multi-relational / Heterogeneous Graphs connecting:
- Device (visitorId from FingerprintJS)
- IP Address (client IP / subnet)
- Session (user browsing session)
- Target (product / ad click target)

Edges represent behavioral and network interactions.
"""

import numpy as np
import torch
from core_ml.features.env_features import extract_env_vector
from core_ml.features.mouse_features import compute_statistical_features


class ClickFraudGraphBuilder:
    def __init__(self):
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

    def add_telemetry_event(self, telemetry: dict, ip_address: str = "127.0.0.1", is_bot_ground_truth: int = None):
        """
        Ingest a single telemetry event into the evolving graph structure.
        """
        session_id = telemetry.get("sessionId", f"sess_{len(self.session_map)}")
        visitor_id = telemetry.get("visitorId", f"dev_{len(self.device_map)}")
        page_url = telemetry.get("pageUrl", "/")
        fingerprint = telemetry.get("fingerprint", {})
        botd = telemetry.get("botd", {})
        mouse = telemetry.get("mouse", {})

        # 1. Device Node
        if visitor_id not in self.device_map:
            dev_idx = len(self.device_map)
            self.device_map[visitor_id] = dev_idx
            # Feature: Hardware & Fingerprint vector
            dev_feat = extract_env_vector(fingerprint, botd)
            self.device_features.append(dev_feat)
        else:
            dev_idx = self.device_map[visitor_id]

        # 2. IP Node
        if ip_address not in self.ip_map:
            ip_idx = len(self.ip_map)
            self.ip_map[ip_address] = ip_idx
            # Dummy initial IP feature: [ip_hash, is_private, request_count=1]
            is_private = 1.0 if ip_address.startswith(("127.", "192.168.", "10.")) else 0.0
            ip_feat = np.array([float(hash(ip_address) % 1000) / 1000.0, is_private, 1.0], dtype=np.float32)
            self.ip_features.append(ip_feat)
        else:
            ip_idx = self.ip_map[ip_address]
            self.ip_features[ip_idx][2] += 1.0  # increment request count

        # 3. Target Node (URL / Ad)
        if page_url not in self.target_map:
            tgt_idx = len(self.target_map)
            self.target_map[page_url] = tgt_idx
            tgt_feat = np.array([float(hash(page_url) % 1000) / 1000.0, 1.0], dtype=np.float32)
            self.target_features.append(tgt_feat)
        else:
            tgt_idx = self.target_map[page_url]
            self.target_features[tgt_idx][1] += 1.0

        # 4. Session Node
        if session_id not in self.session_map:
            sess_idx = len(self.session_map)
            self.session_map[session_id] = sess_idx
            # Features: mouse dynamics stats + heuristic flags
            m_stats = compute_statistical_features(mouse.get("records", []))
            sess_feat = np.array([
                m_stats["mean_speed"],
                m_stats["max_speed"],
                m_stats["straightness"],
                m_stats["pause_ratio"],
                m_stats["angular_entropy"],
                float(botd.get("heuristicScore", 0.0)),
                float(len(mouse.get("records", []))),
            ], dtype=np.float32)
            self.session_features.append(sess_feat)
            self.session_labels.append(is_bot_ground_truth if is_bot_ground_truth is not None else -1)
        else:
            sess_idx = self.session_map[session_id]
            # Update session features with new mouse data (merge events)
            new_records = mouse.get("records", [])
            if new_records:
                m_stats = compute_statistical_features(new_records)
                updated_feat = np.array([
                    m_stats["mean_speed"],
                    m_stats["max_speed"],
                    m_stats["straightness"],
                    m_stats["pause_ratio"],
                    m_stats["angular_entropy"],
                    float(botd.get("heuristicScore", 0.0)),
                    float(self.session_features[sess_idx][6] + len(new_records)),  # accumulate point count
                ], dtype=np.float32)
                self.session_features[sess_idx] = updated_feat

        # 5. Connect Edges (directed towards session for aggregation)
        self.edges_device_session.append((dev_idx, sess_idx))
        self.edges_session_ip.append((ip_idx, sess_idx))
        self.edges_session_target.append((tgt_idx, sess_idx))

        return sess_idx

    def to_torch_tensors(self):
        """
        Exports graph data as pure PyTorch tensors for GNN training/inference.
        Works independently even without torch_geometric installed!
        """
        x_device = torch.tensor(np.array(self.device_features, dtype=np.float32)) if self.device_features else torch.empty((0, 30))
        x_ip = torch.tensor(np.array(self.ip_features, dtype=np.float32)) if self.ip_features else torch.empty((0, 3))
        x_session = torch.tensor(np.array(self.session_features, dtype=np.float32)) if self.session_features else torch.empty((0, 7))
        x_target = torch.tensor(np.array(self.target_features, dtype=np.float32)) if self.target_features else torch.empty((0, 2))

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
        """
        Exports directly to torch_geometric.data.HeteroData if PyG is available.
        """
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
