# Bot Detection Core: Multi-Modal Bot & Click Fraud Detection System

> **Khóa luận tốt nghiệp (2026):** Xây dựng mô hình phân biệt bot và người truy cập trang web  
> **Tác giả:** Thành (`btthanhk4`) | **GVHD:** Thầy Mai  
> **Dataset:** [Web Bot Detection Dataset (M4D-ITI)](https://m4d.iti.gr/web-bot-detection-dataset/)

## Bàn giao thu traffic nghiên cứu

Bản SDK 1.3.0 hỗ trợ nhúng một tag có `data-datacat`, mã đợt thu và mã website.
Xem [hướng dẫn giáo viên](pilot/README.md),
[triển khai và export dataset](docs/PILOT_OPERATOR_GUIDE.md),
[kiểm chứng bản bàn giao](docs/PILOT_HANDOFF_REVIEW_2026-10-19.md).
Stack pilot độc lập nằm ở `docker-compose.pilot.yml`. Model và ngưỡng hiện
được giữ nguyên; sẵn sàng thu dữ liệu không đồng nghĩa chứng nhận accuracy.

## Tổng quan mô hình

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
├── api_service/                 # FastAPI: suy luận, nhận telemetry, dashboard
│   ├── main.py                  # Ứng dụng FastAPI và toàn bộ endpoint
│   ├── config.py                # Cấu hình đọc từ biến môi trường BOT_*
│   ├── database.py              # Truy cập MongoDB
│   ├── sites.py                 # Danh sách trang theo dõi, gán phiên theo Origin
│   ├── auth.py, manage.py       # Tài khoản dashboard; lệnh quản trị tài khoản
│   ├── gateway.py               # Tích hợp reverse proxy (lượt tải trang, chặn request ghi)
│   ├── reports.py, live.py      # Báo cáo theo kỳ; dữ liệu Live View
│   ├── geoip.py                 # Định vị IP offline (DB-IP Lite)
│   ├── spool.py                 # Hàng đợi SQLite khi MongoDB mất kết nối
│   ├── capture.py, research_labels.py, touch_samples.py  # Dữ liệu nghiên cứu
│   └── dashboard.html, login.html, assets/              # Giao diện dashboard
│
├── collector/                   # SDK JavaScript nhúng vào website
│   ├── src/                     # fingerprint, botd, automation, mouse, pristine, profile, pilot, index
│   ├── build.js                 # Đóng gói src/ thành dist/
│   ├── dist/bot-collector.js    # Bundle được phục vụ tại /bot-collector.js (commit kèm mã nguồn)
│   └── test.js, *.test.js       # Kiểm thử collector (npm test)
│
├── core_ml/                     # Mô hình, đặc trưng, huấn luyện, đánh giá
│   ├── features/                # Đặc trưng chuột, môi trường, bằng chứng tự động hóa, cảm ứng
│   ├── models/                  # BiLSTM, XGBoost, ensemble và policy quyết định
│   ├── dataset/                 # Đọc M4D, snapshot thu thập, nhãn thủ công
│   ├── experiments/             # Thí nghiệm đánh giá và ablation
│   ├── data/                    # Dải IP cloud/crawler, mô hình cảm ứng thử nghiệm
│   ├── weights/                 # Trọng số production và model_manifest.json
│   ├── train.py, train_touch.py # Huấn luyện
│   └── evaluate*.py, release_cases.py, model_bundle.py
│
├── tests/                       # pytest cho API, mô hình, đặc trưng, collector windows
├── simulator/                   # Bộ sinh traffic bot và benchmark /api/v1/detect
├── pilot/                       # Gói bàn giao pilot và smoke test Playwright
├── deploy/                      # Gateway nginx SilkMoon, script backup MongoDB
├── docs/                        # Báo cáo release, đánh giá, hướng dẫn vận hành (xem docs/README.md)
├── design-system/               # Quy ước giao diện dashboard
├── .github/workflows/deploy.yml # CI: test rồi deploy lên production
├── Dockerfile, docker-compose.yml          # Image và stack production
├── docker-compose.pilot.yml, .env*.example # Stack pilot độc lập, mẫu biến môi trường
├── requirements*.txt, ruff.toml            # Phụ thuộc Python, cấu hình lint
└── EXPERIMENT_REPORT.md         # Báo cáo thí nghiệm lịch sử
```

---

## Kết quả chính

### Dữ liệu cảm ứng (collector 1.7.0)

Collector 1.7.0 thu cử chỉ chạm/vuốt trên điện thoại; API lưu thành dữ liệu huấn luyện có
nhãn yếu (`touch_samples`, chỉ hình học và thời gian, TTL 180 ngày) và hiển thị cờ nghiên
cứu cùng điểm mô hình vuốt thử nghiệm (huấn luyện trên BrainRun và Touchalytics). Kết luận không đổi (policy
17). Xem [Dữ liệu cảm ứng](docs/TOUCH_DATA.md).

### Policy v32 (current)

Policy v32 thêm mâu thuẫn `PLATFORM_SPOOFED`: hệ điều hành mà trang báo (`navigator.platform`)
khác với hệ điều hành mà một worker báo. Công cụ giả thiết bị chỉ sửa được giá trị trên trang, còn
worker vẫn báo giá trị thật. Trên production, không phiên người thật nào (0/238) có mâu thuẫn này;
cả 241 phiên mang nó đều là thiết bị giả:
- Chrome Android báo platform `Linux armv8l`, trong khi 61/61 Chrome thật báo giá trị cố định
  `Linux armv81`.
- "iPhone" có tỉ lệ điểm ảnh lẻ, điều mà không iPhone nào có.

Mâu thuẫn này cộng với GPU bị sửa (worker báo GPU khác trang) thì kết luận BOT. Trên trang Spin có
146 phiên như vậy trước đây chỉ ở mức NGHI VẤN hoặc chưa đủ dữ liệu. Policy v31 trước đó đã thêm
`UA_API_MISMATCH`. Xem [Model release v32](docs/MODEL_RELEASE_V32.md).

Lịch sử policy v7–v31, bảng kết quả trên tập test cùng nguồn và 9 thí nghiệm đánh giá: [docs/POLICY_HISTORY.md](docs/POLICY_HISTORY.md).

---

## Cài đặt & Sử dụng

### 1. Cài đặt môi trường

Yêu cầu: Python 3.10 (bản dùng trong `Dockerfile` và CI) và Node.js để build collector
(`collector/build.js` không cần package npm nào).

```bash
cd bot-detection-core
pip install -r requirements.txt        # chạy API
pip install -r requirements-dev.txt    # thêm pytest, ruff, mongomock để phát triển
```

Set `BOT_READ_TOKEN` for dashboard data access and `BOT_ADMIN_TOKEN` for delete
actions. Docker Compose binds port `8000` to `127.0.0.1` only; public traffic must
come through an HTTPS reverse proxy on the same Docker network (the API trusts
`X-Forwarded-*` from `172.16.0.0/12`). Copy the values from `.env.example` into the
server environment and restrict `BOT_CORS_ORIGINS` and `BOT_TELEMETRY_ORIGINS` to
trusted website origins.

Production deployment (nginx gateway + Let's Encrypt, renewed by `certbot.timer`):

| URL | Service |
|---|---|
| `https://datacat.io.vn` | Admin dashboard (metrics); `www` redirects here |
| `https://api.datacat.io.vn` | DATACAT API and `bot-collector.js` for other websites |
| `https://silkmoon.datacat.io.vn` | SilkMoon demo shop; collector injected by the gateway, telemetry proxied same-origin |

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

### 6. Kiểm thử

CI chạy đúng ba lệnh sau; cả ba phải qua trước khi push lên `main`:

```bash
python -m ruff check .        # lint, gồm thứ tự import (cấu hình trong ruff.toml)
python -m pytest -q           # test Python, dùng mongomock nên không cần MongoDB
cd collector && npm test      # build dist/bot-collector.js rồi chạy test collector
```

`collector/dist/bot-collector.js` được commit kèm mã nguồn. Sau khi sửa `collector/src/`, chạy
`npm test` (hoặc `npm run build`) và commit cả file dist: CI báo lỗi nếu file này khác bản build.

---

## Triển khai

Push lên `main` chạy workflow [`.github/workflows/deploy.yml`](.github/workflows/deploy.yml):
job **Test** chạy các lệnh kiểm thử ở trên, job **Deploy production** SSH vào server, checkout
đúng commit vừa test, chạy `docker compose up -d --build` và chờ `/health` báo `healthy`. Nếu
không đạt, workflow tự quay lại commit đã deploy trước đó. Chi tiết, biến môi trường và các bước
khôi phục: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

---

## Xử lý sự cố

| Hiện tượng | Nguyên nhân thường gặp |
|---|---|
| `/health` trả `"status": "degraded"` | MongoDB không kết nối được (`database: false`) hoặc mô hình chưa nạp (`inference_ready: false`) |
| Telemetry bị `403 This page is not registered for monitoring` | Trang chưa được thêm ở mục Trang theo dõi của dashboard, hoặc request không có Origin/Referer khớp trang đã đăng ký |
| Telemetry bị `403 Monitoring is paused for this site` | Trang (hoặc trang khách vào đầu tiên) đang tạm dừng |
| API monitoring trả `503 ... until BOT_READ_TOKEN is configured` | Chưa đặt `BOT_READ_TOKEN` và chưa đăng nhập dashboard |
| Job deploy dừng ở "uncommitted or untracked changes" | Thư mục deploy trên server có file lạ; deploy chỉ chạy trên một checkout sạch |
| CI lỗi ở "Verify generated collector is committed" | Đã sửa `collector/src/` nhưng chưa commit `collector/dist/bot-collector.js` mới |

---

## Thu snapshot nghiên cứu

Chế độ `BOT_CAPTURE_ENABLED=true` lưu từng snapshot telemetry trước inference,
giữ dữ liệu khi model lỗi và dùng SQLite khi MongoDB mất kết nối. Mặc định tắt;
TTL mặc định 7 ngày. Không thay đổi model hoặc verdict. Hướng dẫn bật, response,
giới hạn dung lượng và các bước kiểm chứng: [RESEARCH_CAPTURE.md](docs/RESEARCH_CAPTURE.md).

## Vị trí theo IP

Dashboard hiển thị vị trí gần đúng (thành phố, tỉnh/vùng, quốc gia) và nhà mạng (ISP/ASN)
của IP mỗi lượt truy cập, tra từ cơ sở dữ liệu offline DB-IP Lite (CC BY 4.0) đặt trên
server: không gửi IP khách cho dịch vụ bên ngoài, không giới hạn lượt tra. Với
`BOT_GEOIP_AUTO_UPDATE=true` (mặc định trong `docker-compose.yml`) API tự tải bản mới mỗi
tháng vào `BOT_GEOIP_DIR`; tải tay: `python -m api_service.geoip --refresh`. Vị trí chỉ để
hiển thị, không dùng trong kết luận; mạng di động thường định vị về cổng của nhà mạng.

Trang **Live View** (giao diện kiểu Shopify) vẽ các vị trí đó trên quả địa cầu chấm bi: mỗi
vùng là một chấm theo số phiên, màu theo kết luận, vòng sáng cho phiên đang online; bên cạnh
là số khách online (5 phút), số phiên 24 giờ, tỉ lệ phân loại, top vị trí và nhà mạng
(`GET /api/v1/live`).

## API Endpoints

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| `GET` | `/` | Health check + model status |
| `POST` | `/api/v1/detect` | Real-time bot classification |
| `POST` | `/api/v1/telemetry` | Asynchronous telemetry ingestion |
| `GET` | `/api/v1/traffic/timeline` | Lưu lượng phân loại theo khoảng thời gian |
| `GET` | `/api/v1/sites` | Danh sách website, trạng thái cài đặt, traffic 24 giờ (quyền xem) |
| `POST` / `PATCH` / `DELETE` | `/api/v1/sites[/{site_id}]` | Thêm, sửa, tạm dừng, xóa website (quyền quản trị) |
| `GET` | `/api/v1/reports/summary?days=1\|7\|30&site=` | Báo cáo kỳ: tổng theo kết luận, lý do, IP/quốc gia/nhà mạng của bot |
| `GET` | `/api/v1/reports/sessions?days=&site=` | Phiên trong kỳ để dashboard xuất CSV (tối đa 50.000) |
| `GET` | `/api/v1/reports/clicks?days=&site=&verdict=&q=&page=` | Danh sách click trong kỳ (Click ID, Token 1, kết luận), 50 dòng một trang |
| `GET` | `/api/v1/clicks/{clickid}` | Người hay bot cho một click quảng cáo (`?clickid=&t1=` của URL trang đích), xem [Theo dõi click](docs/CLICK_ATTRIBUTION.md) |
| `GET` / `POST` / `PATCH` / `DELETE` | `/api/v1/users[/{username}]`, `POST /api/v1/users/{username}/reset-password` | Quản lý tài khoản (quyền quản trị) |

Các endpoint giám sát (`stats/summary`, `traffic/timeline`, `telemetry/recent`, `research/traffic`,
`live`, `live/online`) nhận thêm `?site=<site_id>`, hoặc `?site=_none` cho phiên chưa gán website.

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
nên dùng giá trị `bot_probability` để chặn người dùng trong trạng thái này. Từ policy 25,
`risk_score` là `null` khi kết luận đến từ luật (điện thoại, dấu vết tự động hóa) hoặc chưa đủ
dữ liệu: khi đó điểm mô hình chuột không có ý nghĩa, hãy dùng `verdict`.

---

## Tích hợp vào Website

### Quản lý nhiều website

Trang **Website** trên dashboard là nơi đăng ký từng website của khách hàng:

1. **Thêm website**: tên, các tên miền (mỗi dòng một tên miền, gồm cả bản `www` nếu có), người
   liên hệ. Lưu xong, dashboard hiện đoạn mã cài đặt riêng của website đó:
   `<script async src="https://api.datacat.io.vn/bot-collector.js" data-datacat data-study-id="datacat_live" data-site-id="<site_id>"></script>`.
2. Hộp **Kết nối** có 8 cách, mỗi cách kèm các bước riêng: Google Tag Manager, WordPress (plugin
   WPCode), Shopify, Haravan, Sapo, Wix, web tự code (dán trước `</head>` trong file khung chung) và
   máy chủ nginx (`sub_filter` chèn tự động). Cách đã chọn được lưu cho website; nút *Sao chép hướng
   dẫn để gửi khách* sao chép các bước kèm mã dưới dạng văn bản. Trạng thái chuyển từ *Chưa có dữ liệu*
   sang *Đang hoạt động* khi có phiên đầu tiên.
3. **Xem traffic** lọc Tổng quan và Live View theo website; bộ chọn website nằm cạnh tiêu đề trang.
4. Trang **Báo cáo** (24 giờ, 7 hoặc 30 ngày, theo website): tỉ lệ người thật/bot/nghi vấn, biểu đồ theo
   ngày, lý do bị đánh dấu, bot theo quốc gia và nhà mạng, IP bot nhiều nhất (sao chép để chặn), tải CSV
   và in/lưu PDF để gửi khách.

Cách gán phiên:

- Website được xác định bằng header `Origin` do trình duyệt gửi, không bằng `data-site-id` trong thẻ:
  trang khác chép nguyên đoạn mã vẫn được tính đúng website của nó, hoặc bị từ chối nếu tên miền
  chưa đăng ký.
- Tên miền đã đăng ký được nhận dữ liệu và qua CORS ngay, không cần sửa `.env` hay khởi động lại.
  Tên miền trong `BOT_TELEMETRY_ORIGINS` vẫn được nhận như trước nhưng không thuộc website nào
  cho đến khi được đăng ký.
- Đăng ký một tên miền sẽ gán cả các phiên cũ của nó (trước đó là *Chưa gán website*). Mục
  *Nguồn chưa đăng ký* liệt kê tên miền đã gửi dữ liệu trong 7 ngày mà chưa thuộc website nào.
- **Tạm dừng** từ chối dữ liệu của website mà không cần khách hàng gỡ mã. **Xóa** chỉ bỏ website
  khỏi danh sách; phiên đã ghi vẫn giữ.
- Trang gắn mã mà không được đăng ký (hoặc đang tạm dừng) bị từ chối với `403` và header
  `X-Datacat-Stop` (86.400 giây, tạm dừng là 3.600 giây). Bước preflight của endpoint telemetry
  được cho qua với mọi Origin (không kèm credentials), nên collector 1.12+ đọc được lời từ chối. Nó
  tắt luôn và ghi nhớ trong `localStorage` của trang đó: các trang sau trên cùng website không gửi gì
  cho tới khi hết hạn (tối đa 7 ngày). Nhờ vậy mỗi khách của trang lạ chỉ gửi một request mỗi ngày,
  thay vì thử lại vài giây một lần. Không có dữ liệu nào của trang lạ được lưu. Muốn chặn hẳn từ
  gốc, chủ trang phải gỡ đoạn mã.
- **Chống lộ mã và spam (collector 1.13+).** Đoạn mã nhúng không chứa bí mật nào; ai mở trang cũng
  đọc được. Vì vậy mỗi phiên phải xin server một token cho lượt tải trang (`GET /api/v1/visit?sid=`):
  - Token được ký HMAC bằng khóa lưu trong MongoDB, gắn với website và phiên, hiệu lực 24 giờ.
  - Mỗi IP chỉ xin được 60 token cho mỗi website trong 10 phút. Mức này để rộng vì nhà mạng di động
    dùng chung IP cho nhiều người.
  - Telemetry không kèm token hợp lệ (thiếu, giả, hoặc là token của phiên khác) không bị từ chối. Nó
    được chấm như một trang mà gateway không phục vụ (`UNVERIFIED_PAGE_LOAD`, policy 24), nên không
    bao giờ được kết luận HUMAN.

  Một script chép mã muốn giả phiên phải bắt tay với server cho từng phiên, và bị giới hạn theo IP.
  Collector cũ (không có token) được miễn xét đến `BOT_PAGE_TOKEN_REQUIRED_FROM` (mặc định
  14/11/2026). Trang chạy qua gateway (silkmoon) chứng minh lượt tải trang bằng cookie của gateway.
- **Chấm lại phiên cũ** theo các luật mâu thuẫn của policy 30–32:
  `python -m api_service.manage rejudge`, thêm `--apply` để ghi. Lệnh chỉ đọc các trường đã lưu
  (fingerprint, nhóm môi trường, mã giả mạo, chạm). Nó chỉ nâng kết luận lên BOT, không bao giờ hạ,
  và ghi kết luận cũ vào trường `rejudged`.
- Tài khoản chỉ xem thấy danh sách và mã cài đặt, không thêm, sửa hay xóa được.
- **Lọc theo quốc gia** (Tổng quan, Live View): một trang thường chạy quảng cáo ở nhiều nước. Ô chọn
  quốc gia nằm cạnh ô chọn trang, liệt kê các nước có phiên kèm số phiên (cập nhật mỗi phút); các ô
  tổng hợp, biểu đồ, bảng lượt truy cập và Live View chỉ tính nước đã chọn. STT của phiên vẫn là STT
  trong trang. Quốc gia được lấy từ IP lúc phiên bắt đầu (DB-IP, ngoại tuyến) và lưu vào
  `detection_results.country_code`; các phiên cũ được bổ sung một lần khi khởi động. Báo cáo và thao
  tác xóa không theo bộ lọc này. API: tham số `country` (mã ISO như `US`, hoặc `_none` = không rõ)
  trên `/api/v1/stats/summary`, `/api/v1/traffic/timeline`, `/api/v1/research/traffic`,
  `/api/v1/live`, `/api/v1/live/online`; danh sách nước: `GET /api/v1/stats/countries?site=`.

### Tài khoản và phân quyền

Trang **Người dùng** (chỉ quản trị viên) tạo và quản lý tài khoản đăng nhập dashboard:

| Vai trò | Xem | Sửa |
|---|---|---|
| Quản trị viên | Mọi website | Website, tài khoản, xóa phiên |
| Nhân viên | Mọi website | Không |
| Khách hàng | Chỉ các website được giao (Tổng quan, Live View, Báo cáo, Website) | Không |

- Tài khoản mới và tài khoản được đặt lại mật khẩu dùng **mật khẩu tạm** do hệ thống sinh, chỉ hiện một
  lần (kèm nút sao chép để gửi). Chủ tài khoản phải đổi mật khẩu trước khi xem được dữ liệu.
- Giới hạn website được áp ở máy chủ: mọi endpoint đọc dữ liệu tự lọc theo website của khách; hỏi website
  khác trả 403, phiên của website khác trả 404. STT trên bảng đếm trong website của khách; khách không
  thấy số traffic toàn hệ thống và các thông số nội bộ (độ trễ, policy, mẫu cảm ứng).
- Khóa tài khoản hoặc đặt lại mật khẩu sẽ đăng xuất mọi phiên của tài khoản đó trong vòng 10 giây.
- Không tự hạ quyền, tự khóa hay tự xóa chính mình, và luôn còn ít nhất một quản trị viên đang hoạt động.
- Quản trị viên đầu tiên vẫn tạo bằng `python -m api_service.manage create-admin --username <tên>`.

`BOT_PUBLIC_API_URL` là địa chỉ đặt trong đoạn mã cài đặt (mặc định trong `docker-compose.yml`:
`https://api.datacat.io.vn`).

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
