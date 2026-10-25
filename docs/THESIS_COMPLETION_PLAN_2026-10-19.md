# Kế hoạch hoàn thiện khóa luận DATACAT

Ngày lập: 2026-10-19. Trạng thái: kế hoạch thực hiện, chưa phải kết quả đã đạt.

Mục tiêu là hoàn thiện nhiều nhất trong phạm vi đã thống nhất: phát hiện một số
nhóm bot trình duyệt trên desktop bằng dấu hiệu automation và hành vi chuột.
Chưa có hạn nộp hoặc rubric chính thức. Các ước lượng dưới đây là ngày công,
không phải ngày bàn giao được giảng viên xác nhận. Không thể bảo đảm điểm 10;
chất lượng cần thể hiện qua bài toán rõ, thực nghiệm đúng và sản phẩm tái hiện được.

Bản [đề cương tóm tắt gửi thầy](THESIS_PROPOSAL_2026-10-19.md) được chuẩn bị
riêng để trao đổi phạm vi trước khi thực hiện.

## 1. Đề tài và câu hỏi nghiên cứu

Tên đề xuất: **Phát hiện bot trên website dựa trên dấu hiệu trình duyệt và
hành vi chuột**.

Câu hỏi chính: kết hợp heuristic trình duyệt, XGBoost và BiLSTM có cải thiện
khả năng nhận diện các nhóm bot mục tiêu so với từng thành phần riêng lẻ,
trong khi kiểm soát nhận nhầm người thật và tỷ lệ chưa đủ cơ sở kết luận không?

Các câu hỏi phụ:

1. Dấu hiệu automation rõ ràng phát hiện được nhóm nào khi chưa có chuột?
2. Hai model chuột đóng góp gì khi không cung cấp tín hiệu automation?
3. Bổ sung dữ liệu cùng website có hữu ích hơn thêm đặc trưng đơn thuần không?
4. Model đổi kết luận như thế nào qua các lần gửi và các mức dữ liệu quan sát?
5. Khi chuyển sang cấu hình hoặc họ bot khác, chất lượng giảm ở đâu?

Đóng góp dự kiến là pipeline thu dữ liệu có nguồn nhãn, benchmark có kiểm soát,
so sánh các thành phần và prototype quan sát trực tiếp. Các module tự triển
khai có thể là đóng góp kỹ thuật; chỉ khẳng định một cải tiến thuật toán hữu
ích khi thực nghiệm chứng minh. Ghi rõ phần tham khảo và phần tự viết.

## 2. Phạm vi cam kết

| Trục | Phạm vi chính |
| --- | --- |
| Website | Một website có sẵn được cho phép nhúng collector; ghi phiên bản/nội dung thử nghiệm |
| Trình duyệt | Chrome/Chromium desktop; ghi OS, phiên bản browser và cấu hình |
| Đầu vào | Bot chạy JavaScript, gửi telemetry qua collector; mouse và touchpad desktop |
| Automation | Một runner Playwright ổn định trước; Selenium là kiểm thử bổ sung nếu đủ thời gian |
| Hành vi | Ba họ kịch bản được đăng ký trước trong protocol v1 |
| Kiến trúc | Heuristic trình duyệt + XGBoost + BiLSTM hiện có |
| Vận hành | Quan sát, ghi bằng chứng, giải thích và đánh giá; chưa tự động chặn |
| Kết luận | HUMAN / SUSPECT / BOT; SUSPECT có mã nguyên nhân |

Ngoài cam kết chính: HTTP crawler không chạy JS, mobile/touch, anti-detect sâu,
quỹ đạo phát lại từ người thật, bot điều khiển bằng người, botnet/GNN và xác
định động cơ gian lận quảng cáo. Lưu các ca đã vượt qua hệ thống trong bộ thử
thách và công bố kết quả; không xóa chúng để làm đẹp chỉ số.

Ba họ là nhóm hành vi trong benchmark, không phải ba nhóm độc lập hoàn toàn.
Macro có thể dùng chung bộ sinh chuột với họ tuyến tính hoặc theo mẫu. Cần
ghi quan hệ dùng chung, tránh diễn giải thành khả năng nhận ra ba thuật toán
độc lập hoặc họ chưa gặp. Chi tiết trong
[THESIS_BENCHMARK_PROTOCOL_V1.md](THESIS_BENCHMARK_PROTOCOL_V1.md).

