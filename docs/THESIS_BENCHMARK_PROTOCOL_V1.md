# Protocol benchmark khóa luận DATACAT v1

Ngày soạn: 2026-10-19. Trạng thái: dự thảo đăng ký trước; chưa thu dataset
theo protocol này. Chốt nội dung trước khi mở tập test mới.

## 1. Đơn vị và nhóm bot

Đơn vị nghiên cứu chính là một phiên người dùng hoặc một lượt browser bot.
Một phiên có thể có nhiều snapshot; một snapshot có nhiều chunk/cửa sổ.
Snapshot, cửa sổ và chunk không phải người dùng độc lập.

| Mã | Họ hành vi | Ví dụ | Tham số cần thay đổi |
| --- | --- | --- | --- |
| F1 | Tuyến tính | Nội suy từ A tới B, theo một hoặc nhiều đoạn thẳng | Khoảng cách, hướng, tốc độ, số bước, khoảng nghỉ |
| F2 | Theo mẫu lặp | Vòng tròn/zigzag hoặc waypoint template lặp | Bán kính/biên độ, số lần lặp, tốc độ, template |
| F3 | Macro tác vụ | Cuộn, tiếp cận mục tiêu, click rồi nghỉ theo quy trình | Lịch thao tác, mục tiêu, dwell, nhịp cuộn và bộ sinh đường đi |

Mỗi run có `scenario_family`, `motion_generator_id`, `interaction_pattern_id`,
`template_id`, `config_block_id`, seed và hash runner. F3 có thể dùng lại bộ
sinh F1/F2, nên family khác không tự chứng minh độc lập về generator.
Giữ toàn bộ run của cùng template/config block trong một split. Nếu công bố
leave-generator-out, group theo bộ sinh dùng chung thay vì theo tên script.

Chọn trước một engine Playwright/Chromium. Cấu hình automation mặc định và
cấu hình che dấu cơ bản là hai điều kiện riêng, có phiên bản rõ; không thêm
công cụ né tránh mới trong lúc xem test. Selenium là bộ chuyển engine bổ
sung, không được gộp thành kết quả engine chính nếu chưa có protocol.

Các script cũ circular/heavy-wander/scrub-hover là development/challenge.
Giữ riêng mapping của chúng; không tự coi cả ba là ba họ chính đã chốt ở đây.

## 2. Người thật và tác vụ

Mục tiêu 15 người, mỗi người sáu phiên ngắn trên cùng website:

1. Đọc và cuộn tự nhiên.
2. Điều hướng/click các mục được mô tả.
3. Di chuyển tới mục tiêu ở các vị trí/kích thước khác nhau.
4. Kéo chọn văn bản hoặc thao tác kéo phù hợp website.
5. Hover, chỉnh hướng rồi click.
6. Thao tác ít chuột: đọc, bàn phím hoặc cuộn là chính.

Mốc thời lượng dự kiến là 90 giây/phiên cho cả người và bot; chốt hoặc sửa
trước pilot. Dừng khi hết mốc, không dừng sớm vì đã có verdict mong muốn.
Điều chỉnh tác vụ theo website trước pilot, không ép người thật vẽ hình như
bot. Cho phép mouse hoặc touchpad desktop, ghi thiết bị tự khai và OS/browser.
Nếu website không có thao tác kéo, thay bằng một tác vụ cụ thể trước khi thu.
Không loại người dùng tự nhiên chỉ vì chưa đủ move cho LSTM.

Full-system human control dùng Chrome/Chromium mở bình thường. Người thật
thao tác trong browser Playwright chỉ làm mouse-only control; đánh dấu loại
driver và không dùng profile đó để đo FPR trên browser thông thường.

## 3. Manifest và nguồn nhãn

Raw payload và manifest nhãn là hai artifact riêng, nối bằng session/page/run
và capture receipts phía server. Trường đề xuất:

| Nhóm | Trường tối thiểu |
| --- | --- |
| Phiên/lượt | study_id, run_id, site_id, page_instance_id/sessionId, thời gian, capture_id list |
| Nhãn | HUMAN/BOT/UNKNOWN, label_source, label_confirmed_by, label_timestamp |
| Người thật | participant_id giả danh, task_id, driver/native status, thiết bị tự khai |
| Bot | scenario_family, motion_generator_id, template_id, config_block_id, seed, runner hash |
| Môi trường | browser/version, OS, viewport, điều kiện profile, collector/schema hash |
| Model | bundle/policy/config tạo dự đoán, feature version; tách khỏi nhãn |
| Dữ liệu | raw/export hash, trạng thái server receipt, lỗi/mất snapshot, nguồn timestamp |
| Đánh giá | split, eligibility, exclusion reason nếu có, thời điểm khóa manifest |

