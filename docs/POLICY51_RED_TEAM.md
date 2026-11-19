# Policy 51: rà lỗ hổng, di chuột thưa, điện thoại có chạm mà cảm biến câm

Ngày 19–20/11/2026. `DECISION_POLICY_VERSION = "51"`. Collector không đổi (1.20.0).

## Cách rà

1. **Payload dựng sẵn:** chạy qua đúng bộ phát hiện và lớp ba kết luận trên máy local, tìm đường rẻ nhất tới
   HUMAN cho từng loại thiết bị (scratchpad `redteam/probe_paths.py`).
2. **Dữ liệu thô trên production:** đọc 4.236 phiên còn telemetry thô (7 ngày) và toàn bộ 55.706 phiên đã lưu,
   chỉ in số tổng hợp, để xem lỗ nào đang bị khai thác.
3. **Tập có nhãn:** đối chiếu mọi điều kiện mới với 52 phiên người thật đã biết.

"Fingerprint gắn cờ" = `bot = bad`, hoặc tampering, hoặc anti-detect.

## Kết quả

| Đường né | Kết luận trước policy 51 | Trên production | Xử lý |
| --- | --- | --- | --- |
| Máy tính, 10–24 lần di chuột (đường thẳng, đứng yên tại chỗ, bước đều), trang hiển thị lâu | HUMAN (`no_bot_evidence`); 9 lần di chuột thì SUSPECT (`DESKTOP_IDLE`) | 173 phiên HUMAN, Fingerprint gắn cờ 35% (cùng kết luận, có 0 lần di chuột: 3%) | **Sửa:** `SPARSE_POINTER` |
| Điện thoại có 1–3 lần chạm, cảm biến câm từ 10 s trở lên, âm thanh không lạ | HUMAN | 13 phiên, Fingerprint gắn cờ 7/8; 0/52 người thật đã biết | **Sửa:** `SENSORS_UNAVAILABLE` chặn HUMAN |
| Máy tính không có chuột, rời trang trước 10 s | HUMAN | Fingerprint gắn cờ 3% (99 có tham chiếu) | Giữ: đánh đổi có chủ đích của policy 48 |
| Chuột "humanizer" (Bézier, tốc độ tăng giảm dần, nhiễu 0,3 px, 60–100 điểm) | SUSPECT (`MODEL_DISAGREEMENT`) ở 6/6 lần chạy, không lần nào HUMAN | – | Không cần sửa |
| 25+ lần di chuột thẳng tắp | BOT (mô hình chuột) | – | Không cần sửa |
| Chạm do công cụ bơm lệnh (thời gian ấn cố định 100 ms, một kiểu tiếp xúc, nhịp không đều) | HUMAN | 9 phiên HUMAN có thời gian ấn cố định, Fingerprint gắn cờ 0/8; một máy người thật đã biết cũng ấn cố định với một kiểu tiếp xúc (CV 0,034) | Còn mở: không bịt được bằng luật đơn giản mà không bắt nhầm người |
| Phát lại chuỗi chạm giữa các phiên | – | 0 chuỗi trùng trong 4.236 phiên | Chưa thấy khai thác |
| Sao chép tóm tắt cảm biến giữa các phiên | – | 2 cặp trùng | Chưa thấy khai thác |
| Android không có sự kiện cảm biến, rời trang trước 10 s | HUMAN | HUMAN bị Fingerprint gắn cờ 2/18 | Giữ |
| Người mở DevTools | SUSPECT (`CDP_ATTACHED`) | Kiểm thử có kiểm soát `thanh-pc-mangcham` | Giới hạn đã biết: DevTools dùng cùng giao thức với công cụ tự động |
| Telemetry được dựng hoàn toàn (không chạy trình duyệt, có token hợp lệ qua proxy dân dụng) | Có thể HUMAN | – | Còn mở: cần kênh phía server (vân tay TLS JA4) |

## Thay đổi

### `SPARSE_POINTER` (lớp ba kết luận, `core_ml/three_verdicts.py`)

Áp cho phiên máy tính mà bộ phát hiện chưa chấm được, khi thoả cả ba điều kiện:
- có từ 10 lần di chuột trở lên;
- con trỏ đi qua ít nhất 3 vị trí khác nhau;
- khoảng cách trung vị giữa hai lần di chuột từ 45 ms trở lên.

Phiên như vậy là bất thường, nên kết luận NGHI VẤN.

