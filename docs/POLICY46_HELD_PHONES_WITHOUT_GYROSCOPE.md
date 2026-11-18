# Policy 46: điện thoại không có con quay hồi chuyển cầm trên tay

Ngày 18/11/2026. `DECISION_POLICY_VERSION = "46"`, `PRESENCE_VERSION = "presence_v5"`. Code:
`core_ml/features/presence.py` (`no_gyroscope`, `held_in_hand`, `HELD_NO_GYRO_*`).

## Phát hiện

Test có kiểm soát trên máy OPPO CPH2653 (18/11): cầm máy không thao tác thì được nhận ra trong Chrome. Trong
trình duyệt của Zalo và Messenger thì không, vì hai app này không gửi sự kiện cảm biến nào, cả chuyển động lẫn
hướng (collector 1.19). Khi không có cảm biến và cũng không chạm thì không có bằng chứng, và kết quả
"Chưa đủ dữ liệu" là đúng.

Trên production, trình duyệt trong app Facebook (nguồn quảng cáo chính) gửi cảm biến ở 94% phiên (203/216, 7 ngày),
nên giới hạn của Zalo/Messenger ảnh hưởng ít. Nhóm lớn hơn là các phiên không chạm, có cảm biến mà vẫn
Chưa đủ dữ liệu (112 phiên Android trong 7 ngày):

| Nguyên nhân | Số phiên |
| --- | --- |
| Đã đủ điều kiện cầm tay, nhưng được chấm bằng policy 41–42, trước khi có luật | 41 |
| Ít hơn 8 lần đo | 22 |
| **Máy không có con quay hồi chuyển (không có số đo xoay nào)** | **20** |
| Máy gần như nằm phẳng (nghiêng dưới 10°) hoặc dựng đứng (trên 85°) | 20 |
| Không rung hoặc không xoay | 6 |

Luật cầm tay của policy 43–44 đòi hỏi con quay báo có xoay, nên máy giá rẻ không có con quay không bao giờ thoả.
Trên replay 3.674 phiên, 636/2.102 điện thoại Android có dữ liệu chuyển động không có con quay (30%).

## Thay đổi

Máy không có con quay (không có số đo xoay nào, `rotation_sd` và `rotation_mean` đều trống) được coi là cầm trên
tay khi: nghiêng 10–85° (như cũ), **từ 50 lần đo**, độ lệch chuẩn gia tốc tuyến tính **≥ 0,03** (rung tay) và độ lệch
chuẩn véc-tơ trọng trường **≥ 0,03** (máy đổi hướng). Ngưỡng chặt hơn máy có con quay (8 lần đo, 0,02) vì thiếu kênh xoay.
Các điều kiện khác của kết luận Người mức thấp nhất giữ nguyên. Luật đổi tên `mobile_held_device_v3`; máy có con
quay giữ nguyên policy 44.

- Giả lập nằm phẳng (`SYNTHETIC_MOTION`, nghiêng ≤ 0,2°) và máy trên giá (không rung) không thoả. Farm "cảm biến câm"
  (policy 43) chỉ có 1 lần đo.
- Release gate: `MOBILE_RULE_GATE_V45` đóng băng cho policy 44–45; 3 fixture mới (không con quay, 120 lần đo → Người;
  40 lần đo → Chưa đủ; trên giá → Chưa đủ).

## Kiểm chứng trên replay

| Dấu hiệu "cầm tay không con quay" (≥ 30 lần đo, rung ≥ 0,03, trọng trường ≥ 0,03) | Số phiên |
| --- | --- |
| Khớp | 223 |
| Trong đó có từ 3 lần chạm thật | 77 (74 là Người) |
| Phiên BOT không con quay có dấu hiệu này | 3/261 |

Áp dụng từ 50 lần đo: **25 phiên** đổi từ Chưa đủ dữ liệu sang Người, ngoài ra không phiên nào đổi. Fingerprint không
gắn cờ phiên nào trong 17 phiên có tham chiếu. Điện thoại được kết luận 75,8% → 76,8% (có tham chiếu: 81,4% →
82,3%), khớp Fingerprint 92,7%. Máy tính không đổi.

## Không làm

- Không coi phiên trong app chặn cảm biến (Zalo, Messenger) mà không chạm là Người: không có bằng chứng nào.
- Không nới ngưỡng nghiêng cho máy gần như phẳng hay dựng đứng: cũng là tư thế của máy trên bàn hoặc trên giá.
