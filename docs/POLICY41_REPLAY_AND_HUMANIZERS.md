# Policy 41: phát lại quỹ đạo chuột, và giới hạn trước humanizer

Ngày 16/11/2026. `DECISION_POLICY_VERSION = "41"`. Code: `core_ml/features/trajectory_signature.py`,
`api_service/trajectory_store.py`, `core_ml/models/ensemble.py`. Đánh giá: `core_ml/evaluate_replay.py`.

## Bối cảnh: red team bằng bot có kiểm soát

`bot-lab/probe_v40.js` cho 14 phiên bot thật vào SilkMoon (Playwright, Selenium, Puppeteer + stealth,
headless và có giao diện; đứng yên, đường thẳng, humanizer, phát lại quỹ đạo người thật, sự kiện giả, mobile
giả lập). Kết quả trên production (policy 40): 12 phiên BOT ngay lần gửi đầu nhờ lớp môi trường (webdriver,
UA headless, ChromeDriver, mâu thuẫn CDP/GPU/HEADLESS/CONTEXT), 2 phiên stealth có giao diện là Nghi vấn
(`FRAME_LOCKED_POINTER`, `CDP_ATTACHED`). Không phiên nào là Người. Các phiên này đã gắn nhãn `controlled_bot`.

Thử offline với môi trường trình duyệt hoàn hảo (môi trường của một phiên người thật có nhãn, chỉ thay quỹ
đạo chuột) cho thấy lớp hành vi có hai điểm mù: **phát lại quỹ đạo người thật** và **humanizer** (Bezier kiểu
ghost-cursor, minimum-jerk có run tay) đều ra Người.

## Luật mới: phát lại quỹ đạo (`replayed_trajectory_v1`)

Không ai rê chuột theo đúng một đường phức tạp hai lần. Mỗi đường đi của con trỏ (tách tại chỗ nhảy, chỗ
nghỉ trên 150 ms, chỗ đứng yên trên 100 ms) được làm mượt 3 điểm, lấy mẫu lại theo quãng đường (mỗi 1% khung
nhìn, nên tốc độ và thời gian không ảnh hưởng), lượng tử hoá hướng thành 8 ô (thêm một lưới lệch nửa ô), rồi
mỗi chuỗi 24 bước đổi hướng ít nhất 5 lần và qua ít nhất 4 ô được băm thành chữ ký. Server giữ 1/8 số chữ
ký (chọn theo chính giá trị băm, nên hai lần của cùng một đường vẫn gặp nhau), 7 ngày, và đếm số chữ ký cả
phiên chung với **một** phiên khác, không tính trang của chính nó (collector đổi session id vẫn gửi lại
cùng trang). Từ 4 chữ ký: chặn kết luận Người (`REPLAYED_TRAJECTORY`, cũng là bằng chứng cho phiên quá ngắn).
Từ 8: BOT, khoá phiên.

Đo trên 109 phiên người của benchmark, mỗi phiên cắt thành các lần gửi kiểu collector 1.17, và replay của 40
phiên, cắt ở **điểm khác** bản gốc (như production):

| Trường hợp | Từ 4 chữ ký (Nghi vấn) | Từ 8 chữ ký (BOT) |
| --- | --- | --- |
| Hai phiên người khác nhau | **0** phiên (trùng nhiều nhất: 0 chữ ký) | 0 |
| Phát lại nguyên vẹn | 93% | 80% |
| Phát lại nhanh ×1,5 | 90% | 72% |
| Phát lại có lấy mẫu lại | 25% | 3% |
| Phát lại + nhiễu 0,5 px | 28% | 7% |
| Phát lại + nhiễu 1 px | 10% | 0% |

Giới hạn: lần phát lại đầu tiên của một bản ghi không có gì để so (chỉ từ lần thứ hai bị bắt; đội bot dùng
lại bản ghi nên thực tế bị bắt), và kẻ tấn công thêm nhiễu cỡ 1 px hoặc lấy mẫu lại thì lọt phần lớn. Người
dùng benchmark cùng làm một nhiệm vụ trên cùng trang, nên con số "0 trùng" trên dữ liệu thật đa dạng hơn chỉ
có thể tốt hơn; vẫn cần theo dõi trên production.

## Thí nghiệm bị loại: dạy model nhận humanizer

Nguyên nhân gốc của điểm mù humanizer: bộ sinh "người" tổng hợp dùng khi train
(`generate_synthetic_human_trajectory`) chính là một humanizer (Bezier tăng/giảm tốc + nhiễu Gauss), và 150
phiên như vậy được gắn nhãn người ở mỗi lần train.

Phân bố điểm BiLSTM trung bình cả phiên (policy 40): người held-out 0,14 (tối đa 0,26), người có nhãn
0,06 (tối đa 0,12), humanizer 0,16-0,20 (tối đa 0,34-0,56). Hai phân bố chồng nhau, nên đổi ngưỡng không
bắt được humanizer mà không bắt nhầm người.

Bản ứng viên `--synthetic-profile humanizer_v1` (bỏ người tổng hợp, thêm 150 humanizer Bezier/minimum-jerk
vào lớp bot, giữ WindMouse ngoài train) **trượt release gate**: cửa sổ người bị Nghi vấn trên validation
tăng từ 413/14.000 (3,0%) lên 1.919/14.000 (13,7%), tỉ lệ cao nhất của một phiên người từ 11,9% lên 36,3%.
Model không được dùng. (Kết quả biến thể giữ người tổng hợp: xem mục dưới.)

## Biến thể giữ người tổng hợp

`--synthetic-profile humanizer_mixed_v1` (giữ 150 người tổng hợp, thêm 150 humanizer vào lớp bot) cũng
**trượt release gate**:

| Bản | Cửa sổ người bị Nghi vấn (validation) | Phiên người tệ nhất | Gate |
| --- | --- | --- | --- |
| Policy 40 (đang chạy) | 413/14.000 (3,0%) | 11,9% | Đạt |
| `humanizer_v1` | 1.919/14.000 (13,7%) | 36,3% | Trượt |
| `humanizer_mixed_v1` | 1.529/14.000 (10,9%) | 28,0% | Trượt |

Kết luận: với đặc trưng hiện có (8 đặc trưng chuyển động cho BiLSTM, 20 thống kê cho XGBoost), humanizer tốt
không tách được khỏi người thật; dạy model nhận chúng làm tăng Nghi vấn sai cho người 3,6–4,6 lần. Phòng thủ
trước humanizer vì vậy dựa vào các lớp không phụ thuộc hình dạng quỹ đạo: môi trường trình duyệt, nguồn gốc sự
kiện (CDP, khớp khung hình, áp lực nhấn), và phát lại quỹ đạo (policy 41). Bot điều khiển chuột ở cấp hệ
điều hành trên một trình duyệt thật, với humanizer tốt, là giới hạn còn lại của hệ thống.
