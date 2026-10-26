# Model release v15

Bundle: `31daa4ac4c5c40eeacdaacc68717010a`. Policy: `15`. Collector: **1.4.0**.
Ngưỡng và tham số mô hình chuột không đổi so với v10–v14.

## Mục tiêu

Patchright có giao diện (trình duyệt thật bị điều khiển, không lộ dấu vết môi trường) là
loại bot mà v10–v14 chưa bắt được trừ khi nó click mặc định. v15 tìm dấu vết ở **cách sự
kiện đầu vào được tạo ra**, độc lập với hình dạng quỹ đạo chuột.

## Thí nghiệm: công cụ tự động hóa để lộ gì? (2026-10-26, Edge/Chrome 155–156)

Trang probe đặt trên `127.0.0.1` (secure context); mỗi công cụ chạy cùng kịch bản: di
chuột, 3 lần nhấn, gõ bằng `keyboard.type` (mặc định và có `delay`), `fill`.

| Dấu vết | Playwright | Patchright | Puppeteer | Có dùng? |
|---|---|---|---|---|
| `pressure` khi nhấn chuột (chuẩn: 0,5) | 0,5 | 0,5 | **0** | Có (luật mới) |
| `width/height`, `movementX`, `pointerrawupdate` | như chuột thật | như chuột thật | như chuột thật | Không lộ |
| Coalesced events | 1 mẫu/sự kiện | 1 | 1 | Chỉ ghi nhận (chưa có chuẩn người) |
| Giữ phím, `type()` mặc định | 1,5–10 ms | 1,5–7 ms | 1,6–20 ms | Có (luật mới) |
| Nhịp phím, `type({delay})` | giữ ~92–106 ms, đều | 104,9–106,1 ms | 105–128 ms | Có (luật mới) |
| `fill()` | 1 sự kiện chèn 17 ký tự, không có phím | như Playwright | — | Chỉ ghi nhận |
| Getter `Error#name` khi `console.debug` (CDP `Runtime.enable`) | 2 lần/lệnh | **1** (giống thật) | 2 | Chỉ ghi nhận (DevTools mở cũng ra 2) |

## Chuẩn người thật

CMU Keystroke Dynamics Benchmark (Killourhy & Maxion, 2009): 51 người, 20.400 lượt gõ
mật khẩu `.tie5Roanl`, 224.400 lần nhấn phím. Đây là kiểu gõ đều nhất có thể (một chuỗi
lặp lại hàng trăm lần); văn bản tự do còn biến thiên hơn.

| Chỉ số (đúng cửa sổ luật dùng) | Người thật thấp nhất | Lượt dưới ngưỡng | Bot |
|---|---|---|---|
| Trung vị thời gian giữ, cửa sổ trượt 8 phím | 30,2 ms | 0 / 20.400 (< 20 ms) | 2,3–3,5 ms |
| CV khoảng cách giữa hai lần nhấn, 11 phím | 0,139 | 0 / 20.400 (< 0,10) | 0,005–0,073 |

## Luật mới

| Luật | Kết luận BOT khi |
|---|---|
| `synthetic_typing_v1` | Trong một cụm gõ (khoảng nghỉ ≤ 1,5 s): 8 phím liên tiếp có trung vị giữ < 20 ms, **hoặc** 11 phím liên tiếp có CV khoảng cách < 0,10 |
| `synthetic_pointer_v1` | Trình duyệt Chromium, ≥ 2 lần nhấn chuột báo `pressure = 0` khi đang giữ nút |

Loại trừ để tránh báo nhầm: bàn phím ảo (phím `Unidentified`/229), thiết bị có con trỏ
thô `(pointer: coarse)` (iOS/Android phát keydown/keyup cùng lúc), ô mật khẩu (không ghi).
Collector chỉ ghi **thời điểm** nhấn/nhả và loại phím (ký tự/khác), không ghi ký tự nào.

Thứ tự ưu tiên: HeadlessChrome → dấu vết framework / môi trường mâu thuẫn → nhấn chuột
giả lập → click giả lập → gõ phím giả lập. Gate mới: 11 fixture (3 BOT, 8 ca không được
kết luận BOT: gõ kiểu người, bàn phím ảo, màn hình cảm ứng, quá ít phím, 1 lần nhấn áp lực
0, Firefox, chỉ có chèn hàng loạt, dữ liệu sai định dạng).

