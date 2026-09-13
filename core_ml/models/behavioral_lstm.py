"""
Behavioral BiLSTM Model with Temporal Attention for Mouse Dynamics Classification (v2)
=======================================================================================
Inspired by DELBOT-Mouse ModelRNN3 architecture (https://github.com/chrisgdt/DELBOT-Mouse)
Improvements:
  - Bidirectional LSTM for capturing both forward/backward temporal context
  - Temporal Attention mechanism to focus on discriminative time steps
  - LeakyReLU activation + L1/L2 regularization per DELBOT best practices
  - Weighted median aggregation for session-level prediction
"""

import os
import torch
import torch.nn as nn
import torch.nn.functional as F


class TemporalAttention(nn.Module):
    """
    Attention mechanism over LSTM hidden states.
    Learns to focus on specific time steps (e.g., sudden direction changes, pauses)
    that are most informative for bot/human classification.
    """
    def __init__(self, hidden_dim: int):
        super().__init__()
        self.attention = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.Tanh(),
            nn.Linear(hidden_dim // 2, 1, bias=False),
        )

    def forward(self, lstm_output: torch.Tensor) -> torch.Tensor:
        """
        lstm_output: (batch_size, seq_len, hidden_dim)
        Returns: (batch_size, hidden_dim) — weighted sum of hidden states
        """
        # Compute attention weights
        attn_scores = self.attention(lstm_output)  # (batch, seq_len, 1)
        attn_weights = F.softmax(attn_scores, dim=1)  # (batch, seq_len, 1)
        # Weighted sum
        context = torch.sum(attn_weights * lstm_output, dim=1)  # (batch, hidden_dim)
        return context


class MouseTrajectoryLSTM(nn.Module):
    def __init__(
        self,
        input_dim: int = 8,
        hidden_dim: int = 64,
        num_layers: int = 2,
        dropout: float = 0.25,
        bidirectional: bool = True,
        l1_lambda: float = 1e-5,
        l2_lambda: float = 1e-4,
    ):
        super().__init__()
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim
        self.num_layers = num_layers
        self.bidirectional = bidirectional
        self.l1_lambda = l1_lambda
        self.l2_lambda = l2_lambda

        # Effective hidden dim after bidirectional concatenation
        self.effective_hidden = hidden_dim * 2 if bidirectional else hidden_dim

        # Input normalization
        self.input_norm = nn.LayerNorm(input_dim)

        # Bidirectional LSTM stack (matching DELBOT ModelRNN3 structure)
        self.lstm1 = nn.LSTM(
            input_size=input_dim,
            hidden_size=hidden_dim,
            num_layers=1,
            batch_first=True,
            dropout=0.0,
            bidirectional=bidirectional,
        )
        self.ln1 = nn.LayerNorm(self.effective_hidden)
        self.act1 = nn.LeakyReLU(0.1)
        self.drop1 = nn.Dropout(0.3)

        self.lstm2 = nn.LSTM(
            input_size=self.effective_hidden,
            hidden_size=hidden_dim // 2,
            num_layers=1,
            batch_first=True,
            dropout=0.0,
            bidirectional=bidirectional,
        )
        self.act2 = nn.LeakyReLU(0.1)
        self.drop2 = nn.Dropout(0.1)

        # Temporal attention over sequence
        attn_input_dim = (hidden_dim // 2) * 2 if bidirectional else hidden_dim // 2
        self.attention = TemporalAttention(attn_input_dim)

        # Classification head with L1/L2 regularization structure
        self.fc = nn.Sequential(
            nn.Linear(attn_input_dim, 32),
            nn.LeakyReLU(0.1),
            nn.Dropout(dropout),
            nn.Linear(32, 16),
            nn.ReLU(),
            nn.Linear(16, 1),
            nn.Sigmoid(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        x: Tensor of shape (batch_size, seq_len=24, input_dim=8)
        Returns: Tensor of shape (batch_size, 1) with values in [0, 1]
        """
        # Input normalization
        x = self.input_norm(x)

        # LSTM Layer 1 (return sequences for attention)
        lstm1_out, _ = self.lstm1(x)  # (batch, seq_len, effective_hidden)
        lstm1_out = self.ln1(lstm1_out)
        lstm1_out = self.act1(lstm1_out)
        lstm1_out = self.drop1(lstm1_out)

        # LSTM Layer 2
        lstm2_out, _ = self.lstm2(lstm1_out)  # (batch, seq_len, attn_input_dim)
        lstm2_out = self.act2(lstm2_out)
        lstm2_out = self.drop2(lstm2_out)

        # Temporal Attention: focus on important time steps
        context = self.attention(lstm2_out)  # (batch, attn_input_dim)

        # Classification
        out = self.fc(context)  # (batch, 1)
        return out

    def get_regularization_loss(self) -> torch.Tensor:
        """Compute L1 + L2 regularization loss for all linear layers."""
        l1_loss = torch.tensor(0.0, device=next(self.parameters()).device)
        l2_loss = torch.tensor(0.0, device=next(self.parameters()).device)
        for name, param in self.named_parameters():
            if 'weight' in name and 'ln' not in name and 'norm' not in name:
                l1_loss += torch.sum(torch.abs(param))
                l2_loss += torch.sum(param ** 2)
        return self.l1_lambda * l1_loss + self.l2_lambda * l2_loss

    def predict_session_proba(self, chunks_tensor: torch.Tensor) -> float:
        """
        Evaluates all chunks from a single session and aggregates their bot probability.
        Uses weighted median: more extreme predictions get higher weight.
        """
        if chunks_tensor is None or chunks_tensor.size(0) == 0:
            return 0.5

        self.eval()
        device = next(self.parameters()).device
        chunks_tensor = torch.nan_to_num(chunks_tensor.to(device), nan=0.0, posinf=100.0, neginf=-100.0)
        with torch.no_grad():
            preds = self.forward(chunks_tensor).squeeze(-1)  # (n_chunks,)

            if preds.size(0) == 1:
                return float(preds[0].item())

            # Weighted aggregation: higher confidence predictions get more weight
            weights = torch.abs(preds - 0.5) * 2.0 + 0.1  # min weight 0.1
            w_sum = float(weights.sum())
            weighted_mean = float((preds * weights).sum() / w_sum) if w_sum > 1e-6 else 0.5

            # Use p75 only as a strong bot signal override
            # Prevents edge case where low p75 overrides a high weighted_mean
            p75 = float(torch.quantile(preds, 0.75).item())
            if p75 > 0.7:
                return max(weighted_mean, p75)
            return weighted_mean

    def save_weights(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        torch.save(self.state_dict(), path)

    def load_weights(self, path: str, device: str = "cpu"):
        if os.path.exists(path):
            self.load_state_dict(torch.load(path, map_location=device, weights_only=True))
            self.eval()
            return True
        return False
