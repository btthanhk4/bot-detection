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

### Dữ liệu cảm ứng (collector 1.7.0)

Collector 1.7.0 thu cử chỉ chạm/vuốt trên điện thoại; API lưu thành dữ liệu huấn luyện có
nhãn yếu (`touch_samples`, chỉ hình học và thời gian, TTL 180 ngày) và hiển thị cờ nghiên
cứu cùng điểm mô hình vuốt thử nghiệm (huấn luyện trên BrainRun và Touchalytics). Kết luận không đổi (policy
17). Xem [Dữ liệu cảm ứng](docs/TOUCH_DATA.md).

### Policy v25 (current)

Policy v25 sửa các trường hợp người thật bị bắt nhầm trên site thật: site có Sentry (bọc
`console`, sửa `toString`), Chrome tắt tăng tốc phần cứng (WARP), người mở nhiều tab. Collector
1.11 lấy `console`, `toString` và `requestAnimationFrame` từ một realm mới, nên thư viện của trang
không làm sai đầu dò. Crawler tự khai được xác minh bằng dải IP chính thức của nhà vận hành
(`python -m core_ml.refresh_crawler_ranges`). Báo cáo đánh dấu IP crawler thật và IP có cả người
thật, và không đưa chúng vào danh sách IP để chặn. Xem [Model release v25](docs/MODEL_RELEASE_V25.md).

### Policy v24

Policy v24 đóng các lỗ "fail-open" bằng gateway nginx của SilkMoon: mọi lượt tải trang được ghi
nhận kèm cookie HttpOnly, telemetry phải đến từ đúng trình duyệt đã tải trang, các request ghi bị
lạm dụng (đăng nhập, đăng ký, OTP, đặt hàng, đánh giá, mã giảm giá, AI) phải qua `/api/v1/gate`,
lượt tải trang không chạy collector hiện trên dashboard. Thêm nhóm bằng chứng CDP (Puppeteer-stealth
trên HTTPS thành BOT), tần suất phiên theo thiết bị, khóa BOT của mô hình sau 2 lần, `/detect` ẩn
danh không còn trả kết luận. Xem [Model release v24](docs/MODEL_RELEASE_V24.md) và
[deploy/silkmoon-gateway](deploy/silkmoon-gateway/README.md).

### Policy v23

Policy v23 vá các cách né luật input của v21 mà rà soát tìm ra: sửa hoặc xóa
`getCoalescedEvents`, di chuột thưa, và gửi payload giả không qua trình duyệt. Collector 1.9.0
chỉ đếm mẫu chuột trusted, mới hơn mẫu trước, và báo khi API thời gian bị thay. Xem
[Model release v23](docs/MODEL_RELEASE_V23.md) và [rà soát điểm yếu](docs/WEAKNESS_AUDIT_2026-10-28.md).

### Policy v22

Policy v22 sửa luật gõ phím giả sau khi kiểm chứng trên 168.593 người (Aalto 136M): luật cũ
kết tội 4.097 người chỉ vì gõ đều và 303 người chỉ vì thời gian giữ phím ngắn. Nay cần dấu
hiệu đi cùng nhau: nhịp và thời gian giữ cùng đều (0 người, mọi script có `delay` đều khớp),
giữ và khoảng cách cùng dưới 12 ms, hoặc giữ tức thì với nhịp cố định (Selenium). Mô hình
chuột cũng được kiểm tra trên 1.676 phiên người thật độc lập (Balabit): 98,6% cửa sổ HUMAN.
Xem [Model release v22](docs/MODEL_RELEASE_V22.md) và
[kiểm chứng dữ liệu ngoài](docs/EXTERNAL_DATA_VALIDATION_2026-10-28.md).

### Policy v21

