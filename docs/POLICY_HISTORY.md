# Lịch sử policy và kết quả thí nghiệm

Các policy trước bản hiện hành (v29, mô tả trong [README](../README.md#policy-v29-current)), giữ nguyên văn để đối chiếu. Mỗi policy có báo cáo chi tiết `MODEL_RELEASE_V*.md` trong thư mục này.

## Policy v28

Policy v28 coi phần cứng máy chủ là thêm một mâu thuẫn. Có 370 phiên trên trang đích quảng cáo báo
640 nhân CPU và vẽ WebGL bằng SwiftShader (GPU phần mềm) dù đi qua IP gia đình. `forged_browser_v1`
nay tính nhóm bằng chứng môi trường neo (headless, GPU, quyền thông báo) như một mâu thuẫn độc lập.
Có nhóm này cộng một mã giả mạo thì kết luận BOT. Không phiên người thật nào mang nhóm môi trường
hay mã giả mạo nào. Policy v27 trước đó đã xét luật con trỏ nhảy ngẫu nhiên từ 10 lần di chuột.
Xem [Model release v28](MODEL_RELEASE_V28.md).

## Policy v27

Policy v27 được kiểm chứng trên 11 phiên chuột người thật. Chuột thật gửi 60–250 mẫu mỗi giây, mỗi
bước khoảng 1% màn hình và chỉ đổi hướng vài độ. Bot trên trang đích quảng cáo gửi khoảng 13 điểm
mỗi giây, mỗi điểm cách điểm trước gần nửa màn hình và gần như quay ngược hướng. Luật con trỏ nhảy
ngẫu nhiên nay xét từ 10 lần di chuột (Balabit: 0 khớp trong 51.863 lần xuất). Hai mâu thuẫn trình
duyệt độc lập thì kết luận BOT (`forged_browser_v1`). `UNALIGNED_POINTER` chỉ còn là cờ nghiên cứu,
vì nó bắt nhầm một laptop thật và chưa từng bắt được bot thật. Xem
[Model release v27](MODEL_RELEASE_V27.md).

## Policy v26

Policy v26 bắt loại bot mà mô hình chuột bỏ sót trên trang đích quảng cáo: con trỏ không đi theo
đường mà nhảy giữa các điểm ngẫu nhiên. Bốn mã mới chặn kết luận HUMAN: `RANDOM_POINTER_JUMPS`,
`UA_POINTER_MISMATCH` (Safari < 13 mà vẫn gửi Pointer Events), `WEBDRIVER_TAMPERED`, `SERVER_CPU`.
Con trỏ nhảy ngẫu nhiên cộng với một mâu thuẫn môi trường độc lập thì thành BOT
(`synthetic_pointer_path_v1`). Phiên chưa đủ thao tác mà trình duyệt tự mâu thuẫn thì thành NGHI
VẤN có kết luận (`client_forgery`). Luật nhảy con trỏ không khớp lần xuất nào trong 41.899 lần xuất
phát lại từ Balabit (10 người). Xem [Model release v26](MODEL_RELEASE_V26.md).

## Policy v25

Policy v25 sửa các trường hợp người thật bị bắt nhầm trên site thật: site có Sentry (bọc
`console`, sửa `toString`), Chrome tắt tăng tốc phần cứng (WARP), người mở nhiều tab. Collector
1.11 lấy `console`, `toString` và `requestAnimationFrame` từ một realm mới, nên thư viện của trang
không làm sai đầu dò. Crawler tự khai được xác minh bằng dải IP chính thức của nhà vận hành
(`python -m core_ml.refresh_crawler_ranges`). Báo cáo đánh dấu IP crawler thật và IP có cả người
thật, và không đưa chúng vào danh sách IP để chặn. Xem [Model release v25](MODEL_RELEASE_V25.md).

## Policy v24

Policy v24 đóng các lỗ "fail-open" bằng gateway nginx của SilkMoon: mọi lượt tải trang được ghi
nhận kèm cookie HttpOnly, telemetry phải đến từ đúng trình duyệt đã tải trang, các request ghi bị
lạm dụng (đăng nhập, đăng ký, OTP, đặt hàng, đánh giá, mã giảm giá, AI) phải qua `/api/v1/gate`,
lượt tải trang không chạy collector hiện trên dashboard. Thêm nhóm bằng chứng CDP (Puppeteer-stealth
trên HTTPS thành BOT), tần suất phiên theo thiết bị, khóa BOT của mô hình sau 2 lần, `/detect` ẩn
danh không còn trả kết luận. Xem [Model release v24](MODEL_RELEASE_V24.md) và
[deploy/silkmoon-gateway](../deploy/silkmoon-gateway/README.md).

## Policy v23

Policy v23 vá các cách né luật input của v21 mà rà soát tìm ra: sửa hoặc xóa
`getCoalescedEvents`, di chuột thưa, và gửi payload giả không qua trình duyệt. Collector 1.9.0
chỉ đếm mẫu chuột trusted, mới hơn mẫu trước, và báo khi API thời gian bị thay. Xem
[Model release v23](MODEL_RELEASE_V23.md) và [rà soát điểm yếu](WEAKNESS_AUDIT_2026-10-28.md).

## Policy v22

Policy v22 sửa luật gõ phím giả sau khi kiểm chứng trên 168.593 người (Aalto 136M): luật cũ
kết tội 4.097 người chỉ vì gõ đều và 303 người chỉ vì thời gian giữ phím ngắn. Nay cần dấu
hiệu đi cùng nhau: nhịp và thời gian giữ cùng đều (0 người, mọi script có `delay` đều khớp),
giữ và khoảng cách cùng dưới 12 ms, hoặc giữ tức thì với nhịp cố định (Selenium). Mô hình
chuột cũng được kiểm tra trên 1.676 phiên người thật độc lập (Balabit): 98,6% cửa sổ HUMAN.
Xem [Model release v22](MODEL_RELEASE_V22.md) và
[kiểm chứng dữ liệu ngoài](EXTERNAL_DATA_VALIDATION_2026-10-28.md).

## Policy v21

Policy v21 chặn bot điều khiển Chrome thật qua CDP với thao tác giống người (patchright,
phát lại quỹ đạo người thật), loại mà mô hình chuột chấm là người. Phiên máy tính có input
không giống phần cứng (chuột chỉ 1 mẫu mỗi khung hình trên Windows, sự kiện dày hơn khung
hình, dồn dưới 1 ms) hoặc môi trường bất thường (IP cloud + GPU giả lập, nhóm bằng chứng
mạnh) → NGHI VẤN có kết luận thay vì HUMAN. Collector 1.8.0 đo khoảng cách khung hình. Xem
[Model release v21](MODEL_RELEASE_V21.md).

## Policy v20

Policy v20 kết luận BOT khi cả request và trình duyệt đều tự khai `HeadlessChrome/` (bản
stealth che `webdriver` trước đây chỉ bị xếp "chưa đủ dữ liệu"). Xem
[Model release v20](MODEL_RELEASE_V20.md).

## Policy v19

Policy v19 tối ưu điện thoại trên cả iPhone và Android: bot stealth sửa `navigator` bị lộ
qua Worker và phần cứng (GPU máy tính, CPU máy chủ, iOS không có bán kính chạm) → BOT;
autoclick (≥ 5 chạm cùng điểm, nhịp đều; 0/2.070 thiết bị người trong BrainRun) → BOT;
điện thoại đủ thao tác nhưng có bằng chứng bất lợi (trình giả lập, vuốt phát lại, IP
cloud…) → NGHI VẤN có kết luận. Collector 1.7.1 bỏ sự kiện chuột giả sau mỗi lần chạm.
Xem [Model release v19](MODEL_RELEASE_V19.md).

## Policy v18

Policy v18 thêm `mobile_clean_environment_v1`: phiên điện thoại/máy tính bảng có ít nhất 3
thao tác chạm thật, không có cờ cảm ứng, không phải trình giả lập, không dùng IP cloud và
không có bằng chứng tự động hóa được kết luận NGƯỜI THẬT (trước đây luôn "chưa đủ dữ liệu"),
giống cách Cloudflare/reCAPTCHA/DataDome chấm trình duyệt điện thoại. Xem
[Model release v18](MODEL_RELEASE_V18.md).

## Policy v17

Policy v17 thêm `mobile_emulation_v1` (trình duyệt máy tính giả làm iPhone/Android: platform
Win32, GPU Direct3D, API Chromium trên iOS — đo trên Playwright và Puppeteer; thiết bị thật,
DevTools và emulator Android Studio không bị gán) và đánh dấu bot tự khai báo (Web Bot Auth
`Signature-Agent`, UA của Googlebot/GPTBot/ClaudeBot/PerplexityBot…). Các hướng đã thử nhưng
bỏ vì không chứng minh được hiệu quả được ghi trong [Model release v17](MODEL_RELEASE_V17.md).

## Policy v16

Policy v16 (collector 1.6.0) sửa các tình huống biên tìm được khi rà soát: người Việt gõ
Telex qua Unikey/EVKey không còn bị nhầm là gõ máy (mô phỏng 3.000 lượt: 93 % → 0 %), người
dùng máy tính ảo trên cloud không còn bị gán BOT vĩnh viễn (luật `idle_cloud_browser_v1`
thay cho việc đếm bằng chứng tương quan), tab bị xóa phiên tự chuyển phiên mới, và giới hạn
tốc độ đủ cho ~60 tab sau một IP. Xem [Model release v16](MODEL_RELEASE_V16.md).

## Policy v15

Policy v15 (collector 1.4.0) bắt bot qua cách sự kiện đầu vào được tạo ra:
`synthetic_typing_v1` (giữ phím < 20 ms hoặc nhịp phím đều với CV < 0,10, ngưỡng kiểm
chứng trên 20.400 lượt gõ của bộ CMU: 0 người vi phạm) và `synthetic_pointer_v1` (chuột
báo áp lực 0 khi đang nhấn, trái chuẩn Pointer Events). Lần đầu Patchright có giao diện
bị bắt khi gõ phím. Xem [Model release v15](MODEL_RELEASE_V15.md).

## Policy v14

Policy v14 thêm nhóm bằng chứng NETWORK (địa chỉ client nằm trong dải IP công bố của Google
Cloud, AWS, Oracle, DigitalOcean, Linode, Vultr) và tín hiệu GPU phần mềm (SwiftShader,
llvmpipe…). NETWORK chỉ củng cố, không phải nhóm neo. Thay đổi bắt nguồn từ một crawler không
di chuột chạy trên Google Cloud mà v13 chỉ gán SUSPECT. Xem
[Model release v14](MODEL_RELEASE_V14.md).

## Policy v13

Policy v13 hiệu chỉnh luật môi trường của v12 theo traffic người thật đầu tiên (23 phiên,
4 IP, Chrome/Edge/Firefox trên Windows/macOS/Linux): nhóm PERMISSION chỉ áp dụng cho
trình duyệt tự nhận là Chromium (Firefox luôn lệch giữa `Notification.permission` và
Permissions API), và thêm tín hiệu GPU `legacy_angle_renderer` cho chuỗi WebGL định dạng
ANGLE cũ trên Chrome ≥ 100. Mô hình và ngưỡng không đổi. Xem
[Model release v13](MODEL_RELEASE_V13.md).

## Policy v12

Policy v12 giữ nguyên mô hình và ngưỡng, thêm lớp BotD v2 (collector 1.3.0) với hai luật:
`automation_marker_v1` (webdriver, ChromeDriver `cdc_`, biến Selenium, binding Playwright)
và `environment_tampering_v1` (mâu thuẫn môi trường ở ít nhất 3 nhóm độc lập). Trên ma
trận thử, Chrome/Edge thật không bị gán BOT, còn Playwright có giao diện, Puppeteer stealth
và Selenium chuyển từ SUSPECT sang BOT. Patchright có giao diện vẫn không bị phát hiện qua
môi trường. Xem [Model release v12](MODEL_RELEASE_V12.md).

## Policy v11

Policy v11 giữ nguyên hai model và ngưỡng của v10, thêm luật `synthetic_click_v1`:
ít nhất 3 click trúng tâm control (lệch ≤ 1 px) và ít nhất 2 lần nhả chuột dưới 5 ms
thì kết luận BOT. Luật bắt click mặc định của Playwright, Puppeteer và Selenium; bot
click ngẫu nhiên và có độ trễ bấm vẫn không bị bắt. Xem
[Model release v11](MODEL_RELEASE_V11.md) và
[tổng hợp công thức chuột](MOUSE_FORMULA_REVIEW_2026-10-25.md).

## Policy v10

The bundled model uses BOT threshold `0.96`, SUSPECT threshold `0.45`, and
monotonic BiLSTM mean/p75 evidence with an abstention rule for model disagreement.
Its release gate replays 1,000 checkpoints from each complete validation and
test session, including known regression windows. A narrow explicit-automation
rule can identify a self-declared HeadlessChrome browser with corroborating
framework markers even without mouse input; ordinary no-mouse visits remain
SUSPECT. See [No-mouse decisions](NO_MOUSE_BOT_DECISION.md) and
[Model release v10](MODEL_RELEASE_V10.md) for measured outcomes and limits.
These same-source splits have been used to select policy values and do not
constitute independent production validation.

A [browser bot pilot](FIELD_BOT_PILOT_2026-09-29.md) reproduced HUMAN
decisions on heavy-mouse, circular, and scrub-hover Playwright runs. Its
captured data and candidate models are diagnostic only; the bundled production
model is unchanged.
The [profile-first review](PROFILE_FIRST_REVIEW_2026-09-29.md) explains
why the current BotD/fingerprint signals cannot resolve most stealth runs.

During a MongoDB outage, acknowledged telemetry is committed to the local
SQLite spool on a persistent Docker volume. Keep the API on one host/worker;
the spool is not a distributed queue.

## Historical policy v7 (749 samples: 449 real M4D + 300 synthetic)

**Policy v7 lịch sử:** Ngưỡng BOT là `0.93` (điểm rủi ro, không phải xác suất đã
hiệu chuẩn). XGBoost chỉ học 20 đặc trưng thống kê chuột vì các phiên thực có nhãn
không kèm fingerprint; 30 cột môi trường vẫn giữ trong schema nhưng không được cây
sử dụng. BotD tiếp tục cung cấp bằng chứng dương qua nhánh heuristic riêng.
Train bổ sung cửa sổ đầu phiên, cửa sổ cuốn giữa phiên và biến thể thời gian chỉ
từ tập train. Release gate kiểm tra cả các cửa sổ giữa phiên trên validation và test.
Chi tiết phép đo và giới hạn: [Model release v7](MODEL_RELEASE_V7.md).
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
Chi tiết và cách tái hiện nằm trong [Model release v7](MODEL_RELEASE_V7.md).
Các report [`heldout_evaluation.json`](../core_ml/heldout_evaluation.json) và
[`early_session_validation.json`](../core_ml/early_session_validation.json) là lịch sử v6.
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

## 9 Thí nghiệm đánh giá

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
