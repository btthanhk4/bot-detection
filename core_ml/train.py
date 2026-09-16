"""
Training Pipeline for Multi-Modal Bot Detection & Graph Neural Network (v2)
============================================================================
Major improvements:
  1. Published test split preservation and leakage-safe stratification
  2. Real data ingestion from web_bot_detection_dataset
  3. Learning rate scheduling (CosineAnnealing)
  4. Early stopping on validation loss
  5. Gradient clipping (max_norm=1.0)
  6. StratifiedKFold cross-validation for robust evaluation
  7. Full metrics: ROC-AUC, F1, Precision, Recall on val/test sets
"""

import os
import sys
import random
import hashlib
import json
import argparse
import numpy as np

# Ensure utf-8 encoding for Windows console
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
from sklearn.metrics import roc_auc_score, f1_score, precision_score, recall_score, confusion_matrix
from sklearn.model_selection import train_test_split

from core_ml.dataset.loader import (
    RealMouseSession,
    generate_synthetic_telemetry,
    load_real_dataset,
    records_to_chunks,
)
from core_ml.features.env_features import extract_env_vector, FEATURE_NAMES as ENV_FEATURE_NAMES
from core_ml.features.mouse_features import (
    extract_sequential_chunks,
    extract_mouse_stat_vector,
    STATISTICAL_FEATURE_NAMES,
)
from core_ml.models.behavioral_lstm import MouseTrajectoryLSTM
from core_ml.models.tabular_classifier import TabularBotClassifier

# Reproducibility
SEED = 42
random.seed(SEED)
np.random.seed(SEED)
torch.manual_seed(SEED)


MOUSE_STAT_FEATURE_NAMES = list(STATISTICAL_FEATURE_NAMES)