## 3. Hiện trạng được xác minh

Đã đọc source và báo cáo hiện có trong repo `bot-detection-core`. GitNexus
được ràng buộc với repo `bot-detection`, HEAD
`c2c9790c3e6ea0e5d5248414e67397102e014806`, index nguồn cập nhật lúc
2026-10-19T04:44:37.589Z. Worktree có nhiều sửa đổi chưa commit: HEAD không
đại diện đầy đủ cho source hiện có; cần đóng băng một snapshot trước thực nghiệm.

| Đã có | Giá trị sử dụng | Việc còn thiếu |
| --- | --- | --- |
| Collector và API inference | Nhúng website, gửi chuột/profile, nhận kết luận | Kiểm chứng nhúng trên website thầy chọn và giao thức/origin thực tế |
| Capture opt-in + spool SQLite | Lưu từng snapshot nghiên cứu, metadata model và phục hồi khi DB lỗi | Export có manifest, nối nhãn, thử MongoDB thật/restart/TTL |
| BiLSTM + XGBoost + heuristic | Baseline có sẵn để so sánh | Đối chứng người thật cùng website, benchmark mới độc lập |
| Phân tích từng thao tác offline | Kiểm toán vận tốc, gia tốc, jerk, press/click/wheel và thiếu dữ liệu | Chưa có bằng chứng đặc trưng mới làm classifier tốt hơn |
| Runner và capture bot | Tái hiện lỗi, tạo bộ regression | Chốt seed, cấu hình, nguồn nhãn và xác nhận request được server nhận |
| Bộ test | Lượt kiểm tra trước: 482 test Python qua, Ruff qua | Không đồng nghĩa đã xác minh độ chính xác hoặc trạng thái server |

Kết quả cần giữ nguyên trong báo cáo:

- Thử nghiệm XGBoost 25 đặc trưng nhận HUMAN ở kết luận cuối của 18/18 lượt
  bot giữ lại theo họ. Đây là thất bại của một cấu hình XGBoost riêng, không
  phải tỷ lệ của ensemble hoặc production.
- Candidate profile từng đổi BOT từ 6 lên 15 trên 42 lượt bot, nhưng dùng
  capture phát triển và chưa có profile người thật đối chứng. Chưa thể lấy
  đó làm bằng chứng cải thiện độc lập.
- Bộ phân tích thao tác mới chạy được trên 18 lượt bot/90 cửa sổ. Đây là
  kiểm tra khả năng đo đạc; các cửa sổ chồng lặp không phải 90 mẫu độc lập.
- `collect-human-control.js` hiện mở browser bằng Playwright và chỉ lưu
  mouse. Dùng được cho đối chứng chuột, không đại diện profile Chrome người
  thật mở bình thường. Nó còn yêu cầu đủ 25 move nên không bao phủ người ít
  dùng chuột; cần luồng thu riêng cho nhóm này.

Nguồn: [mouse ablation](MOUSE_ABLATION_REVIEW_2026-10-13.md),
[profile candidate](PROFILE_POLICY_REVIEW_2026-10-13.md),
[capture](RESEARCH_CAPTURE.md),
[phân tích thao tác](MOUSE_ACTION_ANALYSIS_2026-10-19.md).

## 4. Hai mốc phải bàn giao sớm

**Mốc A: thầy chạy được traffic.** Đầu ra là snippet nhúng cho website thực,
URL kiểm tra, hướng dẫn bật/tắt, một phiên bản collector đã ghi nhận, và bằng
chứng snapshot đến nơi. Thu traffic là luồng độc lập với việc cải thiện model;
raw vẫn phải lưu được khi inference không có kết quả.

**Mốc B: bộ thực nghiệm khóa luận.** Có nhãn độc lập cho người thật/bot có
kiểm soát, split đã đóng băng, model/feature có phiên bản, script tái hiện và
báo cáo so sánh. Traffic tự nhiên chưa rõ nguồn vẫn hữu ích cho vận hành và
nghiên cứu SUSPECT; không tự biến thành ground truth.

## 5. Lộ trình theo ưu tiên