HUMAN lấy từ người tham gia biết nguồn; BOT từ runner thực sự đã chạy.
Hành vi tự động không chứng minh ý đồ gian lận. Traffic tự nhiên chưa rõ
nguồn giữ UNKNOWN; không lấy verdict của DATACAT làm nhãn huấn luyện.
Vendor trial là trường đối chiếu riêng theo request/time, không ghi đè
nhãn gốc hoặc tự coi mọi traffic chưa bị vendor bắt là HUMAN.

`participant_id`, script/family, filename, driver, seed, nhãn vendor và
verdict cũ không là feature. Kiểm tra dấu hiệu rò rỉ từ URL/tên tài khoản,
viewport chỉ dành riêng cho một lớp hoặc thiết bị/OS chỉ xuất hiện ở bot.
Hai lớp nên chia sẻ website/tác vụ và môi trường ở mức khả thi.

## 4. Split và điều kiện độc lập

- Người thật: 9 người train, 3 validation, 3 test; mọi phiên của một người
  nằm cùng split. Không dùng visitor fingerprint thay participant ID.
- Bot mỗi họ: mục tiêu 36/12/12 run, tương ứng 60%/20%/20%. Chia trước theo
  block cấu hình/template; không shuffle các cửa sổ hoặc run lặp giống nhau.
- Khoảng 60 run/họ nên hình thành nhiều block train/val/test riêng, không
  phải một template chạy lại 60 lần. Đăng ký các block trước khi chạy.
- Chỉ đổi seed đo được biến thiên trong cùng bộ sinh; đó là kết quả cho họ
  đã biết. Không gọi nó là nhận diện bot generator chưa từng gặp.
- Dataset cũ và các ca đã xem kết quả là development/regression. Tôn trọng
  split gốc, nhưng không gọi split đã dùng chọn policy là test độc lập mới.
- Audit trùng ID, nội dung chuẩn hóa, clock-shift duplicate và dữ liệu sao
  chép. Scale/normalization học trên train, không fit trên validation/test.
- Tạo split trước khi mở rộng thành window/chunk hoặc augmentation.
- Test mới khóa bằng manifest hash; thầy/người hỗ trợ có thể giữ bản test.
  Nếu làm một mình, khóa manifest và hạn chế truy cập, ghi mọi lần đánh giá.
- Bug công cụ đánh giá có thể được sửa rồi chạy lại nếu ảnh hưởng mọi model
  như nhau và có log; không dùng kết quả đã xem để tune model rồi gọi lần
  chạy sau là test độc lập. Nhu cầu tune tiếp đòi hỏi cohort test mới.

Với đủ dữ liệu, leave-one-generator-out là phân tích phụ. Một họ test đã
được phân tích để chọn feature không còn là held-out mới của lần chọn đó.

## 5. Eligibility và coverage

Đánh giá toàn bộ phiên có nhãn trước. Giữ các phiên thiếu chuột trong mẫu
số và bảng 2x3. Tách một bảng mouse-eligible theo gate được khóa trước:
desktop mouse/touchpad được hỗ trợ, dữ liệu hợp lệ, đủ move/chunk, ít nhất
năm vị trí và năm timestamp khác nhau, khoảng thời gian dương, không lẫn
touch hoặc legacy source không rõ theo policy đã chọn.

Dùng cấu hình/gate hiện hành được ghi trong manifest; không chỉ căn cứ
client `hasEnoughData` hoặc cứng hóa số 25 khi cấu hình đã thay đổi.
Eligibility dữ liệu được tính độc lập với chất lượng score; model tải lỗi
hoặc inference lỗi được ghi lỗi hệ thống, không loại khỏi mẫu để tăng kết quả.

Thiếu mouse/profile không tự thành BOT. Automation rõ có thể quyết định
theo rule đã định. Phiên chưa đủ cơ sở vẫn có thể SUSPECT với mã nguyên nhân.
Touch/mobile ở ngoài miền chính được báo coverage/stress riêng.

## 6. Các mốc theo thời gian

Endpoint chính là snapshot đã được server nhận cuối cùng trong phiên có
thời lượng/tác vụ định trước. Không chờ tới khi model ra nhãn mong muốn mới
dừng. Không dùng `test-probe` thay snapshot đã gửi và có receipt.

Theo dõi tất cả snapshot đã gửi thành công trong cohort mới. Báo thêm mốc
đầu tiên đủ dữ liệu, tại 25/50/100 move nếu quan sát được và các mốc thời
gian có sẵn. Không nội suy thành snapshot chưa từng được thu. Time-to-decision
bị giới hạn bởi chu kỳ gửi; phiên hết hạn vẫn chưa kết luận được giữ là
chưa có quyết định, không âm thầm loại khỏi trung vị.

Nếu raw có lịch sử đủ dài, replay offline có thể dùng checkpoint bổ sung,
nhưng ghi riêng là replay, ghi thuật toán chọn cửa sổ và không nhân số phiên.
Replay gate 1.000 checkpoint hiện có vẫn là regression; không bảo đảm kiểm
tra mọi cửa sổ hoặc thay thế test browser mới.

## 7. Ma trận 2x3 và chỉ số