Policy v21 chặn bot điều khiển Chrome thật qua CDP với thao tác giống người (patchright,
phát lại quỹ đạo người thật), loại mà mô hình chuột chấm là người. Phiên máy tính có input
không giống phần cứng (chuột chỉ 1 mẫu mỗi khung hình trên Windows, sự kiện dày hơn khung
hình, dồn dưới 1 ms) hoặc môi trường bất thường (IP cloud + GPU giả lập, nhóm bằng chứng
mạnh) → NGHI VẤN có kết luận thay vì HUMAN. Collector 1.8.0 đo khoảng cách khung hình. Xem
[Model release v21](docs/MODEL_RELEASE_V21.md).

### Policy v20

Policy v20 kết luận BOT khi cả request và trình duyệt đều tự khai `HeadlessChrome/` (bản
stealth che `webdriver` trước đây chỉ bị xếp "chưa đủ dữ liệu"). Xem
[Model release v20](docs/MODEL_RELEASE_V20.md).

### Policy v19

Policy v19 tối ưu điện thoại trên cả iPhone và Android: bot stealth sửa `navigator` bị lộ
qua Worker và phần cứng (GPU máy tính, CPU máy chủ, iOS không có bán kính chạm) → BOT;
autoclick (≥ 5 chạm cùng điểm, nhịp đều; 0/2.070 thiết bị người trong BrainRun) → BOT;
điện thoại đủ thao tác nhưng có bằng chứng bất lợi (trình giả lập, vuốt phát lại, IP
cloud…) → NGHI VẤN có kết luận. Collector 1.7.1 bỏ sự kiện chuột giả sau mỗi lần chạm.
Xem [Model release v19](docs/MODEL_RELEASE_V19.md).

### Policy v18

Policy v18 thêm `mobile_clean_environment_v1`: phiên điện thoại/máy tính bảng có ít nhất 3
thao tác chạm thật, không có cờ cảm ứng, không phải trình giả lập, không dùng IP cloud và
không có bằng chứng tự động hóa được kết luận NGƯỜI THẬT (trước đây luôn "chưa đủ dữ liệu"),
giống cách Cloudflare/reCAPTCHA/DataDome chấm trình duyệt điện thoại. Xem
[Model release v18](docs/MODEL_RELEASE_V18.md).

### Policy v17

Policy v17 thêm `mobile_emulation_v1` (trình duyệt máy tính giả làm iPhone/Android: platform
Win32, GPU Direct3D, API Chromium trên iOS — đo trên Playwright và Puppeteer; thiết bị thật,
DevTools và emulator Android Studio không bị gán) và đánh dấu bot tự khai báo (Web Bot Auth
`Signature-Agent`, UA của Googlebot/GPTBot/ClaudeBot/PerplexityBot…). Các hướng đã thử nhưng
bỏ vì không chứng minh được hiệu quả được ghi trong [Model release v17](docs/MODEL_RELEASE_V17.md).

### Policy v16

Policy v16 (collector 1.6.0) sửa các tình huống biên tìm được khi rà soát: người Việt gõ
Telex qua Unikey/EVKey không còn bị nhầm là gõ máy (mô phỏng 3.000 lượt: 93 % → 0 %), người
dùng máy tính ảo trên cloud không còn bị gán BOT vĩnh viễn (luật `idle_cloud_browser_v1`
thay cho việc đếm bằng chứng tương quan), tab bị xóa phiên tự chuyển phiên mới, và giới hạn
tốc độ đủ cho ~60 tab sau một IP. Xem [Model release v16](docs/MODEL_RELEASE_V16.md).

### Policy v15

Policy v15 (collector 1.4.0) bắt bot qua cách sự kiện đầu vào được tạo ra:
`synthetic_typing_v1` (giữ phím < 20 ms hoặc nhịp phím đều với CV < 0,10, ngưỡng kiểm
chứng trên 20.400 lượt gõ của bộ CMU: 0 người vi phạm) và `synthetic_pointer_v1` (chuột
báo áp lực 0 khi đang nhấn, trái chuẩn Pointer Events). Lần đầu Patchright có giao diện
bị bắt khi gõ phím. Xem [Model release v15](docs/MODEL_RELEASE_V15.md).