| Giai đoạn | Ngày công dự kiến | Đầu ra phải có | Điều kiện chuyển tiếp |
| --- | ---: | --- | --- |
| P0. Chốt đề cương | 1 | Đề tài, phạm vi, protocol, checklist trao đổi với thầy | Phạm vi và câu hỏi nghiên cứu được ghi rõ |
| P1. Bàn giao script/pilot | 2-3 | Snippet, capture exporter/manifest, xác nhận browser → API → storage | Thu/nạp lại được dữ liệu có phiên bản |
| P2. Thu dữ liệu có nhãn | 3-5, phụ thuộc lịch người tham gia | Người thật native browser + ba họ bot + log thất bại | Nhãn và split kiểm toán được |
| P3. Baseline và tối ưu | 3-4 | So sánh thành phần, giới hạn thử nghiệm, candidate được chọn trên validation | Có báo cáo đầy đủ, kể cả không cải thiện |
| P4. Kiểm thử cuối và demo | 2-3 | Báo cáo test mới, regression, video/demo offline, model card | Không còn lỗi làm sai dữ liệu/kết luận |
| P5. Báo cáo và bảo vệ | 3-4, viết song song từ P0 | Bản luận văn, slide, nguồn tham khảo, gói tái hiện | Kiểm tra chéo số liệu và diễn tập |

Ước lượng lõi: 14-20 ngày công. Lịch thực tế phụ thuộc website và người tham
gia; không dùng chờ dữ liệu để trì hoãn script bàn giao hoặc phần viết.
Nâng cao chỉ triển khai sau khi các đầu ra lõi hoạt động.

## 6. P0: Đóng băng phạm vi và baseline

1. Gửi thầy bản đề cương một trang: đề tài, câu hỏi, ba họ bot, dữ liệu,
   baseline, chỉ số, giới hạn và sản phẩm bàn giao. Xin rubric khi trường có.
2. Xác định website, quyền nhúng, người hỗ trợ, tác vụ người dùng và môi
   trường thu. Đây là thông tin cần để triển khai, hiện chưa có URL cuối.
3. Tạo manifest baseline: commit/source snapshot, lock/dependency, checksum
   collector, weights/bundle, policy, threshold và cấu hình liên quan.
4. Giữ raw cũ, kết quả thất bại và mã runner làm development/regression.
   Tập nào đã dùng để chọn feature/rule/ngưỡng không gọi là test độc lập.
5. Tách công việc trên branch chọn lọc. Repo hiện auto deploy khi push main;
   chỉ hợp nhất/push phần đã kiểm chứng, không gom mù toàn bộ dirty worktree.

Điều kiện xong: một người khác đọc manifest có thể biết chính xác baseline
đang đo là gì và phạm vi kết luận ở đâu.

## 7. P1: Script nhúng và thu dữ liệu tối thiểu đáng tin cậy

Ưu tiên sửa đường đi của dữ liệu trước khi thêm feature hoặc model.

1. Kiểm chứng snippet trên Chrome mở bình thường: script tải được, collector
   chỉ khởi tạo một lần, đúng URL/origin/giao thức và đúng website nghiên cứu.
   Kiểm tra cả điều hướng, reload, tab ẩn, đóng trang và ít di chuột.
2. Kiểm chứng với MongoDB thật: raw snapshot còn sau restart; outage đi vào
   spool đã commit; recovery không tự sinh nhãn; TTL được thử trên cấu hình
   thử nghiệm, không chờ tới khi mất dữ liệu nghiên cứu.
3. Xây exporter đọc snapshot nghiên cứu và tạo JSONL/manifest. Dataset có
   bản lưu ngoài runtime trước hạn TTL; xác minh hash khi nạp lại.
4. Xây manifest nhãn riêng theo phiên/lượt chạy, giữ nguồn nhãn và trạng
   thái xác nhận. Không gửi nhãn, tên bot hoặc participant ID vào feature.
5. Với runner bot, lưu request thực sự collector gửi và đối chiếu capture_id
   hoặc receipt phía server. Phân biệt dự kiến gửi, đã gửi và lưu thành công.
   Kiểm tra chữ trên HTML hoặc gọi một probe riêng không thay thế bước này.
6. Luồng người thật dùng Chrome native thông thường, collector thật và
   hướng dẫn thao tác; không dùng browser automation để đánh giá profile.
   Không bắt người tham gia tạo đủ move để được lưu dữ liệu.
