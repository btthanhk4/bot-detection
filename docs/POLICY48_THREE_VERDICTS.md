# Policy 48: ba trạng thái Người / Nghi vấn / Bot

Ngày 18/11/2026. `DECISION_POLICY_VERSION = "48"`. Code:
- `core_ml/three_verdicts.py` (`input_anomalies`, `apply_three_verdicts`)
- `api_service/main.py` (áp dụng sau mỗi lần `predict`)
- `api_service/database.py` (quy tắc ghi đè)
- `api_service/rejudge.py` + `python -m api_service.manage three-verdicts` (phiên cũ)
- `core_ml/release_cases.py` (`THREE_VERDICT_CASES`)

## Quyết định

Thành quyết định sản phẩm chỉ còn ba trạng thái:
- **BOT:** chỉ khi một luật kết luận chắc chắn.
- **Nghi vấn:** phiên có điểm bất thường.
- **Người:** phiên không có dấu hiệu bot nào ("vô thưởng vô phạt"), như cách các bot score thương mại cho qua phiên sạch.

Trạng thái "Chưa đủ dữ liệu" không còn xuất hiện ở phiên mới.

## Thiết kế hai lớp

| Lớp | Việc làm |
| --- | --- |
| Bộ phát hiện (`EnsembleBotDetector.predict`) | Giữ nguyên. Vẫn trả "chưa đủ bằng chứng" khi không có thao tác và không có gì chống lại phiên. Đây là kết quả trung thực của phương pháp; các release gate của policy 19–47 kiểm tra nó và không đổi |
| Sản phẩm (`apply_three_verdicts`, API) | Đổi kết quả "chưa đủ" thành Nghi vấn (`input_anomaly`, kèm mã bất thường) hoặc Người (`no_bot_evidence`, độ tin cậy thấp nhất). Lưu nguồn gốc vào `breakdown.three_verdicts` (`from_state`, `from_basis`, `from_codes`, `anomalies`) để luận văn vẫn báo cáo được số liệu của bộ phát hiện |

Kết quả do bằng chứng quyết định (BOT, Người có chạm, Nghi vấn có rủi ro…) giữ nguyên. Khi lưu, một kết luận ánh xạ chỉ thay được kết luận ánh xạ khác hoặc kết luận "chưa đủ" cũ (cờ `verdict_mapped`). Nó không bao giờ thay một kết luận do bằng chứng đưa ra: trang thứ hai không thao tác không xoá được Nghi vấn mà trang đầu đã cho thấy.

## Điểm bất thường

Số liệu đo trên replay policy 47 (3.674 phiên, 2.370 có tham chiếu Fingerprint). "Bị cờ" nghĩa là Fingerprint báo bot `bad`, tampering hoặc anti-detect.

| Thiết bị | Bất thường | Số phiên (bị cờ / có tham chiếu) | Lý do |
| --- | --- | --- | --- |
| Điện thoại | `UNVERIFIED_PAGE_LOAD` | 13 (1/3) | Token không hợp lệ hoặc bị dùng lại, hoặc thiếu token khi trang đã hiển thị từ 5 s (collector chỉ chờ token 2 s, beacon rời trang không chờ: 50/63 phiên thiếu token chỉ hiển thị dưới 5 s, Fingerprint không gắn cờ phiên nào trong 19) |
| Điện thoại | `SENSORS_UNAVAILABLE` | 5 (1/1) | Cảm biến không trả số đo thật trong 10 s (farm policy 43) |
| Desktop | `DESKTOP_IDLE` | 58 (38/44) | Trang hiển thị từ 10 s mà di chuột dưới 10 lần |
| Desktop | `ENVIRONMENT_FAMILY` | 20 (15/15) | Có họ bằng chứng tự động hoá nhưng chưa đủ để kết luận BOT |
| Desktop | `UNVERIFIED_PAGE_LOAD` | 17 (2/2) | Không có page token |
| Desktop | `NOT_VIEWED` | 17 (5/7) | Trang không bao giờ hiển thị |
| Mọi thiết bị | `PROFILE_AUTOMATION` | 0 | Hồ sơ trình duyệt có dấu vết tự động hoá (brand/UA HeadlessChrome ở trang hoặc worker, webdriver trong worker): chưa phải luật BOT, nhưng người thật không có |
| Mọi thiết bị | `NO_PAGE_PRESENCE` | 0 | Không có dữ liệu hiển thị trang lẫn tuổi trang (collector từ 1.16 luôn gửi): telemetry trần, không có gì cho thấy trang từng được mở. Lệnh cho phiên cũ bỏ qua dấu hiệu này |
| Mọi thiết bị | `CLIENT_AUTOMATION_SIGNAL`, `HIGH_CLIENT_HEURISTIC_SCORE`, `MODEL_DISAGREEMENT`, `DEGENERATE_TRAJECTORY` | 0 | Do chính bộ phát hiện gắn: bộ phát hiện bot phía trang báo cờ hoặc điểm từ 0,8; hai mô hình chuột bất đồng; từ 25 lần di chuột mà không có biến thiên |

