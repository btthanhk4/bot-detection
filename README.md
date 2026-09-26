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

**Policy v5 hiện tại:** Ngưỡng BOT là `0.93` (điểm rủi ro, không phải xác suất đã
calibrate). Train bổ sung các cửa sổ 25/50/100 điểm chỉ từ phiên train. Trên
validation cùng nguồn với 25 điểm chuột: `TN=14, FP=0, FN=7, TP=39`; trên test
cùng nguồn với phiên đầy đủ: `TN=24, FP=0, FN=10, TP=56`. Release gate kiểm tra
cả phiên và các mốc 25/50/100 điểm trên validation. Xem JSON report bên dưới.
Đây là sự đánh đổi có chủ đích:
giảm gắn nhầm người thật, chấp nhận nhiều bot nằm ở mức SUSPECT cho đến khi có
thêm bằng chứng. Tập test đã được xem khi phát triển và không còn là blind test.
Dữ liệu touch được tách khỏi model chuột; các phiên touch-only sẽ chờ kết luận.
Tín hiệu tự động hóa do BotD báo chỉ có thể nâng nhãn HUMAN lên SUSPECT, không
tự ép kết luận BOT khi hai mô hình ML không đồng ý.

| Model | Test AUC-ROC | Test F1 | Test FPR |
|-------|-------------|--------|---------|
| **XGBoost (50 features)** | **1.0000** | **1.0000** | **0.0000** |
| BiLSTM (session aggregation) | 1.0000 | 1.0000 | 0.0000 |
| Ensemble policy v5 trên test cùng nguồn | 1.0000 | 0.9180 | 0.0000 |

Các số liệu trên được đo trên 90 session test tách khỏi train (24 human, 66 bot)
nhưng cùng nguồn dataset nghiên cứu. Tập này đã được xem trong quá trình sửa
policy, nên không còn là test mù để chứng minh hiệu năng production.
Ở 25 điểm `move` trên validation cùng nguồn, policy v2 (ngưỡng 0.70) gắn nhầm
3/14 người thật và bỏ sót 3/46 bot; policy v5 gắn nhầm 0/14 nhưng bỏ sót 7/46.
Xem
[`heldout_evaluation.json`](core_ml/heldout_evaluation.json) và
[`early_session_validation.json`](core_ml/early_session_validation.json).
Không dùng `is_bot` để tự động chặn khi chưa kiểm định trên dữ liệu thực tế
độc lập, đặc biệt với các phiên ngắn, touch hoặc thiếu dữ liệu.
Artifact đi kèm đã qua release gate trên validation cùng nguồn. `/health` báo
`release_gate_evidence_present: true` khi chạy với đúng ngưỡng 0.93, nhưng đây
chưa phải kiểm định độc lập trên traffic thực tế; không dùng kết quả này để tự
động chặn người dùng mà không có bước theo dõi và xác minh bổ sung.

**Top 5 Feature Importance (XGBoost):**
1. `std_speed` — Độ biến thiên tốc độ
2. `straightness` — Độ thẳng của quỹ đạo
3. `fonts_count` — Số lượng phông chữ trình duyệt báo cáo
4. `angular_entropy` — Entropy hướng di chuyển
5. `mean_accel` — Gia tốc trung bình

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
  "bot_probability": 0.9355,
  "risk_score": 0.9355,
  "score_calibrated": false,
  "policy_version": "5",
  "decision_state": "FINAL",
  "confidence": 0.871,
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
    "minimum_mouse_points": 25
  },
  "latency_ms": 3.42
}
```

`bot_probability` được giữ lại để tương thích API cũ, nhưng hiện là điểm rủi ro
chưa hiệu chuẩn, không phải xác suất bot thống kê. `confidence` là độ lệch
của điểm so với 0.5. Khi thiếu 25 điểm `move`, thiếu model hoặc đầu vào touch/mobile,
`decision_state` là `INSUFFICIENT_EVIDENCE`, `verdict` tạm là `SUSPECT` để tương thích; không
nên dùng giá trị `bot_probability` để chặn người dùng trong trạng thái này.

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
