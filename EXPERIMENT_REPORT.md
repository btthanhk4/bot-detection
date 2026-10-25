# BÁO CÁO QUÁ TRÌNH XÂY DỰNG & TỐI ƯU MÔ HÌNH PHÁT HIỆN BOT

> **Phần 1 trở đi là phụ lục lịch sử, không phải kết quả hiện hành.** Các bảng cũ
> được viết trước khi sửa feature contract và data leakage. Kết quả đánh giá
> lại ngày 2026-09-15 nằm trong [`core_ml/experiment_results.json`](core_ml/experiment_results.json),
> nhưng trạng thái release và thí nghiệm browser mới hơn được tóm tắt ngay dưới đây.
> Không lấy các con số lịch sử làm bằng chứng sẵn sàng production.

> **Đề tài:** Xây dựng mô hình phân biệt bot và người truy cập trang web  
> **Dataset:** Web Bot Detection Dataset (M4D-ITI) — Phase 1  
> **Cập nhật báo cáo:** 2026-10-23; kiểm thử local không phải đợt thu traffic tự nhiên mới.

---

## STT traffic và nhãn dataset thủ công (2026-10-23)

Đã thêm registry cấp STT theo session, giữ số khi heartbeat/retry/restart,
backfill phiên còn lưu theo lần đầu server ghi nhận, và phân trang cursor.
STT không phải định danh người hoặc bằng chứng traffic của nhà cung cấp;
thứ tự khi DB outage chỉ xác lập sau phục hồi, số đã cấp không tái sử dụng.

Dashboard có nút gán BOT/HUMAN/UNKNOWN, nguồn, mã nhóm, ghi chú, reviewer,
xác nhận và revision. Nhãn riêng với dự đoán AI, có lịch sử và quyền admin.
Snapshot đã chọn được giữ riêng không phụ thuộc TTL vận hành; xóa phiên
bao gồm cả dữ liệu dataset/nhãn. Export thêm manual-labels JSONL có checksum,
loader không tự lấy verdict AI làm ground truth.

Có đường nạp mẫu chuột đã gán nhãn vào train thử bằng các nhóm chỉ định,
chỉ ở candidate diagnostic/thư mục riêng. Chưa chạy retrain hoặc đổi weights.
Provider/commercial assertions mặc định chưa là nhãn học đáng tin cậy.
Các kiểm thử bổ sung gồm STT đồng thời, cursor, archive/TTL, xung đột revision,
auth, export/import và giao diện browser desktop/mobile với MongoDB thật.

Kiểm chứng local: **537 test Python qua**, Ruff và collector qua. Smoke thực
qua 10 nhóm collector/storage và 7 nhóm bổ sung cho registry/nhãn/giao diện/
export/import/xóa dataset. Model bundle vẫn là
`e3dd550e4d40453db0e17a743da7e992`; chưa train lại hay deploy cloud.
Chứng cứ riêng ngoài Git: `C:/Users/Admin/bot-detection-research/pilot-runtime/manual-labels-acceptance-2026-10-23/evidence.json`.

Chi tiết sử dụng và giới hạn: [MANUAL_LABELING.md](docs/MANUAL_LABELING.md).

## Hoàn thiện bản bàn giao thu traffic thật (2026-10-19)

Đã rà soát luồng collector/API/capture/spool/export và bổ sung SDK **1.1.0**:
tag tự nhúng có study/site ID, metadata page/version/coordinate frame,
receipt phân biệt raw đã lưu/đã buffer với beacon mới queued, chống nhúng
lặp và giữ tương thích SDK thủ công. Model, policy và weights không đổi.

Đã có CLI export/verify snapshot nghiên cứu theo study/site/thời gian, giữ
hash raw và phiên bản analysis, tạo template nhãn UNKNOWN thay vì lấy dự
đoán model làm ground truth. Kiểm thử MongoDB thật phát hiện và sửa lỗi
kiểm tra timestamp BSON Int64; đã thêm regression test. Có stack Compose
pilot độc lập SilkMoon và hướng dẫn nhúng/vận hành/backup trước TTL.

Kiểm chứng cuối: **517 test Python qua**, Ruff và test collector qua;
Compose pilot config hợp lệ. Browser Chromium + MongoDB thật qua **10 nhóm
kiểm tra**, xuất/verify **6 snapshot thuộc 2 phiên**, gồm retry mất response,
pagehide, outage, restart API và TTL. Các kết quả này chứng minh luồng thu
dữ liệu trong môi trường kiểm thử, không chứng minh accuracy model.

Website cuối chưa có; chưa nghiệm thu TLS/CSP/CORS hoặc deploy cloud trong
lượt này. Docker daemon trên máy không chạy, nên chưa tuyên bố build/chạy
image Docker. Gói code/SDK có thể bàn giao để cấu hình pilot, sau đó cần một
đợt nghiệm thu nhỏ trên website thực.

- [Hướng dẫn giáo viên](pilot/README.md).
- [Hướng dẫn vận hành và export](docs/PILOT_OPERATOR_GUIDE.md).
- [Chi tiết sửa lỗi và chứng cứ](docs/PILOT_HANDOFF_REVIEW_2026-10-19.md).

## Kế hoạch hoàn thiện khóa luận theo phạm vi giới hạn (2026-10-19)

Đã lập kế hoạch và protocol benchmark cho bài toán phát hiện bot trình duyệt
desktop trên một website, tập trung ba nhóm hành vi: tuyến tính, theo mẫu
lặp và macro tác vụ. Đây là phạm vi đề xuất cần thống nhất với giảng viên,
không phải tuyên bố đã nhận diện tốt các nhóm này.

Ưu tiên đầu tiên là bàn giao script để thầy chạy traffic, kiểm chứng lưu/
export snapshot và thu nhãn độc lập. Mốc dataset dự kiến: 15 người x 6 phiên
và ba họ bot x 60 lượt; chia người/config block trước khi tạo cửa sổ. Dữ liệu
cũ tiếp tục là development/regression. Script human control mở Playwright
chỉ là đối chứng chuột; cần browser native để đánh giá profile người thật.

Thực nghiệm E0-E4 tách heuristic, XGBoost, BiLSTM, fusion baseline và candidate.
Báo ma trận 2x3, lỗi người/bot, SUSPECT, coverage và diễn tiến qua snapshot;
không tính SUSPECT là bot phát hiện đúng. Tối ưu trên train/validation, khóa
candidate trước test mới. Chưa chạy thêm thí nghiệm hoặc thay model trong
lượt lập kế hoạch; 482 test là kết quả kiểm tra source của lượt trước.

Kế hoạch khoảng 14-20 ngày công là ước lượng, chưa có hạn nộp/rubric để xác
nhận. Mục tiêu là hoàn thiện nhiều nhất trong phạm vi hiện tại, có dữ liệu và
kết quả tái hiện; không bảo đảm điểm 10 hoặc độ chính xác production.

- [Kế hoạch chi tiết](docs/THESIS_COMPLETION_PLAN_2026-10-19.md).
- [Protocol benchmark v1](docs/THESIS_BENCHMARK_PROTOCOL_V1.md).
- [Đề cương tóm tắt gửi thầy](docs/THESIS_PROPOSAL_2026-10-19.md).

## Phân tích chi tiết từng thao tác chuột (2026-10-19)

Đã bổ sung `core_ml/analyze_mouse_actions.py` để phân tích offline từng sự kiện:
tọa độ, thời gian, vector vận tốc, gia tốc, jerk, góc đổi hướng và độ cong;
tổng hợp theo từng đoạn di chuyển, cặp nhấn–thả, click và sự kiện wheel.
Các đại lượng được tính lại từ tọa độ/thời gian, không tin vào tốc độ client gửi.
Thiếu dữ liệu được giữ là `null`; timestamp trùng, khoảng nghỉ, nguồn touch,
đầu vào lỗi và cặp nhấn–thả không đầy đủ đều được xử lý riêng.

Đã chạy trên **18 lượt bot / 90 cửa sổ gửi thực tế đã lưu**, xuất JSON hợp lệ
cho toàn bộ cửa sổ. Ba báo cáo chi tiết circular, heavy-wander, scrub-hover
lưu tại `C:/Users/Admin/bot-detection-research/mouse-actions-2026-10-19`.
Thêm **38 test**, toàn bộ suite **482 test qua**; Ruff qua, còn một cảnh báo
deprecation của Starlette TestClient.

Đây là lớp đo đạc offline, chưa đưa vào điểm phân loại hoặc dashboard.
Collector hiện chỉ gửi tối đa 100 sự kiện và chưa có button, pointer type,
khung tọa độ hay wheel deltaMode. Vì thế chưa thể gọi là lịch sử đầy đủ của
cả phiên, cũng chưa có bằng chứng tăng độ chính xác. Bước kế tiếp là bổ sung
schema và batch thu sự kiện có định danh/chống trùng, sau đó kiểm chứng đặc
trưng mới bằng dữ liệu người thật và bot trên cùng website trước khi train.

Chi tiết, lệnh chạy và kế hoạch triển khai:
[MOUSE_ACTION_ANALYSIS_2026-10-19.md](docs/MOUSE_ACTION_ANALYSIS_2026-10-19.md).

## Thử nghiệm huấn luyện model chuột từ ý tưởng repo tham khảo (2026-10-13)

Đã xác minh ba clone DELBOT-Mouse, bot-signal, BeCAPTCHA-Mouse và đọc phần
biểu diễn quỹ đạo, chia dữ liệu, cửa sổ hành vi và hướng dẫn benchmark.
DELBOT có ví dụ chia ngẫu nhiên sau khi tạo chunk; thí nghiệm này không dùng
cách chia đó. BeCAPTCHA repo không chứa detector/dataset được cấp sẵn để train.

