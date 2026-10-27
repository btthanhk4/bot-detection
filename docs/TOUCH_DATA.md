# Dữ liệu cảm ứng từ traffic thật (collector 1.7.0)

Mục tiêu: điện thoại hiện luôn ở trạng thái "CHƯA ĐỦ DỮ LIỆU" vì mô hình chỉ học chuột.
Bản này thu cử chỉ chạm/vuốt từ người dùng thật để huấn luyện mô hình cảm ứng. **Kết luận
không đổi**: policy vẫn là 17; phân tích cảm ứng chỉ hiển thị và lưu lại.

## Luồng dữ liệu

1. **Collector 1.7.0** ghi mỗi cử chỉ một ngón (touchstart → touchend/touchcancel) dạng
   điểm `[ms từ lúc chạm, x, y, radiusX, radiusY, force]` (px CSS), tối đa 48 điểm/cử chỉ,
   gửi 20 cử chỉ gần nhất cùng kích thước màn hình và `devicePixelRatio`. Bỏ qua cử chỉ hai
   ngón (pinch) và sự kiện do script tạo (`isTrusted = false`).
2. **API** (`BOT_TOUCH_CAPTURE=true`) lưu mỗi cử chỉ thành một document trong
   `touch_samples`: chỉ hình học và thời gian, không lưu IP, nội dung trang hay phím.
   Id = hash(session | page | t0 | điểm đầu) nên heartbeat gửi lại không tạo bản trùng;
   nhãn được cập nhật khi kết luận của phiên thay đổi. TTL 180 ngày
   (`BOT_TOUCH_RETENTION_DAYS`); nếu không tạo được TTL index thì không lưu gì. Xóa một
   phiên trên dashboard cũng xóa cử chỉ của phiên đó.
3. **Nhãn yếu** (`label_hint`):
   - `automation`: phiên bị kết luận BOT bởi một luật tự động hóa, hoặc mọi lần chạm có
     bán kính 1 và lực 1 (mặc định CDP/Playwright).
   - `human_candidate`: UA điện thoại/máy tính bảng, không bị kết luận BOT, không có dấu
     vết tự động hóa, tối đa một nhóm bằng chứng môi trường, không phải IP cloud, không có cờ
     cảm ứng nào.
   - `unlabeled`: còn lại.

   `human_candidate` là nhãn nhiễu (bot giỏi vẫn có thể lọt vào), chỉ dùng làm dữ liệu
   người khi huấn luyện, không dùng làm ground truth để đánh giá.

## Endpoint

| Endpoint | Quyền | Nội dung |
|---|---|---|
| `GET /api/v1/touch-samples/stats` | đọc | số cử chỉ theo nhãn, thiết bị (ios/android), loại (chạm/vuốt) |
| `GET /api/v1/touch-samples/export?label=&after=&limit=` | admin | phân trang theo id, trả `next` để lấy trang sau |
| `DELETE /api/v1/touch-samples` | admin | xóa toàn bộ dữ liệu cảm ứng |

## Cờ nghiên cứu (`breakdown.touch.research_flags`)

Đo ngày 2026-10-27 bằng Playwright `tap` và CDP `Input.dispatchTouchEvent` (giả lập Pixel 7):

| Cờ | Điều kiện | Ghi chú |
|---|---|---|
| `SYNTHETIC_CONTACT` | mọi cử chỉ: bán kính ≤ 1 và force = 1 khi đang chạm (điểm nhả được phép 0) | CDP báo bán kính 1; thao tác bơm vào Android (thiết bị HID, script phát lại) báo pressure 1, kích thước 0. Bắt 3/3 phiên mouse clicker và script ghi màn hình của Gesture Fingerprint; 0 điểm người (912.133 điểm Touchalytics, 3 bộ người Gesture Fingerprint) có diện tích 0 kèm pressure ≥ 1. Cách trình duyệt Android chuyển đổi các giá trị này chưa được đo trên thiết bị thật |
| `ZERO_TIME_TAPS` | ≥ 2 lần chạm có thời gian chạm < 1 ms | chưa kiểm chứng được trên người: BrainRun ghi thời gian chạm thô (4 % lần chạm bằng 0 ms do cách ứng dụng ghi) |
| `RULER_SWIPES` | ≥ 2 lần vuốt ≥ 5 điểm, lệch khỏi đường thẳng ≤ 0,5 px, độ dài bước CV ≤ 0,05 | BrainRun: 22/147.601 lần vuốt người (0,015 %), 5/8.306 phiên 20 cử chỉ (0,06 %); bắt 91 % lần vuốt CDP thẳng |

Không cờ nào đủ sạch để kết luận BOT; chúng chỉ góp vào nhãn yếu.

## Mô hình vuốt thử nghiệm (shadow)

`python -m core_ml.train_touch --brainrun <gestures.bson> --touchalytics <data.csv> [--live trang_export.json ...]`

- Người (mô hình v2, `341d05cffba6031b`): BrainRun (Papamichail et al., 2019, CC0, Zenodo
  2598135), 40.000 lần vuốt nhanh trong game từ 2.072 thiết bị (tối đa 150/thiết bị), và
  Touchalytics (Frank et al., 2013), 15.021 lần vuốt khi đọc Wikipedia/so sánh ảnh của 41
  người, có thời điểm từng điểm (gần với hành vi lướt shop nhất). Cộng `human_candidate`
  từ traffic thật khi có. Mỗi cử chỉ cắt còn 48 điểm như collector.