def records_signature(records: list) -> str:
    payload = json.dumps(records, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def deduplicate_real_sessions(sessions: list[RealMouseSession]) -> list[RealMouseSession]:
    """Deduplicate trajectories across scenarios without hiding label conflicts."""
    unique = {}
    for session in sessions:
        signature = records_signature(session.records)
        existing = unique.get(signature)
        if existing is None:
            unique[signature] = session
            continue
        if existing.label != session.label:
            raise ValueError(
                f"Conflicting labels for duplicate trajectory: {existing.session_id} / {session.session_id}"
            )
        # A trajectory marked as official test must never be downgraded to train.
        if session.split == "test" and existing.split != "test":
            unique[signature] = session
    return list(unique.values())


def assign_real_session_splits(sessions: list[RealMouseSession], seed: int = SEED) -> list[str]:
    """Preserve official splits and stratify data that has no published split."""
    assignments = [session.split for session in sessions]

    def stable_order(indices):
        return sorted(
            indices,
            key=lambda idx: hashlib.sha256(
                f"{seed}:{sessions[idx].source}:{sessions[idx].session_id}".encode("utf-8")
            ).digest(),
        )

    for label in (0, 1):
        official_train = stable_order([
            idx for idx, session in enumerate(sessions)
            if session.source == "phase1" and session.split == "train" and session.label == label
        ])
        n_val = max(1, round(len(official_train) * 0.15)) if len(official_train) >= 2 else 0
        for idx in official_train[:n_val]:
            assignments[idx] = "val"

        unspecified = stable_order([
            idx for idx, session in enumerate(sessions)
            if session.split == "unspecified" and session.label == label
        ])
        if len(unspecified) >= 3:
            n_test = max(1, round(len(unspecified) * 0.15))
            n_val = max(1, round(len(unspecified) * 0.15))
            for idx in unspecified[:n_test]:
                assignments[idx] = "test"
            for idx in unspecified[n_test:n_test + n_val]:
                assignments[idx] = "val"
            for idx in unspecified[n_test + n_val:]:
                assignments[idx] = "train"
        else:
            for idx in unspecified:
                assignments[idx] = "train"

    return assignments


def resolve_training_indices(labels, splits, seed: int = SEED):
    """Return non-empty train/validation/test indices while preserving a usable official test split."""
    labels = np.asarray(labels)
    splits = np.asarray(splits)
    indices = np.arange(len(labels))
    idx_test = indices[splits == "test"]
    remaining = indices[splits != "test"]
    generated_test = len(idx_test) == 0

    try:
        if not generated_test and len(np.unique(labels[idx_test])) != 2:
            raise ValueError("Official test split must contain both labels")
        if generated_test:
            remaining, idx_test = train_test_split(
                indices, test_size=0.15, stratify=labels, random_state=seed
            )

        idx_train = indices[splits == "train"]
        idx_val = indices[splits == "val"]
        usable_validation = (
            not generated_test
            and len(idx_train) > 0
            and len(idx_val) > 0
            and len(np.unique(labels[idx_train])) == 2
            and len(np.unique(labels[idx_val])) == 2
        )
        if not usable_validation:
            idx_train, idx_val = train_test_split(
                remaining, test_size=0.15, stratify=labels[remaining], random_state=seed
            )
    except ValueError as exc:
        raise ValueError(
            "Dataset is too small or imbalanced for leakage-safe train/validation/test splits"
        ) from exc

    return np.asarray(idx_train), np.asarray(idx_val), np.asarray(idx_test)


def build_tabular_vector(fingerprint: dict, botd: dict, records: list) -> np.ndarray:
    """Build combined env + mouse stats feature vector using canonical extractor."""
    env_vec = extract_env_vector(fingerprint, botd)
    mouse_stat_vec = extract_mouse_stat_vector(records)
    return np.concatenate([env_vec, mouse_stat_vec])


def train_lstm(lstm_model, X_train, y_train, X_val, y_val,
               epochs=30, batch_size=32, lr=0.002, patience=7):
    """Train LSTM with early stopping and LR scheduling."""
    print("--> Training Behavioral BiLSTM Model...")

    train_dataset = TensorDataset(X_train, y_train)
    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True, drop_last=False)

    criterion = nn.BCELoss()
    optimizer = torch.optim.AdamW(lstm_model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs, eta_min=1e-5)

    best_val_loss = float('inf')
    best_state = None
    patience_counter = 0

    lstm_model.train()
    for epoch in range(epochs):
        total_loss = 0.0
        for batch_x, batch_y in train_loader:
            optimizer.zero_grad()
            preds = lstm_model(batch_x)
            bce_loss = criterion(preds.squeeze(-1), batch_y)
            reg_loss = lstm_model.get_regularization_loss()
            loss = bce_loss + reg_loss
            loss.backward()
            # Gradient clipping
            torch.nn.utils.clip_grad_norm_(lstm_model.parameters(), max_norm=1.0)
            optimizer.step()
            total_loss += bce_loss.item()

        scheduler.step()

        # Validation
        lstm_model.eval()
        with torch.no_grad():
            val_preds = lstm_model(X_val).squeeze(-1)
            val_loss = criterion(val_preds, y_val).item()
        lstm_model.train()

        # Early stopping
        if val_loss < best_val_loss - 1e-4:
            best_val_loss = val_loss
            best_state = {k: v.clone() for k, v in lstm_model.state_dict().items()}
            patience_counter = 0
        else:
            patience_counter += 1

        if (epoch + 1) % 5 == 0 or epoch == epochs - 1:
            lr_now = scheduler.get_last_lr()[0]
            print(f"    Epoch [{epoch+1}/{epochs}] Train: {total_loss/len(train_loader):.4f} | Val: {val_loss:.4f} | LR: {lr_now:.6f} | Patience: {patience_counter}/{patience}")

        if patience_counter >= patience:
            print(f"    Early stopping at epoch {epoch+1}")
            break

    # Restore best model
    if best_state is not None:
        lstm_model.load_state_dict(best_state)
    lstm_model.eval()