- **Cơ sở vật lý:** chuột thật báo một lần di chuột mỗi khung hình khi đang di chuyển (17 ms ở 60 Hz; 33 ms khi
  Chrome tiết kiệm pin giảm còn 30 khung hình/giây). Script ngủ giữa các lần phát sự kiện thì không như vậy.
- **Trên production:** ngưỡng 45 ms khoanh 55/173 phiên HUMAN của nhóm này, Fingerprint gắn cờ 14/17 phiên có
  tham chiếu. Phần dưới ngưỡng: 10/52.
- **Người thật đã biết:** mọi phiên máy tính có trung vị 17 ms. Phiên chỉ cuộn là 33 ms, với 1 vị trí: Chrome tự
  phát sự kiện di chuột khi nội dung cuộn dưới con trỏ đứng yên. Điều kiện 3 vị trí bảo vệ đúng nhóm này.
- **Bot do tác giả chạy:** 33–49 ms.

### `SENSORS_UNAVAILABLE` cho điện thoại có chạm (`core_ml/features/mobile_human.py`)

Policy 43 chỉ dùng dấu hiệu cảm biến câm khi đi cùng mã băm âm thanh chưa từng gặp (kết luận BOT), hoặc ở phiên
không chạm (bất thường). Từ policy 51, điện thoại có chạm mà cảm biến câm từ 10 s trở lên mất kết luận HUMAN và
thành NGHI VẤN (`mobile_risk`). Dấu hiệu này đứng một mình vẫn không kết tội.

Fixture policy 43 "một lần chạm muộn, cảm biến câm, âm thanh không lạ" (chỉ số 62) đổi kỳ vọng từ HUMAN sang
NGHI VẤN. Bộ fixture đến policy 50 được giữ nguyên trong `MOBILE_RULE_CASES_V50` để các gate đã đóng băng vẫn
kiểm được.

### Phiên đã lưu (`manage reconcile`)

Hai thay đổi cùng được áp cho phiên không còn dữ liệu thô, chỉ đọc những gì phiên đã lưu:
- `breakdown.interaction_shadow.features.move_interval_median_ms` và `breakdown.distinct_positions`;
- `breakdown.presence.research_flags`.

### Release gate

- **Ba kết luận:** đóng băng `THREE_VERDICT_GATE_V50`; thêm 3 fixture (di chuột thưa → NGHI VẤN; cùng số lần
  di chuột ở 17 ms → HUMAN; 18 lần di chuột do cuộn tại một vị trí → HUMAN), tổng 13 ca.
- **Điện thoại:** đóng băng `MOBILE_RULE_GATE_V50`; ca 62 đổi kỳ vọng, thêm ca 3 lần chạm, tổng 81 ca.

## Còn mở

- Đường thẳng 10–24 điểm ở nhịp 16 ms vẫn qua. Chưa đủ dữ liệu thô của người thật để đặt ngưỡng thẳng/đều an toàn.
- Chạm do công cụ bơm lệnh trên máy thật (ADB, accessibility) có thời gian ấn hợp lý vẫn qua.
- Telemetry dựng sẵn với token lấy hợp lệ qua proxy dân dụng. Kênh độc lập có giá trị nhất là vân tay TLS (JA4)
  của request gửi tới `api.datacat.io.vn`.

## Kết quả trên production (20/11/2026)

Deploy commit 496fd21, bundle `34644e1e` (tensor giống policy 50). Sao lưu trước khi ghi:
`/root/backups/detection_results-20261120-pre-reconcile51.archive.gz` (55.743 phiên, sha256 `2d3f0905…`).

| Thay đổi (`reconcile --apply`) | Phiên | Fingerprint gắn cờ |
| --- | --- | --- |
| Máy tính di chuột thưa → NGHI VẤN | 33 | 13/14 |
| Điện thoại có chạm, cảm biến câm → NGHI VẤN | 13 | 8/9 |

Có 33 phiên di chuột thưa, ít hơn con số 55 ước tính, vì có thêm điều kiện ít nhất 3 vị trí. Chạy lại lần hai: 0.

Sau khi áp:
- Phiên HUMAN bị Fingerprint gắn cờ giảm từ 184 xuống 164 (1,08% → 0,96%).
- Mức trùng trên phiên đã quyết định là 96,5%, κ = 0,884.
- Tập có nhãn không đổi: 50/52 người là HUMAN, 28/30 bot là BOT, không có lỗi nghiêm trọng.
