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
| 4 | **XGBoost** | Phân loại thống kê chuyển động chuột; không học fingerprint synthetic thiếu nhãn thực | Mô hình tabular được huấn luyện trong dự án |

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
│  Environment + BotD reserved (30 dims)           │
│  Total: 50-dimensional feature vector            │
└────────┬────────────────────────────┬────────────┘
         │                            │
┌────────▼────────┐    ┌──────────────▼──────────────┐
│ BiLSTM + Attn   │    │  XGBoost (300 trees, d=6)   │
│ (sequence model)│    │  (tabular aggregate model)   │
└────────┬────────┘    └──────────────┬──────────────┘
         │                            │
┌────────▼────────────────────────────▼──────────────┐
│    ENSEMBLE — Fixed ML weights + BotD evidence       │
│    + decision evidence gate                         │
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
│   │   └── ensemble.py             # Monotonic BotD evidence fusion (v7)
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

### Policy v10 (current)

The bundled model uses BOT threshold `0.96`, SUSPECT threshold `0.45`, and
monotonic BiLSTM mean/p75 evidence with an abstention rule for model disagreement.
Its release gate replays 1,000 checkpoints from each complete validation and
test session, including known regression windows. A narrow explicit-automation
rule can identify a self-declared HeadlessChrome browser with corroborating
framework markers even without mouse input; ordinary no-mouse visits remain
SUSPECT. See [No-mouse decisions](docs/NO_MOUSE_BOT_DECISION.md) and
[Model release v10](docs/MODEL_RELEASE_V10.md) for measured outcomes and limits.
These same-source splits have been used to select policy values and do not
constitute independent production validation.

During a MongoDB outage, acknowledged telemetry is committed to the local
SQLite spool on a persistent Docker volume. Keep the API on one host/worker;
the spool is not a distributed queue.

### Historical policy v7 (749 samples: 449 real M4D + 300 synthetic)

**Policy v7 lịch sử:** Ngưỡng BOT là `0.93` (điểm rủi ro, không phải xác suất đã
hiệu chuẩn). XGBoost chỉ học 20 đặc trưng thống kê chuột vì các phiên thực có nhãn
không kèm fingerprint; 30 cột môi trường vẫn giữ trong schema nhưng không được cây
sử dụng. BotD tiếp tục cung cấp bằng chứng dương qua nhánh heuristic riêng.
Train bổ sung cửa sổ đầu phiên, cửa sổ cuốn giữa phiên và biến thể thời gian chỉ
từ tập train. Release gate kiểm tra cả các cửa sổ giữa phiên trên validation và test.
Chi tiết phép đo và giới hạn: [Model release v7](docs/MODEL_RELEASE_V7.md).
Dữ liệu touch được tách khỏi model chuột; các phiên touch-only giữ nhãn SUSPECT.
Quỹ đạo trùng lặp hoặc không có biến thiên thời gian/vị trí cũng giữ SUSPECT.
BotD chỉ tăng điểm theo bằng chứng dương; khi chưa có quỹ đạo chuột hợp lệ,
BotD đơn lẻ không tự quyết định nhãn BOT. Policy v10 có ngoại lệ hẹp cho
HeadlessChrome tự khai báo cùng tín hiệu framework như mô tả ở trên.

| Model | Test AUC-ROC | Test F1 | Test FPR |
|-------|-------------|--------|---------|
| **XGBoost (20/50 cột học từ chuột)** | **1.0000** | **1.0000** | **0.0000** |
| BiLSTM (session aggregation) | 0.9994 | 0.9778 | 0.1250 |
| Ensemble policy v7 trên test cùng nguồn | 1.0000 | 0.9846 | 0.0000 |

Các số liệu trên được đo trên 90 session test tách khỏi train (24 human, 66 bot)
nhưng cùng nguồn dataset nghiên cứu. Tập này đã được xem trong quá trình sửa
policy, nên không còn là test mù để chứng minh hiệu năng production.
Ở 25 điểm `move` trên validation cùng nguồn, policy v7 gắn nhầm 0/14 người thật
thành BOT và giữ 1/46 bot ở mức không phải BOT. Replay 25 cửa sổ/phiên không có
phiên HUMAN bị BOT trên validation (14 phiên) hoặc test (24 phiên). Đây là
phép đo trên cùng nguồn dữ liệu, không chứng minh tỷ lệ lỗi ngoài thực tế.
Replay dày hơn, 100 cửa sổ/phiên trên toàn bộ quỹ đạo test, phát hiện 1/24
phiên HUMAN từng bị gán BOT và 2/66 phiên BOT từng bị gán HUMAN. Vì vậy
release gate v7 chưa đủ để xác nhận an toàn cho tự động chặn.
Chi tiết và cách tái hiện nằm trong [Model release v7](docs/MODEL_RELEASE_V7.md).
Các report [`heldout_evaluation.json`](core_ml/heldout_evaluation.json) và
[`early_session_validation.json`](core_ml/early_session_validation.json) là lịch sử v6.
Không dùng `is_bot` để tự động chặn khi chưa kiểm định trên dữ liệu thực tế
độc lập, đặc biệt với các phiên ngắn, touch hoặc thiếu dữ liệu.
Artifact v7 từng qua release gate trên validation và test cùng nguồn. `/health` báo
`release_gate_evidence_present: true` khi policy, ngưỡng, contract tiền xử lý và
chỉ số rolling đạt điều kiện cấu hình, nhưng đây
chưa phải kiểm định độc lập trên traffic thực tế; không dùng kết quả này để tự
động chặn người dùng mà không có bước theo dõi và xác minh bổ sung.

**Top 5 Feature Importance (XGBoost):**
1. `std_speed` — Độ biến thiên tốc độ
2. `direction_changes_y` — Số lần đổi hướng theo trục dọc
3. `angular_entropy` — Độ đa dạng góc di chuyển
4. `curvature_mean` — Độ cong trung bình quỹ đạo
5. `curvature_std` — Độ biến thiên độ cong quỹ đạo

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
  "bot_probability": 0.9804,
  "risk_score": 0.9804,
  "score_calibrated": false,
  "policy_version": "8",
  "decision_state": "FINAL",
  "confidence": 0.9608,
  "reasons": [
    "Flagged: platformMismatch",
    "Elevated mouse-behavior model score (LSTM: 1.00)"
  ],
  "breakdown": {
    "behavioral_lstm_score": 1.0,
    "tabular_score": 0.96,
    "heuristic_score": 0.1,
    "has_enough_mouse_data": true,
    "usable_trajectory": true,
    "distinct_positions": 31,
    "mouse_points": 31,
    "records_received": 34,
    "decision_deferred": false,
    "fusion_baseline": 0.98,
    "heuristic_lift": 0.0004,
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
