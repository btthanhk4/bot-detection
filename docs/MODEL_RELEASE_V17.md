# Model release v17 — tối ưu theo khoảng cách với sản phẩm thương mại

Bundle: `90da81c9569f420db2d6e2b7b8c9160a`. Policy: `17`. Collector: 1.6.0 (không đổi).
Tham số mô hình chuột không đổi.

Nguyên tắc: chỉ đưa vào những gì đo được hiệu quả và không gây báo nhầm trên dữ liệu
người thật; hướng nào không chứng minh được thì ghi lại và bỏ.

## Đưa vào

### 1. `mobile_emulation_v1` — trình duyệt máy tính giả làm điện thoại

Trước v17 mọi phiên tự nhận là điện thoại đều bị hoãn (mô hình chỉ học chuột), nên bot
giả lập điện thoại không bao giờ bị kết luận. Đo ngày 2026-10-26:

| Bộ giả lập | `platform` | WebGL | `deviceMemory` (iPhone) |
|---|---|---|---|
| Playwright iPhone 13 / Pixel 7 / Galaxy S9+ (headless và có giao diện) | `Win32` | Direct3D11 (chỉ có trên Windows) | 16 |
| Puppeteer iPhone 13 | `Win32` | Direct3D11 | 16 |
| iPhone thật | `iPhone` | `Apple GPU` | không có (WebKit) |
| Android thật | `Linux aarch64` / `armv8l` | Adreno / Mali / … | có |

Luật: UA điện thoại + **bắt buộc** mâu thuẫn `platform` + ít nhất một mâu thuẫn khác (GPU
Direct3D hoặc không phải Apple trên iOS, `deviceMemory` trên iOS, không có cảm ứng). Chế độ
thiết bị của Chrome DevTools đặt đúng `platform` nên lập trình viên xem thử giao diện di
động không bị gán BOT; emulator Android Studio (`Linux x86_64`) cũng không.

End-to-end: Patchright có giao diện giả lập iPhone 13 — policy 16: SUSPECT (hoãn), policy
17: **BOT** (`mobile_emulation_v1`). Toàn bộ 20 kịch bản end-to-end khác cho kết quả giống policy 16; Chrome/Edge thật không bị gán BOT. 690 test, Ruff và test collector đều qua.

### 2. Bot tự khai báo

- **Web Bot Auth** (IETF draft, chữ ký RFC 9421): header `Signature-Agent` /
  `Signature-Input`, ChatGPT Agent gửi kèm; Cloudflare và AWS đã xác minh chuẩn này.
- **UA crawler đã công bố**: Googlebot, Bingbot, GPTBot, ChatGPT-User, OAI-SearchBot,
  ClaudeBot, PerplexityBot, Bytespider, Applebot, Lighthouse… (so khớp theo ranh giới từ,
  nên điện thoại hãng "Cubot" không bị nhầm).

Cả hai là dấu vết tự động hóa (`automation_marker_v1`): người dùng không bao giờ gửi.

## Đã thử và bỏ

| Hướng | Lý do bỏ |
|---|---|
| Luật "di chuột thẳng, vận tốc đều" cho `mouse.move({steps})` | Người thật trong M4D cũng có chuỗi 10–12 bước đều (Playwright: trung vị 11); SilkMoon chỉ 23 phiên người (tối đa 3) — không đủ biên an toàn. Mô hình chuột vẫn gán SUSPECT |
| Phân tích tần suất nhiều phiên theo fingerprint/IP | `visitorId` trùng nhau giữa các máy cùng cấu hình (đặc biệt Apple); nhiều người sau một IP (NAT); lưu lượng một site quá nhỏ để có tín hiệu |
| JA4 (TLS) ở gateway | Phải build lại nginx với module ngoài; bot dùng Chrome thật có JA4 giống người; agent có JA4 riêng (ChatGPT Agent) đã tự khai báo bằng `Signature-Agent` |
| Ký HMAC payload chống giả mạo | Khóa phải nằm ở client nên kẻ giả mạo lấy được; script ngoài trình duyệt đã lộ ở nhóm HTTP (thiếu `Sec-Fetch-*`) |
| Proof-of-work | Tăng chi phí cho bot nhưng không giúp phát hiện |

## Tái hiện

```powershell
python -m core_ml.train --dataset-root "../Tuần 3/repos/web_bot_detection_dataset" --weights-dir bot-lab/release-v17/weights --device cpu
python -m pytest -q
```
