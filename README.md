# Bot Detection Core: Multi-Modal Bot & Click Fraud Detection System

> **Khóa luận tốt nghiệp (2026):** Xây dựng mô hình phân biệt bot và người truy cập trang web  
> **Tác giả:** Thành (`btthanhk4`) | **GVHD:** Thầy Mai  
> **Dataset:** [Web Bot Detection Dataset (M4D-ITI)](https://m4d.iti.gr/web-bot-detection-dataset/)

## Tổng quan

Hệ thống phát hiện bot đa phương thức (multi-modal), kết hợp sức mạnh từ 3 công nghệ mã nguồn mở và mạng nơ-ron đồ thị:

| # | Công nghệ | Vai trò | Nguồn |
|---|-----------|---------|-------|
| 1 | **FingerprintJS** | Thu thập ~40 đặc trưng phần cứng/trình duyệt | [GitHub](https://github.com/fingerprintjs/fingerprintjs) |
| 2 | **BotD** | 12+ luật heuristic client-side (webdriver, headless, inconsistencies) | [GitHub](https://github.com/fingerprintjs/BotD) |
| 3 | **DELBOT-Mouse** | Phân tích quỹ đạo chuột bằng BiLSTM + Temporal Attention | [GitHub](https://github.com/chrisgdt/DELBOT-Mouse) |
| 4 | **PyTorch Geometric** | Phát hiện botnet phối hợp qua đồ thị Device–IP–Session | [GitHub](https://github.com/pyg-team/pytorch_geometric) |

---

## Kiến trúc hệ thống

```
┌──────────────────────────────────────────────────┐
│              DATA COLLECTION (collector/)          │
│  FingerprintJS  │  BotD Heuristics  │  Mouse SDK  │
└────────┬────────┴──────────┬────────┴──────┬──────┘
         │     Telemetry JSON Payload        │
         ▼                                   ▼
┌──────────────────────────────────────────────────┐
│           FEATURE EXTRACTION (core_ml/features/)  │
│  Mouse Kinematics (8 dims/step + 17 stats)       │
│  Environment + BotD Fingerprint (26 dims)        │
│  Total: 43-dimensional feature vector            │
└────────┬────────────────────────────┬────────────┘
         │                            │
┌────────▼────────┐    ┌──────────────▼──────────────┐
│ BiLSTM + Attn   │    │  XGBoost (300 trees, d=6)   │
│ (sequence model)│    │  (tabular aggregate model)   │
└────────┬────────┘    └──────────────┬──────────────┘
         │                            │
┌────────▼────────────────────────────▼──────────────┐
│    ENSEMBLE — Confidence-based Adaptive Fusion      │
│    + BotD Heuristic Override                        │
│    → Verdict: HUMAN / SUSPECT / BOT                 │
└─────────────────────────────────────────────────────┘
```

---

## Cấu trúc Repository

```
bot-detection-core/
├── collector/                       # Client-side SDK thu thập tín hiệu
│   ├── src/
│   │   ├── fingerprint.js          # Thu thập ~40 đặc trưng & hash visitorId
│   │   ├── botd.js                 # 12 luật heuristic phát hiện bot
│   │   ├── mouse.js                # Mouse tracker + kinematic features
│   │   └── index.js                # Unified Collector SDK
│   └── dist/
│       └── bot-collector.js        # Standalone bundle nhúng vào web
│
├── core_ml/                         # ML Core — Models & Pipeline
│   ├── dataset/
│   │   └── loader.py               # Parser M4D dataset + synthetic generator
│   ├── features/
│   │   ├── env_features.py         # Environment/fingerprint vector (26 dims)
│   │   ├── mouse_features.py       # Mouse dynamics stats + chunks (17 + 8 dims)
│   │   └── graph_builder.py        # Heterogeneous graph construction
│   ├── models/
│   │   ├── behavioral_lstm.py      # BiLSTM + TemporalAttention (v2)
│   │   ├── tabular_classifier.py   # XGBoost + StandardScaler (v2)
│   │   ├── gnn_detector.py         # HeteroConv GNN + Residual (v2)
│   │   └── ensemble.py             # Confidence-based weighted fusion (v2)
│   ├── experiments/
│   │   └── run_all.py              # 9 thí nghiệm đánh giá toàn diện
│   ├── train.py                    # Training pipeline (v2)
│   └── weights/                    # Model weights (.pt, .joblib)
│
├── api_service/
│   └── main.py                     # FastAPI inference server
│
├── simulator/
│   └── run_simulation.py           # Bot traffic simulator & benchmark
│
├── EXPERIMENT_REPORT.md            # Báo cáo thí nghiệm chi tiết
├── requirements.txt
└── README.md
```

---

## Kết quả chính

### Training v2 (600 samples: 200 real M4D + 400 synthetic)

| Model | Val AUC-ROC | Val F1 | Val FPR |
|-------|-------------|--------|---------|
| **XGBoost (43 features)** | **0.9995** | **0.9773** | **0.0000** |
| BiLSTM (mouse chunks) | 0.8240 | 0.6752 | — |
| GNN (graph) | Loss=0.35 | — | — |

**Top 5 Feature Importance (XGBoost):**
1. `direction_changes_y` — Số lần đổi hướng theo trục Y
2. `direction_changes_x` — Số lần đổi hướng theo trục X
3. `std_speed` — Độ biến thiên tốc độ
4. `fonts_count` — Số font phát hiện (fingerprint)
5. `time_regularity` — **Feature mới v2** — std(dt)/mean(dt)

### 9 Thí nghiệm đánh giá

| # | Thí nghiệm | Kết quả chính |
|---|-------------|---------------|
| E1 | Baseline Comparison | ML **+33.1% AUC** so với rule-based |
| E2 | Concept Drift | ⚠️ Train moderate → Recall=**0%** trên advanced bot |
| E3 | Feature Ablation | Mouse dynamics alone = AUC **1.0** |
| E4 | Class Imbalance | Robust đến 1:10 (AUC=**0.97**) |
| E5 | Early Detection | Chỉ cần **5 mouse points** → AUC=**0.99** |
| E6 | Inference Latency | XGBoost **<1ms**, BiLSTM **<2ms** |
| E7 | ROC/FPR Analysis | Optimal threshold=**0.3**: FPR=0, TPR=1 |
| E8 | Short Sessions | Hoạt động tốt mọi độ dài |
| E9 | Power User Test | **0% False Positive** trên power users |

> Chi tiết đầy đủ: [EXPERIMENT_REPORT.md](EXPERIMENT_REPORT.md)

---

## Cài đặt & Sử dụng

### 1. Cài đặt môi trường

```bash
cd bot-detection-core
pip install -r requirements.txt
```

### 2. Huấn luyện mô hình

```bash
python -u -m core_ml.train
```

Kết quả huấn luyện v2:
- **XGBoost:** Val AUC=0.9995 | Test AUC=1.0000
- **BiLSTM:** 30 epochs, Early Stopping, CosineAnnealing LR
- **GNN:** 25 epochs, Loss 0.59→0.35
- Weights saved to `core_ml/weights/`

### 3. Chạy toàn bộ thí nghiệm

```bash
python -u -m core_ml.experiments.run_all
```

Kết quả JSON: `core_ml/experiment_results.json`

### 4. Khởi chạy API Server

```bash
uvicorn api_service.main:app --host 0.0.0.0 --port 8000 --reload
```

Swagger docs: `http://127.0.0.1:8000/docs`

### 5. Chạy Benchmark

```bash
python -m simulator.run_simulation --mode benchmark --endpoint http://127.0.0.1:8000/api/v1/detect --samples 20
```

---

## API Endpoints

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| `GET` | `/` | Health check + model status |
| `POST` | `/api/v1/detect` | Real-time bot classification |
| `POST` | `/api/v1/telemetry` | Asynchronous telemetry ingestion |
| `GET` | `/api/v1/graph/stats` | Graph topology & fraud ring indicators |

### Ví dụ Response từ `/api/v1/detect`

```json
{
  "is_bot": true,
  "verdict": "BOT",
  "bot_probability": 0.8155,
  "confidence": 0.631,
  "reasons": [
    "Flagged: platformMismatch",
    "Mouse dynamics exhibit robotic trajectory (LSTM score: 1.00)"
  ],
  "breakdown": {
    "behavioral_lstm_score": 1.0,
    "tabular_score": 0.782,
    "heuristic_score": 0.1,
    "has_enough_mouse_data": true,
    "mouse_points": 31
  },
  "latency_ms": 3.42
}
```

---

## Tích hợp vào Website

### Cách 1: Nhúng Script trực tiếp

```html
<script src="/bot-collector.js"></script>
<script>
  window.addEventListener('DOMContentLoaded', async () => {
    if (window.BotCollector) {
      const collector = new window.BotCollector({
        endpointUrl: 'https://<API_URL>/api/v1/telemetry',
        detectUrl: 'https://<API_URL>/api/v1/detect',
        autoSendInterval: 5000
      });
      await collector.init();
    }
  });
</script>
```

### Cách 2: React Hook

```jsx
import { useEffect } from 'react';
import { BotCollector } from '../path/to/collector/src/index.js';

export function useBotProtection() {
  useEffect(() => {
    const collector = new BotCollector({
      endpointUrl: 'https://api-bot.yourdomain.com/api/v1/telemetry',
      detectUrl: 'https://api-bot.yourdomain.com/api/v1/detect',
    });
    collector.init();
    return () => collector.destroy();
  }, []);
}
```

---

## Tài liệu tham khảo

1. [FingerprintJS](https://github.com/fingerprintjs/fingerprintjs) — Browser fingerprinting library
2. [BotD](https://github.com/fingerprintjs/BotD) — Bot detection heuristics
3. [DELBOT-Mouse](https://github.com/chrisgdt/DELBOT-Mouse) — Mouse trajectory analysis
4. [Web Bot Detection Dataset (M4D-ITI)](https://m4d.iti.gr/web-bot-detection-dataset/)
5. [FP-Inconsistent (arXiv:2406.07647)](https://arxiv.org/pdf/2406.07647) — Fingerprint consistency checking
6. [Server-side Bot Feature Taxonomy](https://consensus.app/papers/a-taxonomy-and-feature-set-for-serverside-identification-smutz/d55322076b41592796803df678eb9ea5/)

---

## License

Dự án này được phát triển phục vụ mục đích học thuật (khóa luận tốt nghiệp).
