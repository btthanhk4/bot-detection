# Model release v13

Bundle: `6f4513166c6a431aab5cf1a2eafaf6f7`. Policy: `13`. Collector: 1.3.0 (không đổi).
Ngưỡng và tham số mô hình chuột không đổi so với v10–v12; replay cùng nguồn giữ nguyên
(0 cửa sổ người bị gán BOT, 0 cửa sổ bot bị gán HUMAN).

## Nguồn thay đổi: traffic người thật đầu tiên

Ngày 2026-10-26, SilkMoon nhận 24 phiên từ 5 IP: 23 phiên người thật từ 4 IP (Chrome, Edge,
Firefox trên Windows, macOS, Linux) và 1 phiên bị v12 gán BOT. Kết quả trên 23 phiên người:

| Đo lường | Kết quả |
|---|---|
| Mô hình chuột | 0/23 BOT (điểm LSTM lớn nhất 0,40, xác suất ensemble lớn nhất 0,20) |
| Thời gian giữ chuột khi click | trung vị theo phiên 16–180 ms (15 phiên có click); 0 lần nhả dưới 5 ms |
| Click trúng tâm (≤ 1 px) | 1/216 click, 1 phiên |
| Δt giữa hai sự kiện move (p50) | 4–17 ms tùy thiết bị |
| `zero_step` | tới 0,15 ở người |
| Firefox | 2/2 phiên kích hoạt nhóm PERMISSION (dương tính giả) |

Luật click giả lập v11 và mô hình chuột không có dương tính giả. Lỗi duy nhất là nhóm
PERMISSION trên Firefox: Firefox trả `Notification.permission = "default"` nhưng
`permissions.query` trả `prompt`/`denied` theo cách khác Chromium, nên đây là hành vi
bình thường của trình duyệt, không phải dấu hiệu bị vá.

## Phiên bị gán BOT là đúng

Phiên `sess_oye7d0oho5lmvonv0o5` (IP 113.171.237.166) tự nhận Chrome 155 trên Windows,
không có chuột, chỉ gửi 1 snapshot. Bằng chứng:

| Nhóm | Mâu thuẫn |
|---|---|
| CONTEXT | Worker báo platform `Linux x86_64` trong khi trang báo `Win32`; Worker báo 55 nhân CPU, trang báo 8 |
| GPU | WebGL trong Worker khác trang; chuỗi renderer `ANGLE (Intel(R) HD Graphics Direct3D11 vs_5_0 ps_5_0)` là định dạng ANGLE cũ, cả 9/9 phiên Windows thật dùng định dạng mới `ANGLE (Vendor, Device (0x…) Direct3D11 …, D3D11)` |
| PERMISSION | `Notification.permission` mâu thuẫn với Permissions API |

Ngoài luật: audio hash khác giá trị giống hệt nhau của mọi máy Windows thật, 9 font so với
11, `availHeight` bằng `height` (không có taskbar). Đây là máy Linux nhiều nhân giả làm
Chrome Windows, khả năng cao là trình duyệt chống phát hiện hoặc cloud browser.

## Thay đổi

1. Nhóm PERMISSION chỉ áp dụng khi UA tự nhận là Chromium (`Chrome/` và không có
   `Firefox/`).
2. Thêm tín hiệu `server.legacy_angle_renderer` vào nhóm GPU: Chrome ≥ 100 nhưng chuỗi
   WebGL bắt đầu bằng `ANGLE (` và không có dấu phẩy. Chrome từ năm 2021 luôn ghi
   `ANGLE (Vendor, Device, Backend)`.
3. Sửa lỗi lưu MongoDB: `_sanitize_bson_value` cắt ở độ sâu 4, làm
   `breakdown.automation_evidence.families` bị lưu thành `[null]`. Giới hạn nay là 6.

Release gate tăng từ 8 lên 11 fixture: thêm 1 ca BOT (đúng mẫu phiên trên) và 2 ca không
được kết luận BOT (Firefox có lệch permission; Chrome với renderer ANGLE định dạng mới).
Gate của policy 12 được đóng băng để bundle v12 vẫn kiểm chứng được.

## Kiểm chứng trên traffic thật

Replay luật v13 trên 24 phiên đã lưu: 23 phiên người không còn nhóm nào (trước đó 2 phiên
Firefox có PERMISSION); phiên BOT vẫn BOT với 3 nhóm CONTEXT, GPU, PERMISSION.

## Giới hạn

- Vẫn chỉ có 23 phiên người thật từ 4 IP. Brave, Safari, trình duyệt di động, máy ảo và
  Remote Desktop chưa có mẫu.
- `legacy_angle_renderer` dựa trên định dạng chuỗi của Chrome hiện tại; driver hoặc bản
  build lạ có thể trả định dạng khác. Tín hiệu chỉ là một nhóm, không đủ để kết luận BOT.
- SilkMoon chạy HTTP nên các tín hiệu cần secure context (Sec-Fetch, Client Hints,
  coalesced events) chưa dùng được.

## Tái hiện

```powershell
python -m core_ml.train --dataset-root "../Tuần 3/repos/web_bot_detection_dataset" --weights-dir bot-lab/release-v13/weights --device cpu
python -m pytest -q
cd collector; npm test
```

Bundle v12 được giữ trong `bot-lab/rollback-v12/` (không commit).
