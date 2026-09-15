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
│  Mouse Kinematics (8 dims/step + 20 stats)       │
│  Environment + BotD Fingerprint (30 dims)        │
│  Total: 50-dimensional feature vector            │
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

The GNN architecture is retained as an offline research component, but no weight is
shipped because the public mouse dataset has no observed device/IP/target graph.
Live API verdicts use BiLSTM, XGBoost, and BotD heuristics.

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
│   │   ├── env_features.py         # Environment/fingerprint vector (30 dims)
│   │   ├── mouse_features.py       # Mouse dynamics stats + chunks (20 + 8 dims)
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

### Training v2 (749 samples: 449 real M4D + 300 synthetic)

| Model | Test AUC-ROC | Test F1 | Test FPR |
|-------|-------------|--------|---------|
| **XGBoost (50 features)** | **0.9931** | **0.9924** | **0.0000** |
| BiLSTM (session aggregation) | 0.9962 | 0.9924 | 0.0000 |

**Top 5 Feature Importance (XGBoost):**
1. `std_speed` — Độ biến thiên tốc độ
2. `fonts_count` — Số font trình duyệt phát hiện được
3. `straightness` — Độ thẳng của quỹ đạo
4. `max_speed` — Tốc độ cực đại
5. `mean_accel` — Gia tốc trung bình

### 9 Thí nghiệm đánh giá

| # | Thí nghiệm | Kết quả chính |
|---|-------------|---------------|
| E1 | Baseline Comparison | ML **+50.5% AUC** so với rule-based |
| E2 | Concept Drift | ⚠️ Train moderate → Recall=**0%** trên advanced bot |
| E3 | Feature Ablation | Mouse dynamics alone = AUC **1.0** |
| E4 | Class Imbalance | Robust đến 1:10 (AUC=**0.97**) |
| E5 | Early Detection | Chỉ cần **5 mouse points** → AUC=**0.9968** |
| E6 | Inference Latency | XGBoost **1.668ms**, BiLSTM **4.820ms** trung bình |
| E7 | ROC/FPR Analysis | Threshold **0.4**: FPR=0, TPR=0.9932 |
| E8 | Short Sessions | Hoạt động tốt mọi độ dài |
| E9 | Power User Test | **0% False Positive** trên power users |

> `core_ml/experiment_results.json` và `EXPERIMENT_REPORT.md` là artifact lịch sử
> của pipeline random-split cũ. Cần chạy lại E1-E9 trước khi trích dẫn các kết quả này.

---

## Cài đặt & Sử dụng

### 1. Cài đặt môi trường

```bash
cd bot-detection-core
pip install -r requirements.txt
```

Set `BOT_READ_TOKEN` for dashboard data access and `BOT_ADMIN_TOKEN` for delete
actions. Docker Compose publishes port `8000`; production should put this port
behind an HTTPS reverse proxy. Copy the values from `.env.example` into the
server environment and restrict `BOT_CORS_ORIGINS` to trusted website origins.

### 2. Huấn luyện mô hình

```bash
python -u -m core_ml.train --dataset-root "/path/to/web_bot_detection_dataset"
```

Kết quả huấn luyện v2:
- **XGBoost:** Test AUC=0.9931 | Test F1=0.9924
- **BiLSTM:** Test AUC=0.9962 | Test F1=0.9924 (aggregated by session)
- **GNN:** not trained; real graph relationships are required to avoid target leakage
- Weights saved to `core_ml/weights/`

### 3. Chạy toàn bộ thí nghiệm

```bash
python -u -m core_ml.experiments.run_all --dataset-root "/path/to/web_bot_detection_dataset"
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
