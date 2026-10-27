# Model release v18 — kết luận NGƯỜI THẬT cho điện thoại

Bundle: `d05a4253a0984b14998aaf9d1a327676`. Policy: `18`. Collector: 1.7.0 (không đổi). Tham số mô hình chuột không đổi.

## Vấn đề

Mô hình chuột không đánh giá được thao tác cảm ứng, nên trước v18 mọi phiên điện thoại
không có dấu vết bot đều ở trạng thái "CHƯA ĐỦ DỮ LIỆU", kể cả người dùng thật.

## Các sản phẩm thương mại làm gì

Cloudflare (bot score 1–99), reCAPTCHA v3 (điểm 0–1) và DataDome đều xếp một trình duyệt
điện thoại bình thường, có fingerprint và mạng sạch, vào nhóm "likely human". Hành vi chỉ
là một tín hiệu cộng thêm; khi nghi ngờ thì đưa ra thử thách. Không sản phẩm nào yêu cầu
mô hình hành vi vuốt mới được kết luận người.

## Luật `mobile_clean_environment_v1`

Phiên được kết luận **HUMAN** (FINAL, không khóa) khi đồng thời:

| Điều kiện | Mã khi thiếu |
|---|---|
| UA iPhone/iPad/Android/mobile, hoặc iPad xin bản desktop (UA Mac Safari, `MacIntel`, GPU Apple, nhiều điểm chạm) | `NOT_MOBILE` |
| ≥ 3 cử chỉ chạm/vuốt thật (`isTrusted`) | `FEW_GESTURES` |
| Không có cờ cảm ứng (`SYNTHETIC_CONTACT`, `ZERO_TIME_TAPS`, `RULER_SWIPES`) | `TOUCH_FLAGS` |
| Không phải trình giả lập (GPU phần mềm/emulator, Android trên CPU x86) | `EMULATOR` |
| Thông tin thiết bị không mâu thuẫn (luật giả lập điện thoại v17) | `PLATFORM_CONTRADICTION` |
| IP không thuộc cloud | `CLOUD_IP` |
| Không có dấu vết tự động hóa; tối đa một nhóm bằng chứng môi trường, không phải nhóm neo (headless, GPU, quyền) | `ENVIRONMENT_EVIDENCE` |
| Không có cờ webdriver/tự động hóa từ trình duyệt | `CLIENT_AUTOMATION_SIGNAL` |
| Mô hình chuột đã nạp (dịch vụ khỏe) | — |

Mọi luật BOT vẫn được xét trước. Kết luận không khóa: nếu sau đó xuất hiện dấu hiệu bất
thường, phiên trở lại NGHI VẤN hoặc BOT. Dashboard ghi rõ kết luận dựa trên việc không có
bằng chứng bot, chưa chấm điểm hành vi vuốt.

## Kiểm tra

12 fixture (`MOBILE_HUMAN_CASES`, gate `mobile_human_rule_gate`): 3 dương (iPhone thật
với giá trị đo trên site — lực 0, bán kính 36,4; Android thật; iPad chế độ desktop) và 9 âm
(2 cử chỉ, chạm CDP, vuốt thẳng tắp, trình giả lập Android, IP cloud, Playwright giả lập
iPhone → BOT, webdriver → BOT, laptop Windows cảm ứng, Chrome trên Mac giả lập cảm ứng).

## Sửa lỗi sau khi deploy (2026-10-27)

Thử trên thiết bị thật: iPhone → HUMAN đúng; một điện thoại Android giá rẻ (Adreno 610,
Android 10) bị giữ ở NGHI VẤN vì `SYNTHETIC_CONTACT`. Máy không có cảm biến lực và diện tích
chạm nên Chrome báo bán kính 0,3, lực 1, lực 0 khi nhả, giống hệt thao tác bơm vào Android.
Cờ được thu hẹp về chữ ký CDP (bán kính đúng 1, lực 1 cả khi nhả). Fixture của gate không
đổi nên bundle giữ nguyên; dữ liệu thật của máy này thành test hồi quy.

## Giới hạn

- Đây là kết luận "không thấy bot", không phải mô hình hành vi đã kiểm chứng. Bot chạy
  trên điện thoại thật bằng thao tác vật lý (phone farm người bấm, cánh tay robot) hoặc
  công cụ tạo sự kiện có tiếp xúc giống người sẽ được gán HUMAN.
- Tỉ lệ bot điện thoại bị cho qua chưa đo được: cần bộ bot có nhãn trên thiết bị thật
  (xem kế hoạch trong [Dữ liệu cảm ứng](TOUCH_DATA.md)).
- iOS có ít tín hiệu cảm ứng hơn Android (lực luôn 0, bán kính 3 mức).
- Thao tác bơm vào Android (adb, HID, autoclick) không phân biệt được với điện thoại giá rẻ thiếu cảm biến chỉ bằng giá trị tiếp xúc; cần tín hiệu khác (nhịp chạm lặp, cảm biến chuyển động).

## Tái hiện

```powershell
python -m core_ml.train --dataset-root "../Tuần 3/repos/web_bot_detection_dataset" --weights-dir bot-lab/release-v18/weights --device cpu
python -m pytest -q
```
