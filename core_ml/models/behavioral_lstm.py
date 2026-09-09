"""
Behavioral LSTM Model for Mouse Dynamics Classification
Inspired by DELBOT-Mouse LSTM architecture (https://github.com/chrisgdt/DELBOT-Mouse)
Trained on sequences of 24 points with 8 features: [dx, dy, speedX, speedY, speed, accel, distance, timeDiff]
Outputs probability of being a BOT (0.0 = Human, 1.0 = Bot).
"""

import os
import torch
import torch.nn as nn


class MouseTrajectoryLSTM(nn.Module):
    def __init__(self, input_dim: int = 8, hidden_dim: int = 64, num_layers: int = 2, dropout: float = 0.2):
        super().__init__()
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim
        self.num_layers = num_layers

        self.lstm = nn.LSTM(
            input_size=input_dim,
            hidden_size=hidden_dim,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
            bidirectional=False,
        )

        self.fc = nn.Sequential(
            nn.Linear(hidden_dim, 32),
            nn.BatchNorm1d(32),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(32, 1),
            nn.Sigmoid(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        x: Tensor of shape (batch_size, seq_len=24, input_dim=8)
        Returns: Tensor of shape (batch_size, 1) with values in [0, 1]
        """
        # lstm_out: (batch_size, seq_len, hidden_dim)
        lstm_out, (h_n, _) = self.lstm(x)
        # Take the last hidden state from the topmost LSTM layer
        last_hidden = h_n[-1]  # (batch_size, hidden_dim)
        out = self.fc(last_hidden)  # (batch_size, 1)
        return out

    def predict_session_proba(self, chunks_tensor: torch.Tensor) -> float:
        """
        Evaluates all chunks from a single session and aggregates their bot probability.
        If no chunks (insufficient data), returns default 0.5 (neutral/inconclusive).
        """
        if chunks_tensor is None or chunks_tensor.size(0) == 0:
            return 0.5

        self.eval()
        with torch.no_grad():
            preds = self.forward(chunks_tensor)  # (n_chunks, 1)
            # Using 75th percentile / max to catch bot burst intervals
            return float(torch.quantile(preds, 0.75).item())

    def save_weights(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        torch.save(self.state_dict(), path)

    def load_weights(self, path: str, device: str = "cpu"):
        if os.path.exists(path):
            self.load_state_dict(torch.load(path, map_location=device))
            self.eval()
            return True
        return False
