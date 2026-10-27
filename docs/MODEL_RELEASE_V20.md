# Model release v20 — trình duyệt tự khai HeadlessChrome

Bundle: `5516a2e5ab324d838a66669aa9a5ff60`. Policy: `20`. Collector: 1.7.1 (không đổi). Tham số mô hình chuột không đổi.

## Vấn đề

Ngày 2026-10-27, một bot gửi vào site lúc 10:57 chỉ được xếp "chưa đủ dữ liệu":

| Bằng chứng | Giá trị |
|---|---|
| User-Agent (request và trình duyệt) | `... HeadlessChrome/154.0.0.0 ...` |
| GPU | SwiftShader (CPU giả lập) |
| Cờ trình duyệt | `headlessUa`, `headlessScreen`, `appVersionAutomation` |
| `navigator.webdriver` | đã bị giấu |
| Thao tác chuột | 0 |

Luật HeadlessChrome của v10 đòi thêm một dấu vết framework (webdriver, biến ChromeDriver),
nên bản stealth che webdriver không khớp. Luật môi trường mâu thuẫn cần 3 nhóm bằng chứng,
bot này chỉ có 2 (headless, GPU), vì nó khai UA thật nên không mâu thuẫn Client Hints.

## Thay đổi

Dấu vết tự động hóa mới `server.declared_headless_ua`: cả User-Agent của request lẫn
User-Agent trình duyệt báo về đều chứa `HeadlessChrome/`. Chỉ Chrome chạy không giao diện
mới tự đặt chuỗi này; người dùng không duyệt shop bằng nó. Cùng loại với crawler tự khai
(policy 17). Một header giả riêng lẻ (chỉ request hoặc chỉ trình duyệt) không đủ.

Gate HeadlessChrome: 7 trường hợp như v10, trường hợp "cả hai UA khai HeadlessChrome, không
có webdriver" chuyển từ NGHI VẤN sang BOT (`automation_marker`). Gate dấu vết tự động hóa
thêm 2 fixture: payload thật của bot trên và một header HeadlessChrome giả (vẫn NGHI VẤN).
Gate của policy 17–19 được đóng băng để rollback.

## Kiểm tra trên phiên thật

| Phiên | Policy 19 | Policy 20 |
|---|---|---|
| Bot HeadlessChrome stealth (10:57) | chưa đủ dữ liệu | **BOT** (trình duyệt tự khai HeadlessChrome) |
| Bot giả UA Windows trên Linux (10:57) | BOT | BOT |
| Người thật trên máy tính (11:06) | HUMAN | HUMAN |

## Tái hiện

```powershell
python -m core_ml.train --dataset-root "../Tuần 3/repos/web_bot_detection_dataset" --weights-dir bot-lab/release-v20/weights --device cpu
python -m pytest -q
```
