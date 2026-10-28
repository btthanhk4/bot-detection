# Model release v24 — đóng các lỗ "fail-open" bằng gateway của shop

Bundle: `137c74b45c834a9db7cf1ef4a37cf5fd`. Policy: `24`. Collector: 1.10.0. Mô hình chuột train lại cùng dữ liệu và seed: số liệu val/test giống hệt v23.

Xuất phát từ mục 3 của [rà soát điểm yếu](WEAKNESS_AUDIT_2026-10-28.md): phát hiện ở phía
trình duyệt thì bot không chạy collector (hoặc tự dựng telemetry) sẽ không bị thấy, và SilkMoon
không dùng kết quả để chặn gì.

## 1. Gateway SilkMoon (nginx) — `deploy/silkmoon-gateway/`

| Cơ chế | Chi tiết |
|---|---|
| Ghi nhận lượt tải trang | `mirror` mọi request HTML tới `/api/v1/pageview` (kèm IP, User-Agent, đường dẫn); trả cookie HttpOnly `__dc_pv` = id của request đó. File tĩnh không có cookie, không được ghi |
| Chặn request ghi | `auth_request` tới `/api/v1/gate` cho: đăng nhập, đăng ký, xác minh và gửi lại OTP, quên/đặt lại mật khẩu, đặt hàng, đánh giá, bình luận blog, newsletter, kiểm tra mã giảm giá, chat AI, AR. Không chặn webhook PayOS và các API admin (đã có JWT) |
| Fail-open | Gate lỗi, quá 2 giây, hoặc API chưa bật gateway (404): cho qua |
| Collector | `/_dc/c.js`, `/_dc/t`; thẻ `data-datacat-embed` tự khởi động, không có biến toàn cục |
| Admin | Cổng 5175 qua TLS (trước đây HTTP thường); HTTP trên 5175 chuyển sang HTTPS |

Hai endpoint nội bộ đòi header `X-Datacat-Gateway` (bí mật chung, chỉ có trên server) và trả 404
trên `api.` và tên miền gốc.

## 2. Quyết định của gate

| Lý do từ chối | Điều kiện |
|---|---|
| `no_page_view` | Không có cookie, hoặc cookie không phải trang gateway đã phục vụ (gọi thẳng API) |
| `ua_mismatch` | User-Agent của request khác User-Agent đã tải trang |
| `no_collector` | Trang chưa từng chạy collector: collector 1.10 chào API ngay khi tải, trước khi người dùng kịp bấm |
| `no_telemetry` | Đã chào nhưng sau 60 giây vẫn chưa có telemetry được chấm |
| `bot` | Phiên của trang là BOT |
| `forged` | Phiên có `NON_BROWSER_REQUEST`, `UNVERIFIED_PAGE_LOAD` hoặc `POINTER_API_TAMPERED` |
| `risk` | Chỉ chat AI và AR: NGHI VẤN có bằng chứng (`desktop_risk`, `mobile_risk`) |

## 3. Thay đổi mô hình và luật

| Thay đổi | Lý do |
|---|---|
| Nhóm bằng chứng `CDP` (`signals.cdpRuntime`) | Đo qua HTTPS thật: Puppeteer-stealth mất mâu thuẫn quyền thông báo, chỉ còn GPU + CONTEXT nên chỉ NGHI VẤN; CDP Runtime là nhóm thứ ba nên thành BOT. Patchright và trình duyệt thật: false |
| `CDP_ATTACHED` | CDP một mình (hoặc DevTools đang mở) chỉ chặn HUMAN |
| `UNVERIFIED_PAGE_LOAD` | Telemetry từ shop mà không kèm trang gateway đã phục vụ, trang do User-Agent khác tải, hoặc một cookie được ≥ 10 phiên dùng |
| `DEVICE_VELOCITY` | Cùng fingerprint thiết bị trên cùng IP mở ≥ 30 phiên trong 1 giờ (farm xóa dữ liệu giữa các lượt). API chỉ đếm cho máy tính: điện thoại cùng đời có fingerprint giống nhau và nhà mạng dùng chung IP (CGNAT), nên nhiều người sẽ trông như một thiết bị |
| BOT từ mô hình chuột khóa sau 2 lần | Một cửa sổ lạ (Balabit: 1/1.676 người, ghi qua RDP 9 Hz) không còn khóa cả phiên; luật dấu vết vẫn khóa ngay |
| `/detect` ẩn danh không trả kết luận | Bot không dùng được endpoint để dò cách né; backend của site đọc kết luận bằng token |
| Phiên "không telemetry" | Lượt tải trang không chạy collector sau 2 phút: BOT nếu là crawler tự khai hoặc công cụ HTTP (curl, python, Go…), NGHI VẤN nếu UA trình duyệt |