Đã triển khai `core_ml/experiments/mouse_ablation.py` và train **9 model XGBoost
thử nghiệm** (3 cấu hình x 3 họ bot giữ lại). So sánh 20 đặc trưng cũ, thêm
bot từ runner, và thêm 5 đặc trưng chuyển động cục bộ. Phiên được chia trước
khi tạo cửa sổ; fixed/jitter cùng họ không được chia sang train và test.
Trọng số cân bằng theo lớp và phiên, không theo độ dài phiên. Ngưỡng và
hyperparameter được giữ cố định, không điều chỉnh theo kết quả test.

**Kết quả chưa đạt, không thay bundle chính:** bản 25 đặc trưng nhận nhầm
HUMAN ở kết luận cuối của **18/18 lượt bot thuộc các họ giữ lại**. XGBoost
đóng băng hiện tại khi chạy riêng nhận 5 BOT, 8 HUMAN, 5 SUSPECT trên cùng
các cửa sổ. Đây là so sánh thành phần XGBoost, không phải kết luận ensemble.
9 phiên người thật test không có cửa sổ BOT trong các lượt thử, nhưng cùng
9 phiên được dùng lại qua ba fold, không phải 27 người; cũng chưa có người
thật đối chứng cùng website. Kết quả này không chứng nhận production.

Model thử nghiệm lưu ngoài repo tại
`C:/Users/Admin/bot-detection-research/mouse-ablation-2026-10-13-v1`;
không thay trọng số, API hay collector. Bộ kiểm thử thêm 27 ca, gồm kiểm tra
rò rỉ dữ liệu, cửa sổ thiếu dữ liệu, cân bằng phiên và nạp lại artifact.
Kiểm tra cuối: `python -m pytest -q` qua **444 test**, còn một cảnh báo
deprecation của Starlette TestClient; Ruff qua. Test code qua không có nghĩa
là chất lượng model thử nghiệm đã cải thiện.

Chi tiết giao thức, nguồn code và phân tích kết quả:
[MOUSE_ABLATION_REVIEW_2026-10-13.md](docs/MOUSE_ABLATION_REVIEW_2026-10-13.md).
Kết quả đầy đủ:
[MOUSE_ABLATION_RESULTS_2026-10-13.json](docs/MOUSE_ABLATION_RESULTS_2026-10-13.json).

---

## Tích hợp policy profile thử nghiệm vào luồng predict (2026-10-13)

Đã bổ sung `predict(payload, profile_candidate=True)` trong ensemble chính để
chạy A/B thực sự, không chỉ đổi nhãn ở công cụ báo cáo. Mặc định vẫn là false;
API/server chưa bật policy này. Candidate có phiên bản riêng
`10+profile_corroborated_v1`, không dùng lại chứng nhận release của policy 10.

Tham khảo BotD về dấu vết automation và fpscanner về đối chiếu page/worker:
HeadlessChrome phải xuất hiện ở cả hai ngữ cảnh, hoặc đi kèm một marker
automation boolean rõ ràng. Không coi hai trường UA/brands trong cùng ngữ cảnh
là hai nguồn; worker lỗi không được dùng để đối chiếu. Lệch OS, thiếu API,
điểm heuristic cao hoặc chuyển động đều không tự động kích hoạt quy tắc.

**Replay 42 lượt BOT có nhãn runner, 186 snapshot đã gửi:**

| Kết luận cuối | Baseline | Candidate |
| --- | ---: | ---: |
| BOT | 6 | 15 |
| HUMAN (bỏ sót bot) | 20 | 14 |
| SUSPECT | 16 | 13 |

9 lượt đổi kết luận là stealth circular/heavy-wander/scrub-hover trên
secure localhost, nơi Client Hints còn lộ HeadlessChrome ở page và worker.
36 snapshot đổi kết luận. Nhóm HTTP không cải thiện. Đây là replay dữ liệu
đã dùng để phân tích rule, không phải kiểm thử độc lập hay tỷ lệ production.

449 phiên dataset chuột (109 HUMAN, 340 BOT) giữ nguyên kết luận cuối.
Dataset này không có profile, nên không chứng minh candidate không nhận nhầm
người thật. **Chưa có người thật đối chứng với profile trên website; chưa bật
candidate mặc định, chưa retrain, chưa deploy hoặc push.**

Kiểm chứng: **417 test Python passed**, Ruff, test collector và Compose config
đều qua. Chi tiết, nguồn, giới hạn và lệnh tái hiện:
[PROFILE_POLICY_REVIEW_2026-10-13.md](docs/PROFILE_POLICY_REVIEW_2026-10-13.md).
Kết quả máy đọc:
[PROFILE_CANDIDATE_RESULTS_2026-10-13.json](docs/PROFILE_CANDIDATE_RESULTS_2026-10-13.json).

---

## Nghiên cứu mã nguồn mở và đặc trưng chuyển động cục bộ (2026-10-13)

Đã clone 9 repository tham khảo vào `C:/Users/Admin/bot-detection-research`,
nằm ngoài repo sản phẩm: BotD, FingerprintJS, fpscanner, CreepJS, bot-signal,
DELBOT-Mouse, BeCAPTCHA-Mouse, CrowdSec và Baskerville. Đã ghi commit nguồn;
không cài dependency hay chạy script của các repo này, không đưa chúng lên GitHub sản phẩm.

`interaction_window_v2` bổ sung 5 đặc trưng liên tục về biến thiên tốc độ,
độ thẳng và độ đều khi đổi hướng trong các cửa sổ 14 điểm, dịch từng điểm.
Giữ nguyên 11 đặc trưng cũ. Touch, khoảng nghỉ dài và timestamp trùng không
bị nối thành cùng một đoạn; dữ liệu không đủ giữ `null`. Tất cả vẫn ở chế độ
`measurement_only`, `release_approved: false`, không tham gia quyết định model.

Replay offline cùng bundle trên **18 lượt bot, 90 snapshot, 6 họ kịch bản**:
kết luận cuối vẫn **8 HUMAN, 10 SUSPECT, 0 BOT**. Đây là lỗi bỏ sót đã biết,
không phải cải thiện độ chính xác. Không có người thật trong bộ capture này.
Không đổi trọng số, ngưỡng, collector hay artifact model; chưa retrain/deploy.

Đã thêm **23 test**, toàn bộ suite **389 passed**; Ruff, test collector và
`docker compose config --quiet` đều qua. Phép đo cục bộ 100 điểm/87 cửa sổ,
200 lần mỗi cách tính, cho median 4,132 ms so với 17,760 ms của cách tính
CV tham chiếu bằng `pstdev`. Đây chỉ là tốc độ trích xuất đặc trưng mới,
không phải tốc độ HTTP hay so sánh với production v1 vốn tính ít đặc trưng hơn.

Chi tiết, nguồn tham khảo và kế hoạch kiểm chứng:
[LOCAL_MOTION_REVIEW_2026-10-13.md](docs/LOCAL_MOTION_REVIEW_2026-10-13.md).
Kết quả tổng hợp: [INTERACTION_RESULTS_2026-10-13.json](docs/INTERACTION_RESULTS_2026-10-13.json).

---

## Triển khai nền tảng thu snapshot nghiên cứu (2026-10-12)

Đã bổ sung chế độ opt-in `BOT_CAPTURE_ENABLED` (mặc định false), lưu snapshot
telemetry vào `telemetry_captures` trước inference. Bản JSON nghiên cứu giữ
scroll/touch/profile sau validation, không dùng projection rút gọn của dashboard.

- Snapshot có timestamp và sequence được chống trùng bằng hash nội dung;
  payload thiếu định danh ổn định dùng UUID, không gộp nhầm các lần gửi.
- Model không sẵn sàng hoặc inference lỗi không làm mất raw đã thu: API chỉ
  trả 202/recorded sau khi MongoDB hoặc SQLite đã ghi thành công; không tạo verdict giả.
- Prediction đầu tiên ghi thành công được lưu riêng với bundle thực sự dùng;
  replay không chạy lại model hoặc gắn prediction cũ với bundle mới.
- TTL capture mặc định 7 ngày; maintenance dọn capture hết hạn trong spool
  kể cả khi MongoDB lỗi. Admin delete xóa cả bản tổng hợp và lịch sử capture.
- Hàng đợi/đĩa không nhận được dữ liệu thì trả lỗi retryable, không xác nhận ghi giả.

Hai regression test đã thất bại trên luồng cũ trước khi sửa (503 và không ghi
raw khi model lỗi). Bộ kiểm thử mới bổ sung retry, dữ liệu đầy đủ, outage,
restart/replay, phiên bản prediction, TTL và tình huống xóa đồng thời.
Hướng dẫn chi tiết: [RESEARCH_CAPTURE.md](docs/RESEARCH_CAPTURE.md).

**Kiểm chứng local:** `python -m pytest -q`: 366 passed; `python -m ruff
check .`: passed; `npm test` trong collector: build/lifecycle/profile passed;
`docker compose config --quiet`: passed. Generated collector không đổi.
Có một cảnh báo deprecation từ Starlette/httpx trong test, không phải test failure.
Thay đổi index tác động luồng DB/readiness dùng chung, nên đã chạy cả suite
thay vì chỉ test capture. Bộ test DB hiện dùng test double, chưa phải MongoDB thật.

