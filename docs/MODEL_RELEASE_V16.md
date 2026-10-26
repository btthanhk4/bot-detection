# Model release v16 — rà soát tình huống biên

Bundle: `673dc8ddd0224da5beb02132a18b3a7e`. Policy: `16`. Collector: **1.6.0**.
Tham số mô hình chuột không đổi so với v10–v15.

## Lỗi tìm thấy và cách sửa

### 1. Người Việt gõ Telex bị gán BOT (nghiêm trọng, có trên policy 15)

Unikey/EVKey thay chữ bằng cách **chèn Backspace và chữ có dấu với thời gian giữ ~0 ms**
(gõ `Huwowngf` → xóa và gõ lại `ờng`). Policy 15 tính cửa sổ 8 phím trên mọi phím nên
các phím chèn kéo trung vị xuống dưới ngưỡng.

Mô phỏng Monte Carlo: thời gian giữ/nhịp phím lấy mẫu từ người thật (CMU), mô hình chèn
phím Telex, 14 chuỗi tiếng Việt kiểu cửa hàng (tên, địa chỉ, tìm sản phẩm), 3.000 lượt:

| Phiên bản | Lượt gõ tiếng Việt bị gán BOT |
|---|---|
| Policy 15 | **2.799 / 3.000 (93 %)** |
| Policy 16, collector cũ | 0 / 3.000 |
| Policy 16, collector 1.6.0 | 0 / 3.000 |
| Bot `keyboard.type` gõ chữ có dấu | vẫn bị bắt |

Sửa: collector phân loại phím `c` (ASCII), `n` (chữ có dấu), `b` (Backspace/Delete);
cửa sổ chỉ tính trên chuỗi chữ liên tiếp; cụm gõ có Backspace giữ < 10 ms (dấu hiệu bộ
gõ chèn phím) không bị xét. Bot không gõ Backspace nên vẫn bị xét. Ngưỡng giữ phím hạ từ
20 xuống 12 ms để chừa biên cho bàn phím rapid-trigger (người thấp nhất 30,2 ms; bot
1,4–3,5 ms). Giả định mô hình Unikey chưa được đo trực tiếp bằng Unikey thật.

### 2. Người dùng máy tính ảo trên cloud bị gán BOT vĩnh viễn

Amazon WorkSpaces/Citrix trên AWS: IP AWS (NETWORK) + GPU "Microsoft Basic Render
Driver" (GPU) + `rtt = 0` (HEADLESS_ENV) = 3 nhóm có neo → BOT ngay gói đầu tiên, và kết
luận dính của collector 1.5.0 không bao giờ gỡ. Ba bằng chứng chỉ nói một điều: đây là
máy ảo cloud.

Sửa: trên IP cloud, GPU phần mềm và `rtt = 0` được gộp vào NETWORK. Luật mới
`idle_cloud_browser_v1`: IP cloud + GPU phần mềm + **không có thao tác nào trong ≥ 10 s**
(crawler Google Cloud hôm 26/10 ở lại 14 s không thao tác: vẫn BOT). Kết luận này
**không khóa**: khi người dùng thật thao tác đủ và mô hình kết luận HUMAN, nó được thay.
Mọi kết luận BOT khác vẫn khóa cho cả phiên.

### 3. Admin xóa một phiên đang mở → tab mất dữ liệu 10 phút

Từ collector 1.5.0 tab giữ `sessionId`, mà phiên đã xóa bị chặn ghi 10 phút. Sửa: API
trả `session_closed: true`, collector chuyển ngay sang phiên mới.

### 4. Giữ kết luận cũ nhưng báo "degraded"

Khi trang sau không được ghi đè kết luận, API trả `recorded: false` và không cập nhật
thời điểm hoạt động. Sửa: vẫn cập nhật trang hiện tại, IP, thời điểm; báo đã ghi nhận.

### 5. Nhiều người sau một IP (lớp học, buổi bảo vệ)

Mỗi tab SilkMoon gửi ~12 gói/phút; giới hạn 240/phút/IP chỉ đủ ~20 tab. Nâng mặc định
lên 720 (~60 tab).

## Tình huống đã kiểm tra, không cần sửa

| Tình huống | Kết quả |
|---|---|
| Điện thoại / máy tính bảng | Luôn "chưa đủ dữ liệu" (mô hình chỉ cho chuột); không luật nào gán BOT nhầm: luật gõ bỏ qua con trỏ thô, luật áp lực bỏ qua chạm/bút, tín hiệu môi trường chỉ cho Chromium desktop |
| Safari, Firefox | `productSub`, PERMISSION, Client Hints, `rtt` đều có điều kiện trình duyệt |
| Toàn màn hình (F11), PWA, kiosk | `noBrowserFrame` không dùng để quyết định |
| Máy ảo VirtualBox/VMware, Remote Desktop | GPU hypervisor không tính; RDP từ IP nhà chỉ có 1 nhóm |
| Linux không driver GPU (llvmpipe) | 1 nhóm GPU, không đủ 3 nhóm |
| Bàn phím ảo Android/iOS, IME tiếng Việt của Windows/macOS | Phím `Unidentified`/229 bị loại |
| Giữ phím lặp (autorepeat), ô mật khẩu | Loại khỏi phân tích |
| Click bằng bàn phím, trình đọc màn hình | `detail = 0` bị bỏ qua |
| Touchpad tap-to-click | Nhả tức thì nhưng không trúng tâm → luật click không bắn |
| Tải lại / chuyển trang, bfcache | Cùng phiên (collector ≥ 1.5.0) |
| Bộ nhớ trình duyệt bị chặn (ẩn danh nghiêm ngặt) | Quay về một phiên mỗi trang |

## Giới hạn còn lại (đã biết, chưa xử lý)

- **Nhân bản tab** (Duplicate tab) chép `sessionStorage`: hai tab dùng chung phiên.
- **Macro bàn phím** (AutoHotkey, auto-type của KeePass ở ô tên đăng nhập) gõ máy móc và
  bị coi là tự động hóa; bàn phím ảo trên màn hình Windows chưa được đo.
- **Tiện ích bảo vệ quyền riêng tư mạnh** (JShelter, CanvasBlocker) có thể tạo nhiều nhóm
  bằng chứng; chưa có trình duyệt mẫu để đo.
- **Giả mạo telemetry** bằng script ngoài trình duyệt chỉ lộ ở nhóm HTTP (thiếu
  `Sec-Fetch-*`), không đủ kết luận một mình; kết luận chỉ phục vụ giám sát, không chặn.

## Tái hiện

```powershell
python -m core_ml.train --dataset-root "../Tuần 3/repos/web_bot_detection_dataset" --weights-dir bot-lab/release-v16/weights --device cpu
python -m pytest -q
cd collector; npm test
```
