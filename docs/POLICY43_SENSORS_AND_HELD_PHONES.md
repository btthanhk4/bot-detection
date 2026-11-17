# Policy 43: cảm biến không chạy và điện thoại cầm trên tay

Ngày 17/11/2026. `DECISION_POLICY_VERSION = "43"`, `PRESENCE_VERSION = "presence_v3"`. Code:
`core_ml/features/presence.py` (`sensors_unavailable`, `held_in_hand`, `sensorless_phone_fires`),
`core_ml/features/mobile_human.py` (`held_eligible`), `core_ml/models/ensemble.py`.

## Phát hiện

Chạy lại toàn bộ 3.674 phiên có raw capture (bản sao lưu 17/11 cộng các phiên mới) qua policy 42, rồi so với
Fingerprint trên 2.370 phiên có kết quả tham chiếu. Điện thoại chỉ được kết luận ở 65,9% số phiên (khớp 93,2%);
máy tính 66,4% (khớp 99,4%). Phần lệch lớn nhất nằm ở hai nhóm điện thoại:

1. **Nghi vấn mà Fingerprint gắn cờ.** Gần như cùng một hồ sơ: cảm biến chuyển động báo `ok` nhưng chỉ có 1
   sự kiện, gia tốc trọng trường bằng 0, trang hiển thị 32–58 giây, đúng một lần chạm ở giây 25–40, âm thanh
   `AUDIO_NOVEL` (stack audio không điện thoại nào khác báo), VPN. Một gia tốc kế thật phát khoảng 60 sự kiện mỗi
   giây với trọng trường ≈ 9,8.
2. **Đang chờ (không chạm) mà Fingerprint thấy sạch.** Nhiều phiên có cảm biến cho thấy máy đang được cầm:
   nghiêng 10–85°, rung (độ lệch chuẩn gia tốc tuyến tính ≥ 0,02), xoay (con quay hồi chuyển). Fingerprint chỉ
   gắn cờ 1/88 phiên như vậy, thấp hơn cả nhóm điện thoại được kết luận Người nhờ cử chạm (14/840).

Kiểm tra từng kênh riêng: cảm biến "câm" + `AUDIO_NOVEL` có 200 phiên; Fingerprint gắn cờ 159/189 (84%), 30
phiên còn lại cùng hồ sơ farm (VPN 30/30, một lần chạm sau 25–40 giây 30/30). Không có phiên nào trong nhóm này
có từ 3 cử chạm thật.

## Thay đổi

- `SENSORS_UNAVAILABLE` (research flag, chỉ Android): cảm biến báo `ok` với ≤ 5 sự kiện, trọng trường không có
  hoặc < 1, trang hiển thị ≥ 10 giây.
- `sensorless_phone_v1` (BOT): `SENSORS_UNAVAILABLE` **và** `AUDIO_NOVEL` (kênh server, độc lập). Mỗi kênh đứng
  riêng vẫn chỉ tối đa Nghi vấn. Đặt sau `emulated_phone_v1` trong chuỗi luật tự động hoá.
- `HELD_DEVICE` (research flag): nghiêng 10–85°, linear SD ≥ 0,02, rotation SD > 0,1, ≥ 30 sự kiện.
- `mobile_held_device_v1` (Người, độ tin cậy thấp nhất): điện thoại không có cử chạm nào, thứ duy nhất còn thiếu
  là `FEW_GESTURES`, có `HELD_DEVICE`, không có cờ chạm nào, không có rủi ro điện thoại hay bằng chứng tự động
  hoá, và model đọc được. Có bất kỳ rủi ro nào (lệch múi giờ, audio lạ, trang không được xem…) thì vẫn là Nghi
  vấn/Đang chờ như cũ.

Release gate: `MOBILE_RULE_GATE_V42` được đóng băng cho policy 39–42; policy 43 dùng `MOBILE_RULE_GATE` với
9 fixture mới (chỉ số 55–63 trong `MOBILE_RULE_CASES`). Tensor của model không đổi.

## Kết quả trên replay

| | Policy 42 | Policy 43 |
| --- | --- | --- |
| Điện thoại được kết luận (BOT/Người) | 65,9% | 80,5% |
| Khớp Fingerprint trên phần được kết luận | 93,2% | 92,5% |
| Điện thoại Fingerprint gắn cờ → BOT | 61,4% | 90,4% |
| Điện thoại Fingerprint sạch → Người | 826 | 913 |
| Toàn bộ phiên được kết luận | ~66% | ~78% |
| Máy tính | không đổi | không đổi |

## Không làm

- Máy tính: `NATIVE_PATCH` (14/14 bị Fingerprint gắn cờ) và lệch ngữ cảnh không kèm `PLUGINS_EMPTY` (21/21)
  trông hứa hẹn, nhưng mẫu quá nhỏ và các extension bảo vệ quyền riêng tư / đổi UA của người thật cũng sinh ra
  đúng các dấu này. Giữ Nghi vấn.
- Khoảng 305 điện thoại Đang chờ mà Fingerprint sạch còn lại: cảm biến không hỗ trợ hoặc cần quyền (iOS), máy để
  trên bàn, trang không được xem. Không có bằng chứng theo hướng nào nên không kết luận.
- Fingerprint không phải nhãn thật: nó bỏ sót emulator và farm, và gắn cờ nhầm Samsung Internet / trình duyệt HMS
  của Huawei. Các con số trên chỉ là mức đồng thuận.
