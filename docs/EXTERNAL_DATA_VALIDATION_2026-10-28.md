# Kiểm chứng trên dữ liệu ngoài (2026-10-27/28)

Mục tiêu: dùng dataset công khai để đo tỷ lệ bắt nhầm người thật của từng thành phần, vì
trước đây mô hình chuột chỉ được đánh giá trên M4D, cùng nguồn với dữ liệu train. Không
dataset nào dưới đây được dùng để train. Script nằm ngoài repo (scratchpad); mục "Tái hiện"
mô tả cách làm.

## Tóm tắt

| Dataset | Dùng để kiểm tra | Kết quả | Hệ quả |
|---|---|---|---|
| Balabit Mouse Dynamics Challenge | Mô hình chuột (BiLSTM + XGBoost + luật) | 98,6% cửa sổ HUMAN, 0/1.676 phiên kết thúc BOT | Giữ nguyên |
| Aalto 136M Keystrokes | Luật gõ phím giả | Luật policy 15–21 bắt nhầm 4.097 người (nhịp) và 303 người (giữ phím) | Sửa thành policy 22 |
| Mendeley Mouse Dynamics 2026 | Ngưỡng nhả chuột tức thì (< 5 ms) | 3,7% click của người thật dưới 5 ms; 1.125/1.748 người có ≥ 2 click như vậy | Xác nhận luật click phải kèm điều kiện trúng tâm; giữ nguyên |

Không dùng: ReMouse (không tìm được bản tải công khai), DELBOT (tác vụ vẽ vòng tròn, không
phải duyệt web), các dataset CTR/giao dịch/vân tay sinh trắc (không có tín hiệu chuột, bàn phím
hay nhãn bot).

## 1. Balabit: mô hình chuột trên người thật độc lập

10 người, 1.676 phiên làm việc thật qua Remote Desktop (`training_files` và `test_files`; các
phiên "illegal" là người khác, không phải bot). Mỗi phiên phát lại như bản export của collector
tại 25 thời điểm (`core_ml.collector_windows.rolling_windows`), đúng cách đánh giá phát hành.

| Chỉ số | Kết quả |
|---|---|
| Cửa sổ HUMAN / NGHI VẤN / BOT | 41.311 / 588 / 1 (trên 41.900) |
| Phiên từng có cửa sổ BOT | 1 (0,06%) |
| Phiên kết thúc BOT | 0 |
| Phiên kết thúc HUMAN | 1.657 (98,9%) |
| BiLSTM trung vị / p90 | 0,003 / 0,15 |

Cửa sổ BOT duy nhất là 25 điểm đầu của một phiên được ghi ở khoảng 9 Hz (109 ms giữa hai điểm),
do Remote Desktop gửi chậm. Trình duyệt thật báo khoảng 60 Hz.

## 2. Aalto 136M: luật gõ phím giả

168.593 người gõ 15 câu trên một trang kiểm tra tốc độ gõ (Dhakal và cộng sự, CHI 2018; giấy
phép nghiên cứu phi thương mại, phải trích dẫn). Mỗi người được cắt thành các đoạn 60 phím
(lượng tối đa collector gửi) và đưa qua đúng hàm `analyze_typing` của production.

| Luật | Người thật khớp | Bot khớp (đo 2026-10-28) |
|---|---|---|
| Policy 15–21: CV khoảng cách < 0,10 (11 phím) | **4.097** (2,4%) | |
| Policy 15–21: giữ phím trung vị < 12 ms (8 phím) | **303** (0,18%) | |
| Policy 22 `TYPING_METRONOME`: CV khoảng cách **và** CV thời gian giữ < 0,02 | **0** (thấp nhất 0,027) | `type(text, {delay})` của Playwright, Puppeteer, patchright: 0,004–0,009 |
| Policy 22 `TYPING_INSTANT_HOLD`: giữ **và** khoảng cách trung vị < 12 ms | 153, xem dưới | `type()` không delay, Selenium `sendKeys`: 0,3–1,9 ms |
| Policy 22 `TYPING_INSTANT_METRONOME`: giữ < 12 ms và CV khoảng cách < 0,05 | **0** (thấp nhất 0,090) | Selenium gõ từng ký tự rồi chờ cố định: 0,017 |

Chạy lại toàn bộ bằng code policy 22 (123 triệu phím, 2,13 triệu đoạn 60 phím): `TYPING_METRONOME`
và `TYPING_INSTANT_METRONOME` không khớp người nào; `TYPING_INSTANT_HOLD` khớp 153 người (174
đoạn, 0,008%).

153 người khớp `TYPING_INSTANT_HOLD` đều có 8 phím liên tiếp trong 0–12 ms (nhiều người
0 ms), điều tay người không làm được. Nhiều khả năng đây là công cụ tự gõ dùng gian lận bài
kiểm tra tốc độ, hoặc dữ liệu ghi lỗi. 303 người khớp luật cũ phần lớn dùng bàn phím laptop
hoặc bàn phím rời, có thời gian giữ gần 0 nhưng gõ với tốc độ người (bàn phím hoặc driver báo
key-up cùng lúc key-down).

Giới hạn: script đặt `delay` 12–40 ms, hoặc ngẫu nhiên hóa từng phím, không bị luật gõ phím
bắt. Gõ nhanh như vậy là rất hiếm, nhưng trong Aalto có 291 người có cửa sổ 8 phím với
khoảng cách trung vị 12–40 ms, nên không dùng làm luật BOT.

## 3. Mendeley Mouse Dynamics 2026: nhả chuột tức thì

Popkov (2026), CC BY 4.0. 1.748 người, 9,48 triệu click trong các bài thi trên máy tính
(2015–2018). Bộ này chỉ có đặc trưng đã gộp (thời gian giữ click, tốc độ, hướng), không có tọa
độ thô, nên không dùng được cho BiLSTM.

| Chỉ số | Kết quả |
|---|---|
| Click giữ < 5 ms | 349.944 (3,7%), gần hết là đúng 0 ms |
| Người có ≥ 2 click < 5 ms | 1.125 / 1.748 |
| Phân bố thời gian giữ | Đỉnh ở 15, 30, 45 ms: độ phân giải timer 15,6 ms của Windows, nên "0 ms" nghĩa là dưới 15,6 ms |

Nhả nhanh một mình rất phổ biến ở người thật (chạm-để-click trên touchpad, timer thô). Luật
`synthetic_click_v1` đã đòi thêm điều kiện mọi click trúng đúng tâm nút; dữ liệu này cho thấy
điều kiện kép đó là bắt buộc. Không đổi luật.

## Tái hiện

- Balabit: `git clone https://github.com/balabit/Mouse-Dynamics-Challenge`; Move/Drag → `move`,
  Pressed → `down`, Released → `up` (+ `click` với nút trái); thời gian = client timestamp × 1000.
- Aalto: `https://userinterfaces.aalto.fi/136Mkeystrokes/data/Keystrokes.zip` (1,5 GB, đọc thẳng
  trong zip); LETTER một ký tự → `c`/`n`, BKSP/DEL → `b`, còn lại → `o`; giữ = RELEASE_TIME − PRESS_TIME.
- Mendeley: `https://data.mendeley.com/datasets/3rfsbcmgfw/1` (`dataset.csv`, 1,6 GB, đọc theo
  luồng); dòng click là dòng có `duration`.
