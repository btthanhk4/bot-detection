"""
Graph Neural Network (GNN) Model for Coordinated Botnet & Click Fraud Detection (v2)
======================================================================================
Improvements:
  - Heterogeneous GraphSAGE aggregation across device/session/IP/target relations
  - Residual connections between message-passing layers
  - LayerNorm after each conv layer
  - Improved fallback aggregation without PyG
  - Skip connections in classifier head
"""

import os
import warnings
import torch
import torch.nn as nn
import torch.nn.functional as F

from core_ml.features.env_features import FEATURE_NAMES as ENV_FEATURE_NAMES
from core_ml.features.graph_builder import SESSION_FEATURE_DIM, IP_FEATURE_DIM, TARGET_FEATURE_DIM

# Filter known PyG warning about star-topology destination nodes (device, ip, target are sources)
warnings.filterwarnings("ignore", message=".*There exist node types.*representations do not get updated.*")

try:
    from torch_geometric.nn import HeteroConv, SAGEConv
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
            "device": len(ENV_FEATURE_NAMES),
            "ip": IP_FEATURE_DIM,
            "session": SESSION_FEATURE_DIM,
            "target": TARGET_FEATURE_DIM,
        }
        self.hidden_dim = hidden_dim
        self.out_dim = out_dim
        self.num_layers = num_layers

        # 1. Linear projections for heterogeneous node features to shared hidden_dim
        self.input_projections = nn.ModuleDict({
            node_type: nn.Sequential(
                nn.Linear(dim, hidden_dim),
                nn.LeakyReLU(0.1),
                nn.LayerNorm(hidden_dim),
                nn.Dropout(0.1),
            )
            for node_type, dim in self.in_dims.items()
        })

        # 2. Heterogeneous GraphSAGE convolutions (PyG HeteroConv if available)
        if HAS_PYG:
            self.convs = nn.ModuleList()
            self.layer_norms = nn.ModuleList()
            for layer_idx in range(num_layers):
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    conv = HeteroConv({
                        ("device", "operates", "session"): SAGEConv((hidden_dim, hidden_dim), hidden_dim),
                        ("ip", "originates", "session"): SAGEConv((hidden_dim, hidden_dim), hidden_dim),
                        ("target", "targeted_by", "session"): SAGEConv((hidden_dim, hidden_dim), hidden_dim),
                    }, aggr="sum")
                self.convs.append(conv)
                # Per-node-type layer norms
                ln_dict = nn.ModuleDict({
                    nt: nn.LayerNorm(hidden_dim) for nt in self.in_dims
                })
                self.layer_norms.append(ln_dict)
        else:
            self.convs = None
            self.layer_norms = None

        # 3. Session Classification Head with skip connection
        self.classifier = nn.Sequential(
            nn.Linear(hidden_dim, 32),
            nn.LeakyReLU(0.1),
            nn.Dropout(0.2),
            nn.Linear(32, out_dim),
        )

    def forward(self, x_dict: dict, edge_index_dict: dict) -> torch.Tensor:
        """
        x_dict: {node_type: tensor of shape (N_type, feature_dim)}
        edge_index_dict: {edge_type_tuple: tensor of shape (2, E)}
        Returns: Logits for session nodes of shape (N_session, out_dim)
        """
        # Determine target device
        device = "cpu"
        for val in x_dict.values():
            if isinstance(val, torch.Tensor) and val.numel() > 0:
                device = val.device
                break

        # Step 1: Project each node type to hidden dimension (guaranteeing all node types exist)
        h_dict = {}
        for node_type, dim in self.in_dims.items():
            x = x_dict.get(node_type)
            if x is not None and isinstance(x, torch.Tensor) and x.size(0) > 0 and node_type in self.input_projections:
                h_dict[node_type] = self.input_projections[node_type](x.to(device))
            else:
                n_nodes = x.size(0) if (x is not None and isinstance(x, torch.Tensor)) else 0
                h_dict[node_type] = torch.zeros((n_nodes, self.hidden_dim), device=device)

        # Ensure all expected edge types exist in edge_index_dict
        safe_edge_index_dict = {}
        expected_edges = [
            ("device", "operates", "session"),
            ("ip", "originates", "session"),
            ("target", "targeted_by", "session"),
        ]
        for edge_t in expected_edges:
            edge_idx = edge_index_dict.get(edge_t)
            if edge_idx is not None and isinstance(edge_idx, torch.Tensor) and edge_idx.dim() == 2:
                safe_edge_index_dict[edge_t] = edge_idx.to(device)
            else:
                safe_edge_index_dict[edge_t] = torch.empty((2, 0), dtype=torch.long, device=device)

        # Step 2: Message Passing with residual connections
        if HAS_PYG and self.convs is not None:
            for layer_idx, conv in enumerate(self.convs):
                # Save residuals
                h_residual = {k: v.clone() for k, v in h_dict.items()}

                out_dict = conv(h_dict, safe_edge_index_dict)
                for k, v in out_dict.items():
                    # Apply LayerNorm
                    if k in self.layer_norms[layer_idx]:
                        v = self.layer_norms[layer_idx][k](v)
                    v = F.leaky_relu(v, 0.1)
                    # Residual connection (add input back)
                    if k in h_residual and h_residual[k].size() == v.size():
                        v = v + h_residual[k]
                    h_dict[k] = v
        else:
            # Fallback aggregation: mean-pool neighbor messages
            h_session = h_dict.get("session", torch.empty((0, self.hidden_dim)))
            
            for edge_type_key, src_type in [
                (("device", "operates", "session"), "device"),
                (("ip", "originates", "session"), "ip"),
                (("target", "targeted_by", "session"), "target"),
            ]:
                edge_idx = safe_edge_index_dict.get(edge_type_key)
                if edge_idx is not None and edge_idx.numel() > 0 and h_session.size(0) > 0:
                    h_src = h_dict.get(src_type, torch.empty((0, self.hidden_dim)))
                    src_nodes, dst_nodes = edge_idx[0], edge_idx[1]
                    valid_mask = (src_nodes < h_src.size(0)) & (dst_nodes < h_session.size(0))
                    if valid_mask.any():
                        h_session = h_session.clone()
                        # Mean aggregation with scaling
                        for dst_idx in dst_nodes[valid_mask].unique():
                            mask = (dst_nodes == dst_idx) & valid_mask
                            src_feats = h_src[src_nodes[mask]]
                            h_session[dst_idx] += src_feats.mean(dim=0)

            h_dict["session"] = F.leaky_relu(h_session, 0.1)

        # Step 3: Classify session nodes (0=Human, 1=Bot/Fraud)
        session_reps = h_dict.get("session", torch.empty((0, self.hidden_dim)))
        if session_reps.size(0) == 0:
            return torch.empty((0, self.out_dim))

        logits = self.classifier(session_reps)
        return logits

    def predict_session_probabilities(self, x_dict: dict, edge_index_dict: dict) -> torch.Tensor:
        self.eval()
        device = next(self.parameters()).device
        x_dict = {k: v.to(device) for k, v in x_dict.items()}
        edge_index_dict = {k: v.to(device) for k, v in edge_index_dict.items()}
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
            try:
                self.load_state_dict(torch.load(path, map_location=device, weights_only=True))
                self.eval()
                return True
            except Exception:
                return False
        return False