7. Giữ cửa sổ inference hữu hạn hiện có. Ghi rõ sampling, timestamp, chuẩn
   tọa độ, touch và phần thiếu. Nếu cần thêm metadata khung tọa độ/phiên bản,
   version schema và test tương thích; chưa cần ghi liên tục toàn bộ phiên.
8. Bàn giao thầy snippet, cấu hình, cách nhận biết dữ liệu đến, cách ngừng
   thu và một runbook ngắn. Sửa URL/query nhạy cảm trước khi xuất mẫu chia sẻ.

Đầu ra: script nhúng + runbook + capture export + label manifest + 10 phiên
pilot nhỏ kiểm tra đường thu. Pilot dùng để sửa quy trình, không đưa vào test
cuối. Không đánh dấu P1 xong chỉ từ unit test hoặc HTTP 200.

## 8. P2: Dataset mới trong khả năng hiện tại

Mốc kế hoạch: 15 người x 6 phiên = 90 phiên người thật; ba họ bot x 60 lượt
= 180 lượt bot. Tổng 270 phiên/lượt, không phải 270 người độc lập. Đây là
quy mô pilot thực hành, chưa phải cỡ mẫu bảo đảm độ chính xác production.

| Nguồn | Train | Validation | Test cuối | Tổng |
| --- | ---: | ---: | ---: | ---: |
| Người thật, chia theo người | 9 người / 54 phiên | 3 người / 18 phiên | 3 người / 18 phiên | 15 người / 90 phiên |
| Bot mỗi họ, chia theo block cấu hình/lượt chạy | 36 | 12 | 12 | 60 |
| Ba họ bot | 108 | 36 | 36 | 180 |
| Tổng phiên/lượt | 162 | 54 | 54 | 270 |

Phân bổ là mục tiêu trước khi thu, không phải dữ liệu hiện đã có. Mỗi split
phải có cấu hình/tác vụ được xác định trước; chỉ đổi seed không chứng minh
khái quát hóa sang bộ sinh mới. Sáu tác vụ người thật gồm đọc/cuộn tự nhiên,
điều hướng/click, trỏ mục tiêu, kéo chọn, hover/chỉnh hướng và thao tác ít chuột.

Nếu chỉ tiếp cận 10 người, điều chỉnh cỡ pilot trước khi mở test và ghi hạn
chế rõ. Nếu chưa có người thật native browser, tiếp tục baseline dataset và
chuẩn bị thu; chưa kết luận FPR trên website hoặc chấp thuận policy profile.

Data audit bắt buộc: nguồn timestamp thật/ước lượng, phiên/người/group ID,
trùng dữ liệu, toàn vẹn snapshot, tỷ lệ thiếu và tác vụ thực sự hoàn thành.
Không mặc định mọi timestamp Phase 2 đều là thật vì parser có fallback.
Dataset cũ thiếu participant ID chỉ cho phép phát biểu ở mức chia theo phiên.

Traffic do thầy chạy được thu song song. Nhãn do thầy/runner xác nhận được
đưa vào tập tương ứng theo protocol; traffic chưa rõ giữ UNKNOWN. Trial
thương mại là nguồn đối chiếu tùy chọn, ghi provider/version/time và nối đúng
request. Bất đồng giữ để xem xét, không tự đổi thành HUMAN hoặc BOT chắc chắn.

## 9. P3: Thực nghiệm gọn, có thể giải thích

Các nhánh so sánh bắt buộc:

| ID | Nhánh | Mục đích |
| --- | --- | --- |
| E0 | Heuristic hiện có | Đo mức dựa vào dấu hiệu automation |
| E1 | XGBoost chuột | Baseline feature thống kê |
| E2 | BiLSTM chuột | Baseline chuỗi chuyển động |
| E3 | Fusion hiện có | Baseline hệ thống đầy đủ |
| E4 | Fusion với candidate được chọn trên validation | Đo tác dụng tối ưu cụ thể nếu có |

E0 là heuristic tự triển khai trong dự án, không tự gọi là kết quả của package
BotD chính thức. E1/E2 chỉ được chấm điểm khi có đầu vào thuộc miền đã định;
những phiên không đủ dữ liệu vẫn có mặt trong bảng coverage toàn bộ.

