# Model release v21 — bot điều khiển Chrome thật qua CDP

Bundle: `d7a3abe3b73d4b60a7259174add85288`. Policy: `21`. Collector: 1.8.0. Mô hình chuột train lại cùng dữ liệu và seed: số liệu val/test giống hệt v20.

## Vấn đề sau v20

Ngày 2026-10-27, mô phỏng 8 kiểu bot thường gặp ngoài thực tế trên Chrome 156 (Windows):

| Kịch bản | v20 |
|---|---|
| Puppeteer-stealth (có cửa sổ và headless) | BOT (môi trường mâu thuẫn, nhấn chuột áp lực 0) |
| Selenium-stealth | BOT (dấu vết ChromeDriver) |
| Playwright headless giả UA, chỉ cuộn | chưa đủ dữ liệu |
| Patchright có cửa sổ, chỉ cuộn | chưa đủ dữ liệu |
| **Patchright headless giả UA, thao tác giống người** | **HUMAN** |
| **Patchright có cửa sổ, thao tác giống người** | **HUMAN** (lần chạy khác: BOT) |
| **Patchright phát lại quỹ đạo chuột người thật (M4D)** | **HUMAN** |

Patchright điều khiển Chrome thật qua CDP và che `webdriver`, nên trình duyệt sạch. Chuột đi
đường cong Bezier theo luật Fitts, có rung và vượt đích; phím giữ ~95 ms với nhịp ngẫu
nhiên; click giữ ~95 ms. BiLSTM (0,12–0,29) và XGBoost (< 0,04) đều chấm là người.

## Tín hiệu: chuột do CDP bơm vào không giống phần cứng

Đo trên cùng bản Chrome, cùng máy (màn hình 60 Hz):

| Nguồn input | Mẫu gộp / `pointermove` | Khoảng cách `pointermove` |
|---|---|---|
| Patchright, Puppeteer (chờ từng lệnh) | 1,000–1,002 | 16,7 ms hoặc bội số |
| Patchright bắn 8 lệnh CDP cùng lúc | 3,3 | **0,3 ms** |
| Patchright bắn mỗi 2 ms, không chờ | 1,07 | **4 ms** |
| SendInput 125 Hz (như chuột thường) | 1,85 | 17 ms |
| SendInput 1000 Hz (chuột gaming) | 10,2 | 17 ms |
| SendInput 60 Hz | 1,01 | 17 ms |

Chromium gom input thật theo khung hình. Chuột và touchpad báo ≥ 125 Hz, nên trên màn
60 Hz mỗi `pointermove` mang khoảng 2 mẫu. CDP chờ từng lệnh được xử lý, nên chỉ được
1 mẫu mỗi khung. Muốn giả nhiều mẫu thì phải bắn nhiều lệnh, và khi đó sự kiện đến dày hơn
khung hình, điều input thật không làm.

Phiên người thật trên site (truy vấn chỉ đọc ngày 2026-10-27):

| Nhóm | Phiên | Kết quả |
|---|---|---|
| Windows, HTTPS, có số mẫu gộp | 3 | 1,88 / 2,11 / 2,29 |
| Linux (X11), màn 144 Hz | 1 | 1,02, cách 7 ms |
| Khoảng cách `pointermove` ≤ 1 ms tại vị trí mới | 27 phiên, ~2.700 khoảng | **0** |
| Nhóm bằng chứng môi trường | 25 phiên máy tính | 0 (2 phiên Firefox cũ trước v13) |

macOS và X11 gộp chuyển động trước khi Chrome nhận, và màn ≥ 120 Hz với chuột 125 Hz cũng
cho khoảng 1 mẫu. Vì vậy luật số mẫu gộp chỉ xét **Windows + Chromium, màn ≤ 83 Hz**.

## Thay đổi

### 1. `desktop_risk_v1`: không kết luận HUMAN khi input hoặc môi trường bất thường

Chỉ áp dụng khi mô hình chuột đã chấm là người. Kết quả là **NGHI VẤN (FINAL)**, không phải
BOT: từng tín hiệu riêng lẻ chưa đủ để kết tội. Kết quả không khóa.

| Mã | Điều kiện |
|---|---|
| `FRAME_LOCKED_POINTER` | Windows (UA hoặc GPU Direct3D) + Chromium, HTTPS, ≥ 25 `pointermove`, màn ≤ 83 Hz, mẫu gộp 0,95–1,05 và ≤ 2% sự kiện có hơn 1 mẫu |
| `UNALIGNED_POINTER` | Chromium, khoảng cách `pointermove` trung vị ≤ 0,4 × khung hình đo được, mẫu gộp ≤ 1,5 |
| `SUBFRAME_POINTER_BURST` | ≥ 10 cặp `mousemove` cách nhau ≤ 1 ms ở vị trí mới, chiếm ≥ 10% |
| `CLOUD_SOFTWARE_GPU` | IP cloud + GPU giả lập bằng CPU (máy thuê để chạy bot) |
| `ENVIRONMENT_EVIDENCE` | Có nhóm headless/GPU/quyền, hoặc ≥ 2 nhóm bằng chứng môi trường |

