# Policy 50: chạm 0 ms lẫn trong lần ấn thật, đối chiếu lại phiên cũ, collector 1.20

Ngày 19/11/2026. `DECISION_POLICY_VERSION = "50"`, collector `1.20.0`.

## Vì sao làm

Sau khi khôi phục dữ liệu 10–16/11, production có 55.581 phiên. Tỉ lệ kết luận lệch mạnh giữa hai trang:

| Nhóm | Phiên | Người | Nghi vấn | BOT | Fingerprint gắn cờ |
| --- | --- | --- | --- | --- | --- |
| Downloader, máy tính, 10–16/11 | 14.295 | 2,6% | 7,1% | 90,3% | 75,4% |
| Downloader, máy tính, từ 17/11 | 2.195 | 72,2% | 25,6% | 2,2% | 27,9% |
| Spin, điện thoại, 10–16/11 | 20.055 | 77,1% | 6,6% | 16,3% | 15,3% |

"Fingerprint gắn cờ" = `bot = bad`, hoặc tampering, hoặc anti-detect, trên các phiên có tham chiếu.

Độ lệch chủ yếu đến từ lưu lượng: Downloader máy tính bị Fingerprint gắn cờ 75%, Spin điện thoại 15%. Tỉ lệ BOT của
DATACAT bám theo con số đó trên cả hai trang, và giảm theo ngày khi chiến dịch bot ở Downloader dừng. Khi bỏ qua Nghi
vấn, mức đồng thuận với Fingerprint là 95,9% (κ ≈ 0,87): điện thoại 96,1%, máy tính 94,5%.

Rà các nhóm hai bên không đồng ý (script đọc, chỉ in số tổng hợp) cho ra ba lỗi có nguyên nhân rõ:

1. **BOT cũ mà luật hiện hành không còn kết luận.** 320 phiên Android ở Spin bị kết luận `forged_browser` trước
   policy 42 chỉ vì worker lệch GPU và platform. Từ policy 42, hai dấu hiệu này tính là một mâu thuẫn, nên những
   phiên này chỉ còn là Nghi vấn. Fingerprint gắn cờ 33/122 (27%).
2. **38 BOT `autoclick_taps_v1`** (chạm cùng điểm, đều nhịp) ở Spin. Fingerprint không gắn cờ phiên nào (0/26).
   Policy 49 cho thấy v1 bắt nhầm người bấm dồn dập. Những phiên này không còn dữ liệu thô để kiểm tra theo v2.
3. **172 điện thoại bị Nghi vấn chỉ vì `ZERO_TIME_TAPS`.** Mỗi máy có từ 3 thao tác trở lên, và Fingerprint chỉ
   gắn cờ 1/102. Trong các phiên này, chạm 0 ms là thiểu số: thường 2 trên 5–19 lần chạm, các lần còn lại ấn
   30–150 ms như ngón tay thật. Đây là màn hình đôi khi báo cả hai đầu của một lần chạm cùng một thời điểm.
   Bot WebView ở policy 29 chạm 0 ms ở mọi lần, `adb input tap` cũng vậy.

Thêm một nguyên nhân phía collector: 184 điện thoại chạm thật từ 3 lần trở lên bị Nghi vấn vì
`UNVERIFIED_PAGE_LOAD`, Fingerprint gắn cờ 1/66. Dữ liệu thô cho thấy collector 1.16–1.17 không có token ở mọi
snapshot. Collector chỉ gọi `/visit` một lần với timeout 5 s, nên trên mạng di động chậm (BR/BD/PK/ID), mất lần
gọi đó là mất token cả phiên.

## Thay đổi

### Luật (`core_ml/features/mobile_human.py`)

`zero_time_taps_among_presses`: `ZERO_TIME_TAPS` không còn ngăn kết luận Người của điện thoại khi:
- phiên có ít nhất 3 lần chạm khác không phải 0 ms;
- số lần chạm 0 ms không quá một nửa số lần chạm.

Bản thân cờ và vai trò mâu thuẫn của nó trong `forged_browser_v1` (policy 29) giữ nguyên, nên WebView giấu
webdriver mà chạm 0 ms vẫn là BOT.

### Đối chiếu phiên cũ (`python -m api_service.manage reconcile [--apply]`)

Lệnh này dùng cho phiên không còn dữ liệu thô, chỉ đọc những gì phiên đã lưu:

| Điều kiện | Kết luận mới |
| --- | --- |
| BOT `forged_browser` trên điện thoại mà `judge` hiện hành không còn kết luận | Nghi vấn (`client_forgery`) |
| BOT `autoclick_taps_v1` | Nghi vấn (`mobile_risk`) |
| Nghi vấn `mobile_risk` mà điều duy nhất còn thiếu là `TOUCH_FLAGS = [ZERO_TIME_TAPS]`, và thoả điều kiện của policy 50 | Người (`mobile_clean_environment`) |

Kết luận cũ được ghi vào `rejudged` (`rule = reconcile_v1`). Phiên cập nhật trong 30 phút gần nhất được để lại
cho lưu lượng đang chạy. Chạy lại lệnh thì không còn gì để đổi.

### Collector 1.20.0

Khi `/visit` không trả lời (timeout, lỗi mạng) hoặc trả 5xx, collector hỏi lại sau 3 s và 10 s, chạy nền.
Lần trả lời đầu tiên vẫn mở khoá lời chào như trước, và các snapshot sau mang token. Không hỏi lại khi:
- server đã trả lời 2xx/4xx (hết quota 429, bị từ chối 403, 204);
- collector đã bị huỷ;
- phiên đã đổi.

## Ước tính trên production (dry-run 19/11)

| Thay đổi | Phiên | Fingerprint gắn cờ |
| --- | --- | --- |
| forged_browser → Nghi vấn | 320 | 27,0% (122 có tham chiếu) |
| autoclick_v1 → Nghi vấn | 38 | 0,0% (26) |
| chạm 0 ms lẫn trong lần ấn → Người | 123 | 1,2% (86) |

Mọi thay đổi đều ở Spin. Downloader không đổi: các BOT `forged_browser` ở đó vẫn thoả luật hiện hành.

## Không làm

- **Không chuyển Nghi vấn thành BOT.** Ví dụ điện thoại 1–2 chạm có `AUDIO_NOVEL` + `TIMEZONE_MISMATCH`
  (Fingerprint gắn cờ 74–80%) vẫn ở Nghi vấn: mức đó chưa đủ để kết luận.
- **Không đổi luật máy tính.** Nghi vấn `client_forgery` trên máy tính (788 phiên, Fingerprint gắn cờ 33%) là
  những máy không rê chuột nhưng có dấu hiệu môi trường. Mức gắn cờ gấp gần 4 lần nhóm Người (8,9%), nên Nghi vấn
  là kết luận đúng nghĩa. Người trên máy tính bị Fingerprint gắn cờ tập trung ở phiên có 10–49 lần di chuột
  (23%). Mẫu còn nhỏ (29 phiên), cần thêm dữ liệu người thật có nhãn trên máy tính.
- **Không bỏ `UNVERIFIED_PAGE_LOAD`.** Sửa ở collector thay vì nới luật, vì token là thứ chống telemetry giả.