Hai track đánh giá dùng cùng phiên: full-system với dữ liệu browser thực;
mouse-only bỏ profile/heuristic khỏi nhánh phân loại để đo riêng đóng góp
chuột. Phải thực thi việc bỏ tín hiệu ở đầu vào/nhánh tính điểm, không sửa
nhãn đầu ra trong báo cáo. Định nghĩa trước gate và threshold của từng nhánh.

Thứ tự tối ưu:

1. Sửa sai khác dữ liệu train/inference, nguồn timestamp và đơn vị nếu audit
   phát hiện. Thay feature contract thì tăng phiên bản, không nạp weights cũ
   rồi diễn giải như thể model đã học feature mới.
2. Train lại XGBoost với dữ liệu train mới, giữ feature hiện tại làm mốc.
   Kiểm tra cân bằng đóng góp giữa phiên/người, không cân bằng bằng cách
   nhân cửa sổ của một vài người lên hàng nghìn mẫu độc lập.
3. Thử một nhóm feature nhỏ có giả thuyết từ dữ liệu train: nhịp thời gian,
   mức lặp hoặc đặc trưng đoạn cục bộ. Báo missingness; không mặc định thêm
   cả 5 feature thử trước sẽ tốt hơn.
4. Train/fine-tune BiLSTM với cùng split, sample trên toàn quỹ đạo và trọng
   số theo phiên. Augmentation phải giữ nhãn hợp lý và chỉ dùng trong train.
5. Chọn fusion/ngưỡng bằng validation, giới hạn search. Khi score không được
   hiệu chỉnh xác suất thì ghi là điểm rủi ro, không gọi là độ chắc chắn 95%.
6. Chạy tối đa khoảng 12 cấu hình XGBoost rẻ; tối đa 3 cấu hình BiLSTM ban
   đầu. Chỉ lặp 3 seed cho cấu hình cuối đã chọn; ghi cả thời gian và tài nguyên.

XGBoost chạy CPU trước; Colab dùng khi BiLSTM cần GPU. Thiết lập checkpoint,
seed, dữ liệu/manifest đầu vào, thời gian chạy và resume để có thể lặp lại.
Không chọn mô hình theo biểu đồ đẹp, một video bot hoặc score một phiên.

## 10. Chỉ số, SUSPECT và tiêu chí chọn candidate

Đơn vị chính là phiên/lượt chạy. Báo ma trận nhãn thật 2 lớp x kết luận 3
trạng thái, tách từng họ bot, từng tác vụ người thật và điều kiện profile.
Kèm số phiên không có kết quả do lỗi gửi/lưu/inference. Đây là trạng thái
đánh giá vận hành, không tạo verdict thứ tư hoặc tự điền SUSPECT cho API lỗi.
Chỉ số end-to-end giữ các phiên lỗi này trong mẫu số; bảng classifier hợp lệ
được trình bày riêng với phạm vi và mẫu số rõ.

- BOT recall: số BOT thật được kết luận BOT / toàn bộ BOT thật.
- Bot-as-HUMAN: số BOT thật nhận HUMAN / toàn bộ BOT thật.
- Human-as-BOT: số người thật nhận BOT / toàn bộ người thật.
- BOT precision: số BOT thật trong nhóm được kết luận BOT / toàn bộ kết luận BOT.
- SUSPECT rate và decision coverage: lần lượt SUSPECT/N và (HUMAN+BOT)/N.
- No-result rate: phiên không có kết quả tại endpoint / N; không tính thành
  một bot được phát hiện hoặc người thật được nhận diện đúng.
- Thời gian tới quyết định đầu tiên, số lần đổi nhãn, ever-HUMAN của bot,
  ever-BOT của người thật và tỷ lệ hết phiên vẫn SUSPECT.

Precision mẫu số 0 là undefined, không điền 100%. Không chấm SUSPECT thành BOT
đúng, không bỏ phiên ít chuột khỏi bảng toàn bộ, không coi thiếu input là lỗi
phân loại chuột. PR/ROC chỉ tính cho score hợp lệ ở track phù hợp, công bố số
phiên bị loại khỏi biểu đồ. Chi tiết phép đo trong protocol.

Tách SUSPECT theo mã nguyên nhân: thiếu chuột, quỹ đạo suy biến, model lỗi,
ngoài miền hỗ trợ, mâu thuẫn hai model và risk trung gian. Tối ưu nguyên nhân
dữ liệu/hệ thống trước; không đổi toàn bộ SUSPECT sang BOT để tăng recall.