Tín hiệu thời gian chỉ xét payload của collector (có `pointerStats`). Dữ liệu huấn luyện ghi
bằng công cụ khác nên số liệu train/val không đổi.

### 2. Collector 1.8.0

Đo khoảng cách khung hình bằng `requestAnimationFrame` (60 khung, một lần mỗi trang, bỏ
khoảng nghỉ khi tab ẩn) và gửi trong `pointerStats.frameMs`/`frames`. Không thu thêm dữ liệu cá nhân.

### 3. Gate phát hành

`desktop_risk_rule_gate`: 14 fixture trên cùng một quỹ đạo người (M4D, lấy mẫu lại 60 Hz,
`core_ml/fixtures/m4d_human_60hz.json`). 8 trường hợp người phải là HUMAN và không có mã
rủi ro: Windows 1,9 mẫu, Linux 1,02, Mac 1,0, màn 144 Hz, HTTP, Firefox, VPN, một nhóm
Client Hints. 6 trường hợp bot phải khác HUMAN và đúng mã. Các gate khác giữ nguyên như v20.

## Kiểm tra

Chạy trên API local (bundle `d7a3abe3`, collector 1.8.0), Chrome 156 trên Windows:

| Kịch bản | v20 | v21 |
|---|---|---|
| Patchright headless giả UA, thao tác giống người | HUMAN | **NGHI VẤN** (`FRAME_LOCKED_POINTER`) |
| Patchright có cửa sổ, thao tác giống người | HUMAN | **NGHI VẤN** (`FRAME_LOCKED_POINTER`) |
| Patchright phát lại quỹ đạo người thật | HUMAN | **NGHI VẤN** (`FRAME_LOCKED_POINTER`) |
| Né: bắn 8 lệnh CDP cùng lúc | (mới) | **NGHI VẤN** (`SUBFRAME_POINTER_BURST`) |
| Né: bắn mỗi 2 ms, không chờ | HUMAN | **NGHI VẤN** (`UNALIGNED_POINTER`) |
| Chrome thật, input hệ điều hành 125 Hz theo đường cong giống người | HUMAN | HUMAN (không mã rủi ro) |
| Puppeteer-stealth (2), Selenium-stealth | BOT | BOT |
| Chỉ cuộn, không di chuột (2) | chưa đủ dữ liệu | chưa đủ dữ liệu |

Các bộ e2e cũ không đổi: 12 stack không thao tác (10 bot: 9 BOT; Chrome và Edge thật: chưa
đủ dữ liệu), 8 kịch bản điền form (6 BOT, 2 NGHI VẤN), 9/9 bot điện thoại BOT.

Chạy lại luật trên 27 phiên máy tính của người thật đã lưu ở server: **0** phiên bị gắn mã.

### Kiểm tra người thật độc lập: Balabit

Trước đây mô hình chuột chỉ được đánh giá trên M4D, cùng nguồn với dữ liệu train. Balabit
Mouse Dynamics Challenge gồm 10 người, 1.676 phiên làm việc thật qua Remote Desktop, không
dùng khi train. Mỗi phiên được phát lại như bản export của collector tại 25 thời điểm,
giống bước đánh giá phát hành:

| Chỉ số | Kết quả |
|---|---|
| Cửa sổ HUMAN | 41.311 / 41.900 (98,6%) |
| Cửa sổ NGHI VẤN | 588 (1,4%) |
| Cửa sổ BOT | 1 (0,002%) |
| Phiên có kết luận cuối là BOT | 0 / 1.676 |
| Phiên có kết luận cuối là HUMAN | 1.657 / 1.676 (98,9%) |

Cửa sổ BOT duy nhất là 25 điểm đầu của một phiên, ghi ở khoảng 9 Hz (109 ms giữa hai điểm):
Remote Desktop gửi chậm. Trình duyệt thật báo khoảng 60 Hz, nên đây là nhiễu của công cụ
ghi. BiLSTM trung vị 0,003, p90 0,15.

## Giới hạn

- Mới có 3 phiên Windows HTTPS có số mẫu gộp. Người dùng Remote Desktop, máy ảo, hoặc chuột
  và touchpad báo ≤ 60 Hz sẽ thành NGHI VẤN. Cần theo dõi `desktop_risk` trên dashboard khi
  có thêm traffic.
- Bot chạy trên màn ≥ 120 Hz, hoặc trên macOS/Linux mà không bơm dồn, không bị
  `FRAME_LOCKED_POINTER` bắt.
- Bot dùng input mức hệ điều hành (pyautogui, thiết bị phần cứng giả chuột) trên máy thật
  không để lại dấu vết nào ở phía trình duyệt. Cần tín hiệu phía server: tần suất phiên theo
  fingerprint/IP, uy tín IP, thử thách.
- Một trang sau có kết luận HUMAN vẫn ghi đè NGHI VẤN của trang trước trong cùng phiên.

## Tái hiện

```powershell
python -m core_ml.train --dataset-root "../Tuần 3/repos/web_bot_detection_dataset" --weights-dir bot-lab/release-v21/weights --device cpu
python -m pytest -q
cd collector; npm test
```