- Bot: 4 bộ sinh, mỗi lần vuốt giả chép điểm đầu, điểm cuối, thời lượng và số điểm của một
  lần vuốt người, nên mô hình chỉ học được cách đường vuốt được vẽ: `linear` (CDP),
  `linear_noise`, `bezier_ease` (kiểu ghost-cursor), `lognormal` (kiểu BeCAPTCHA).
- Đặc trưng: chỉ hình dạng và tổng thời lượng. BrainRun không có thời điểm từng điểm,
  bán kính hay lực, nên các đặc trưng đó sẽ dạy mô hình đặc điểm của bộ dữ liệu.

Kết quả (người tách theo thiết bị):

| Bộ sinh | AUC khi đã thấy khi huấn luyện | AUC khi bị giữ lại (chưa từng thấy) |
|---|---|---|
| linear | 0,9996 | 0,80 |
| linear_noise | 0,979 | 0,71 |
| bezier_ease | 0,976 | 0,68 |
| lognormal | 0,990 | 0,57 |

Người chưa từng thấy (huấn luyện không có nguồn đó, ngưỡng 0,5):

| Nguồn bị giữ lại | Vuốt bị gắn bot | Nhóm 5 vuốt bị gắn bot |
|---|---|---|
| BrainRun | 21 % | 8,3 % |
| Touchalytics | 26 % | 12,9 % |

Kiểm tra ngoài (Gesture Fingerprint, chưa dùng để huấn luyện): người 0/104 lần vuốt bị gắn
bot; mouse clicker 38 %, cánh tay robot 28 %, script phát lại thao tác người 0 % (hình dạng
giống hệt người, chỉ `SYNTHETIC_CONTACT` bắt được). Mô hình v1 (chỉ BrainRun) gắn bot 31,5 %
lần vuốt và 22 % phiên của Touchalytics; v2 còn 6 % lần vuốt và 0,09 % phiên.

Giống kết luận của BeCAPTCHA-Mouse (~60 % với bộ sinh lạ khi chỉ dùng cảm ứng): mô hình
nhận ra loại bot đã biết nhưng không tổng quát sang loại mới, và hình dạng vuốt thay đổi
mạnh giữa các nhóm người/ứng dụng. Thử end-to-end với CDP thật, điểm v1 chỉ 0,51 vì trình
duyệt gộp các touchmove. Vì vậy điểm `breakdown.touch.shadow.score` chỉ hiển thị, không bao
giờ đổi kết luận; dữ liệu người trên chính SilkMoon là thứ còn thiếu.

## Đánh giá các bộ dữ liệu cảm ứng công khai (2026-10-27)

| Bộ dữ liệu | Khả thi | Ghi chú |
|---|---|---|
| BrainRun | đã dùng | CC0; vuốt game ngắn, không có thời điểm từng điểm, bán kính, lực |
| Touchalytics | đã dùng | 41 người Android, có thời gian/pressure/area; không ghi license, chỉ dùng nghiên cứu, không phân phối lại |
| Gesture Fingerprint | dùng làm bộ kiểm tra | duy nhất có nhãn máy (HID, script phát lại, cánh tay robot); chỉ ~270 cử chỉ công bố, license dữ liệu không ghi (code Apache-2.0) |
| H-MOG | được, cần đồng ý điều khoản | 100 người Android, chỉ nghiên cứu phi thương mại, không phân phối lại |
| Oxford Touch (FETA) | nên thử | 470 người iPhone, 1,16 triệu lần vuốt; bổ sung iOS mà hiện còn thiếu; trang ORA chặn tải tự động, cần tải tay |
| AITouch v2 | được | CC BY-NC; 45 người, máy tính bảng Samsung |
| KidsOnThePhone | được | 50 người Nexus 6, có t/x/y/p/s; không ghi license |
| BB-MAS | cần tài khoản IEEE DataPort | 117 người; license không ghi |
| HuMIdb | cần giảng viên cơ hữu ký license | có cảm biến; dùng trong BeCAPTCHA |
| AITW, AndroidControl, GUI-Odyssey, AMEX… | không dùng | ảnh màn hình + hành động của agent (tọa độ chạm/vuốt đầu-cuối), không có quỹ đạo ngón tay |
| WISDM | không dùng | chỉ gia tốc/con quay, không có cảm ứng |

## Khi nào có thể cho cảm ứng tham gia kết luận

1. Đủ dữ liệu người thật trên chính site (gợi ý ≥ 200 phiên `human_candidate`, cả iOS và
   Android), huấn luyện lại với `--live`.
2. Đo tỉ lệ báo nhầm trên phiên người đã xác minh (ví dụ người dùng đăng nhập/mua hàng),
   không dùng `human_candidate` để tự chấm.
3. Chỉ khi tỉ lệ báo nhầm ≈ 0 mới thêm luật/điểm vào policy mới, kèm fixture và gate như
   các policy trước.

Khuyến nghị pháp lý: thêm thông báo thu thập dữ liệu hành vi trên SilkMoon (Nghị định
13/2023/NĐ-CP về bảo vệ dữ liệu cá nhân).