Mục tiêu vận hành thử trên validation, cần xác nhận trước khi dùng: observed
human-as-BOT <= 5%, bot-as-HUMAN <= 10%, BOT recall >= 80% trong các họ đã
đăng ký, và coverage >= 75% trên nhóm đủ dữ liệu. Đây là mục tiêu candidate,
không phải kết quả đã có hoặc điều kiện bảo đảm đạt điểm khóa luận. Công bố
per-family, số đếm và khoảng bất định, không che nhóm yếu bằng số trung bình.

Chọn candidate trên validation theo ưu tiên: tránh nhận nhầm người thật,
tăng BOT recall trong giới hạn đó, rồi cải thiện coverage. Nếu không có
candidate đạt mục tiêu, giữ baseline, báo kết quả âm và nguyên nhân. Tập test
cuối chỉ đo một lần sau khi khóa model/rule/ngưỡng; không quay lại tune trên nó.
Giữ cả kết quả validation và test nếu chúng khác nhau.

Các phiên của một người không độc lập. Báo khoảng bất định theo nhóm người
và lượt/config bot khi cỡ mẫu cho phép; với chỉ ba người test, nói rõ khoảng
rất rộng. Kết quả 0 lỗi trên 18 phiên không chứng minh FPR production bằng 0.
Precision của benchmark cân bằng cũng không phải precision ở mọi tỷ lệ bot
ngoài thực tế. So sánh các model theo cặp trên cùng phiên; chưa hứa cải thiện
có ý nghĩa thống kê khi dữ liệu nhỏ.

## 11. P4: Kiểm thử và demo bảo vệ

Kiểm thử phải nối được browser thật → collector → storage → export → feature
→ model → dashboard. Unit test hiện có là một phần trong chuỗi này.

| Nhóm | Kịch bản bắt buộc |
| --- | --- |
| Thu dữ liệu | Retry, mất mạng, pagehide, reload, hai tab, điều hướng, duplicate snapshot |
| Input | Không chuột, chỉ click, chỉ wheel, timestamp trùng, quỹ đạo đứng yên, touch ngoài miền |
| Storage | Mongo outage/recovery, restart, spool đầy, snapshot hết TTL trước export, thiếu analysis |
| Model | Weight thiếu/sai contract, NaN/Inf, chunk lỗi, score không hợp lệ, candidate không cải thiện |
| Giao diện | Thiếu dữ liệu hiển thị --, profile chỉ mở đúng thao tác, URL dài, trạng thái/phiên bản khớp API |
| Tái hiện | Raw/manifest hash khớp, split không trùng, cùng weights/config cho cùng input ra cùng kết quả trong dung sai |

Demo gồm: một người thật, bot automation rõ không chuột, bot chuột trong phạm
vi, phiên ít dữ liệu và một ca khó vẫn chưa phát hiện tốt. Tất cả hiện verdict,
nguồn bằng chứng, dữ liệu đã quan sát và phiên bản model. Có replay dữ liệu
đóng băng/video dự phòng nếu mạng lỗi; phải nói rõ lúc nào đang replay.

P4 xong khi có report test mới, video/demo, log và cách rollback bundle. Nếu
candidate kém hơn thì demo baseline kèm phân tích thất bại, không ép nhãn.

## 12. P5: Cấu trúc luận văn và bằng chứng

| Chương | Nội dung | Bằng chứng/đầu ra |
| --- | --- | --- |
| 1 | Bối cảnh, mục tiêu, phạm vi, câu hỏi nghiên cứu | Đề cương và threat model |
| 2 | Nền tảng và nghiên cứu liên quan | Bảng so sánh BotD, mouse dynamics, DELBOT, BeCAPTCHA; nguồn gốc code |
| 3 | Thiết kế hệ thống và dataset | Sơ đồ luồng, schema, protocol nhãn, split và lỗi thu dữ liệu |
| 4 | Mô hình và thực nghiệm | E0-E4, feature/threshold, cấu hình, bảng kết quả và phân tích lỗi |
| 5 | Prototype và đánh giá vận hành | Demo nhúng, lưu/replay, dashboard, giới hạn và case study |
| 6 | Kết luận và phát triển | Trả lời từng câu hỏi, giới hạn bằng chứng, công việc còn lại |

