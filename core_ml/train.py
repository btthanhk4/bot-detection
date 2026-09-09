"""
Training Pipeline for Multi-Modal Bot Detection & Graph Neural Network
Trains:
1. Behavioral LSTM on mouse movement chunks
2. Tabular XGBoost classifier on environment & kinematic statistics
3. HeteroClickFraudGNN on graph relations (Device - IP - Session - Target)
Saves trained models into core_ml/weights/
"""

import os
import sys
import random
import numpy as np

# Ensure utf-8 encoding for Windows console
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
from sklearn.metrics import roc_auc_score, f1_score, precision_score, recall_score

from core_ml.dataset.loader import generate_synthetic_telemetry
from core_ml.features.env_features import extract_env_vector
from core_ml.features.mouse_features import compute_statistical_features, extract_sequential_chunks
from core_ml.features.graph_builder import ClickFraudGraphBuilder
from core_ml.models.behavioral_lstm import MouseTrajectoryLSTM
from core_ml.models.tabular_classifier import TabularBotClassifier
from core_ml.models.gnn_detector import HeteroClickFraudGNN


def train_lstm(lstm_model, X_chunks, y_chunks, epochs=15, batch_size=32, lr=0.003):
    print("--> Training Behavioral LSTM Model...")
    dataset = TensorDataset(X_chunks, y_chunks)
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=True)

    criterion = nn.BCELoss()
    optimizer = torch.optim.Adam(lstm_model.parameters(), lr=lr, weight_decay=1e-4)

    lstm_model.train()
    for epoch in range(epochs):
        total_loss = 0.0
        for batch_x, batch_y in loader:
            optimizer.zero_grad()
            preds = lstm_model(batch_x)
            loss = criterion(preds.squeeze(), batch_y)
            loss.backward()
            optimizer.step()
            total_loss += loss.item()
        if (epoch + 1) % 5 == 0 or epoch == epochs - 1:
            print(f"    Epoch [{epoch+1}/{epochs}] Loss: {total_loss / len(loader):.4f}")

    lstm_model.eval()


def train_tabular(tabular_model, X_tab, y_tab):
    print("--> Training Tabular XGBoost Classifier...")
    tabular_model.fit(X_tab, y_tab)
    importances = tabular_model.get_feature_importances()
    top3 = list(importances.items())[:3]
    print(f"    Top 3 Features: {top3}")


def train_gnn(gnn_model, graph_data, epochs=30, lr=0.01):
    print("--> Training HeteroClickFraudGNN Model...")
    x_dict = graph_data["x_dict"]
    edge_index_dict = graph_data["edge_index_dict"]
    y_session = graph_data["y_session"]

    if y_session.numel() == 0:
        print("    No session labels found in graph. Skipping GNN training.")
        return

    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(gnn_model.parameters(), lr=lr, weight_decay=1e-4)

    gnn_model.train()
    for epoch in range(epochs):
        optimizer.zero_grad()
        logits = gnn_model(x_dict, edge_index_dict)
        loss = criterion(logits, y_session)
        loss.backward()
        optimizer.step()
        if (epoch + 1) % 10 == 0 or epoch == epochs - 1:
            print(f"    GNN Epoch [{epoch+1}/{epochs}] Loss: {loss.item():.4f}")

    gnn_model.eval()


