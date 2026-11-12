# Model release v32: platform bị giả, và rà soát traffic Downloader + Spin

Bundle: `9981e7bf8d844034a548fdba1d791c7c`. Policy: `32`. Collector: 1.12.0 (không đổi). Mô hình chuột train lại cùng dữ liệu và seed.

## 1. Rà soát (2026-11-12)

Phạm vi: các phiên tạo từ lúc đăng ký trang Spin (`therewrds.com/global_rewards`, 23:20 ngày 11/11
giờ Việt Nam). Tất cả được chấm bằng policy 31.

| Trang | Phiên | Quốc gia | BOT | NGHI VẤN | Chưa đủ dữ liệu | HUMAN |
|---|---|---|---|---|---|---|
| Downloader | 1.004 | Mỹ 97% | 848 | 11 | 126 | 19 |
| Spin | 1.819 | Brazil, Bangladesh, Indonesia, Pakistan, Mexico; gần như toàn điện thoại | 592 | 34 | 1.041 | 152 |

### Downloader

- **BOT:** các trại bot đã biết:
  - Linux 640 nhân dùng SwiftShader;
  - WebView mang tên TV, giấu cờ webdriver (115 phiên bị luật của policy 30 bắt);
  - Mac "Safari 9.1.2".
- **HUMAN (19):** máy tính ở Mỹ, phần lớn dùng mạng gia đình. Mỗi phiên có 38–100 lần di chuột, cả
  hai mô hình chấm là người, không có mâu thuẫn môi trường nào.
- **NGHI VẤN (11):**
  - "Firefox 129" có `deviceMemory`;
  - Chrome Android giấu cờ webdriver nhưng chỉ có 0–1 lần chạm 0 ms;
  - máy tính có API đo chuột bị sửa.
- **Chưa đủ dữ liệu (126):** phiên có ít thao tác.

### Spin

- **BOT:** 553/592 phiên thuộc một trại bot ở Brazil:
  - Chrome Android 133–139 và WebView chạy trên máy đời cũ (Mali-T8xx, Adreno 308);
  - cờ webdriver bị xóa rồi sửa, request thiếu header Sec-Fetch;
  - mỗi phiên chạm 10–20 lần, nhiều lần 0 ms.
- **HUMAN (152):** điện thoại sạch, có ít nhất 3 lần chạm tự nhiên, ở Bangladesh, Pakistan và
  Indonesia; trình duyệt Chrome, WebView của Facebook, Safari.
- **Chưa đủ dữ liệu (1.041):**
  - 907 phiên là điện thoại sạch, chạm 0–2 lần rồi rời trang, đúng định nghĩa "chưa đủ dữ liệu";
  - 125 phiên thuộc nhóm thiết bị giả ở mục 2.
- **NGHI VẤN (34):** 23 phiên thuộc nhóm thiết bị giả; phần còn lại có cờ webdriver bị giấu hoặc có
  thao tác chạm phát lại.

## 2. Nhóm thiết bị giả: worker và trang khai khác nhau

Có 169 phiên trên Spin, 131 phiên ở Indonesia. Worker riêng của trình duyệt báo `navigator.platform`
và GPU khác với trang.

| | Nhóm này | Phiên thật cùng loại |
|---|---|---|
| Chrome Android 14x–15x: platform của trang | `Linux armv8l` (39/39) | `Linux armv81`, giá trị cố định của Chrome (61/61) |
| "iPhone": tỉ lệ điểm ảnh | 2,727; 1,875; 2,857 (kích thước màn hình Android) | 2 hoặc 3 (390×844, 414×896…) |
| "iPhone": số nhân CPU | 6, worker báo số khác | 4, đúng giá trị Safari luôn báo |
| "Firefox" | `deviceMemory` 8, GPU dạng ANGLE | Không có `deviceMemory`, GPU dạng "…, or similar" |

Đây là công cụ giả thiết bị. Nó sửa được `navigator` của trang nhưng không sửa được của worker.
Trên toàn production, không phiên HUMAN nào (0/238) có platform của worker khác trang, còn cả 241
phiên mang dấu hiệu này đều là thiết bị giả.

## 3. Thay đổi: `PLATFORM_SPOOFED`

**Điều kiện:** worker báo `navigator.platform` khác trang. Collector đã bỏ qua trường hợp iPadOS
Safari tự khai là Mac.

**Cách tính:** mã này là thêm một mâu thuẫn để đủ hai mâu thuẫn của `forged_browser_v1`.
- Có thêm GPU bị sửa (worker báo WebGL renderer khác trang, thuộc nhóm neo GPU) thì kết luận BOT,
  dù phiên có thao tác chạm hay không.
- Đứng một mình, nó chỉ chặn kết luận HUMAN.

## 4. Ước tính trên production, nếu chấm lại

| Thay đổi | Số phiên |
|---|---|
| Chưa đủ dữ liệu → BOT | 123 |
| NGHI VẤN → BOT | 23 |

Policy mới chỉ áp dụng cho dữ liệu gửi đến sau khi triển khai.

## 5. Giới hạn

- **Nhóm "chưa đủ dữ liệu" sạch của Spin (907 phiên):** người dùng điện thoại chạm dưới 3 lần
  trước khi rời trang. Từ 1–2 lần chạm, hệ thống không đủ căn cứ để kết luận là người.
- **Platform bị giả nhưng GPU không bị sửa:** chỉ ở mức NGHI VẤN.

## Kiểm tra

- **Gate `client_forgery`:** 43 fixture, trong đó 5 fixture mới:
  - BOT: Chrome Android giả và "iPhone" giả, cả hai có worker lệch platform và GPU.
  - NGHI VẤN: platform giả đứng một mình, có và không có thao tác chạm.
  - Chưa đủ dữ liệu: Chrome thật (`Linux armv81`) không có thao tác.

  Gate của policy 31 được đóng băng (`CLIENT_FORGERY_RULE_GATE_V31`). Các gate khác không đổi.
- **Mô hình chuột:** hai file trọng số giống v31 từng byte; test, rolling test và rolling validation
  không đổi.
- **Test:** bộ test Python, test collector và Ruff đạt.