Gói tái hiện gồm source snapshot, danh sách dependency, hướng dẫn chạy,
dataset card, split manifest, model card, weights/checksum, config thí nghiệm,
kết quả máy đọc được, script tạo bảng/hình và tài liệu dữ liệu được chia sẻ.
Không công khai credential/raw fingerprint/IP hoặc dữ liệu không có quyền chia sẻ.

Hình bắt buộc: kiến trúc; luồng collector tới kết luận; phân bố dữ liệu;
ma trận 2x3; kết quả từng họ; coverage/SUSPECT theo nguyên nhân; một timeline
đổi nhãn. Mỗi hình chỉ rõ dataset, split, đơn vị mẫu và phiên bản model.

Luyện trả lời: vì sao cần hai model chuột; vì sao fingerprint không phải
định danh chắc chắn; vì sao nhiều SUSPECT; vì sao chia theo người; dữ liệu
tổng hợp có giới hạn gì; heuristic có làm ML trở nên thừa không; đóng góp
tự làm ở đâu; trường hợp nào hệ thống chưa xử lý được. Câu trả lời dựa vào
số liệu E0-E4 và ca lỗi đã lưu, không dựa vào tên công nghệ.

## 13. Danh sách công việc theo module

Đây là bản đồ thực hiện; đường dẫn mới là dự kiến, chưa được tạo trong lượt lập kế hoạch.

| Ưu tiên | Module/đường dẫn | Công việc | Kiểm chứng |
| --- | --- | --- | --- |
| P0 | `docs/THESIS_BENCHMARK_PROTOCOL_V1.md` | Chốt nhóm, nhãn, split, chỉ số | Đủ thông tin để người khác thu đúng |
| P1 | `collector/src/index.js`, `mouse.js` | Kiểm chứng snippet/lifecycle/metadata phiên bản trong scope | Browser native và ca retry/navigation |
| P1 | `api_service/capture.py`, `database.py`, `main.py` | Kiểm chứng đường lưu/receipt, không tự sinh nhãn | MongoDB thật, restart, outage |
| P1 | `core_ml/dataset/export_captures.py` (mới) | Export snapshot + manifest theo phạm vi | Hash round-trip, đủ/sai phiên, thiếu analysis |
| P1 | `core_ml/dataset/study_manifest.py` (mới) | Nhãn, participant/config group, nguồn dữ liệu, split | Từ chối overlap, nhãn xung đột và trường nguồn thiếu |
| P1 | Runner trong `C:/Users/Admin/bot-detection-test` | Seed/config block, run manifest, server receipt | Mỗi run độc lập, trace cấu hình, không lấy verdict làm nhãn |
| P1 | Hướng dẫn native human capture (mới) | Thu profile thật và ít chuột | Không do Playwright mở, không ép đủ move |
| P2 | `core_ml/dataset/field_captures.py` | Hỗ trợ study manifest mới, giữ legacy | Test loader cũ + trace split/nhãn mới |
| P2 | `core_ml/experiments/` và `core_ml/train.py` | E0-E4, weights theo phiên, budget và artifact ngoài bundle chính | Split audit, train/inference parity, nạp lại artifact |
| P2 | `core_ml/evaluate_thesis.py` (mới) | Ma trận 2x3, per-family, eligibility, timeline | Số đếm tính tay, undefined metrics, nhóm thiếu dữ liệu |
| P2 | `api_service/dashboard.html` | Bằng chứng, thiếu dữ liệu, trạng thái/version đúng | Smoke test desktop, dữ liệu dài và phiên không chuột |
| P3 | `docs/`, báo cáo luận văn | Dataset/model card, số liệu và hình từ JSON | Đối chiếu tổng số mẫu và mọi tuyên bố |

File đang mở `Tuần 4/silkmoon/admin/src/components/Dashboard.jsx` thuộc ứng
dụng khác; kế hoạch DATACAT dùng `bot-detection-core/api_service/dashboard.html`.
Không sửa nhầm dashboard SilkMoon khi hoàn thiện giao diện khóa luận.

## 14. Rủi ro và cách giữ tiến độ

