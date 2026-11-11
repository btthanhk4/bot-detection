# Model release v31: Safari/Firefox có API chỉ Chromium có, và rà soát toàn bộ phiên

Bundle: `c3f62b64dec64c878b98769a01068367`. Policy: `31`. Collector: 1.11.1 (không đổi). Mô hình chuột train lại cùng dữ liệu và seed.

## 1. Rà soát toàn bộ phiên (2026-11-11)

Trên production có 5.267 phiên, tích lũy từ lần xóa lúc 23:39 ngày 10/11 (giờ Việt Nam):

| Trang | BOT | NGHI VẤN | Chưa đủ dữ liệu | HUMAN |
|---|---|---|---|---|
| Downloader | 4.083 | 647 | 466 | 51 |
| silkmoon | 5 | 0 | 0 | 5 |

### Phiên BOT

- Không phiên nào có thao tác giống người. Không có chạm tự nhiên, cũng không có quỹ đạo chuột mà
  mô hình chấm là người.
- 5 phiên BOT trên silkmoon:
  - Googlebot thật, IP nằm trong dải địa chỉ Google công bố.
  - Máy chủ Facebook mở link để tạo ảnh xem trước: headless, cửa sổ kích thước 0.

### Phiên HUMAN

Có 56 phiên HUMAN:

- 5 phiên là người dùng tự thử trên silkmoon: Android Chrome, Android trong Messenger và các
  iPhone. Kết luận đúng.
- Phần lớn các phiên còn lại trên Downloader là máy tính dùng mạng gia đình ở Mỹ, có 25–100 lần
  di chuột, được cả hai mô hình chấm là người.
- Hai phiên khai Firefox 129 nhưng có `navigator.deviceMemory`. Policy 31 chuyển chúng sang NGHI VẤN.

### Phiên NGHI VẤN

| Nhóm | Số phiên | Nguyên nhân | Xử lý |
|---|---|---|---|
| Mac "Safari 9.1.2" trên macOS 10.9–15, không thao tác | 334 | Chỉ có cờ webdriver bị giấu | Policy 31 → BOT |
| WebView Android giấu webdriver | 250 | Được chấm trước khi policy 30 triển khai | Policy 30 đã bắt phiên mới |
| iPad, chạm bán kính 1 và lực 1 | 25 | 21 phiên được chấm theo policy 29; 2 phiên khai Safari 17 (dưới ngưỡng WebKit 18); 2 phiên khai Safari 16 | Giữ nguyên |
| Máy tính có chuột giống người nhưng môi trường bất thường | khoảng 30 | `FRAME_LOCKED_POINTER`, `POINTER_API_TAMPERED`, môi trường bất thường | Giữ nguyên |

Mục "2 phiên khai Safari 17" có kết luận đúng như thiết kế. Phiên bản WebKit cũ chưa đo được cách
báo diện tích chạm, nên luật không xét.

### Lỗi ở luồng nhận dữ liệu

Không có lỗi 5xx. Gateway ghi khoảng 21.000 lần trình duyệt bị từ chối khi xin phép gửi dữ liệu
(yêu cầu `OPTIONS /api/v1/telemetry` trả về 400) và 2.600 lần gửi dữ liệu bị chặn (`POST` trả về
403). Tất cả đến từ Chrome, Samsung Internet và Opera thật trên Android.

API ghi lại hai trang gửi dữ liệu mà không được đăng ký: `befitfashion.com/click` và một trang có
Origin `null` cùng đường dẫn `/click`. `befitfashion.com/click?key=…&cost=…&pub=…&campaign_id=…` là
trang chuyển hướng của một mạng quảng cáo đang gắn mã theo dõi. Trang này không có trong danh sách
"Trang theo dõi", nên dữ liệu bị từ chối đúng như thiết kế (policy từ 2026-11-08: chỉ nhận dữ liệu
từ trang đã đăng ký). Nếu cần theo dõi trang này, hãy đăng ký nó trong mục Trang theo dõi.

## 2. Thay đổi: `UA_API_MISMATCH`

User agent tự khai là Safari trên máy tính hoặc Firefox, nhưng trang lại báo `navigator.deviceMemory`.
Chỉ Chromium có API này; WebKit và Gecko chưa từng có.

| Nhóm phiên trên production | Có `deviceMemory` |
|---|---|
| Người dùng tự khai Safari/Firefox | 2/15 (cả hai cùng khai "Firefox 129") |
| BOT tự khai Safari/Firefox | 3.114/3.133 |
| NGHI VẤN tự khai Safari/Firefox | 344/369 |

Mã này là thêm một mâu thuẫn để đủ hai mâu thuẫn của `forged_browser_v1`. Có thêm cờ webdriver bị
giấu thì kết luận BOT. Đứng một mình, nó chỉ chặn kết luận HUMAN.

iOS không dùng mã này. iOS đã có kiểm tra riêng (`chromium_api_on_ios`, policy 17), và chế độ giả
lập thiết bị của DevTools vẫn được giữ ở mức chưa đủ dữ liệu.

## 3. Ước tính trên 5.267 phiên, nếu chấm lại

| Thay đổi | Số phiên |
|---|---|
| NGHI VẤN → BOT | 340 |
| HUMAN → NGHI VẤN (Firefox 129 có `deviceMemory`) | 2 |
| Chưa đủ dữ liệu → BOT | 1 |
| Chưa đủ dữ liệu → NGHI VẤN | 3 |

Policy mới chỉ áp dụng cho dữ liệu gửi đến sau khi triển khai. Phiên cũ giữ nguyên kết luận cũ.

## 4. Giới hạn

- **Tiện ích chống theo dõi trên Firefox:** một tiện ích có thể tự thêm `deviceMemory`. Trường hợp
  đó chỉ khiến phiên mất kết luận HUMAN, không thành BOT, trừ khi cờ webdriver cũng bị giấu.
- **Phiên đã chấm trước khi triển khai:** không tự được chấm lại, gồm 250 WebView, 21 iPad và 334 Mac.

## Kiểm tra

- **Gate `client_forgery`:** 38 fixture, trong đó 7 fixture mới:
  - BOT: Safari hoặc Firefox có `deviceMemory`, cộng cờ webdriver bị giấu.
  - NGHI VẤN:
    - `deviceMemory` đứng một mình, không có thao tác.
    - Firefox có `deviceMemory`, chuột giống người.
  - HUMAN: Firefox không có `deviceMemory`.
  - Chưa đủ dữ liệu: Safari 17 thật; Chrome trên Mac có `deviceMemory`.

  Gate của policy 30 được đóng băng (`CLIENT_FORGERY_RULE_GATE_V30`). Các gate khác không đổi.
- **Mô hình chuột:** hai file trọng số giống v30 từng byte; test, rolling test và rolling validation
  không đổi.
- **Test:** bộ test Python, test collector và Ruff đạt.