def train_tabular(tabular_model, X_train, y_train, X_val, y_val, feature_names=None):
    """Train XGBoost with validation set."""
    print("--> Training Tabular XGBoost Classifier...")
    tabular_model.fit(X_train, y_train, feature_names=feature_names, X_val=X_val, y_val=y_val)
    importances = tabular_model.get_feature_importances()
    top5 = list(importances.items())[:5]
    print(f"    Top 5 Features: {top5}")


def train_gnn(gnn_model, graph_data, train_indices=None, val_indices=None, test_indices=None, epochs=30, lr=0.01):
    """Train GNN without using validation/test labels in the loss."""
    print("--> Training HeteroClickFraudGNN Model...")
    x_dict = graph_data["x_dict"]
    edge_index_dict = graph_data["edge_index_dict"]
    y_session = graph_data["y_session"]

    if y_session.numel() == 0:
        print("    No session labels found in graph. Skipping GNN training.")
        return

    train_indices = torch.as_tensor(
        train_indices if train_indices is not None else np.arange(len(y_session)), dtype=torch.long
    )
    val_indices = torch.as_tensor(val_indices if val_indices is not None else [], dtype=torch.long)
    test_indices = torch.as_tensor(test_indices if test_indices is not None else [], dtype=torch.long)

    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(gnn_model.parameters(), lr=lr, weight_decay=1e-4)

    gnn_model.train()
    for epoch in range(epochs):
        optimizer.zero_grad()
        logits = gnn_model(x_dict, edge_index_dict)
        loss = criterion(logits[train_indices], y_session[train_indices])
        loss.backward()
        torch.nn.utils.clip_grad_norm_(gnn_model.parameters(), max_norm=1.0)
        optimizer.step()
        if (epoch + 1) % 10 == 0 or epoch == epochs - 1:
            print(f"    GNN Epoch [{epoch+1}/{epochs}] Loss: {loss.item():.4f}")

    gnn_model.eval()
    if val_indices.numel() > 0:
        with torch.no_grad():
            val_proba = gnn_model.predict_session_probabilities(x_dict, edge_index_dict)[val_indices].numpy()
        evaluate_metrics(y_session[val_indices].numpy(), val_proba, prefix="[Val GNN] ")
    if test_indices.numel() > 0:
        with torch.no_grad():
            test_proba = gnn_model.predict_session_probabilities(x_dict, edge_index_dict)[test_indices].numpy()
        evaluate_metrics(y_session[test_indices].numpy(), test_proba, prefix="[Test GNN] ")


def evaluate_metrics(y_true, y_pred_proba, threshold=0.5, prefix=""):
    """Compute and print all classification metrics."""
    y_pred = (y_pred_proba >= threshold).astype(int)
    metrics = {}
    try:
        metrics["roc_auc"] = roc_auc_score(y_true, y_pred_proba)
    except ValueError:
        metrics["roc_auc"] = 0.0
    metrics["f1"] = f1_score(y_true, y_pred, zero_division=0)
    metrics["precision"] = precision_score(y_true, y_pred, zero_division=0)
    metrics["recall"] = recall_score(y_true, y_pred, zero_division=0)
    metrics["accuracy"] = np.mean(y_true == y_pred)

    cm = confusion_matrix(y_true, y_pred, labels=[0, 1])

    print(f"    {prefix}ROC-AUC:   {metrics['roc_auc']:.4f}")
    print(f"    {prefix}F1-Score:  {metrics['f1']:.4f}")
    print(f"    {prefix}Precision: {metrics['precision']:.4f}")
    print(f"    {prefix}Recall:    {metrics['recall']:.4f}")
    print(f"    {prefix}Accuracy:  {metrics['accuracy']:.4f}")
    print(f"    {prefix}Confusion Matrix:")
    print(f"      [[TN={cm[0,0]:3d}  FP={cm[0,1]:3d}]")
    print(f"       [FN={cm[1,0]:3d}  TP={cm[1,1]:3d}]]")
    return metrics


