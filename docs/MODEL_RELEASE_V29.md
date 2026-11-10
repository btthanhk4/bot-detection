# Model release v29: chạm 0 ms là một mâu thuẫn nữa

Bundle: `73987d40bbf84730a2ccafe990e0dcb4`. Policy: `29`. Collector: 1.11.1 (không đổi). Mô hình chuột train lại cùng dữ liệu và seed.

## 1. Kiểm chứng trên điện thoại thật (2026-11-10)

Đo thời gian từ lúc ngón tay chạm xuống đến lúc nhấc lên của mỗi lần chạm.

| Nguồn | Số lần chạm | Ngắn nhất | Trung vị | Dưới 1 ms |
|---|---|---|---|---|
| iPhone (iOS 18.7) của người dùng, chạm nhanh nhất có thể, chỉ chạm | 20 lần phân tích; 6 lần đo chính xác | 47 ms | 62 ms | 0/20 |
| Hai iPhone khác trên shop | 5 | | | 0/5 |
| Bot WebView trên trang đích (40 phiên, giả Android TV và điện thoại) | 237 | 0 ms | 0 ms (p90: 1 ms) | 145 (14–20/20 mỗi phiên) |
| Playwright giả iPhone | 8 | | | 8/8 |

Ngón tay thật luôn nằm trên mặt kính vài chục mili giây. Bot gửi sự kiện chạm xuống và nhấc lên
cùng một thời điểm.

## 2. Thay đổi

`ZERO_TIME_TAPS` (ít nhất 2 lần chạm có thời gian dưới 1 ms) nay được tính là một mâu thuẫn độc
lập trong `forged_browser_v1`. Phiên có cờ này cộng thêm một mâu thuẫn khác thì kết luận BOT. Mâu
thuẫn khác thường là `navigator.webdriver` bị sửa.

- **Khi đứng một mình, cờ này vẫn chỉ chặn kết luận HUMAN (NGHI VẤN `mobile_risk`).** Trình đọc
  màn hình (TalkBack) có thể tạo ra những lần chạm tức thời, nên một người dùng khiếm thị không
  bị kết luận BOT chỉ vì cờ này.
- Một lần chạm 0 ms duy nhất không bật cờ.

## 3. Ước tính

Lần rà dữ liệu trước (policy 28) đếm được khoảng 709 phiên trên trang đích có cả chạm 0 ms và
`navigator.webdriver` bị sửa: 503 phiên giả Android TV, 191 phiên điện thoại, 15 phiên còn lại.
Theo policy 29, các phiên này thành BOT.

## 4. Giới hạn

- Chưa có điện thoại Android thật trong phép đo. Lập luận vật lý áp dụng cho mọi màn hình cảm ứng,
  nhưng chưa đo trực tiếp trên Android.
- Các phiên điện thoại hoặc TV chỉ có `navigator.webdriver` bị sửa mà không chạm, hoặc chạm bình
  thường, vẫn là NGHI VẤN.

## Kiểm tra

- Gate `client_forgery`: 21 fixture. Thêm 3 fixture:
  - BOT: chạm 0 ms cộng webdriver bị sửa.
  - NGHI VẤN: chạm 0 ms đứng một mình, giống trường hợp TalkBack.
  - NGHI VẤN: một lần chạm 0 ms cộng webdriver bị sửa.

  Gate của policy 28 được đóng băng (`CLIENT_FORGERY_RULE_GATE_V28`). Các gate khác không đổi.
- Mô hình chuột: hai file trọng số giống v28 từng byte; test, rolling test và rolling validation
  không đổi.
- Bộ test Python, test collector và Ruff đạt.