**Giới hạn:** chưa bật cờ trên server, chưa deploy, chưa chạy lại benchmark
model hay thu traffic/vendor mới. Đây không phải bằng chứng tăng độ chính xác.
Docker daemon local chưa chạy nên chưa xác minh MongoDB/TTL thật. Chưa có
export dataset và mapping nhãn vendor; cần hoàn thiện trước đợt thu chính.

---

## Nghiên cứu hướng thương mại và chuẩn bị thu traffic thật (2026-10-12)

Đã đối chiếu tài liệu chính thức của Cloudflare, DataDome, Fingerprint,
Kasada, HUMAN và Akamai với source hiện tại. Phân tích cơ chế, nguồn tài liệu,
tính khả thi, corner case và kế hoạch kiểm chứng nằm trong
[COMMERCIAL_BOT_DETECTION_RESEARCH_2026-10-12.md](docs/COMMERCIAL_BOT_DETECTION_RESEARCH_2026-10-12.md).
Đây là nghiên cứu và đề xuất; chưa tích hợp vendor, đổi model/policy hay chạy
benchmark mới trong lần cập nhật này. Không xác nhận trạng thái server từ
việc đọc source local.

**Ưu tiên được đề xuất:** kho sự kiện và nhãn có nguồn; chống trùng/phát lại;
profile có trạng thái khả dụng; candidate tương tác ngắn; lịch sử không đếm
lặp và fusion theo miền đầu vào. Request nghiệp vụ cần tích hợp backend/CDN
website; TLS fingerprint và học biểu diễn tự giám sát để ở giai đoạn sau.
Giữ BiLSTM + XGBoost + heuristic làm baseline và ba verdict HUMAN/SUSPECT/BOT.

**Điểm phát hiện khi nghiên cứu, trước bản sửa bên trên:** `detection_results`
cập nhật theo phiên, chưa lưu mọi snapshot; collector có cửa sổ giới hạn và
ingestion chạy inference trước persistence. Chế độ capture mới giải quyết
phần lưu snapshot độc lập; export và mapping đến kết quả vendor còn cần
hoàn thiện trước đợt thu chính. Trial vendor nên chạy đồng thời với traffic
thật; nhãn thương mại là tham khảo, không mặc định là ground truth.

Kế hoạch thu thật của giảng viên thay đổi ưu tiên trước đây chỉ thử offline.
Cần nhóm người thật dùng browser thường và các lần chạy bot biết nguồn để đo
nhận nhầm. Tỷ lệ SUSPECT phải tách theo nguyên nhân, thời điểm và miền đầu vào;
không giảm bằng cách ép các phiên thiếu bằng chứng sang HUMAN hoặc BOT.

---

## Trạng thái hiện tại và hướng tối ưu (2026-09-29)

**Bundle đang phục vụ:** `e3dd550e4d40453db0e17a743da7e992`, decision policy 10.
Hệ thống dùng BiLSTM, XGBoost trên thống kê chuột và BotD. Dataset huấn luyện
chưa có profile trình duyệt có nhãn tương ứng, nên các cột environment của
XGBoost được điền 0 khi train; không được diễn giải điểm XGBoost hiện tại là
khả năng phân loại fingerprint. Quy tắc profile độc lập hiện chỉ kết luận BOT
cho HeadlessChrome tự khai kèm dấu hiệu automation được đối chiếu với HTTP UA.
Không có chuột, profile yếu hoặc không khớp miền huấn luyện vẫn là SUSPECT;
không tự động nâng tất cả lên BOT.

**Bằng chứng browser có nhãn:** 15 lần chạy Playwright trên cùng website,
5 lần mỗi họ heavy-mouse, circular-spiral và scrub-hover. Đây là nhãn từ
runner, không lấy từ model. Tại snapshot cuối đã gửi lên collector: 0/15 BOT,
12/15 HUMAN, 3/15 SUSPECT. Cả 3 SUSPECT đều có mã
`MODEL_DISAGREEMENT`; không có phiên nào trong nhóm này bị hoãn vì thiếu
chuột tại snapshot cuối. Các mã nguyên nhân là nhãn chẩn đoán, không làm thay
đổi kết luận. Chi tiết giao thức và các candidate ở
[`docs/FIELD_BOT_PILOT_2026-09-29.md`](docs/FIELD_BOT_PILOT_2026-09-29.md).
Mẫu này quá nhỏ, cùng một website/generator và không có người thật đối chứng
cùng site; không suy ra tỷ lệ lỗi production từ 15 lần chạy.

**Chẩn đoán domain gap (cửa sổ collector cuối/phiên, bundle trên):**

| Nguồn nhãn | Số phiên | HUMAN | SUSPECT | BOT | Trung vị độ thẳng | Trung vị tốc độ |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Phase 1 người thật | 50 | 50 | 0 | 0 | 0,7604 | 0,3551 |
| Phase 1 bot | 100 | 0 | 11 | 89 | 0,8664 | 0,1975 |
| Phase 2 người thật | 59 | 57 | 2 | 0 | 0,3660 | 0,9002 |
| Phase 2 bot | 240 | 0 | 38 | 202 | 0,8615 | 0,1596 |
| Bot browser, 3 họ | 15 | 12 | 3 | 0 | 0,1556–0,2690 | 0,3170–0,5199 |

Đây là phép **chẩn đoán trên cả train/validation/test của dataset gốc**,
không phải chỉ số holdout hoặc tỷ lệ chính xác. Bot browser có hình học gần
nhóm người thật hơn các bot gốc; trung vị XGBoost của ba họ bot browser chỉ
0,0004–0,0059 (điểm model chưa hiệu chuẩn). Kết quả có thể chạy lại bằng
`python -m core_ml.evaluate_mouse_domain --dataset-root <dataset> --capture-dir <bot-captures>`.
Thêm `--human-capture-dir <human-captures>` để so sánh người thật cùng site
khi đã có dữ liệu. Dữ liệu người thật cần được thu bằng thao tác thực, nhãn
do người tham gia xác nhận; script private `bot-detection-test/collect-human-control.js`
chỉ lưu chuột và mã người tham gia giả danh. Browser Playwright có thể làm
BotD báo automation, nên mẫu đó **chỉ đối chứng nhánh chuột**, không đối chứng
profile. Không huấn luyện hay phát hành lại từ phép chẩn đoán này.

| Phiên bản thử nghiệm | Kết quả trên 15 bot browser | Kiểm tra người thật tập test gốc | Quyết định |
| --- | --- | --- | --- |
| Baseline đang phục vụ | 0 BOT, 12 HUMAN, 3 SUSPECT | 1.255/24.000 cửa sổ test là SUSPECT | Giữ làm mốc so sánh, chưa bật chặn tự động |
| Chỉ train lại XGBoost `4da81d59...` | 0 BOT, 0 HUMAN, 15 SUSPECT | 1.279/24.000 cửa sổ test là SUSPECT; BOT recall cuối test giảm từ 60/66 xuống 58/66 | Diagnostic-only, không phát hành |
| Train lại BiLSTM + XGBoost `d27030f7...` | Circular (họ train) 5/5 BOT; heavy 0/5 BOT; scrub holdout 0/5 BOT | 3.446/24.000 cửa sổ test là SUSPECT, max 32,8%/phiên, vượt release gate | Diagnostic-only, không phát hành |
| Train lại BiLSTM + XGBoost `0c7b1c0e...` | Circular và scrub (họ train) 8/10 BOT; heavy-mouse holdout 0/5 BOT, 5/5 HUMAN | 2.463/24.000 cửa sổ test là SUSPECT (10,26%); max 25,2%/phiên, đều vượt gate | Diagnostic-only, không phát hành |

Phép thử giữ riêng `heavy-mouse` cho thấy candidate học được hai họ đã thấy nhưng
không khái quát sang họ chưa thấy. Báo cáo holdout hiện được tính **trước** replay
90.000 cửa sổ và lưu trong manifest cả khi candidate trượt gate; bot có nhãn bị
kết luận HUMAN ở snapshot cuối sẽ làm candidate trượt ngay. Đây là kiểm tra chống
lọt lỗi đã biết, không chứng minh khả năng phát hiện mọi bot mới. Chưa có nhóm
người thật có nhãn độc lập trên cùng site để đánh giá trade-off false positive.

**Kế hoạch tối ưu có kiểm chứng:**

1. **Đã bắt đầu:** gắn `suspect_reason_codes` vào breakdown và đếm nguyên
   nhân ở snapshot cuối theo họ bot. Mã có thể đồng xuất hiện; tổng theo mã
   không nhất thiết bằng số SUSPECT. Không đổi verdict, score hoặc ngưỡng.
2. **Thu nhãn độc lập:** khoảng 30-50 lần/họ bot với biến thiên seed, tốc độ,
   viewport và cách thao tác; thêm 20-30 người thật tự nguyện dùng chính site,
   gồm chuột, touchpad, kéo chọn, ít di chuột. Lưu payload collector đã gửi,
   header HTTP quan sát được, nhãn nguồn chạy, phiên bản script/model và từng
   snapshot. Đây là cỡ mẫu khảo sát, không phải chứng nhận production.
3. **Sửa domain gap trước retrain:** đánh giá riêng Phase 1 (timestamp ước
   lượng) và Phase 2/browser (timestamp quan sát), làm ablation đặc trưng nhịp
   thời gian, độ lặp, độ cong. Chia theo phiên/người/họ generator trước khi
   tạo cửa sổ; giữ nguyên một họ bot làm holdout.
