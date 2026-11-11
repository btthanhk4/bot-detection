# Model release v30: WebView giấu cờ webdriver và chạm CDP trên iPhone/iPad

Bundle: `99cc2c839e0d4753a4142bf2e381c6ec`. Policy: `30`. Collector: 1.11.1 (không đổi). Mô hình chuột train lại cùng dữ liệu và seed.

## 1. Rà soát các phiên còn lại (2026-11-11)

Trang đích Downloader trên production, 225 phiên còn lưu, tất cả đến từ click quảng cáo:

| Kết luận | Số phiên |
|---|---|
| BOT | 172 |
| NGHI VẤN | 22 |
| Chưa đủ dữ liệu | 30 |
| HUMAN | 1 |

Các phiên NGHI VẤN và chưa đủ dữ liệu chia thành các nhóm sau:

| Nhóm | Nghi vấn | Chưa đủ | Bằng chứng | Policy 30 |
|---|---|---|---|---|
| WebView Android mang tên hộp TV và điện thoại (Chromecast, MiTV-MOOQ3, FlowBox-Z3) | 20 | 0 | `navigator.webdriver` bị xóa và sửa; request thiếu header Sec-Fetch; 15 phiên không chạm, 5 phiên chạm 1 lần | BOT |
| iPad, Safari 26–27 ở chế độ máy tính | 3 | 2 | Mọi điểm chạm có bán kính 1, lực 1 (`SYNTHETIC_CONTACT`), 2–19 lần chạm | BOT |
| Máy ảo Windows, AS29770 (The Internet Subway, Virginia) | 0 | 16 | Cùng một ảnh máy (WARP, 1024×768, cùng canvas hash, múi giờ Los Angeles); không thao tác | Giữ nguyên |
| Chromebook trường học, Windows, Firefox | 0 | 9 | Thoát sau 0–22 lần di chuột | Giữ nguyên |
| Môi trường bất thường nhưng không thao tác | 0 | 2 | SwiftShader hoặc `rtt` 0 | Giữ nguyên (policy 12) |
| Android TV để yên, không mâu thuẫn | 0 | 1 | Không có | Giữ nguyên |
| Windows Chrome 128, chuột giống người | 1 | 0 | API đo chuột bị sửa (`POINTER_API_TAMPERED`) | Giữ nguyên |

Phiên HUMAN duy nhất cũng thuộc nhóm máy ảo AS29770: 33 lần di chuột trong 9 phút, cả hai mô hình
đều chấm là người. Trong phiên không có bằng chứng nào chống lại kết luận này.

## 2. Thay đổi

### `webview_webdriver_v1`

**Điều kiện:**
- User agent là Android WebView (có `; wv)`).
- `navigator.webdriver` bị định nghĩa lại hoặc bị xóa (`WEBDRIVER_TAMPERED`).
- GPU không phải GPU máy tính.

**Kết luận:** BOT, kể cả khi phiên không có thao tác nào.

Trên máy tính, tiện ích mở rộng của trình duyệt có thể sửa cờ này. Vì thế, từ policy 26, cờ này
đứng một mình chỉ chặn kết luận HUMAN. WebView không chạy được tiện ích mở rộng. Do đó chỉ có trang
web hoặc ứng dụng chứa WebView sửa được cờ này. Trang đích không sửa cờ; nếu trang sửa thì mọi
khách đều mang cờ, kể cả người thật. Vậy ứng dụng đã giấu dấu hiệu tự động hóa của chính nó.

Trên trang đích có 59 WebView như vậy, cùng Chrome 156/157, cùng thiếu header Sec-Fetch. 39 phiên đã
là BOT từ policy 29 vì chạm 12–20 lần, lần nào cũng 0 ms. 20 phiên còn lại cùng nhóm thiết bị nhưng
rời trang trước khi chạm đủ hai lần.

Chrome trên Android vẫn giữ quy tắc cũ (NGHI VẤN), vì một số trình duyệt Android như Edge và Firefox
có chạy tiện ích mở rộng.

