# Policy 47: điện thoại bật "Trang web cho máy tính"

Ngày 18/11/2026. `DECISION_POLICY_VERSION = "47"`, `PRESENCE_VERSION = "presence_v6"`, collector 1.19.1.

Các file thay đổi:
- `core_ml/features/mobile_human.py` (`android_desktop_site`)
- `core_ml/features/presence.py` (`analyze_presence(..., desktop_site=)`)
- `core_ml/models/ensemble.py`
- `api_service/database.py` (chủ phiên)
- `api_service/research_labels.py` (gắn nhãn)
- `collector/src/index.js`

## Phát hiện

**Kịch bản test.** Test có kiểm soát ngày 18/11 trên một máy Samsung: GPU Mali-G57, không có con quay hồi chuyển, Chrome 157. Trang mở ở giao diện điện thoại. Sau 1,6 giây bật "Trang web cho máy tính", rồi đọc, cuộn và chạm như bình thường.

**Triệu chứng.** Dashboard dừng ở trạng thái của 1,6 giây đầu: 0 chạm, "Chưa đủ dữ liệu", hành động cuối là `pagehide`. Nhìn vào thì tưởng DATACAT ngừng thu thập.

| Lớp | Điều xảy ra |
| --- | --- |
| Collector | Vẫn gửi đủ: 11 snapshot sau khi đổi chế độ, qua 3 lần tải trang (34 chạm ở lần đầu) |
| Trình duyệt | Chỉ User-Agent đổi, từ `Linux; Android 10; K … Mobile` sang `X11; Linux x86_64`. Các giá trị khác giữ nguyên: `navigator.platform` vẫn `Linux armv81` (cả trong worker), 5 điểm chạm, GPU Mali-G57, màn 385×854. Client Hints: x86, 64 bit, Linux, `mobile` false, model rỗng |
| `visitorId` | Là hàm băm của 15 thông số, có cả UA, nên đổi theo |
| API | Chỉ cập nhật phiên khi `visitorId` trùng (để chống ghi đè). Cả 11 snapshot bị bỏ qua, không có log, phản hồi là `degraded` |
| Gắn nhãn | `set_manual_label` từ chối phiên có hai `visitorId` |
| Mô hình (từng snapshot) | Nghi vấn FINAL (basis `client_forgery`). UA không có `android`/`mobile` nên phiên đi nhánh máy tính: không có chuột và 0 plugin (`PLUGINS_EMPTY`) |

**Quy mô trên production.**
- 2/1.298 phiên có dữ liệu thô (0,15%) đổi `visitorId` giữa phiên: chính phiên test này, và một phiên Android có renderer WebGL khác nhau giữa hai lần tải trang.
- Trong 14 ngày có 3 phiên vào thẳng ở chế độ máy tính (Chrome, platform `Linux armv81`, màn hình cảm ứng, GPU điện thoại). Cả 3 đều ra Nghi vấn.

## Thay đổi

1. **Policy 47 (`android_desktop_site_v1`).** Phiên được xếp loại `android_desktop_site` và chấm bằng luật điện thoại (`unsupported_mobile`, presence Android) khi thỏa đủ các điều kiện:
   - UA dạng `(X11; Linux x86_64) … Chrome/N`, không có Android, Mobile hay HeadlessChrome;
   - platform ARM: `Linux armv81`, `armv8l`, `armv7l` hoặc `aarch64`;
   - `maxTouchPoints` lớn hơn 1;
   - GPU điện thoại: Mali, Adreno, Xclipse, PowerVR, Immortalis hoặc Maleoon.

   Ở chế độ này, `CH_EMULATOR` bỏ qua architecture x86 (do Chrome tự khai) nhưng vẫn xét tên model. Cờ `CH_DESKTOP_HINTS` cũng không được gắn.
2. **API.** Snapshot có `visitorId` khác vẫn được nhận nếu mang `deviceToken` trùng với phiên. Đây là chuỗi ngẫu nhiên 128 bit trong localStorage của chính trình duyệt đó. Thiết bị khác, hoặc snapshot không có token, vẫn bị từ chối.
3. **Gắn nhãn.** Áp dụng cùng quy tắc; `study_id` và `site_id` vẫn phải trùng.
4. **Collector 1.19.1.** Khi trang đang ẩn, heartbeat lặp lại đúng nội dung beacon `hidden` sẽ không được gửi. Trước đây heartbeat này làm Live View tưởng người dùng đã quay lại trang thêm tối đa 2 phút.

**Release gate.** Đóng băng `MOBILE_RULE_GATE_V46`. Thêm 5 fixture:

| Fixture | Kết quả |
| --- | --- |
| Chế độ máy tính, có chạm | Người |
| Chế độ máy tính, cầm tay | Người |
| Model giả lập | Nghi vấn |
| Không có màn hình cảm ứng | Vẫn là máy tính, Nghi vấn |
| Laptop cảm ứng | Vẫn là máy tính, chưa đủ |

## Kiểm chứng

Replay 36 snapshot của 6 phiên Samsung bằng code mới:
- **Phiên bật chế độ máy tính:** ra Người (mọi snapshot có chạm đều là Người).
- **5 phiên còn lại:** không đổi.

| Phiên | Kết quả |
| --- | --- |
| Chrome đọc | Người |
| Chrome cầm tay | Người |
| Chrome nằm bàn | Chưa đủ |
| Zalo đọc | Người |
| Zalo cầm tay | Chưa đủ (Zalo chặn cảm biến) |

## Ghi chú

- **Policy 46.** Máy không có con quay, nên đây là lần kiểm chứng trên máy thật đầu tiên của policy 46.
  - Phiên cầm tay ra Người ở mốc 60 lần đo (linear SD 0,037).
  - Ở mốc 400 lần đo, linear SD còn 0,021, dưới ngưỡng 0,03. Phiên vẫn là Người vì kết luận FINAL không bị thay bằng "chưa đủ".
  - Ngưỡng 0,03 có thể quá chặt với tay cầm yên; cần thêm dữ liệu trước khi nới.
- **Zalo trên máy này.**
  - `devicemotion` bị chặn (`permission_gated`, sau đó chỉ có 1 sự kiện).
  - `deviceorientation` chỉ toàn sự kiện rỗng. Máy không có con quay nên không trình duyệt nào tính được hướng.

## Không làm

- Không coi chế độ máy tính của Firefox Android là điện thoại (UA có `rv:`), vì chưa có dữ liệu.
- Không dùng việc `visitorId` đổi giữa phiên làm tín hiệu bot, vì mới có 2 phiên.
- Không chấm lại phiên test đã lưu trên production.