Gate phát hành: `desktop_risk_rule_gate` 29 fixture (thêm 6), `mobile_rule_gate` 25 (thêm 3),
`automation_evidence_rule_gate` 31 (thêm 2). Gate của policy 19–23 được đóng băng.

## Kiểm tra

**Cấu hình nginx** (nginx 1.31.8 như production, upstream giả, Docker): 42/42 kiểm tra đạt.
Gồm: cookie chỉ gắn cho tài liệu HTML; mirror mang đúng id của cookie và bí mật; file tĩnh không
được ghi; 9 nhóm endpoint bị chặn khi gate từ chối, kèm JSON tiếng Việt cho SPA; webhook PayOS
và API admin không bị chặn; lỗi 403 của backend giữ nguyên. Gate lỗi, quá chậm, không cấu hình
(404) hoặc API sập: vẫn cho qua, tối đa 2 giây. Cổng 5175 chỉ chạy TLS; HTTP chuyển sang HTTPS.

**Trọn luồng** (nginx + API thật + MongoDB + bundle `137c74b4`, Chrome 156):

| Kịch bản | Kết luận | Request đăng nhập |
|---|---|---|
| Gọi thẳng API đăng nhập (dò mật khẩu) | — | chặn (`no_page_view`) |
| Tải HTML bằng `curl` rồi đăng nhập ngay | — | chặn (`no_collector`) |
| Cookie bịa | — | chặn |
| Giả mạo trọn giao thức: tải trang, hello, telemetry giả có quỹ đạo người | NGHI VẤN (`NON_BROWSER_REQUEST`, `UNVERIFIED_PAGE_LOAD`) | chặn (`forged`) |
| Người thật, Chrome, input hệ điều hành | HUMAN | cho qua |
| Patchright giống người | NGHI VẤN (`FRAME_LOCKED_POINTER`) | cho qua (không phải endpoint nghiêm) |
| Puppeteer-stealth | BOT (GPU + CONTEXT + CDP) | chặn (`bot`) |
| Playwright, Selenium | BOT (dấu vết tự động hóa) | chặn (`bot`) |
| Trang tải bằng `curl`, không chạy collector | BOT (`non_browser_client`) sau 2 phút | — |

Người thật mở DevTools: NGHI VẤN (`FRAME_LOCKED_POINTER` vì DevTools giao từng sự kiện chuột như
CDP, thêm `CDP_ATTACHED`), vẫn đăng nhập được.

Các bộ e2e cũ không đổi: mô phỏng thực tế (15 kịch bản), điền form (6 BOT, 2 NGHI VẤN), 9/9 bot
điện thoại BOT. 849 test Python và test collector đạt.

## Giới hạn

- Kẻ tấn công làm đủ giao thức (tải trang bằng đúng User-Agent, giữ cookie, gửi hello, dựng
  telemetry có header trình duyệt và dữ liệu chuột giống người) vẫn có thể được HUMAN. Cần collector
  được làm rối và có chữ ký payload, hoặc thử thách (CAPTCHA, proof-of-work).
- Người dùng chặn `/_dc/c.js` (hiếm, nhờ đường dẫn trung tính) không đăng nhập hay đặt hàng được;
  thông báo yêu cầu tải lại trang.
- Bot CDP giống người như patchright vẫn chỉ NGHI VẤN và đi qua các endpoint thường; chỉ chat AI
  và AR chặn NGHI VẤN có bằng chứng. Ngưỡng này cấu hình bằng `BOT_GATE_STRICT_PATHS`.
- `DEVICE_VELOCITY` chưa có dữ liệu thật để hiệu chỉnh; ngưỡng 30 phiên/giờ được chọn thận trọng.
