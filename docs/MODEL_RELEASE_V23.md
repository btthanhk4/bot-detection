# Model release v23 — vá các cách né luật input của policy 21

Bundle: `083037f597dd419b8af1627e72e477af`. Policy: `23`. Collector: 1.9.0. Mô hình chuột train lại cùng dữ liệu và seed: số liệu val/test giống hệt v22.

Xuất phát từ [rà soát điểm yếu](WEAKNESS_AUDIT_2026-10-28.md).

## Vấn đề

Kẻ tấn công biết luật policy 21 có thể:

| Cách né | Kết quả v22 |
|---|---|
| Sửa `getCoalescedEvents` để trả về chính sự kiện hai lần (3 dòng init script) | HUMAN |
| Xóa `getCoalescedEvents` | HUMAN |
| Di chuột thưa, mỗi bước trên 100 ms (luật khóa khung hình cần khoảng cách giữa các sự kiện) | không bị luật bắt |
| Gửi payload "người thật" bằng script, không qua trình duyệt | HUMAN |

## Thay đổi

### Collector 1.9.0

- Chỉ đếm mẫu gộp là sự kiện trusted và mới hơn mẫu trước. Mẫu chính là sự kiện gốc được đếm vào
  `coalescedSelf`; mẫu cũ hoặc không trusted vào `coalescedStale`. Đo bằng input hệ điều hành:
  mẫu thật không bao giờ là sự kiện gốc, và khoảng 1% trùng mốc thời gian.
- `pointerrawupdate` được bỏ trùng theo thời gian sự kiện.
- `signals.inputApiPatched`: `getCoalescedEvents` hoặc `requestAnimationFrame` không còn là hàm gốc.
- Khung hình báo ở phân vị 25% của 60 khung, để khung kéo dài lúc tải trang không làm sai.

### `desktop_risk_v1`

| Mã mới | Điều kiện |
|---|---|
| `POINTER_API_TAMPERED` | Chromium HTTPS, ≥ 25 `pointermove`, và có mẫu là chính sự kiện, hoặc trung bình < 0,5 mẫu (API bị xóa), hoặc API thời gian không phải hàm gốc |
| `NON_BROWSER_REQUEST` | Request telemetry của Chromium thiếu `Accept-Language`, hoặc thiếu `Sec-Fetch-*` qua HTTPS |

`FRAME_LOCKED_POINTER` dùng khoảng khung hình đo được khi có, không còn cần khoảng cách giữa các
sự kiện chuột. Ngưỡng nới từ ≤ 1,05 mẫu và ≤ 2% sự kiện nhiều mẫu lên ≤ 1,10 và ≤ 6%: một lượt
chạy bot di chuột thưa đo được 1,051 và 4,8%, do luồng chính bị nghẽn làm hai lệnh CDP dồn lại.
Người thật trên Windows: 1,73–2,52 và 72–91%.

### Gate

`desktop_risk_rule_gate`: 23 fixture (v21–22: 14). Thêm 3 ca người: MacBook M4 trên site thật
(3,56 mẫu, 30 khung/giây), Cốc Cốc, và request HTTPS đủ header. Thêm 6 ca bot: API sửa, API xóa,
API không phải hàm gốc, di chuột thưa, thiếu `Accept-Language`, thiếu `Sec-Fetch`. Gate v21–22
được đóng băng.

## Kiểm tra

API local, bundle `083037f5`, Chrome 156 trên Windows:

| Kịch bản | v22 | v23 |
|---|---|---|
| Playwright sửa `getCoalescedEvents`, chuột giống người | HUMAN | NGHI VẤN (`POINTER_API_TAMPERED`) |
| Playwright xóa `getCoalescedEvents` | HUMAN | NGHI VẤN (`POINTER_API_TAMPERED`) |
| Patchright di chuột thưa (3 lượt) | không bị luật input bắt | NGHI VẤN (`FRAME_LOCKED_POINTER`) |
| Payload giả gửi bằng Python | HUMAN | NGHI VẤN (`NON_BROWSER_REQUEST`) |
| 5 biến thể patchright của v21 | NGHI VẤN | NGHI VẤN |
| Chrome thật, input hệ điều hành (3 lượt) | HUMAN | HUMAN, 1,76–1,80 mẫu, không mã |
| Cốc Cốc thật, input hệ điều hành (3 lượt) | HUMAN | HUMAN, 1,80–2,52 mẫu, không mã |
| Puppeteer-stealth (2), Selenium-stealth | BOT | BOT |

Các bộ e2e cũ không đổi: 12 stack không thao tác (10 bot: 9 BOT), 8 kịch bản điền form (6 BOT,
2 NGHI VẤN), 9/9 bot điện thoại BOT.

## Giới hạn

Xem mục 3 của [rà soát điểm yếu](WEAKNESS_AUDIT_2026-10-28.md). Quan trọng nhất: collector chạy
trong trang, nên kẻ tấn công viết lại được payload hoặc tự thêm header. Bản vá này chỉ loại các
cách rẻ nhất.