Các trường hợp **không** tính là bất thường, nên vào Người:
- Điện thoại không có dấu hiệu gì: 334 phiên, bị cờ 4/177 (2,3%).
- Điện thoại có trang không hiển thị: 127 phiên, 3/81 (3,7%). Trình duyệt trong app thường tải trước trang quảng cáo.
- Điện thoại có một họ dấu hiệu môi trường: 9 phiên, 0/5. Trình duyệt trong app tự tạo ra những dấu hiệu này; policy 18 đã chấp nhận một họ.
- Desktop xem ngắn hoặc có di chuột.

## Kết quả trên replay

| | Trước | Sau | Fingerprint gắn cờ |
| --- | --- | --- | --- |
| Điện thoại: Người | 1.319 (50,9%) | 1.830 (70,6%) | 1,4% → 1,7% |
| Điện thoại: Nghi vấn | 97 (3,7%) | 114 (4,4%) | 44,4% → 44,8% |
| Điện thoại: Chưa đủ dữ liệu | 528 (20,4%) | 0 | |
| Desktop: Người | 16 (1,5%) | 35 (3,2%) | 0% → 5,6% |
| Desktop: Nghi vấn | 74 (6,8%) | 154 (14,2%) | 89,5% → 87,1% |
| Desktop: Chưa đủ dữ liệu | 99 (9,1%) | 0 | |

BOT không đổi (điện thoại 25,0%, desktop 82,5%).

## Giới hạn (cần ghi trong luận văn)

- **Người mới là "không thấy dấu hiệu bot", không phải "đã thấy người".**
  - Trong 1.368 điện thoại Fingerprint thấy sạch, DATACAT chứng minh được 105 phiên là bot (cảm biến giả lập, farm không có cảm biến, trình duyệt giả). Vì vậy tỉ lệ bị cờ của nhóm Người chỉ là cận dưới.
  - Đội máy không thao tác và qua mặt được cả hai hệ thống sẽ thành Người. Ở mức đội máy, `INERT_COHORT` (policy 38) vẫn đưa chúng vào Nghi vấn.
- **Desktop Người 5,6% bị cờ** vì lưu lượng desktop của Downloader gần như toàn bot. Trên site có người thật, tỉ lệ này thấp hơn.
- **Phiên cũ không tự đổi.**
  - Dùng `python -m api_service.manage three-verdicts` để đếm, thêm `--apply` để ghi.
  - Lệnh chỉ đọc những gì phiên đã lưu. Desktop lưu trước collector 1.16 không có thời gian hiển thị, nên không bị tính `DESKTOP_IDLE`.
- **Báo cáo trong luận văn:** số liệu của phương pháp (có "chưa đủ bằng chứng") lấy từ `breakdown.three_verdicts.from_state`; số liệu sản phẩm lấy từ `verdict`.