### Policy v14

Policy v14 thêm nhóm bằng chứng NETWORK (địa chỉ client nằm trong dải IP công bố của Google
Cloud, AWS, Oracle, DigitalOcean, Linode, Vultr) và tín hiệu GPU phần mềm (SwiftShader,
llvmpipe…). NETWORK chỉ củng cố, không phải nhóm neo. Thay đổi bắt nguồn từ một crawler không
di chuột chạy trên Google Cloud mà v13 chỉ gán SUSPECT. Xem
[Model release v14](docs/MODEL_RELEASE_V14.md).

### Policy v13

Policy v13 hiệu chỉnh luật môi trường của v12 theo traffic người thật đầu tiên (23 phiên,
4 IP, Chrome/Edge/Firefox trên Windows/macOS/Linux): nhóm PERMISSION chỉ áp dụng cho
trình duyệt tự nhận là Chromium (Firefox luôn lệch giữa `Notification.permission` và
Permissions API), và thêm tín hiệu GPU `legacy_angle_renderer` cho chuỗi WebGL định dạng
ANGLE cũ trên Chrome ≥ 100. Mô hình và ngưỡng không đổi. Xem
[Model release v13](docs/MODEL_RELEASE_V13.md).

### Policy v12

Policy v12 giữ nguyên mô hình và ngưỡng, thêm lớp BotD v2 (collector 1.3.0) với hai luật:
`automation_marker_v1` (webdriver, ChromeDriver `cdc_`, biến Selenium, binding Playwright)
và `environment_tampering_v1` (mâu thuẫn môi trường ở ít nhất 3 nhóm độc lập). Trên ma
trận thử, Chrome/Edge thật không bị gán BOT, còn Playwright có giao diện, Puppeteer stealth
và Selenium chuyển từ SUSPECT sang BOT. Patchright có giao diện vẫn không bị phát hiện qua
môi trường. Xem [Model release v12](docs/MODEL_RELEASE_V12.md).

### Policy v11

Policy v11 giữ nguyên hai model và ngưỡng của v10, thêm luật `synthetic_click_v1`:
ít nhất 3 click trúng tâm control (lệch ≤ 1 px) và ít nhất 2 lần nhả chuột dưới 5 ms
thì kết luận BOT. Luật bắt click mặc định của Playwright, Puppeteer và Selenium; bot
click ngẫu nhiên và có độ trễ bấm vẫn không bị bắt. Xem
[Model release v11](docs/MODEL_RELEASE_V11.md) và
[tổng hợp công thức chuột](docs/MOUSE_FORMULA_REVIEW_2026-10-25.md).

### Policy v10

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

A [browser bot pilot](docs/FIELD_BOT_PILOT_2026-09-29.md) reproduced HUMAN
decisions on heavy-mouse, circular, and scrub-hover Playwright runs. Its
captured data and candidate models are diagnostic only; the bundled production
model is unchanged.
The [profile-first review](docs/PROFILE_FIRST_REVIEW_2026-09-29.md) explains
why the current BotD/fingerprint signals cannot resolve most stealth runs.

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
nên dùng giá trị `bot_probability` để chặn người dùng trong trạng thái này.

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
   dẫn để gửi khách* sao chép các bước kèm mã dưới dạng văn bản. Trạng thái chuyển từ *Chờ cài đặt*
   sang *Đang nhận dữ liệu* khi có phiên đầu tiên.
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
- Tài khoản chỉ xem thấy danh sách và mã cài đặt, không thêm, sửa hay xóa được.

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
  khác trả 403, phiên của website khác trả 404. Khách không thấy số thứ tự traffic toàn hệ thống và các
  thông số nội bộ (độ trễ, policy, mẫu cảm ứng).
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
