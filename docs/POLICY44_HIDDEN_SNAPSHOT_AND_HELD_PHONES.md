# Policy 44 và collector 1.18: lượt xem ngắn trên điện thoại

Ngày 18/11/2026. `DECISION_POLICY_VERSION = "44"`, `PRESENCE_VERSION = "presence_v4"`, collector `1.18.0`.
Code: `collector/src/index.js` (`UNLOAD_ACTIONS`, `presenceKey`, `handleVisibilityChange`),
`core_ml/features/presence.py` (`HELD_MIN_EVENTS`, `MOBILE_HELD_RULE`), `api_service/live.py` (`LEFT_ACTIONS`).

## Phát hiện

Sau policy 43, phần lớn điện thoại chưa được kết luận là **Chưa đủ dữ liệu**: 257/842 phiên điện thoại từ khi
xoá dữ liệu (16/11) đến sáng 18/11. Đo trên production và trên raw capture:

| Nguyên nhân | Số đo |
| --- | --- |
| Trang chưa từng hiển thị (tải trước, tab nền) | 72/257 |
| Hiển thị dưới 10 giây, không chạm, không cuộn | 159/257 |
| Snapshot đầu tiên tới server sau khi trang mở | trung vị 3,5 s, P75 5,7 s (điện thoại) |
| Phiên Chưa đủ (lượt ngắn) không có snapshot cuối `pagehide` | 28% (phiên Người: 4%) |
| Phiên Chưa đủ có dấu hiệu cầm tay nhưng dưới 30 sự kiện cảm biến | 63 trên production |

Hai lỗi thu thập gây ra phần lớn nhóm này:

1. **Script khởi động muộn so với trang.** Collector chỉ đo chuyển động từ lúc chạy. Với lượt xem 3–10 giây,
   bản tóm tắt cảm biến thường chỉ có vài sự kiện, không đủ 30 sự kiện mà luật cầm tay của policy 43 yêu cầu.
2. **Gói cuối chỉ gửi ở `pagehide`.** Trên điện thoại, người dùng thường rời trang bằng cách chuyển ứng dụng,
   đóng trình duyệt trong ứng dụng hoặc tắt màn hình. Lúc đó `pagehide` thường không xảy ra; sự kiện cuối cùng
   một trang chắc chắn nhận được là `visibilitychange` sang `hidden` (Page Lifecycle API).

## Thay đổi

### Collector 1.18.0

- Khi trang chuyển sang ẩn, collector gửi snapshot `hidden` bằng `sendBeacon` (cùng đường truyền với
  `pagehide`: `text/plain`, giới hạn 60 KB). Ẩn rồi đóng trang mà không có gì mới thì chỉ gửi một lần; trang ẩn
  không có gì mới so với snapshot đã được xác nhận thì không gửi.
- Snapshot `hidden` không xác nhận (ack) dữ liệu chuột: nếu trang quay lại, heartbeat sau gửi lại các điểm đó,
  nên mất beacon không làm thủng chuỗi chuột của policy 40.
- Heartbeat coi bản tóm tắt cảm biến của điện thoại là "hoạt động" (`presenceKey`): số lần đo chuyển động thật
  và các mốc thời gian hiển thị 0,5/3/10/30 s. Điện thoại không chạm vẫn gửi bản tóm tắt đầy đủ ở heartbeat 15 s.
  Chỉ tính lần đo có số liệu (`events − nullEvents`): Chrome trên máy tính bắn đúng một sự kiện rỗng khi không có
  cảm biến (90% phiên máy tính đã ghi), nên máy tính giữ nguyên hành vi cũ.
- Trang ẩn khi chưa lấy xong fingerprint thì không gửi gì; snapshot `init` vẫn đến sau như trước.

Kiểm thử trên trình duyệt thật (Edge headless, API giả lập cục bộ, cảm biến giả lập qua CDP
`Emulation.setSensorOverrideReadings` nên sự kiện `devicemotion` là sự kiện thật): `init` báo 1.18.0; bản tóm tắt
chuyển động tăng từ 5 lên 64 sự kiện và đi theo heartbeat khi không có thao tác; trang ẩn gửi beacon `hidden`
(`text/plain`, kèm 26 điểm chuột); ẩn lần nữa không có gì mới thì không gửi; đóng tab vẫn gửi `pagehide`. Trang
máy tính để yên 6 giây (heartbeat 1 giây) chỉ gửi `init`.

### API

- `last_action = "hidden"` được coi là đã rời trang trong Live View (`live.LEFT_ACTIONS`, `get_online_sessions`).

### Policy 44

- `HELD_DEVICE` cần **8** sự kiện chuyển động thay vì 30 (nghiêng 10–85°, linear SD ≥ 0,02, gyroscope SD > 0,1
  giữ nguyên). Luật đổi tên `mobile_held_device_v2`; các điều kiện khác của kết luận Người mức thấp nhất giữ
  nguyên (không chạm, chỉ thiếu `FEW_GESTURES`, không cờ chạm, không rủi ro, model đọc được).
- Giả lập vẫn không lọt: cảm biến giả lập nằm phẳng (tilt ≤ 0,2°) và không xoay; máy trong farm nằm yên trên giá.
- Release gate: `MOBILE_RULE_GATE_V43` đóng băng cho policy 43; 3 fixture mới (12 sự kiện cầm tay → Người;
  6 sự kiện → Chưa đủ; 12 sự kiện không có gyroscope → Chưa đủ). Bundle từ policy 40 trở đi đều kiểm tra
  `session_mouse_aggregation` (trước đây chỉ kiểm tra ở policy 40–41).

## Kết quả trên replay

Cùng 3.674 phiên có raw capture như policy 43 (dữ liệu do collector 1.16–1.17 gửi, nên chưa có hiệu ứng của 1.18):

| | Policy 43 | Policy 44 |
| --- | --- | --- |
| Điện thoại được kết luận (2.550 phiên) | 73,5% | 75,8% |
| Điện thoại có tham chiếu Fingerprint được kết luận (1.888) | 80,5% | 81,4% |
| Khớp Fingerprint trên phần được kết luận | 92,5% | 92,6% |
| Điện thoại Fingerprint sạch → Người | 913 | 931 |
| Máy tính | không đổi | không đổi |

Chỉ có 59 phiên đổi kết quả, tất cả từ Chưa đủ sang Người (`mobile_held_device`), với 8–28 sự kiện chuyển động.
Fingerprint không gắn cờ phiên nào trong 18 phiên có tham chiếu. Không phiên BOT hay Nghi vấn nào thay đổi.

## Đo lại sau khi triển khai

Collector 1.18 chỉ có tác dụng với dữ liệu mới. Sau 1–2 ngày lưu lượng cần đo: tỉ lệ phiên có snapshot `hidden`,
tỉ lệ điện thoại Chưa đủ dữ liệu (trước: 31%), số sự kiện chuyển động ở snapshot cuối, và mức khớp với Fingerprint
của các phiên `mobile_held_device`.

## Không làm

- Không gửi snapshot trước khi lấy xong fingerprint: phiên rời đi trong khoảng đó không có gì để chấm, chỉ làm
  tăng số phiên Chưa đủ.
- Không coi lượt xem không hiển thị là Người hay Bot: trang chưa từng hiển thị không phải một lượt xem.
- Nhúng script sớm hơn (`<head>`, `preconnect`) cần người quản lý trang spin/downloader sửa HTML của họ.