Ký hiệu H_H/H_S/H_B là người thật nhận HUMAN/SUSPECT/BOT; B_H/B_S/B_B là
bot nhận HUMAN/SUSPECT/BOT. H_E/B_E là phiên đã đăng ký nhưng không có kết
quả tại endpoint do lỗi gửi/lưu/inference. Đây là trạng thái đánh giá vận
hành, không phải verdict thứ tư. Giữ số lỗi cạnh bảng 2x3, không tự gán một
nhãn dự đoán cho request đã lỗi. N_H=H_H+H_S+H_B+H_E; N_B=B_H+B_S+B_B+B_E.

| Nhãn thật | Kết luận HUMAN | Kết luận SUSPECT | Kết luận BOT |
| --- | ---: | ---: | ---: |
| HUMAN | H_H | H_S | H_B |
| BOT | B_H | B_S | B_B |

```text
BOT recall          = B_B / N_B
Bot-as-HUMAN        = B_H / N_B
Human-as-BOT        = H_B / N_H
BOT precision       = B_B / (B_B + H_B)
SUSPECT rate        = (H_S + B_S) / (N_H + N_B)
No-result rate      = (H_E + B_E) / (N_H + N_B)
Decision coverage   = (H_H + H_B + B_H + B_B) / (N_H + N_B)
Decided-only error  = (H_B + B_H) / (H_H + H_B + B_H + B_B)
```

Mẫu số bằng 0 trả undefined/null. Nếu tính BOT F1 end-to-end, bot SUSPECT và
bot không có kết quả vẫn chưa được phát hiện: FN=B_H+B_S+B_E.
Không trình bày F1 nhị phân trong đó
SUSPECT được bỏ qua mà thiếu ghi chú/mẫu số.

Decided-only error luôn đi cùng coverage vì có thể giảm lỗi bằng cách từ
chối gần hết mẫu. BOT recall + bot-as-HUMAN + bot-SUSPECT rate + bot-no-result
rate = 1 trong nhóm BOT; kiểm tra đẳng thức từ số đếm để bắt lỗi báo cáo.

PR/ROC chỉ dùng score hợp lệ trong track phù hợp và endpoint cố định, báo
eligibility và số thiếu. Không gán risk mặc định 0.5 cho mẫu không phân tích
được. Precision phụ thuộc tỷ lệ bot của cohort; không suy rộng sang mọi site.

Mỗi bảng báo số đếm và tổng mẫu, từng họ, từng tác vụ và full-system vs
mouse-only. Theo thời gian báo thêm ever-BOT của người thật, ever-HUMAN của
bot, đổi nhãn và thời gian tới quyết định. Biểu đồ cửa sổ không thay thế bảng
phiên. Khoảng bất định phải tôn trọng nhóm người/run config và cỡ mẫu nhỏ.

## 8. So sánh và khóa mô hình

E0 heuristic, E1 XGBoost, E2 BiLSTM, E3 fusion baseline và E4 candidate dùng
cùng split và cùng endpoint. Đăng ký trước input/gate/threshold của mỗi nhánh.
Mouse-only bỏ tín hiệu browser bằng đường inference thực, không sửa nhãn
sau dự đoán. Hệ thống đầy đủ giữ input browser đúng như đã thu.

Huấn luyện/chọn feature/scaler trên train; chọn threshold/fusion trên val.
Giữ budget và log cả thử nghiệm âm. Candidate chỉ được chọn trước khi mở
test. Chạy các nhánh đã khóa trên test để so sánh; không chọn lại model
thắng test rồi trình bày đó là hiệu quả không thiên lệch của quá trình chọn.

Mục tiêu validation dự thảo nằm trong kế hoạch chính. Nếu không đạt, báo số
liệu và giữ baseline; hoàn thành nghiên cứu không yêu cầu làm giả cải thiện.
Thí nghiệm cũ 18/18 bot nhận HUMAN ở candidate XGBoost vẫn là bằng chứng
giới hạn, không được xóa khỏi lịch sử.

## 9. Artifact phải xuất

Protocol/version; manifest raw và nhãn; split/hash; config/seed; checksum
collector/model; feature schema; predictions JSONL theo từng snapshot; bảng
phiên và bảng 2x3; per-family; coverage/missingness; runtime; danh sách lỗi
và loại dữ liệu loại trừ với lý do. Raw riêng tư lưu ngoài Git; bản chia sẻ
ẩn định danh và chỉ gồm dữ liệu được phép công bố.

## 10. Nguồn tham khảo

[Scikit-learn group cross-validation](https://scikit-learn.org/stable/modules/cross_validation.html#cross-validation-iterators-for-grouped-data)
là cơ sở chia theo nhóm; [model evaluation](https://scikit-learn.org/stable/modules/model_evaluation.html)
là nguồn định nghĩa precision/recall. Ma trận 2x3, coverage và phân nhóm nguồn
nhãn ở đây là lựa chọn protocol cho DATACAT, chưa phải kết quả đo.