4. **Thử từng thay đổi:** XGBoost trên bộ train cân bằng theo phiên; BiLSTM
   trên dữ liệu có timestamp thật; cuối cùng mới đánh giá lại fusion/ngưỡng
   trên validation. So sánh số bot bị HUMAN, người thật bị BOT, thời lượng
   SUSPECT và replay dày của bundle cũ với candidate.
5. **Release gate:** chỉ phát hành khi không tăng false BOT ở nhóm người thật
   độc lập, giảm bot HUMAN trên họ chưa gặp và qua toàn bộ regression/replay.
   Chạy shadow trước; chưa bật chặn tự động khi chưa có nhãn đối chứng.

**Giới hạn còn mở:** chưa có đủ dữ liệu người thật trên website này, các bot
giả chuột tinh vi vẫn thường bị HUMAN và BotD không phát hiện các generator
đã che automation marker. Vì vậy chưa thể xác nhận độ chính xác production
hoặc tuyên bố mô hình đã tối ưu tối đa.

---

## Thử nghiệm profile shadow (2026-10-02)

Đã triển khai bước đầu của kế hoạch nghiên cứu: collector thu profile của trang
và Worker, gồm UA, platform, trạng thái webdriver và Client Hints (kể cả
`fullVersionList`). Mỗi probe có timeout tối đa 1 giây mặc định; Worker được
dọn khi hoàn tất, timeout hoặc hủy collector. API trả phân tích riêng ở
`breakdown.profile_shadow` và lưu cùng telemetry. Các tín hiệu này **chưa
tham gia score/verdict của policy 10**; không thay trọng số hoặc weights model.

Nhánh shadow thử phát hiện HeadlessChrome ở UA/Client Hints và webdriver trong
Worker. Mâu thuẫn OS chỉ tạo gợi ý SUSPECT; thiếu API, CSP chặn Worker, khác CPU,
locale hay phiên bản UA không tự tạo bằng chứng BOT. Profile không có tín hiệu
không được coi là bằng chứng HUMAN. Hai tín hiệu cùng nguồn không phải hai
bằng chứng độc lập.

**Benchmark mới:** 24 phiên automation trên trang fixture local, gồm 6 phiên
Playwright thường và 18 phiên stealth (heavy-wander, circular, scrub-hover;
3 seed/họ/origin). Chạy collector UMD thật, gửi 4 snapshot/phiên đến HTTP server
local và giữ một probe riêng để chẩn đoán. Đây là kịch bản được dựng cho thử
nghiệm profile; không phải chạy lại y nguyên 15 phiên trên website ngày 29/09.

| Nhóm | Số phiên | Baseline BOT / SUSPECT / HUMAN | Overlay shadow BOT / SUSPECT / HUMAN |
| --- | ---: | --- | --- |
| Playwright thường, cả hai origin | 6 | 6 / 0 / 0 | 6 / 0 / 0 |
| Stealth trên localhost secure context | 9 | 0 / 3 / 6 | 9 / 0 / 0 |
| Stealth trên HTTP insecure context | 9 | 0 / 3 / 6 | 0 / 3 / 6 |

Origin an toàn vẫn để lộ brand `HeadlessChrome` trong Client Hints của trang
và Worker dù UA đã được stealth sửa. HTTP không cung cấp Client Hints và UA
Worker cũng được sửa, nên chưa giảm điểm mù ở nhóm HTTP. Cả 24 Worker hoạt động,
không có page error. Kết quả so sánh dùng bundle
`e3dd550e4d40453db0e17a743da7e992`, không retrain trên benchmark này.

**Chưa có người thật đối chứng:** không suy ra false-positive rate, không xem
9/9 là khả năng phát hiện mọi stealth bot, không phát hành overlay thành policy.
HTTP website hiện tại vẫn có điểm mù. Dữ liệu/script bot nằm ngoài Git trong
`C:/Users/Admin/bot-detection-test`; chỉ báo cáo tổng hợp được commit.

Đã sửa thêm bộ test collector: dùng vị trí resolver động và watchdog để test
có promise chưa hoàn tất không âm thầm kết thúc thành công. Kiểm thử mới bao
phủ profile bị thiếu/sai định dạng, timeout/CSP, hủy Worker, privacy CPU/locale,
Android, bảo toàn verdict/weights và round-trip detect/telemetry.

Lần kiểm tra này: **301 test Python, test collector/profile và Ruff đều qua**.
Không chạy lại replay 90.000 cửa sổ cho thay đổi diagnostic-only này và không
dùng kết quả shadow để chứng nhận một policy mới.

Rà soát cuối bổ sung hủy probe cho đường lấy payload/status trước `start()` và
bỏ probe mới khi pagehide; regression test đã tái hiện lỗi trước khi sửa.

**Bước tiếp theo:** thu người thật bằng trình duyệt thường, có cả privacy mode;
đánh giá từng tín hiệu trước khi cho tham gia quyết định. Nhánh HTTP cần thử
đặc trưng chuỗi click/scroll/di chuyển và dữ liệu bot có timestamp thật theo
hướng FP-Agent, rồi mới retrain XGBoost và đối chiếu holdout theo họ bot/người.
Giữ BeCAPTCHA-Mouse ở bước nghiên cứu neuromotor sau khi xin quyền dùng dữ liệu
và xác minh thông tin thời gian; chưa cài trọn các thư viện fingerprint.

Nguồn tham khảo:

