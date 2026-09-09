# Bot Detection Core: Multi-Modal Bot & Click Fraud Detection System

> **Khóa luận tốt nghiệp (2026):** Phát hiện gian lận click có tổ chức bằng mạng nơ-ron đồ thị (Graph Neural Networks).  
> **Tác giả:** Thành (`btthanhk4`) | **GVHD:** Thầy Mai.

Hệ thống phát hiện bot và gian lận click quảng cáo đa phương thức kết hợp sức mạnh từ 3 công nghệ:
1. **[FingerprintJS](https://github.com/fingerprintjs/fingerprintjs):** Thu thập ~40 đặc trưng phần cứng/trình duyệt, sinh mã định danh thiết bị duy nhất (`visitorId`).
2. **[BotD](https://github.com/fingerprintjs/BotD):** Bộ kiểm tra 12+ luật heuristic client-side (webdriver, headless indicators, plugin/language/platform inconsistencies).
3. **[DELBOT-Mouse](https://github.com/chrisgdt/DELBOT-Mouse):** Trích xuất động học quỹ đạo chuột (vận tốc, gia tốc, độ giật, độ cong) và phân loại bằng **mạng nơ-ron hồi quy LSTM**.
4. **[Graph Neural Networks (PyTorch Geometric)](https://github.com/pyg-team/pytorch_geometric):** Mô hình hóa đồ thị quan hệ không thuần nhất (*Device – IP – Session – Target*) nhằm bóc gỡ các mạng lưới botnet/click farm phối hợp quy mô lớn.

---

## 1. Kiến trúc Hệ thống

```
+-----------------------------------------------------------------------------------+
| 1. Client-Side Collector SDK (collector/)                                         |
|    - FingerprintJS (Canvas, WebGL, Audio, Concurrency, Screen, Visitor ID)        |
|    - BotD Heuristics (Webdriver, Virtual GPU, Headless UA, Inconsistencies)       |
|    - DELBOT Mouse Tracker (x, y, dx, dy, speed, accel, 24-point chunks)           |
+------------------------------------------+----------------------------------------+
                                           | Telemetry Payload (JSON)
                                           v
+-----------------------------------------------------------------------------------+
| 2. API Inference Server (api_service/ - FastAPI)                                  |
|    - Endpoint POST /api/v1/detect   : Real-time inference (< 10ms latency)        |
|    - Endpoint POST /api/v1/telemetry: Asynchronous beacon telemetry ingestion     |
|    - Endpoint GET  /api/v1/graph/stats: Graph topology & fraud ring indicators    |
+------------------------------------------+----------------------------------------+
                                           | Feature Extraction
                                           v
+-----------------------------------------------------------------------------------+
| 3. Multi-Modal Machine Learning Core (core_ml/)                                   |
|    ├── Branch A: Behavioral LSTM (Mouse Trajectory 24-point Sequential Chunks)    |
|    ├── Branch B: Tabular XGBoost (Hardware Fingerprint + Motion Stats + BotD)     |
|    ├── Fusion  : Multi-Modal Weighted Ensemble + Hard Heuristic Overrides         |
|    └── Branch C: HeteroClickFraudGNN (Device - IP - Session - Target Graph)       |
+-----------------------------------------------------------------------------------+
```

---

## 2. Cấu trúc Repository

```
bot-detection-core/
├── collector/                      # Bộ thu thập tín hiệu phía Client
│   ├── src/
│   │   ├── fingerprint.js         # Thu thập ~40 đặc trưng & hash visitorId
│   │   ├── botd.js                # 12 luật heuristic phát hiện tự động hóa
│   │   ├── mouse.js               # Theo dõi chuột & cắt chunk 24 điểm theo DELBOT
│   │   └── index.js               # Unified Collector SDK chính
│   ├── dist/
│   │   └── bot-collector.js       # Standalone bundle nhúng trực tiếp vào Web
│   └── package.json
│
├── core_ml/                        # Phân hệ Học máy & Xử lý Dữ liệu
│   ├── dataset/
│   │   └── loader.py              # Loader nạp dataset thật & sinh dữ liệu giả lập
│   ├── features/
│   │   ├── mouse_features.py      # Trích xuất tensor chuỗi (LSTM) & thống kê (Tabular)
│   │   ├── env_features.py        # Vector hóa dấu vân tay & BotD flags
│   │   └── graph_builder.py       # Xây dựng Heterogeneous Graph (Device - IP - Session)
│   ├── models/
│   │   ├── behavioral_lstm.py     # Mô hình PyTorch LSTM phân tích chuyển động chuột
│   │   ├── tabular_classifier.py  # Mô hình XGBoost phân loại đặc trưng môi trường
│   │   ├── ensemble.py            # Mô hình kết hợp (Multi-modal Ensemble)
│   │   └── gnn_detector.py        # Mô hình HeteroClickFraudGNN (PyTorch Geometric)
│   ├── weights/                   # Lưu trữ checkpoint mô hình đã huấn luyện (.pt, .joblib)
│   └── train.py                   # Script huấn luyện toàn bộ các mô hình
│
├── api_service/                    # Dịch vụ API phục vụ dự đoán thời gian thực
│   └── main.py                    # FastAPI server
│
├── simulator/                      # Công cụ sinh traffic giả lập & benchmark
│   └── run_simulation.py          # Benchmark kiểm tra độ chính xác API & Playwright
│
├── requirements.txt
└── README.md
```

---

## 3. Cài đặt & Sử dụng

### 3.1. Cài đặt môi trường Python
```bash
cd bot-detection-core
pip install -r requirements.txt
```

### 3.2. Huấn luyện Mô hình
Huấn luyện cả 3 nhánh mô hình (LSTM, XGBoost, HeteroGNN) và lưu checkpoint vào thư mục `core_ml/weights/`:
```bash
python -m core_ml.train
```
*Kết quả huấn luyện trên dữ liệu mô phỏng:*
* **ROC-AUC:** `1.0000`
* **F1-Score:** `1.0000`
* **Behavioral LSTM Loss:** giảm từ `0.0901` xuống `0.0115` qua 15 epochs.
* **HeteroGNN Loss:** giảm từ `0.1781` xuống `0.0017` qua 25 epochs.

### 3.3. Khởi chạy API Server
```bash
uvicorn api_service.main:app --host 0.0.0.0 --port 8000 --reload
```
Kiểm tra endpoint Swagger docs tại: `http://127.0.0.1:8000/docs`.

### 3.4. Chạy Benchmark / Kiểm thử Giả lập
```bash
# Gửi 20 mẫu Human và 20 mẫu Bot (Naive, Moderate, Advanced) lên API server
python -m simulator.run_simulation --mode benchmark --endpoint http://127.0.0.1:8000/api/v1/detect --samples 20
```

---

## 4. Hướng dẫn Tích hợp vào Website Silkmoon (hoặc Web bất kỳ)

### Cách 1: Nhúng trực tiếp file Script (Đơn giản nhất)
1. Copy file [collector/dist/bot-collector.js](collector/dist/bot-collector.js) vào thư mục `frontend/public/` của web.
2. Thêm vào thẻ `<head>` của `index.html`:
```html
<script src="/bot-collector.js"></script>
<script>
  window.addEventListener('DOMContentLoaded', async () => {
    if (window.BotCollector) {
      const collector = new window.BotCollector({
        endpointUrl: 'http://<IP_SERVER_CUA_BAN>:8000/api/v1/telemetry',
        detectUrl: 'http://<IP_SERVER_CUA_BAN>:8000/api/v1/detect',
        autoSendInterval: 5000 // Tự động gửi heartbeat mỗi 5 giây
      });
      await collector.init();
    }
  });
</script>
```

### Cách 2: Tích hợp vào React Component
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

## 5. Kết quả Đầu ra Phân loại Mẫu từ API

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
  "latency_ms": 3.42,
  "client_ip": "127.0.0.1",
  "sessionId": "sess_894102",
  "visitorId": "fp_2319"
}
```