## Kiểm chứng end-to-end

Collector 1.4.0 → API policy 15 trên máy cục bộ; mỗi công cụ điền một form tìm kiếm như
scraper thật rồi gọi `/detect`.

| Kịch bản | Policy 14 | Policy 15 | Bằng chứng |
|---|---|---|---|
| Patchright có giao diện, `keyboard.type` | SUSPECT | **BOT** `synthetic_typing_v1` | trung vị giữ phím 1,4 ms |
| Patchright có giao diện, `type({delay: 80})` | SUSPECT | **BOT** `synthetic_typing_v1` | CV khoảng cách 0,026 |
| Patchright có giao diện, `fill` | SUSPECT | SUSPECT | chỉ có `BULK_TEXT_INSERT` (ghi nhận) |
| Chrome thật mở cổng debug + `puppeteer.connect`, 3 click | SUSPECT | **BOT** `synthetic_pointer_v1` | 3 lần nhấn áp lực 0 |
| Playwright có giao diện, `type({delay})` | BOT (webdriver) | BOT (webdriver) | nhịp phím cũng bị đánh dấu |
| Puppeteer stealth, 3 click | BOT (môi trường) | BOT (môi trường) | 3 lần nhấn áp lực 0 |

Ma trận môi trường 12 kịch bản (Chrome/Edge thật, Playwright, Puppeteer, Selenium,
Patchright) cho kết quả giống hệt policy 14: Chrome/Edge thật không bị gán BOT.
Tổng: 664 test Python, test collector và Ruff đều qua.

## Giới hạn

- Bot gõ với độ trễ **ngẫu nhiên** kiểu người (thư viện humanize) vượt được luật nhịp phím.
- Macro bàn phím của người dùng (AutoHotkey, trình mở rộng văn bản, auto-type của trình
  quản lý mật khẩu ngoài ô mật khẩu) cũng gõ máy móc và sẽ bị coi là tự động hóa.
- Chuẩn người thật cho gõ phím là dữ liệu công bố (CMU), chưa phải người dùng SilkMoon;
  cần theo dõi `input_provenance.typing` trên traffic thật.

## Tái hiện

```powershell
python -m core_ml.train --dataset-root "../Tuần 3/repos/web_bot_detection_dataset" --weights-dir bot-lab/release-v15/weights --device cpu
python -m pytest -q
cd collector; npm test
```

## Bổ sung: collector 1.5.0 — phiên theo tab (2026-10-26)

Một phiên thử nghiệm thật (tải trang rồi chuyển trang ngay sau 1 giây) tạo ra **hai phiên**:
phiên đầu kẹt ở 12 điểm chuột, mãi là SUSPECT, và hai phiên còn khác `visitorId`.

| Nguyên nhân | Sửa |
|---|---|
| Mỗi lần tải trang sinh `sessionId` mới | Một phiên cho mỗi tab (`sessionStorage`), hết hạn sau 30 phút không hoạt động; tải lại hoặc sang trang khác giữ nguyên phiên |
| Dò font trong trang đếm cả web font của site: Roboto (Google Fonts) không có ở lần tải đầu, có ở lần sau (11 → 12 font) nên `visitorId` đổi | Dò font trong một iframe trống, không thấy `@font-face` của trang |
| Trang sau ghi đè kết luận trang trước | Kết luận "dính": trang thiếu dữ liệu không ghi đè kết luận FINAL; BOT FINAL không bị trang sau đổi thành HUMAN (khớp tiêu chí "ever BOT" của release gate) |
| Dashboard gộp "chưa đủ dữ liệu" vào "Nghi vấn" | Nhãn xám "CHƯA ĐỦ DỮ LIỆU"; KPI Nghi vấn ghi rõ số phiên chưa đủ dữ liệu |

Kiểm chứng bằng Chrome thật (Patchright) trên trang có Roboto: collector 1.4.0 cho 3 phiên
và 2 `visitorId` qua 3 lần tải; 1.5.0 cho 1 phiên, 1 `visitorId`. Lưu ý: `visitorId` của mọi
khách đổi một lần khi chuyển sang 1.5.0 nếu trước đó web font bị đếm.
