# Bot Detection Core: Multi-Modal Bot & Click Fraud Detection System

> **Khóa luận tốt nghiệp (2026):** Xây dựng mô hình phân biệt bot và người truy cập trang web  
> **Tác giả:** Thành (`btthanhk4`) | **GVHD:** Thầy Mai  
> **Dataset:** [Web Bot Detection Dataset (M4D-ITI)](https://m4d.iti.gr/web-bot-detection-dataset/)

## Tổng quan

Hệ thống phát hiện bot đa phương thức (multi-modal), kết hợp ba nhánh phân tích: hành vi chuột, đặc trưng trình duyệt và luật phát hiện automation.

| # | Thành phần | Vai trò | Ghi chú |
|---|------------|---------|---------|
| 1 | **Fingerprint collector** | Thu thập 25 trường tín hiệu phần cứng/trình duyệt | Tự triển khai, tham khảo [FingerprintJS](https://github.com/fingerprintjs/fingerprintjs) |
| 2 | **BotD heuristic detector** | 13 luật client-side: webdriver, headless, inconsistencies | Tự triển khai, tham khảo [BotD](https://github.com/fingerprintjs/BotD) |
| 3 | **Behavioral BiLSTM** | Phân tích quỹ đạo chuột bằng BiLSTM + Temporal Attention | Tự triển khai, tham khảo [DELBOT-Mouse](https://github.com/chrisgdt/DELBOT-Mouse) |
| 4 | **XGBoost** | Phân loại fingerprint và thống kê hành vi tổng hợp | Mô hình tabular được huấn luyện trong dự án |

---

## Kiến trúc hệ thống

```
┌──────────────────────────────────────────────────┐
│              DATA COLLECTION (collector/)          │
│ Fingerprint SDK │  BotD Heuristics  │  Mouse SDK  │
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

Live API verdicts use BiLSTM, XGBoost, and BotD heuristics.

---

## Cấu trúc Repository

```
bot-detection-core/
├── collector/                       # Client-side SDK thu thập tín hiệu
│   ├── src/
│   │   ├── fingerprint.js          # Thu thập 25 trường tín hiệu & hash visitorId
│   │   ├── botd.js                 # 13 luật heuristic phát hiện bot
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
│   │   └── mouse_features.py       # Mouse dynamics stats + chunks (20 + 8 dims)
│   ├── models/
│   │   ├── behavioral_lstm.py      # BiLSTM + TemporalAttention (v2)
│   │   ├── tabular_classifier.py   # XGBoost + StandardScaler (v2)
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
| **XGBoost (50 features)** | **1.0000** | **1.0000** | **0.0000** |
| BiLSTM (session aggregation) | 1.0000 | 0.9778 | 0.1250 |
| Production ensemble | 1.0000 | 1.0000 | 0.0000 |

Các số liệu trên được đo trên 90 session test độc lập (24 human, 66 bot). Đây là
kết quả trên dataset nghiên cứu, không phải cam kết hiệu năng trên traffic production.

**Top 5 Feature Importance (XGBoost):**
1. `std_speed` — Độ biến thiên tốc độ
2. `angular_entropy` — Entropy hướng di chuyển
3. `mean_accel` — Gia tốc trung bình
4. `jerk_mean` — Mức thay đổi gia tốc
5. `mean_speed` — Tốc độ trung bình

### 9 Thí nghiệm đánh giá

| # | Thí nghiệm | Kết quả chính |
|---|-------------|---------------|
| E1 | Baseline Comparison | ML **+42.6% AUC** so với rule-based tốt nhất |
| E2 | Concept Drift | ⚠️ Train moderate → Recall=**0%** trên advanced bot |
| E3 | Feature Ablation | Mouse dynamics alone = AUC **1.0** |
| E4 | Class Imbalance | Tỷ lệ bot:human 1:10: AUC=**0.9931**, Recall=**75%** |
| E5 | Early Detection | Model retrain ở 5 điểm: AUC=**0.9924** |
| E6 | Inference Latency | XGBoost **0.571ms**, BiLSTM **1.395ms** trung bình |
| E7 | ROC/FPR Analysis | Threshold chọn trên validation: **0.6**; test FPR=0 |
| E8 | Short Sessions | Model full-session ở 5 điểm có FPR **87.5%**; 24 điểm còn **8.33%** |
| E9 | Power User Test | **0% False Positive** trên power users |

> `core_ml/experiment_results.json` được tạo bởi pipeline dùng chung tập test độc lập.
> `EXPERIMENT_REPORT.md` vẫn là báo cáo lịch sử và cần được tái lập trước khi trích dẫn.

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
- **XGBoost:** Test AUC=1.0000 | Test F1=1.0000
- **BiLSTM:** Test AUC=1.0000 | Test F1=0.9778 (aggregated by session)
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
| `GET` | `/api/v1/traffic/timeline` | Lưu lượng phân loại theo khoảng thời gian |

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
    "mouse_points": 31,
    "records_received": 34,
    "decision_deferred": false,
    "minimum_mouse_points": 24
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
        autoSendInterval: 15000,
        idleHeartbeatInterval: 60000
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