def main():
    print("=== STARTING TRAINING PIPELINE ===")
    weights_dir = os.path.join(os.path.dirname(__file__), "weights")
    os.makedirs(weights_dir, exist_ok=True)

    # 1. Synthesize balanced training & evaluation telemetry
    print("1. Generating synthetic training samples (Human vs Bot)...")
    train_telemetries = []
    y_train = []

    # 150 Humans + 150 Bots
    for _ in range(150):
        t = generate_synthetic_telemetry(is_bot=False)
        train_telemetries.append(t)
        y_train.append(0)

    for _ in range(150):
        level = random.choice(["naive", "moderate", "advanced"])
        t = generate_synthetic_telemetry(is_bot=True, bot_level=level)
        train_telemetries.append(t)
        y_train.append(1)

    # 2. Prepare Tabular & Graph Data
    X_tab_list = []
    all_chunks = []
    all_chunk_labels = []

    graph_builder = ClickFraudGraphBuilder()

    for idx, (t, label) in enumerate(zip(train_telemetries, y_train)):
        fp = t["fingerprint"]
        bd = t["botd"]
        mouse = t["mouse"]
        records = mouse.get("records", [])
        chunks = mouse.get("chunks", [])

        # Tabular feature vector
        env_vec = extract_env_vector(fp, bd)
        m_stats = compute_statistical_features(records)
        mouse_stat_vec = np.array([
            m_stats["mean_speed"], m_stats["std_speed"], m_stats["max_speed"],
            m_stats["mean_accel"], m_stats["std_accel"], m_stats["straightness"],
            m_stats["pause_ratio"], float(m_stats["direction_changes_x"]),
            float(m_stats["direction_changes_y"]), m_stats["jerk_mean"], m_stats["angular_entropy"]
        ], dtype=np.float32)
        X_tab_list.append(np.concatenate([env_vec, mouse_stat_vec]))

        # LSTM chunks
        tensor_c = extract_sequential_chunks(chunks)
        if tensor_c.size(0) > 0:
            for c in tensor_c:
                all_chunks.append(c)
                all_chunk_labels.append(label)

        # Graph event (simulate some shared IPs among bot clusters)
        ip = f"192.168.1.{random.randint(1, 10) if label == 1 else random.randint(20, 100)}"
        graph_builder.add_telemetry_event(t, ip_address=ip, is_bot_ground_truth=label)

    X_tab = np.array(X_tab_list, dtype=np.float32)
    y_tab = np.array(y_train, dtype=int)

    # 3. Train Tabular Classifier
    tabular_model = TabularBotClassifier()
    train_tabular(tabular_model, X_tab, y_tab)
    tabular_path = os.path.join(weights_dir, "tabular_model.joblib")
    tabular_model.save(tabular_path)
    print(f"    Saved Tabular Model -> {tabular_path}")

    # 4. Train Behavioral LSTM
    if all_chunks:
        X_chunks_tensor = torch.stack(all_chunks)
        y_chunks_tensor = torch.tensor(all_chunk_labels, dtype=torch.float32)
        lstm_model = MouseTrajectoryLSTM()
        train_lstm(lstm_model, X_chunks_tensor, y_chunks_tensor, epochs=15)
        lstm_path = os.path.join(weights_dir, "behavioral_lstm.pt")
        lstm_model.save_weights(lstm_path)
        print(f"    Saved LSTM Weights -> {lstm_path}")

    # 5. Train GNN Model
    graph_tensors = graph_builder.to_torch_tensors()
    gnn_model = HeteroClickFraudGNN()
    train_gnn(gnn_model, graph_tensors, epochs=25)
    gnn_path = os.path.join(weights_dir, "gnn_model.pt")
    gnn_model.save_model(gnn_path)
    print(f"    Saved GNN Model -> {gnn_path}")

    # 6. Evaluation Benchmark
    print("\n=== EVALUATION RESULTS ON SIMULATED TRAFFIC ===")
    preds = tabular_model.model.predict(X_tab)
    probas = tabular_model.model.predict_proba(X_tab)[:, 1]
    roc = roc_auc_score(y_tab, probas)
    f1 = f1_score(y_tab, preds)
    prec = precision_score(y_tab, preds)
    rec = recall_score(y_tab, preds)

    print(f"    ROC-AUC:   {roc:.4f}")
    print(f"    F1-Score:  {f1:.4f}")
    print(f"    Precision: {prec:.4f}")
    print(f"    Recall:    {rec:.4f}")
    print("=== TRAINING COMPLETE ===")


if __name__ == "__main__":
    main()
