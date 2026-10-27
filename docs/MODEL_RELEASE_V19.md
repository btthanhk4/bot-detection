# Model release v19 — phát hiện gian lận trên điện thoại (iPhone và Android)

Bundle: `28430e3fc35b4218903b61073c36e55f`. Policy: `19`. Collector: 1.7.1. Tham số mô hình chuột không đổi.

## Vấn đề sau v18

Thử 9 kịch bản bot điện thoại trên trình duyệt thật (2026-10-27):

| Kịch bản | v18 | v19 |
|---|---|---|
| Playwright WebKit giả iPhone 13 / iPad, Chromium giả Pixel 7 (mặc định) | BOT (`webdriver`) | BOT |
| WebKit iPhone **stealth** (sửa `platform`, `webdriver`, `maxTouchPoints`) | chưa đủ dữ liệu | **BOT** |
| Chromium Pixel stealth, chạm Playwright | chưa đủ dữ liệu | **BOT** |
| Chromium Pixel stealth, chạm CDP giống người (bán kính, lực, thời gian giữ ngẫu nhiên) | chưa đủ dữ liệu | **BOT** |
| Chromium Pixel không cờ webdriver, chạm CDP giống người | BOT | BOT |
| Autoclick (WebKit, Chromium) | BOT (`webdriver`) | BOT |

Phiên thật của iPhone (iOS 18, GSA) và Android giá rẻ (Adreno 610) trên site: HUMAN ở cả hai.

## Thay đổi

### 1. Giả lập điện thoại: thêm bằng chứng (`mobile_emulation_v1`)

Vẫn cần một mâu thuẫn hệ điều hành và ít nhất một mâu thuẫn phần cứng.

| Bằng chứng mới | Lý do |
|---|---|
| `spoofed_platform`: Worker báo hệ điều hành khác trang | Script stealth sửa `navigator` của trang, không sửa được Worker riêng |
| `desktop_gpu` mở rộng: GeForce, Quadro, Radeon, Intel HD/UHD/Iris, PCIe/SSE2 | Điện thoại không có GPU máy tính (GPU AMD của Samsung báo "Xclipse") |
| `server_cpu`: hơn 16 lõi | Điện thoại tối đa ~10 lõi; crawler giả Android trên site báo 49 |
| `ios_touch_without_contact`: iOS 18+/Safari 18+ mà mọi điểm chạm không có bán kính | WebKit của Playwright không báo bán kính; iPhone thật báo 24,3/36,4/48,6 |

### 2. Autoclick: `autoclick_taps_v1` (BOT)

≥ 5 lần chạm trong 0,5 px quanh một điểm với khoảng cách thời gian có CV < 0,10.

Đo trên BrainRun (2.073 thiết bị, 307.542 cửa sổ 20 cử chỉ): chỉ 5 thiết bị từng khớp
các dấu hiệu lặp lại. Ba trong số đó là máy chạy tự động có sẵn trong dataset (137.000 và
88.000 cử chỉ, thời gian chạm trung vị 1 ms, một điểm bị chạm 7.607 lần; một máy phát lại
cùng cú vuốt ngang đúng 117 ms). Trên 2.070 thiết bị người còn lại (283.742 cửa sổ):

| Luật | Cửa sổ người khớp | Cửa sổ máy khớp |
|---|---|---|
| ≥ 5 chạm cùng điểm + CV < 0,10 | **0** | 529 |
| ≥ 5 chạm cùng điểm (không xét nhịp) | 154 (4 thiết bị) | 6.182 |
| ≥ 3 vuốt giống hệt (≥ 5 điểm, ≥ 30 px, thời lượng ±3 ms) | 6 (1 thiết bị) | 439 |

Touchalytics (37 người, 377 lần chạm): chưa từng 2 lần chạm cùng một điểm.

### 3. NGHI VẤN có kết luận: `mobile_risk_v1`

Điện thoại đã có ≥ 3 thao tác (đủ để đánh giá) mà có bằng chứng bất lợi thì là **NGHI VẤN
(FINAL)** thay vì "chưa đủ dữ liệu": cờ cảm ứng (CDP, chạm 0 ms, vuốt thẳng tắp, **vuốt
phát lại**), trình giả lập (GPU phần mềm hoặc GPU máy tính như LDPlayer/BlueStacks), mâu
thuẫn thiết bị, CPU máy chủ, IP cloud, môi trường bất thường, cờ tự động hóa. Không khóa:
dữ liệu sau có thể đổi kết luận. Dưới 3 thao tác vẫn là "chưa đủ dữ liệu".

### 4. Collector 1.7.1

Sau mỗi lần chạm, điện thoại phát sự kiện chuột giả (mousemove/mousedown/mouseup/click)
tại vị trí chạm. Bản cũ đếm chúng là chuột: phiên có chạm thì có vài "điểm chuột", phiên
chỉ vuốt thì không có, và thời gian nhấn 0 ms của chúng có thể lọt vào luật click giả lập.
Bản mới bỏ qua (dùng `sourceCapabilities.firesTouchEvents` hoặc trong 800 ms sau sự kiện
chạm); click vẫn được tính là thao tác chạm.

## Đã cân nhắc và không làm

| Hướng | Lý do |
|---|---|
| Tăng ngưỡng "chạm 0 ms" lên 5 ms | Touchalytics có lần chạm thật 3 ms |
| `SYNTHETIC_CONTACT` (chữ ký CDP) thành BOT | Mới đo được một máy Android thật; giữ ở mức NGHI VẤN |
| Bắt `adb input` / HID qua giá trị tiếp xúc | Giống hệt điện thoại giá rẻ thiếu cảm biến (xem v18) |
| Cảm biến chuyển động | iOS phải xin quyền; Android cần thông báo thu thập dữ liệu trước |

## Kiểm tra

Gate `mobile_rule_gate`: 22 fixture (7 HUMAN, 10 SUSPECT, 5 BOT) gồm dữ liệu chạm thật
của iPhone và Android trên site, các bot stealth đã đo, autoclick, vuốt phát lại, trình
giả lập, CPU máy chủ. Gate của policy 18 được đóng băng (`MOBILE_HUMAN_RULE_GATE_V18`) để
vẫn rollback được.

## Tái hiện

```powershell
python -m core_ml.train --dataset-root "../Tuần 3/repos/web_bot_detection_dataset" --weights-dir bot-lab/release-v19/weights --device cpu
python -m pytest -q
```
