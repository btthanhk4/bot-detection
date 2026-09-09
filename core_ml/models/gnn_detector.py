"""
Graph Neural Network (GNN) Model for Coordinated Botnet & Click Fraud Detection
Implements Heterogeneous Graph Message Passing across Device, IP, Session, and Target nodes.
Directly implements the core research direction of the Graduation Thesis.
"""

import os
import torch
import torch.nn as nn
import torch.nn.functional as F

try:
    from torch_geometric.nn import HeteroConv, SAGEConv, GATConv
    HAS_PYG = True
except ImportError:
    HAS_PYG = False


class HeteroClickFraudGNN(nn.Module):
    """
    Heterogeneous Graph Neural Network for detecting coordinated fraud rings.
    Propagates information between devices, sessions, and IPs to uncover botnets.
    """
    def __init__(self, in_dims: dict = None, hidden_dim: int = 64, out_dim: int = 2, num_layers: int = 2):
        super().__init__()
        self.in_dims = in_dims or {
            "device": 26,
            "ip": 3,
            "session": 7,
            "target": 2,
        }
        self.hidden_dim = hidden_dim
        self.out_dim = out_dim

        # 1. Linear projections for heterogeneous node features to shared hidden_dim
        self.input_projections = nn.ModuleDict({
            node_type: nn.Sequential(
                nn.Linear(dim, hidden_dim),
                nn.ReLU(),
                nn.LayerNorm(hidden_dim),
            )
            for node_type, dim in self.in_dims.items()
        })

        # 2. Graph Convolutions (PyG HeteroConv if available)
        if HAS_PYG:
            self.convs = nn.ModuleList()
            for _ in range(num_layers):
                conv = HeteroConv({
                    ("device", "operates", "session"): SAGEConv((hidden_dim, hidden_dim), hidden_dim),
                    ("ip", "originates", "session"): SAGEConv((hidden_dim, hidden_dim), hidden_dim),
                    ("target", "targeted_by", "session"): SAGEConv((hidden_dim, hidden_dim), hidden_dim),
                }, aggr="sum")
                self.convs.append(conv)
        else:
            self.convs = None

        # 3. Session Classification Head
        self.classifier = nn.Sequential(
            nn.Linear(hidden_dim, 32),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(32, out_dim),
        )

    def forward(self, x_dict: dict, edge_index_dict: dict) -> torch.Tensor:
        """
        x_dict: {node_type: tensor of shape (N_type, feature_dim)}
        edge_index_dict: {edge_type_tuple: tensor of shape (2, E)}
        Returns: Logits for session nodes of shape (N_session, out_dim)
        """
        # Step 1: Project each node type to hidden dimension
        h_dict = {}
        for node_type, x in x_dict.items():
            if x.size(0) > 0 and node_type in self.input_projections:
                h_dict[node_type] = self.input_projections[node_type](x)
            else:
                h_dict[node_type] = torch.zeros((x.size(0), self.hidden_dim), device=x.device if x.numel() > 0 else "cpu")

        # Step 2: Message Passing across graph edges
        if HAS_PYG and self.convs is not None:
            for conv in self.convs:
                out_dict = conv(h_dict, edge_index_dict)
                for k, v in out_dict.items():
                    h_dict[k] = F.relu(v)
        else:
            # Fallback simple aggregation across edges if PyG is not loaded
            h_session = h_dict.get("session", torch.empty((0, self.hidden_dim)))
            dev_sess_edge = edge_index_dict.get(("device", "operates", "session"))
            if dev_sess_edge is not None and dev_sess_edge.numel() > 0 and h_session.size(0) > 0:
                h_dev = h_dict.get("device", torch.empty((0, self.hidden_dim)))
                src_dev, dst_sess = dev_sess_edge[0], dev_sess_edge[1]
                valid_mask = (src_dev < h_dev.size(0)) & (dst_sess < h_session.size(0))
                if valid_mask.any():
                    h_session = h_session.clone()
                    h_session[dst_sess[valid_mask]] += h_dev[src_dev[valid_mask]] * 0.5
                h_dict["session"] = F.relu(h_session)

        # Step 3: Classify session nodes (0=Human, 1=Bot/Fraud)
        session_reps = h_dict.get("session", torch.empty((0, self.hidden_dim)))
        if session_reps.size(0) == 0:
            return torch.empty((0, self.out_dim))

        logits = self.classifier(session_reps)
        return logits

    def predict_session_probabilities(self, x_dict: dict, edge_index_dict: dict) -> torch.Tensor:
        self.eval()
        with torch.no_grad():
            logits = self.forward(x_dict, edge_index_dict)
            if logits.size(0) == 0:
                return torch.empty(0)
            return F.softmax(logits, dim=-1)[:, 1]  # prob of bot

    def save_model(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        torch.save(self.state_dict(), path)

    def load_model(self, path: str, device: str = "cpu") -> bool:
        if os.path.exists(path):
            self.load_state_dict(torch.load(path, map_location=device))
            self.eval()
            return True
        return False