def predict_lstm_sessions(lstm_model, chunks_tensor, chunk_session_indices, session_indices, labels):
    """Aggregate chunk predictions exactly as the production detector does."""
    chunk_sessions = np.asarray(chunk_session_indices)
    probabilities = []
    session_labels = []
    for session_idx in session_indices:
        positions = np.flatnonzero(chunk_sessions == int(session_idx))
        if positions.size == 0:
            continue
        probabilities.append(lstm_model.predict_session_proba(chunks_tensor[positions.tolist()]))
        session_labels.append(int(labels[int(session_idx)]))
    return np.asarray(session_labels, dtype=int), np.asarray(probabilities, dtype=float)


def main(dataset_root=None):
    print("=" * 60)
    print("  BOT DETECTION CORE — TRAINING PIPELINE v2")
    print("=" * 60)

    weights_dir = os.path.join(os.path.dirname(__file__), "weights")
    os.makedirs(weights_dir, exist_ok=True)

    # ================================================================
    # PHASE 1: Data Preparation
    # ================================================================
    print("\n[PHASE 1] Data Preparation")

    # 1a. Try to load real dataset (Phase 1 + Phase 2)
    real_data_root = dataset_root or os.getenv("BOT_DATASET_ROOT", "")
    real_sessions = []
    if os.path.isdir(real_data_root):
        print("  Loading real mouse data from web_bot_detection_dataset...")
        for scenario in ["humans_and_moderate_bots", "humans_and_advanced_bots"]:
            sessions = load_real_dataset(real_data_root, scenario=scenario,
                                          include_phase2=True, with_metadata=True)
            real_sessions.extend(sessions)
        real_sessions = deduplicate_real_sessions(real_sessions)
        n_real_h = sum(1 for session in real_sessions if session.label == 0)
        n_real_b = sum(1 for session in real_sessions if session.label == 1)
        print(f"  Loaded {len(real_sessions)} real sessions ({n_real_h} Human + {n_real_b} Bot)")
    else:
        print("  Real dataset not found. Using synthetic data only.")

    # 1b. Generate synthetic data (reduced ratio since real data is now larger)
    print("  Generating synthetic training samples...")
    all_telemetries = []
    all_labels = []
    all_splits = []

    n_synthetic = 150 if real_sessions else 300

    for sample_idx in range(n_synthetic):
        t = generate_synthetic_telemetry(is_bot=False)
        t["sessionId"] = f"synthetic_human_{sample_idx}"
        all_telemetries.append(t)
        all_labels.append(0)
        all_splits.append("train")

    for sample_idx in range(n_synthetic):
        level = random.choice(["naive", "moderate", "advanced"])
        t = generate_synthetic_telemetry(is_bot=True, bot_level=level)
        t["sessionId"] = f"synthetic_bot_{sample_idx}"
        all_telemetries.append(t)
        all_labels.append(1)
        all_splits.append("train")

    # 1c. Build real data telemetry payloads
    real_splits = assign_real_session_splits(real_sessions)
    for real_idx, (session, split) in enumerate(zip(real_sessions, real_splits)):
        records, label = session.records, session.label
        # Create telemetry-like structure from real mouse data
        chunks = records_to_chunks(records, chunk_size=24, stride=12)
        telemetry = {
            "sessionId": f"real_{real_idx}",
            "visitorId": f"fp_real_{real_idx}",
            "timestamp": 1725800000000,
            "pageUrl": "https://example.com/test",
            "fingerprint": {},  # No fingerprint data for real sessions
            "botd": {"heuristicScore": 0.0, "flaggedCount": 0, "detectors": {}, "reasons": []},
            "mouse": {"records": records, "chunks": chunks},
        }
        all_telemetries.append(telemetry)
        all_labels.append(label)
        all_splits.append(split)

    print(f"  Total samples: {len(all_telemetries)} (Humans: {all_labels.count(0)}, Bots: {all_labels.count(1)})")

    # ================================================================
    # PHASE 2: Feature Extraction
    # ================================================================
    print("\n[PHASE 2] Feature Extraction")

    X_tab_list = []
    all_chunks = []
    all_chunk_labels = []
    all_chunk_session_indices = []

    feature_names = list(ENV_FEATURE_NAMES) + MOUSE_STAT_FEATURE_NAMES

    total_samples = len(all_telemetries)
    for idx, (t, label) in enumerate(zip(all_telemetries, all_labels)):
        if (idx + 1) % 100 == 0 or idx == 0:
            print(f"  Processing sample {idx+1}/{total_samples}...")
        fp = t.get("fingerprint", {})
        bd = t.get("botd", {})
        mouse = t.get("mouse", {})
        records = mouse.get("records", [])
        chunks = mouse.get("chunks", [])

        # Tabular feature vector
        tab_vec = build_tabular_vector(fp, bd, records)
        X_tab_list.append(tab_vec)

        # LSTM chunks (cap at 10 per session to keep training fast on CPU)
        tensor_c = extract_sequential_chunks(chunks)
        if tensor_c.size(0) > 0:
            max_chunks_per_session = 10
            if tensor_c.size(0) > max_chunks_per_session:
                perm_idx = torch.randperm(tensor_c.size(0))[:max_chunks_per_session]
                tensor_c = tensor_c[perm_idx]
            for c in tensor_c:
                all_chunks.append(c)
                all_chunk_labels.append(label)
                all_chunk_session_indices.append(idx)

    X_tab = np.array(X_tab_list, dtype=np.float32)
    y_tab = np.array(all_labels, dtype=int)

    # Replace NaN/Inf
    X_tab = np.nan_to_num(X_tab, nan=0.0, posinf=100.0, neginf=-100.0)

    print(f"  Tabular features: {X_tab.shape}")
    print(f"  LSTM chunks: {len(all_chunks)}")
    print(f"  Feature names: {len(feature_names)}")

    # ================================================================
    # PHASE 3: Train/Val/Test Split (Stratified)
    # ================================================================
    print("\n[PHASE 3] Leakage-safe Train/Val/Test Split")

    if real_sessions:
        idx_train, idx_val, idx_test = resolve_training_indices(y_tab, all_splits)
    else:
        indices = np.arange(len(y_tab))
        idx_train, idx_temp = train_test_split(
            indices, test_size=0.30, stratify=y_tab, random_state=SEED
        )
        idx_val, idx_test = train_test_split(
            idx_temp, test_size=0.50, stratify=y_tab[idx_temp], random_state=SEED
        )

    X_train_tab, X_val_tab, X_test_tab = X_tab[idx_train], X_tab[idx_val], X_tab[idx_test]
    y_train_tab, y_val_tab, y_test_tab = y_tab[idx_train], y_tab[idx_val], y_tab[idx_test]

    print(f"  Train: {len(idx_train)} | Val: {len(idx_val)} | Test: {len(idx_test)}")
    print(f"  Train dist: H={sum(y_train_tab==0)} B={sum(y_train_tab==1)} | Val dist: H={sum(y_val_tab==0)} B={sum(y_val_tab==1)} | Test dist: H={sum(y_test_tab==0)} B={sum(y_test_tab==1)}")

    # ================================================================
    # PHASE 4: Train Tabular Classifier
    # ================================================================
    print("\n[PHASE 4] Training Models")

    tabular_model = TabularBotClassifier(
        n_estimators=300,
        max_depth=6,
        scale_pos_weight=sum(y_train_tab == 0) / max(1, sum(y_train_tab == 1)),
    )
    train_tabular(tabular_model, X_train_tab, y_train_tab, X_val_tab, y_val_tab, feature_names=feature_names)
    tabular_path = os.path.join(weights_dir, "tabular_model.joblib")
    tabular_model.save(tabular_path)
    print(f"    Saved Tabular Model -> {tabular_path}")

    # ================================================================
    # PHASE 5: Train Behavioral BiLSTM
    # ================================================================
    lstm_trained = False
    if all_chunks:
        X_chunks_tensor = torch.stack(all_chunks)
        y_chunks_tensor = torch.tensor(all_chunk_labels, dtype=torch.float32)

        # Keep every chunk from a session in the same split to avoid leakage.
        train_sessions = set(idx_train.tolist())
        val_sessions = set(idx_val.tolist())
        test_sessions = set(idx_test.tolist())
        train_idx = torch.tensor(
            [i for i, session_idx in enumerate(all_chunk_session_indices) if session_idx in train_sessions],
            dtype=torch.long,
        )
        val_idx = torch.tensor(
            [i for i, session_idx in enumerate(all_chunk_session_indices) if session_idx in val_sessions],
            dtype=torch.long,
        )
        test_idx = torch.tensor(
            [i for i, session_idx in enumerate(all_chunk_session_indices) if session_idx in test_sessions],
            dtype=torch.long,
        )

        X_chunks_train = X_chunks_tensor[train_idx]
        y_chunks_train = y_chunks_tensor[train_idx]
        X_chunks_val = X_chunks_tensor[val_idx]
        y_chunks_val = y_chunks_tensor[val_idx]
        print(f"    LSTM chunks — Train: {len(train_idx)} | Val: {len(val_idx)} | Test: {len(test_idx)}")

        lstm_model = MouseTrajectoryLSTM(input_dim=8, hidden_dim=64)
        if len(train_idx) and len(val_idx):
            train_lstm(lstm_model, X_chunks_train, y_chunks_train, X_chunks_val, y_chunks_val,
                       epochs=30, patience=7)
            lstm_trained = True
            lstm_path = os.path.join(weights_dir, "behavioral_lstm.pt")
            lstm_model.save_weights(lstm_path)
            print(f"    Saved LSTM Weights -> {lstm_path}")
        else:
            print("    Insufficient session-separated chunks; leaving LSTM untrained.")
    else:
        print("    No LSTM chunks available for training.")
        lstm_model = MouseTrajectoryLSTM()

    # A GNN requires observed device/IP/target relationships. The public mouse
    # dataset has none, so synthesizing graph edges from labels would leak the
    # target into model inputs. Train it separately only on real graph data.
    print("\n[PHASE 6] Skipping GNN: no observed graph relationships in this dataset")

    # ================================================================
    # PHASE 7: Evaluation on Train/Val/Test
    # ================================================================
    print("\n" + "=" * 60)
    print("  EVALUATION RESULTS")
    print("=" * 60)

    # Tabular evaluation
    for name, X_set, y_set in [
        ("Train", X_train_tab, y_train_tab),
        ("Val", X_val_tab, y_val_tab),
        ("Test", X_test_tab, y_test_tab),
    ]:
        print(f"\n  --- {name} Set (Tabular XGBoost) ---")
        probas = tabular_model.predict_batch(X_set)
        evaluate_metrics(y_set, probas, prefix=f"[{name}] ")

    # LSTM evaluation on sessions, matching production aggregation.
    if all_chunks and lstm_trained:
        print("\n  --- Val Set (BiLSTM by session) ---")
        lstm_val_true, lstm_val_preds = predict_lstm_sessions(
            lstm_model, X_chunks_tensor, all_chunk_session_indices, idx_val, y_tab
        )
        if len(lstm_val_true):
            evaluate_metrics(lstm_val_true, lstm_val_preds, prefix="[Val LSTM] ")
        if len(idx_test):
            lstm_test_true, lstm_test_preds = predict_lstm_sessions(
                lstm_model, X_chunks_tensor, all_chunk_session_indices, idx_test, y_tab
            )
            if len(lstm_test_true):
                print("\n  --- Test Set (BiLSTM by session) ---")
                evaluate_metrics(lstm_test_true, lstm_test_preds, prefix="[Test LSTM] ")

    print("\n" + "=" * 60)
    print("  TRAINING COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train bot detection models")
    parser.add_argument("--dataset-root", default=os.getenv("BOT_DATASET_ROOT", ""))
    args = parser.parse_args()
    main(dataset_root=args.dataset_root)