- [FP-Inconsistent, bài báo](https://arxiv.org/html/2406.07647v2) và
  [repo tác giả](https://github.com/hariv/fp_inconsistent): phương pháp kiểm tra
  tính nhất quán; chưa sao chép bộ luật hoặc dùng tỷ lệ của bài báo làm metric DATACAT.
- [CreepJS](https://github.com/abrahamjuliot/creepjs): tham khảo kiểm tra profile
  bị can thiệp; fingerprint protection không đồng nghĩa automation.
- [bot-signal](https://github.com/okasi/bot-signal): maintainer ghi nhận khác CPU
  giữa trang/Worker trên Opera; DATACAT loại tín hiệu này khỏi shadow verdict.
- [MDN userAgentData](https://developer.mozilla.org/en-US/docs/Web/API/Navigator/userAgentData):
  giới hạn secure context và hỗ trợ browser.
- [FP-Agent, bài báo](https://arxiv.org/html/2605.01247v1) và
  [repo](https://github.com/ethanbwang/fp-agent): tham khảo bước phân tích tương tác;
  chưa tải dữ liệu OSF hay tích hợp classifier của tác giả.
- [BeCAPTCHA-Mouse](https://github.com/BiDAlab/BeCAPTCHA-Mouse): benchmark cần xin
  quyền truy cập, raw được mô tả chỉ có x/y; chưa dùng để huấn luyện.

Báo cáo và lệnh tái hiện: [PROFILE_SHADOW_REVIEW_2026-10-02.md](docs/PROFILE_SHADOW_REVIEW_2026-10-02.md).

---

## Đo tương tác và benchmark HTTP bổ sung (2026-10-02)

Đã sửa lỗi bộ đọc capture loại bỏ `scrollEvents`: replay hiện giữ dữ liệu cuộn
hợp lệ, báo lỗi nếu dữ liệu sai thay vì âm thầm bỏ qua. Tám regression case đã
thất bại trước sửa và qua sau sửa. Nhánh `breakdown.interaction_shadow` bổ sung
11 đặc trưng nhịp move/click, thời gian nhấn, khoảng dừng trước click và cuộn.
Thiếu quan sát trả `null`; dữ liệu bị giới hạn 100 record/50 wheel event, tách
touch và không ghép nhầm các lần nhấn thiếu cặp. Đây là phép đo cửa sổ giữ lại,
không phải tổng cả phiên, không đưa ra verdict và không thay score/weights.

Theo lựa chọn hiện tại của người dùng, **chưa có người thật đối chứng, tiếp tục
thử nghiệm offline**. Không retrain hoặc thay bundle đang phục vụ. Đã chạy thêm
18 phiên stealth HTTP local, ba họ heavy-wander/circular/scrub-hover, nhịp cố định
và jitter, ba seed mỗi cấu hình. Collector thật gửi 90 snapshot; probe không
tham gia đánh giá, không có page error. Cả 18 phiên có dữ liệu click/cuộn để đo
nhịp; benchmark 24 phiên trước đó không đủ click/cuộn cho phép đo này.

Kết luận cuối của baseline trên benchmark mới vẫn là **0 BOT, 10 SUSPECT,
8 HUMAN**; có 9 phiên từng bị HUMAN. Nhánh mới chưa cải thiện các verdict này.
Phân bố click-CV giữa nhịp cố định/jitter có giao nhau, nên chưa có cơ sở thêm
luật “nhịp đều là BOT”. Không dùng tỷ lệ này làm metric production hoặc so sánh
trực tiếp với fixture cũ. Bundle/policy vẫn là `e3dd550e4d40453db0e17a743da7e992`/10.

Kiểm chứng: **339 test Python, test collector/profile và Ruff đều qua**; có một
cảnh báo deprecation thư viện test. Không chạy lại replay 90.000 cửa sổ và không
phát hành weights mới. Chi tiết và lệnh tái hiện:
[INTERACTION_REVIEW_2026-10-02.md](docs/INTERACTION_REVIEW_2026-10-02.md),
[kết quả tổng hợp](docs/INTERACTION_RESULTS_2026-10-02.json).

Bước tiếp theo là mở rộng benchmark theo họ bot/tốc độ/viewport, rồi thu người
thật độc lập khi có thể. Không trộn timestamp ước lượng của Phase 1 với timestamp
browser để train nhịp tương tác, không điền thiếu click/cuộn thành số 0. Tách theo
người/phiên/họ generator trước khi tạo cửa sổ; giữ một họ bot chưa gặp để kiểm
chứng khả năng khái quát trước khi thêm đặc trưng vào XGBoost.

---

## 1. TỔNG QUAN KIẾN TRÚC HỆ THỐNG

### 1.1 Pipeline tổng thể

```
                    ┌──────────────────────────────────────────────────┐
                    │              DATA COLLECTION                     │
                    │                                                  │
                    │  ┌─────────┐   ┌──────────┐   ┌─────────────┐   │
                    │  │ Mouse   │   │ Browser  │   │ BotD        │   │
                    │  │ Events  │   │ Finger-  │   │ Heuristic   │   │
                    │  │ (x,y,t) │   │ print    │   │ Detectors   │   │
                    │  └────┬────┘   └────┬─────┘   └──────┬──────┘   │
                    └───────┼─────────────┼────────────────┼──────────┘
                            │             │                │
                    ┌───────▼─────────────▼────────────────▼──────────┐
                    │              FEATURE EXTRACTION                   │
                    │                                                  │
                    │  ┌──────────────┐  ┌───────────────────────┐    │
                    │  │ Kinematic    │  │ Environment + BotD    │    │
                    │  │ Features     │  │ Features (43 dims)    │    │
                    │  │ (8 dims/step)│  │                       │    │
                    │  └──────┬───────┘  └──────────┬────────────┘    │
                    └─────────┼─────────────────────┼─────────────────┘
                              │                     │
                    ┌─────────▼──────────┐  ┌───────▼─────────────┐
                    │  Behavioral BiLSTM │  │  Tabular XGBoost    │
                    │  + Temporal Attn   │  │  + StandardScaler   │
                    │  (sequence model)  │  │  (aggregate model)  │
                    └─────────┬──────────┘  └───────┬─────────────┘
                              │                     │
                    ┌─────────▼─────────────────────▼─────────────┐
                    │       ENSEMBLE (Confidence-based Fusion)     │
                    │  + BotD Heuristic Score                      │
                    │  → Verdict: HUMAN / SUSPECT / BOT            │
                    └──────────────────────────────────────────────┘
```

### 1.2 Các mô hình thành phần

| Model | Kiến trúc | Input | Output | Vai trò |
|-------|-----------|-------|--------|---------|
| **BiLSTM** | 2-layer Bidirectional LSTM + TemporalAttention | Chuỗi 24 time steps × 8 features kinematics | P(bot) ∈ [0,1] | Phân tích hành vi chuột theo thời gian |
| **XGBoost** | Gradient Boosted Trees (300 trees, depth 6) | Vector 43 features (env + mouse stats) | P(bot) ∈ [0,1] | Phân tích fingerprint + thống kê hành vi |
| **BotD Heuristic** | Luật phát hiện automation phía client | Fingerprint và browser signals | P(bot) ∈ [0,1] | Bằng chứng trực tiếp về WebDriver/headless |
| **Ensemble** | Confidence-based weighted fusion | BiLSTM + XGBoost + heuristic | Verdict + probability | Kết hợp đa modal |

### 1.3 Bộ Features (50 chiều)

**Nhóm Environment/Fingerprint (30 features):**
- BotD heuristic score, flagged count
- 10 binary detectors (webdriver, virtualGpu, pluginsInconsistency, distinctiveProperties, languagesInconsistency, windowSize, errorTrace, hasProcess, platformMismatch, headlessUa)
- Hardware: concurrency, memory, touch points, screen resolution, color depth, pixel ratio
- Fingerprint: plugins count, fonts count, canvas hash entropy, audio hash entropy
- Consistency checks (FP-Inconsistent paper inspired): is_virtual_concurrency, is_desktop_chrome_zero_plugins, touch_desktop_mismatch, low_screen_resolution, no_audio_support, low_font_count

**Nhóm Mouse Dynamics — Thống kê (20 features — Canonical Single Source of Truth):**
- Cơ bản: mean/std/max speed, mean/std acceleration, max_accel
- Hình học: straightness, direction_changes_x/y
- Thời gian: pause_ratio, jerk_mean, angular_entropy
- **Đặc trưng vi mô (v2):** curvature_mean, curvature_std, time_regularity, velocity_autocorrelation, accel_zero_crossing_rate, movement_efficiency
- **Đặc trưng tương tác hành vi (v2.1):** click_to_move_ratio, speed_skewness, idle_time_ratio

---

## 2. DATASET & TIỀN XỬ LÝ

### 2.1 Nguồn dữ liệu

**Web Bot Detection Dataset (M4D-ITI):**
- Phase 1: 100 sessions (mouse movements) cho scenario `humans_and_moderate_bots`
  - 35 human sessions (train) + 30 moderate_bot sessions (train)
  - 15 human + 20 moderate_bot (test)
- Phase 1: Tương tự cho scenario `humans_and_advanced_bots`
- Dữ liệu gốc ở dạng notation: `[m(x,y)][c(l)][s(n)]`

**Synthetic data (tự tạo):**
- 200 human trajectories (Bézier curves + micro-pauses + overshoot)
- 200 bot trajectories (3 loại: naive/instant, moderate/linear+grid, advanced/bézier)

### 2.2 Tiền xử lý dữ liệu thật

```
Notation "[m(246,6)][m(244,9)]..." 
    → Parse bằng regex → List[{time, x, y, type}]
    → Ước lượng timestamp dựa trên khoảng cách (Fitts's law)
    → Sliding window chunking (chunk_size=24, stride=12)
    → Feature extraction (8 kinematic features per time step)
```

> **Lưu ý quan trọng:** Dataset gốc KHÔNG có timestamp → phải ước lượng. Điều này ảnh hưởng đến các features phụ thuộc thời gian (speed, acceleration). Đây là hạn chế cần nêu rõ.

### 2.3 Phân chia dữ liệu

```
Total: 600 samples (300 Human + 300 Bot)
  - 200 real sessions từ M4D
  - 400 synthetic sessions

Split (stratified):
  Train: 420 (210H + 210B)
  Val:    90 ( 45H +  45B)
  Test:   90 ( 45H +  45B)
```

---

## 3. KẾT QUẢ TRAINING v2 (Baseline)

### 3.1 XGBoost (Tabular — 43 features)

| Tập | ROC-AUC | F1-Score | Precision | Recall | Accuracy |
|-----|---------|----------|-----------|--------|----------|
| Train | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| **Val** | **0.9995** | **0.9773** | **1.0000** | **0.9556** | **0.9778** |
| **Test** | **1.0000** | **1.0000** | **1.0000** | **1.0000** | **1.0000** |

**Confusion Matrix (Val):**
```
           Predicted
           Human  Bot
Actual Human  45    0   ← FP = 0 (không chặn nhầm ai)
       Bot     2   43   ← FN = 2 (bỏ sót 2 bot)
```

**Top 5 Feature Importance:**
1. `direction_changes_y` (0.199) — Số lần đổi hướng theo trục Y
2. `direction_changes_x` (0.121) — Số lần đổi hướng theo trục X
3. `std_speed` (0.105) — Độ biến thiên tốc độ
4. `fonts_count` (0.089) — Số font chữ phát hiện (fingerprint)
5. `time_regularity` (0.080) — **Feature MỚI v2** — std(dt)/mean(dt)

> **Nhận xét:** `time_regularity` là feature mới thêm trong v2, đã lọt Top 5 importance. Điều này xác nhận giả thuyết rằng bot có timing rất đều đặn so với người.

### 3.2 BiLSTM (Behavioral — mouse chunks)

| Tập | ROC-AUC | F1-Score | Precision | Recall | Accuracy |
|-----|---------|----------|-----------|--------|----------|
| **Val** | **0.8240** | **0.6752** | **0.7465** | **0.6163** | **0.7385** |

**Training curve:**
```
Epoch  5/30: Train=0.5695 | Val=0.6022 | LR=0.001867
Epoch 10/30: Train=0.5505 | Val=0.5507 | LR=0.001503
Epoch 15/30: Train=0.5109 | Val=0.5375 | LR=0.001005
Epoch 20/30: Train=0.4782 | Val=0.5153 | LR=0.000508
Epoch 25/30: Train=0.4658 | Val=0.5081 | LR=0.000143
Epoch 30/30: Train=0.4542 | Val=0.5113 | Early stop
```

> **Nhận xét:** LSTM performance thấp hơn XGBoost do: (1) dataset thật không có timestamp gốc → kinematic features bị nhiễu, (2) số lượng chunks ít (2,604) so với model capacity. Tuy nhiên trong Ensemble, LSTM bổ trợ XGBoost ở các case mà tabular features không đủ phân biệt.

## 4. THÍ NGHIỆM TỐI ƯU

### Danh sách thí nghiệm theo thứ tự ưu tiên:

| # | Thí nghiệm | Mục đích | Trạng thái |
|---|-------------|----------|------------|
| E1 | **Baseline Comparison** — Rule-based vs ML | Chứng minh ML tốt hơn heuristic đơn giản | ✅ Hoàn thành |
| E2 | **Concept Drift** — Train moderate → test advanced | Đánh giá khả năng generalize khi bot tiến hóa | ✅ Hoàn thành |
| E3 | **Feature Ablation** — Thiếu fingerprint/mouse thì sao? | Xác định feature group quan trọng nhất | ✅ Hoàn thành |
| E4 | **Class Imbalance** — Ratio 1:1, 1:3, 1:5, 1:10 | Đánh giá robustness khi dữ liệu mất cân bằng | ✅ Hoàn thành |
| E5 | **Early Detection** — Cần bao nhiêu mouse points? | Detection latency analysis | ✅ Hoàn thành |
| E6 | **Inference Latency** — Đo ms per prediction | Tính thực tiễn triển khai | ✅ Hoàn thành |
| E7 | **FPR/ROC Analysis** — Trade-off threshold | Phân tích chi phí chặn nhầm vs bỏ sót | ✅ Hoàn thành |
| E8 | **Short Session** — Session < 10 mouse points | Edge case session quá ngắn | ✅ Hoàn thành |
| E9 | **Power User** — Human straightness > 0.85 | Stress test: model có nhầm "người giỏi" thành bot? | ✅ Hoàn thành |

---

## 5. KẾT QUẢ THÍ NGHIỆM

### 5.1 E1: Baseline Comparison (Rule-based vs ML)

**Mục tiêu:** Chứng minh ML thực sự tốt hơn phương pháp đơn giản.

| Phương pháp | ROC-AUC | F1-Score | Mô tả |
|-------------|---------|----------|-------|
| Heuristic Score chỉ dùng 1 feature | 0.7444 | 0.0000 | Chỉ dùng BotD heuristic score (threshold) |
| Multi-rule (heuristic + straightness + time_regularity) | 0.7515 | 0.6957 | Kết hợp 3 rules thủ công |
| **XGBoost ML (43 features)** | **1.0000** | **1.0000** | Machine Learning toàn bộ 43 features |

> **Kết luận:** ML cải thiện **+33.1% AUC** so với baseline tốt nhất. Rule-based chỉ đạt ~0.75 AUC do không thể khai thác được các mối tương quan phức tạp giữa 43 features. **Đây là bằng chứng mạnh nhất chứng minh giá trị của ML approach.**

---

### 5.2 E2: Concept Drift (Train moderate → Test advanced)

**Mục tiêu:** Kiểm tra model có phát hiện được loại bot CHƯA TỪNG THẤY không.

| Scenario | ROC-AUC | F1 | Recall | Nhận xét |
|----------|---------|-----|--------|----------|
| Train=Moderate → Test=Advanced | **0.6062** | **0.0000** | **0.0000** | ⚠️ THẤT BẠI HOÀN TOÀN |
| Train=Advanced → Test=Moderate | 0.9960 | 0.8889 | 0.8000 | Tốt — advanced bot khó hơn nên model mạnh hơn |
| Train=Both → Test=Both | 1.0000 | 1.0000 | 1.0000 | Hoàn hảo khi train đa dạng |

> **Kết luận QUAN TRỌNG:** Đây là phát hiện **có giá trị học thuật cao nhất** trong đồ án:
> - Model train chỉ trên moderate bot **hoàn toàn không phát hiện được advanced bot** (Recall=0.0!) → **Concept drift là mối đe dọa thực sự.**
> - Ngược lại, model train trên advanced bot vẫn phát hiện tốt moderate bot (Recall=0.80) → Bot phức tạp hơn giúp model học được patterns tổng quát hơn.
> - **Giải pháp:** Training trên đa dạng loại bot là BẮT BUỘC. Khi deploy cần retrain định kỳ khi xuất hiện bot mới.

---

### 5.3 E3: Feature Ablation Study

**Mục tiêu:** Feature group nào quan trọng nhất?

| Feature Group | Số features | ROC-AUC | F1-Score |
|---------------|-------------|---------|----------|
| Tất cả features | 43 | 1.0000 | 1.0000 |
| **Chỉ Mouse Dynamics** | **17** | **1.0000** | **1.0000** |
| Chỉ v2 new features | 6 | 1.0000 | 0.9944 |
| Không có v2 features | 37 | 1.0000 | 1.0000 |
| Không có BotD heuristics | 40 | 1.0000 | 1.0000 |
| **Chỉ Environment/Fingerprint** | **26** | **0.9369** | **0.7755** |

> **Kết luận:**
> - **Mouse dynamics (17 features) đủ mạnh để đạt AUC=1.0 một mình** → Hành vi chuột là tín hiệu phân biệt mạnh nhất.
> - Environment/Fingerprint chỉ đạt 0.9369 khi dùng đơn lẻ → Fingerprint dễ bị giả mạo, không đáng tin nếu dùng riêng.
> - **6 features MỚI (v2) đủ mạnh để đạt AUC=1.0** với chỉ 6 chiều → Curvature và time_regularity là features rất discriminative.
> - **Ý nghĩa thực tế:** Ngay cả khi bot giả fingerprint hoàn hảo, mouse dynamics vẫn phát hiện được.

---

### 5.4 E4: Class Imbalance Robustness

**Mục tiêu:** Model hoạt động ra sao khi tỷ lệ bot trong training data rất thấp?

| Tỷ lệ H:B | Train | ROC-AUC | F1 | Recall | FPR |
|-----------|-------|---------|-----|--------|-----|
| 1:1 | 150H + 150B | 0.9912 | 0.9873 | 0.9750 | 0.0000 |
| 1:3 | 150H + 50B | 0.9894 | 0.9873 | 0.9750 | 0.0000 |
| 1:5 | 150H + 30B | 0.9825 | 0.9873 | 0.9750 | 0.0000 |
| **1:10** | 150H + 15B | **0.9675** | **0.9041** | **0.8250** | **0.0000** |

> **Kết luận:**
> - Model **cực kỳ robust**: ngay cả khi chỉ có 15 bot samples (1:10), AUC vẫn đạt 0.9675 và FPR=0.
> - Recall giảm dần (0.975→0.825) nhưng Precision luôn giữ 100% (FPR=0) → **Không bao giờ chặn nhầm người thật.**
> - `scale_pos_weight` của XGBoost phát huy hiệu quả trong xử lý imbalanced data.

---

### 5.5 E5: Early Detection (Minimum Mouse Points Required)

**Mục tiêu:** Cần bao nhiêu điểm chuột tối thiểu để phát hiện bot?

| Mouse Points | AUC-ROC | F1 | Recall |
|-------------|---------|-----|--------|
| **5 points** | **0.9898** | **0.9524** | **0.9722** |
| 10 points | 0.9994 | 0.9859 | 0.9722 |
| 15 points | 1.0000 | 0.9859 | 0.9722 |
| 20 points | 0.9997 | 0.9859 | 0.9722 |
| 30 points | 1.0000 | 0.9930 | 0.9861 |
| 50+ points | 1.0000 | 1.0000 | 1.0000 |

> **Kết luận:**
> - **Chỉ cần 5 điểm chuột** đã đạt AUC=0.9898 → Model có thể phát hiện bot **trong chưa đầy 100ms** sau khi người dùng bắt đầu di chuột.
> - 10 điểm đạt AUC=0.9994 → gần như hoàn hảo.
> - **Ý nghĩa thực tiễn:** Có thể chặn bot TRƯỚC KHI chúng hoàn thành hành động mục tiêu (click mua hàng, submit form).

---

### 5.6 E6: Inference Latency Benchmark

**Mục tiêu:** Model có đủ nhanh cho real-time không?

| Model | Mean (ms) | P50 (ms) | P95 (ms) | P99 (ms) |
|-------|-----------|----------|----------|----------|
| **XGBoost** | **0.830** | — | **1.326** | **1.871** |
| BiLSTM | 2.001 | — | 3.569 | 5.495 |

> **Kết luận:**
> - XGBoost: **<1ms trung bình** → Hoàn toàn real-time. Có thể xử lý >1000 requests/second trên single CPU.
> - BiLSTM: ~2ms → Vẫn real-time nhưng chậm hơn 2.4x.
> - **So với yêu cầu production (<50ms response time):** Cả 2 model đều vượt xa yêu cầu.

---

### 5.7 E7: FPR/ROC Threshold Analysis

**Mục tiêu:** Threshold nào tối ưu cho trade-off FPR vs Detection Rate?

| Threshold | FPR | TPR (Recall) | Precision | F1 |
|-----------|-----|-------------|-----------|-----|
| 0.1 | 0.0222 | 1.0000 | 0.9783 | 0.9890 |
| 0.2 | 0.0222 | 1.0000 | 0.9783 | 0.9890 |
| **0.3** | **0.0000** | **1.0000** | **1.0000** | **1.0000** |
| 0.4–0.6 | 0.0000 | 1.0000 | 1.0000 | 1.0000 |
| 0.7–0.9 | 0.0000 | 0.9889 | 1.0000 | 0.9944 |

> **Kết luận:**
> - **Threshold tối ưu: 0.3** — FPR=0 và TPR=1.0 (hoàn hảo).
> - Ở threshold thấp (0.1-0.2): FPR=2.2% (chặn nhầm ~2% người thật).
> - Ở threshold cao (≥0.7): Bỏ sót 1.1% bot.
> - **Khuyến nghị production:** Dùng threshold=0.3 để cân bằng, hoặc 0.5 cho bảo thủ.

---

### 5.8 E8: Short Session Analysis

| Nhóm session | Số lượng test | AUC | F1 | FPR |
|-------------|--------------|-----|-----|-----|
| Very short (<10 points) | 22 | — | 1.0000 | 0.0000 |
| Short (10-25 points) | 6 | — | 1.0000 | 0.0000 |
| Medium (25-50 points) | 72 | 1.0000 | 1.0000 | 0.0000 |
| Long (50+ points) | 80 | 1.0000 | 1.0000 | 0.0000 |

> **Kết luận:** Model hoạt động tốt trên mọi độ dài session. AUC=0 ở nhóm rất ngắn là do tất cả samples trong nhóm đó cùng 1 class (không phải lỗi model).

---

### 5.9 E9: Power User Stress Test

**Mục tiêu:** Model có nhầm "người giỏi" (thao tác nhanh/thẳng) thành bot không?

| Nhóm | Số lượng | False Positive | FPR | Mean P(bot) | Max P(bot) |
|------|---------|---------------|-----|-------------|------------|
| **Power users** (straightness>0.85 / speed>P90) | 52 | **0** | **0.0%** | 0.0256 | 0.2849 |
| Normal humans | 38 | 0 | 0.0% | 0.0169 | — |

> **Kết luận:**
> - **0% False Positive trên power users** → Model KHÔNG nhầm người thao tác nhanh/chính xác thành bot.
> - Mean P(bot) chỉ 0.026 cho power users → Model rất confident rằng đây là người thật.
> - Max P(bot)=0.2849 < threshold 0.3 → Ngay cả trường hợp xấu nhất cũng không bị chặn.

---

## 6. TỔNG HỢP ĐÃ LÀM / CHƯA LÀM

### ✅ Đã hoàn thành

| Hạng mục | Chi tiết | Kết quả chính |
|----------|----------|---------------|
| Kiến trúc Ensemble 3 thành phần | BiLSTM + XGBoost + BotD heuristic, confidence-based fusion | XGBoost AUC=0.9995 (val) |
| Real data integration | Parse 200 sessions từ M4D dataset | 600 total samples |
| Feature engineering v2 | +6 features mới (curvature, time_regularity) | `time_regularity` Top 5 importance |
| Proper evaluation split | Train/Val/Test 70/15/15, stratified | Không còn overfit trên train |
| Training pipeline | Early stopping, LR scheduling, gradient clipping | Convergent training |
| E1: Baseline comparison | Rule-based vs XGBoost | **ML +33.1% AUC** so với rule-based |
| E2: Concept drift | Train moderate → test advanced | **Critical finding: Recall=0 khi gặp bot mới** |
| E3: Feature ablation | 6 groups tested | **Mouse dynamics alone = AUC 1.0** |
| E4: Class imbalance | 1:1 → 1:10 ratios | **Robust: AUC≥0.97 ở mọi ratio** |
| E5: Early detection | 5→100 mouse points | **5 points đủ: AUC=0.99** |
| E6: Inference latency | XGBoost + LSTM benchmark | **<1ms (XGBoost), <2ms (LSTM)** |
| E7: ROC/FPR analysis | 9 threshold levels | **Optimal threshold=0.3: FPR=0, TPR=1** |
| E8: Short sessions | 4 length groups | Hoạt động tốt mọi độ dài |
| E9: Power user test | 52 power users tested | **0% False Positive** |
| Scope analysis | 48 edge cases phân loại | 13 LÀM, 19 MỘT PHẦN, 16 KHÔNG |

### 🔄 Đang thực hiện / Có thể bổ sung

| Hạng mục | Chi tiết |
|----------|----------|
| Deploy API + Collector lên cloud | Cần chọn cloud provider (Railway/Render) |
| Thu thập dữ liệu thật từ web deploy | SilkMoon integration chưa bắt đầu |
| Adversarial robustness test | Thêm noise vào bot features |

### ❌ Chưa làm / Ngoài phạm vi

| Hạng mục | Lý do |
|----------|-------|
| Mobile detection | M4D không có dữ liệu mobile touch/gyroscope |
| GAN-based bot detection | Cần GAN mouse generator riêng — ngoài scope |
| Session-replay detection | Cần cross-session matching ở mức production |
| Online learning / MLOps | Đồ án dùng offline training |
| GDPR compliance | Vấn đề pháp lý, không phải ML |

---

## 7. HẠN CHẾ & HƯỚNG PHÁT TRIỂN

### 7.1 Hạn chế chính

1. **Thiếu timestamp gốc** trong M4D dataset → kinematic features (speed, acceleration) phụ thuộc vào ước lượng dựa trên khoảng cách giữa các điểm. Điều này giải thích phần nào hiệu năng BiLSTM thấp hơn expected (AUC=0.82 trên validation).

2. **Concept drift nghiêm trọng** (E2) — Model train trên 1 loại bot HOÀN TOÀN THẤT BẠI khi gặp loại bot mới. Trong thực tế, bot liên tục tiến hóa → cần cơ chế retrain liên tục.

3. **Dataset bias** — M4D thu trên trang Wikipedia demo, khác biệt đáng kể với e-commerce (SilkMoon). Mouse behavior trên trang mua sắm (scroll sản phẩm, hover ảnh, click add to cart) khác hoàn toàn với trang đọc bài viết.

4. **Chỉ desktop** — Không có mobile/tablet data. Trong thực tế, 60-70% traffic là mobile → cần pipeline riêng cho touch events.

5. **Synthetic data chiếm tỷ lệ lớn** (400/600 = 67%) — Kết quả trên synthetic có thể optimistic hơn so với real-world traffic.

### 7.2 Hướng phát triển

1. **Thu thập dữ liệu thật** — Deploy collector SDK lên web thực (SilkMoon), thu thập traffic production có timestamp chính xác.
2. **Adversarial training** — Train model với GAN-generated bot trajectories để tăng robustness.
3. **Mobile support** — Mở rộng feature pipeline cho touch events (tap, swipe, pinch), accelerometer, và gyroscope.
4. **Online learning** — Implement incremental learning pipeline để model tự cập nhật khi phát hiện pattern bot mới.
5. **Cross-site generalization** — Test model trên nhiều loại website khác nhau (login form, search, checkout) để đánh giá khả năng generalize.

---

## PHỤ LỤC

### A. Cấu trúc thư mục dự án

```
bot-detection-core/
├── core_ml/
│   ├── dataset/
│   │   └── loader.py          # Data loading + synthetic generation
│   ├── features/
│   │   ├── env_features.py    # Environment/fingerprint features (26)
│   │   └── mouse_features.py  # Mouse dynamics features (17)
│   ├── models/
│   │   ├── behavioral_lstm.py # BiLSTM + TemporalAttention
│   │   ├── tabular_classifier.py # XGBoost + StandardScaler
│   │   └── ensemble.py        # Confidence-based fusion
│   ├── experiments/
│   │   └── run_all.py         # 9 experiments suite
│   ├── train.py               # Training pipeline
│   └── weights/               # Saved model weights
├── collector/                  # JavaScript SDK for data collection
├── api_service/                # FastAPI inference server
└── EXPERIMENT_REPORT.md        # This file
```

### B. Cách chạy lại thí nghiệm

```bash
# Training pipeline
python -u -m core_ml.train

# All experiments
python -u -m core_ml.experiments.run_all

# Results saved to: core_ml/experiment_results.json
```


### Danh sách thí nghiệm theo thứ tự ưu tiên:

| # | Thí nghiệm | Mục đích | Trạng thái |
|---|-------------|----------|------------|
| E1 | **Baseline Comparison** — Rule-based vs ML | Chứng minh ML tốt hơn heuristic đơn giản | ✅ Đã hoàn thành (ML vượt 49.1% AUC) |
| E2 | **Concept Drift** — Train moderate → test advanced | Đánh giá khả năng generalize khi bot tiến hóa | ✅ Đã hoàn thành (AUC=0.9992) |
| E3 | **Feature Ablation** — Thiếu fingerprint/mouse thì sao? | Xác định feature group quan trọng nhất | ✅ Đã hoàn thành (Mouse AUC=1.0) |
| E4 | **Class Imbalance** — Ratio 1:1, 1:3, 1:5, 1:10 | Đánh giá robustness khi dữ liệu mất cân bằng | ✅ Đã hoàn thành (FPR=0.0 across all) |
| E5 | **Early Detection** — Cần bao nhiêu mouse points? | Detection latency analysis | ✅ Đã hoàn thành (15 pts đủ AUC=1.0) |
| E6 | **Inference Latency** — Đo ms per prediction | Tính thực tiễn triển khai | ✅ Đã hoàn thành (XGBoost 0.51ms) |
| E7 | **FPR/ROC Analysis** — Trade-off threshold | Phân tích chi phí chặn nhầm vs bỏ sót | ✅ Đã hoàn thành (Threshold 0.5 FPR=0) |
| E8 | **Short Session** — Session < 10 mouse points | Edge case session quá ngắn | ✅ Đã hoàn thành (F1=1.0) |
| E9 | **Power User** — Human straightness > 0.95 | Stress test: model có nhầm "người giỏi" thành bot? | ✅ Đã hoàn thành (FP=0/38, 0.0%) |

---

## 5. KẾT QUẢ THÍ NGHIỆM CHI TIẾT

### 5.1 E1: Baseline Comparison (Rule-based vs ML)
So sánh mô hình học máy (XGBoost 50 chiều) với các luật Heuristic truyền thống:

| Phương pháp | ROC-AUC | F1-Score | Precision | Recall | Accuracy | FPR |
|---|---|---|---|---|---|---|
| **Heuristic Score Only** (BotD đơn thuần) | 0.7167 | 0.0000 | 0.0000 | 0.0000 | 0.4643 | 0.0000 |
| **Multi-rule Threshold** (Heuristics kết hợp) | 0.6709 | 0.6765 | 1.0000 | 0.5111 | 0.7381 | 0.0000 |
| **Tabular XGBoost (50 features)** | **1.0000** | **1.0000** | **1.0000** | **1.0000** | **1.0000** | **0.0000** |

> **Kết luận:** Mô hình ML vượt trội luật Heuristic **+49.1% về AUC** và giải quyết triệt để vấn đề bot vượt rào khi che giấu webdriver.

### 5.2 E2: Concept Drift (Khả năng phát hiện Bot tiến hóa)
Đánh giá khi huấn luyện trên Bot thông thường (Moderate - di chuyển thẳng/grid) nhưng kiểm thử trên Bot ngụy trang nâng cao (Advanced - đường cong Bézier, motor jitter):

| Kịch bản | ROC-AUC | F1-Score | Recall | Ghi chú |
|---|---|---|---|---|
| **Train Moderate → Test Advanced** | **0.9992** | **0.9568** | **0.9172** | Bot nâng cao vẫn bị chặn 91.7% |
| **Train Advanced → Test Moderate** | **1.0000** | **1.0000** | **1.0000** | Nhận diện tuyệt đối bot đơn giản |
| **Train Both → Test Both** | **1.0000** | **1.0000** | **1.0000** | Đầy đủ dữ liệu đa dạng |

> **Kết luận:** Mô hình có tính khái quát hóa cực cao, độ sụt giảm hiệu năng khi gặp loại bot mới chưa từng thấy trong tập train chỉ là **-0.0008 AUC**.

### 5.3 E3: Feature Ablation Study (Đóng góp từng nhóm đặc trưng)

| Nhóm đặc trưng | Chiều | ROC-AUC | F1-Score | Precision | Recall |
|---|---|---|---|---|---|
| **Tất cả đặc trưng kết hợp** | 50 | **1.0000** | **1.0000** | 1.0000 | 1.0000 |
| **Chỉ dùng Động học chuột (Mouse Dynamics)** | 20 | **1.0000** | **1.0000** | 1.0000 | 1.0000 |
| **Chỉ dùng Môi trường / Fingerprint** | 30 | 0.8966 | 0.8451 | 0.7317 | 1.0000 |
| **Chỉ dùng 6 đặc trưng v2 mới** | 6 | 0.9987 | 0.9780 | 0.9674 | 0.9889 |
| **Bỏ qua toàn bộ luật BotD Heuristics** | 47 | **1.0000** | **1.0000** | 1.0000 | 1.0000 |

> **Kết luận:** Động học chuột (Mouse Dynamics) là thành phần phòng thủ quan trọng và đáng tin cậy nhất khi fingerprint bị bot giả mạo.

### 5.4 E4: Class Imbalance Robustness (Mất cân bằng dữ liệu)

| Tỷ lệ Người:Bot (Train) | ROC-AUC | F1-Score | Recall | FPR |
|---|---|---|---|---|
| **1 : 1** (150H : 150B) | 0.9975 | 0.9873 | 0.9750 | 0.0000 |
| **1 : 3** (150H : 50B) | 0.9962 | 0.9873 | 0.9750 | 0.0000 |
| **1 : 5** (150H : 30B) | 0.9944 | 0.9744 | 0.9500 | 0.0000 |
| **1 : 10** (150H : 15B) | 0.9950 | 0.9744 | 0.9500 | 0.0000 |

> **Kết luận:** Nhờ tham số `scale_pos_weight` tối ưu, mô hình duy trì AUC > 0.995 và tỷ lệ chặn nhầm người dùng (FPR) luôn bằng **0.0%** ngay cả khi bot chỉ chiếm 10% tập huấn luyện.

### 5.5 E5: Early Detection (Phát hiện sớm theo số điểm chuột)

| Số điểm chuột tối thiểu | ROC-AUC | F1-Score | Recall | Thời gian tương tác |
|---|---|---|---|---|
| **5 điểm** | 0.9991 | 0.9865 | 0.9865 | ~80 - 150 ms |
| **10 điểm** | 0.9995 | 0.9799 | 0.9865 | ~150 - 250 ms |
| **15 điểm** | **1.0000** | **1.0000** | **1.0000** | ~250 - 400 ms |
| **30 điểm** | **1.0000** | **1.0000** | **1.0000** | ~500 - 800 ms |
| **100 điểm** | 0.9969 | 0.9733 | 0.9865 | > 1.5 s |

> **Kết luận:** Hệ thống đạt độ chính xác hoàn hảo **100% chỉ sau 15 điểm chuột di chuyển đầu tiên** (chưa tới 0.4 giây tương tác).

### 5.6 E6: Inference Latency Benchmark (Độ trễ suy luận Production)

| Model | Thời gian trung bình | Phân vị p95 | Phân vị p99 |
|---|---|---|---|
| **XGBoost (50 features)** | **0.513 ms** | 0.609 ms | 0.731 ms |
| **BiLSTM (24 steps)** | **1.291 ms** | 1.810 ms | 2.212 ms |
| **End-to-end Ensemble (HTTP API)** | **~1.77 ms** | 2.84 ms | 3.50 ms |

> **Kết luận:** Tốc độ suy luận sub-millisecond, hoàn toàn đáp ứng yêu cầu phân loại bot thời gian thực tại API Gateway / Reverse Proxy.

### 5.7 E7: FPR/ROC Threshold Analysis

| Ngưỡng (Threshold) | FPR (Chặn nhầm) | TPR (Bắt đúng bot) | Precision | F1-Score |
|---|---|---|---|---|
| **0.1** | 0.0897 | 1.0000 | 0.9278 | 0.9626 |
| **0.2** | 0.0385 | 1.0000 | 0.9677 | 0.9836 |
| **0.3 - 0.7** | **0.0000** | **1.0000** | **1.0000** | **1.0000** |
| **0.8** | 0.0000 | 0.9889 | 1.0000 | 0.9944 |
| **0.9** | 0.0000 | 0.9667 | 1.0000 | 0.9831 |

> **Khuyến nghị:** Chọn ngưỡng **0.50** làm điểm cân bằng tối ưu với $FPR=0.0\%$ và $F1=1.0000$.

### 5.8 E8: Phân tích Session ngắn (Short Session Analysis)
- **Session rất ngắn (< 10 điểm)**: F1 = 1.0000, FPR = 0.0000
- **Session trung bình (25 - 50 điểm)**: AUC = 1.0000, F1 = 1.0000, FPR = 0.0000
- **Session dài (> 50 điểm)**: AUC = 1.0000, F1 = 1.0000, FPR = 0.0000

### 5.9 E9: Power User Stress Test (Người dùng cao cấp / Thao tác cực nhanh)
- Số lượng Power Users trong tập test: **38 người** (người dùng di chuyển thẳng và nhanh, straightness > 0.95).
- Tỷ lệ nhận diện sai thành Bot: **0 / 38 (0.0%)**!
- Xác suất trung bình bị gán Bot: **0.0235** (cực kỳ an toàn, cách xa ngưỡng 0.50).
- Xác suất cao nhất của một Power User: **0.1203**.
- **Kết luận:** Mô hình phân biệt rõ ràng giữa "người thao tác nhanh, chuẩn xác" và "bot di chuyển máy móc" nhờ các đặc trưng vi mô như rung lắc tự nhiên (jitter), angular entropy và biến thiên gia tốc (jerk).

---

## 6. TỔNG HỢP ĐÃ LÀM / CHƯA LÀM
 
### ✅ Đã hoàn thành pipeline Core ML phục vụ nghiên cứu

| Hạng mục | Chi tiết |
|----------|----------|
| Kiến trúc Multi-Modal Ensemble | BiLSTM + XGBoost + BotD heuristic, confidence-based adaptive fusion |
| Real data integration | Nạp đầy đủ Phase 1 và Phase 2 M4D dataset (258 sessions thật) |
| Chuẩn hóa không gian tọa độ | Normalize tọa độ chuột về [0, 1] trên cả dữ liệu thật và browser SDK |
| Single Source of Truth đặc trưng | `STATISTICAL_FEATURE_NAMES` (20 features) và `ENV_FEATURE_NAMES` (30 features) |
| Khử sập 500 & None-safe | Toàn bộ helper `safe_float`, `safe_bool` và sanitization `np.nan_to_num` |
| Bộ 9 Thí nghiệm E1 - E9 | Đã chạy và ghi nhận đầy đủ bảng số liệu thực tế |
| Serving API & Collector SDK | FastAPI server (4 endpoints) + Client-side JS Collector |

### ❌ Chưa làm / Hạn chế ngoài phạm vi (Future Work)

| Hạng mục | Lý do |
|----------|-------|
| Mobile touch / gyroscope | Dataset M4D chỉ thu thập chuột trên desktop |
| GAN-based bot generator | Cần huấn luyện bộ sinh GAN riêng — ngoài scope luận văn |
| Cloud deployment | Đang chạy tại local server / private datacenter |

---

## 7. HẠN CHẾ & HƯỚNG PHÁT TRIỂN

### Hạn chế chính

1. **Thiếu timestamp gốc** trong M4D → kinematic features (speed, accel) phụ thuộc vào ước lượng.
2. **Dataset bias** — M4D thu trên trang Wikipedia demo, khác với e-commerce/login form thực tế.
3. **Chỉ desktop** — không có mobile/tablet data.
4. **Bot types hạn chế** — M4D chỉ có Selenium-based bot, không có GAN/replay/hybrid bot.

### Hướng phát triển

1. Thu thập dữ liệu thật từ web deploy (SilkMoon) với collector SDK đã xây.
2. Thêm GAN-based adversarial training.
3. Mở rộng sang mobile (touch events, accelerometer).
4. Online learning pipeline cho concept drift liên tục.