| Tình huống | Xử lý |
| --- | --- |
| Thầy chưa cung cấp website | Hoàn thiện snippet/runbook trên site kiểm soát; việc nhúng thực còn ghi là phụ thuộc |
| Chưa có người tham gia | Chuẩn bị lịch thu và baseline cũ; không tự tạo nhãn HUMAN từ script hoặc vendor |
| Model mới không tốt hơn | Giữ baseline, báo ablation âm, tập trung sửa nguyên nhân dữ liệu và giải thích giới hạn |
| Người ít chuột thành SUSPECT | Giữ trong coverage toàn bộ; tách khỏi chất lượng classifier khi chưa đủ evidence |
| Candidate profile chỉ bắt được headless | Báo đúng nhóm áp dụng; không gọi đó là cải thiện model chuột |
| Không đủ GPU | XGBoost CPU trước, BiLSTM giới hạn search, checkpoint/Colab khi cần |
| Script/code/schema đổi giữa đợt thu | Tăng phiên bản, tách cohort, ghi manifest; không âm thầm gộp |
| Kết quả test thấp hơn validation | Công bố; không sửa test hoặc chuyển ca lỗi ra khỏi phạm vi sau khi xem kết quả |
| Không có trial thương mại | Hoàn thành bằng nhãn từ người/runner; vendor không là phụ thuộc bắt buộc |

## 15. Nâng cao có chọn lọc

Chỉ làm khi dữ liệu/benchmark/báo cáo lõi đã có: một engine Selenium chưa dùng
train; một website hoặc đợt thời gian mới; đánh giá leave-family-out; một nhóm
feature tương tác có ablation; biểu đồ trade-off coverage và lỗi; vendor trial
đối chiếu theo request. Mỗi mục phải tạo được bằng chứng mới, không chỉ thêm code.

GNN, nhiều framework mới, ghi mọi sự kiện vô hạn, tự huấn luyện từ nhãn model
và cố detect mọi stealth bot không nằm trên đường hoàn thành chính.

## 16. Checklist hoàn thành khóa luận

- [ ] Đề tài/phạm vi/câu hỏi được thống nhất và có tiêu chí chấm khi trường cung cấp.
- [ ] Thầy có script nhúng hoạt động và dữ liệu đã được kiểm chứng đến nơi.
- [ ] Raw, nhãn, participant/config group và schema có nguồn gốc rõ.
- [ ] Có người thật native browser; các trường hợp ít chuột được giữ lại.
- [ ] Split theo người/phiên/config; cửa sổ chồng lặp không rò rỉ.
- [ ] Model/rule/threshold khóa trước lần test mới cuối cùng.
- [ ] Có E0-E4 hoặc giải thích rõ vì sao một candidate không được triển khai.
- [ ] Báo cáo 2x3, per-family, SUSPECT/coverage và diễn tiến theo phiên.
- [ ] Có kiểm thử end-to-end, demo thật và replay dự phòng được ghi rõ.
- [ ] Luận văn/slide/gói tái hiện thống nhất số liệu và nguồn tham khảo.
- [ ] Công bố giới hạn, lỗi còn lại và khác biệt giữa prototype và production.

Hoàn thành nghiên cứu và chấp thuận một candidate là hai quyết định khác nhau.
Một thử nghiệm không cải thiện vẫn là kết quả nghiên cứu cần trình bày trung
thực; không tự đổi thành tuyên bố model mới tốt hơn để đạt checklist.

## 17. Nguồn phương pháp

- [Scikit-learn: cross-validation và group split](https://scikit-learn.org/stable/modules/cross_validation.html):
  cơ sở giữ người/nhóm khỏi đồng thời xuất hiện trong train và test, và tách
  chọn model khỏi đánh giá cuối. Không mặc định môi trường cài đúng phiên bản
  tài liệu mới nhất; dùng API tương thích dependency đã khóa trong dự án.
- [Scikit-learn: model evaluation](https://scikit-learn.org/stable/modules/model_evaluation.html):
  định nghĩa metric nhị phân, PR/ROC và mẫu số; bảng 2x3 và coverage ở đây là
  protocol riêng cho hệ thống có SUSPECT.
- [BeCAPTCHA-Mouse](https://arxiv.org/abs/2005.00890): tham khảo nghiên cứu
  hành vi chuột và đánh giá trên benchmark xác định; không chuyển con số của
  bài báo thành kết quả của DATACAT.
- [BotD](https://github.com/fingerprintjs/BotD): nguồn tham khảo dấu hiệu
  automation; heuristic tự viết trong DATACAT phải được đánh giá riêng.