### `apple_synthetic_touch_v1`

**Điều kiện:**
- User agent là iPhone, iPad, hoặc iPadOS Safari ở chế độ máy tính. Chế độ máy tính nhận diện bằng
  user agent Macintosh không có Chrome hoặc Firefox, `platform` là `MacIntel`, và màn hình cảm ứng
  có hơn 1 điểm chạm.
- WebKit từ bản 18 trở lên.
- Có ít nhất 2 lần chạm.
- Mọi điểm chạm có bán kính đúng bằng 1 và lực đúng bằng 1, kể cả điểm nhả.

**Kết luận:** BOT.

Bán kính 1 và lực 1 là giá trị mặc định của `Input.dispatchTouchEvent` trong CDP của Chromium.
WebKit trên máy thật báo diện tích tiếp xúc của ngón tay. Các iPhone đã đo trên shop báo bán kính
24,3, 36,4 hoặc 48,6 px với lực 0. WebKit của Playwright không báo bán kính. Một trình duyệt tự nhận
là Safari mà gửi kiểu chạm này thực chất là Chromium được điều khiển qua CDP.

Luật này áp dụng cả khi WebGL không khả dụng; một iPad trên trang đích rơi vào trường hợp này. Trên
Android, `SYNTHETIC_CONTACT` vẫn chỉ chặn kết luận HUMAN, vì điện thoại giá rẻ không có cảm biến lực
và diện tích tiếp xúc (policy 19).

## 3. Ước tính trên 225 phiên

| Kết luận | Policy 29 | Policy 30 |
|---|---|---|
| BOT | 172 | 197 |
| NGHI VẤN | 22 | 1 |
| Chưa đủ dữ liệu | 30 | 28 |
| HUMAN | 1 | 1 |

Policy mới áp dụng cho dữ liệu gửi đến sau khi triển khai. Phiên cũ không được chấm lại, vì phần lớn
không còn dữ liệu thô để chấm.

## 4. Giới hạn

- **iPad thật:** chưa đo trực tiếp. Lập luận dựa trên iPhone thật, vì hai thiết bị cùng dùng WebKit.
  Để kiểm chứng, cần chạm thử trên shop bằng một iPad thật, cả bằng ngón tay và bằng Apple Pencil.
- **Ứng dụng đổi user agent:** luật WebView dựa vào token `; wv)`. Ứng dụng bỏ token này thì luật
  không áp dụng. Khi đó bot lọt qua, nhưng không có người thật nào bị bắt nhầm.
- **Máy ảo AS29770:** mỗi phiên riêng lẻ không chứa bằng chứng. Nhận ra được nhóm này cần đối chiếu
  nhiều phiên với nhau: cùng canvas hash, cùng dải IP, cùng màn hình. Policy này chưa làm việc đó, vì
  máy tính ở trường học hoặc công ty dùng chung một ảnh máy cũng giống hệt nhau. Các Chromebook của
  trường học trong bảng trên là một ví dụ.

## Kiểm tra

- **Gate `client_forgery`:** 31 fixture, trong đó 10 fixture mới:
  - BOT: WebView giấu webdriver, có hoặc không có thao tác chạm.
  - Không đổi:
    - WebView không giấu cờ (chưa đủ dữ liệu).
    - Chrome Android giấu cờ (NGHI VẤN).
    - User agent WebView nhưng GPU máy tính (NGHI VẤN).
  - BOT: chạm CDP trên iPad ở chế độ máy tính (có và không có WebGL) và trên iPhone iOS 18.
  - Không đổi:
    - iOS 16 (NGHI VẤN, WebKit cũ không được xét).
    - Chỉ 1 lần chạm (chưa đủ dữ liệu).

  Gate của policy 29 được đóng băng (`CLIENT_FORGERY_RULE_GATE_V29`). Các gate khác không đổi.
- **Mô hình chuột:** hai file trọng số giống v29 từng byte; test, rolling test và rolling validation
  không đổi.
- **Test:** bộ test Python, test collector và Ruff đạt.
