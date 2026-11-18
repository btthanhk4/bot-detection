# Collector 1.19 và cờ tham chiếu Fingerprint (18/11/2026)

Không đổi kết luận của DATACAT: `DECISION_POLICY_VERSION` vẫn là `"45"`, bundle giữ nguyên.

## Bối cảnh: test có kiểm soát trên Redmi K30 5G (18/11)

9 phiên do tác giả tự thực hiện, gắn nhãn `known_human` (nhóm `thanh-redmi`): 8/9 đúng kỳ vọng, không phiên nào
bị kết luận BOT hay Nghi vấn. Kết quả lệch duy nhất: cầm máy không chạm trong trình duyệt của Zalo cho ra
Chưa đủ dữ liệu, vì trình duyệt trong Zalo và Messenger không gửi sự kiện `devicemotion` nào (trạng thái
`permission_gated`). Chrome và Trình duyệt Mi gửi đủ.

## Cờ tham chiếu Fingerprint

`api_service/reference.py` (`strong_flag`): một phiên được coi là bị Fingerprint gắn cờ khi Fingerprint báo
can thiệp trình duyệt (`tampering`) hoặc trình duyệt anti-detect. Điểm nghi ngờ (`suspect_score` ≥ 20) không còn
được tính.

- Điểm nghi ngờ là tổng rủi ro gian lận của Fingerprint (VPN, hệ điều hành đã root hoặc sửa đổi, ẩn danh…), không
  phải nhãn bot. Redmi của tác giả (ROM tuỳ biến, build `TQ3A`) được chấm đúng 20 điểm ở 3/9 phiên, với
  `bot = not_detected` và không có cờ nào khác.
- Trên replay 3.674 phiên: định nghĩa cũ gắn cờ 6/411 phiên người (proxy: phiên Người có từ 3 lần chạm) và 85,2%
  phiên BOT; định nghĩa mới 4/411 và 84,0%. Điểm nghi ngờ chỉ thêm cờ cho 11/945 phiên BOT.
- Báo cáo (`report`) và dashboard tính lại cờ từ các trường đã lưu, nên phiên cũ được đọc theo cùng định nghĩa.

## Collector 1.19.0: cảm biến hướng

`collector/src/presence.js` tóm tắt thêm `deviceorientation` (beta/gamma: trung bình, độ lệch chuẩn, độ thay đổi
giữa hai lần đo; tối đa 400 sự kiện hoặc 12 giây, giống chuyển động) vào `presence.orientation`. Đây là dữ liệu
nghiên cứu: server chưa dùng nó cho kết luận nào. Mục đích: biết trình duyệt trong Zalo/Messenger có gửi hướng
thiết bị không, vì chúng chiếm khoảng 1/3 lưu lượng điện thoại.

- Heartbeat coi số lần đo hướng có số liệu là "hoạt động" (cùng cơ chế `presenceKey` của 1.18). Sự kiện rỗng không
  tính: Edge/Chrome trên máy tính bắn đúng một sự kiện hướng rỗng, giống `devicemotion`.
- Kiểm thử trên Edge headless, hướng giả lập qua CDP `DeviceOrientation.setDeviceOrientationOverride`: bản tóm tắt
  tăng 1 → 12 lần đo và đi theo heartbeat; trang máy tính để yên 6 giây chỉ gửi `init`. Smoke test của 1.18 (beacon
  `hidden`, chống gửi trùng, `pagehide`) vẫn qua.

## Bước tiếp theo

Test lại trên Redmi: `thanh-redmi-zalo-camtay-v2` và `thanh-redmi-messenger-camtay-v2` (cầm máy, không chạm, 10 giây,
rồi đóng). Nếu trình duyệt trong app gửi hướng thiết bị có độ rung của tay, một policy sau mới cân nhắc dùng nó cho
luật cầm tay, sau khi kiểm chứng trên dữ liệu.
