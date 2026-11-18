# Policy 45: Chrome cũ nhưng có API mới (`ANACHRONISTIC_UA`)

Ngày 18/11/2026. `DECISION_POLICY_VERSION = "45"`. Code: `core_ml/features/client_forgery.py`
(`CHROME_UA_HINTS`, `page_exposes_ua_hints`, `forgery_codes`).

## Phát hiện

Sau policy 44, nhóm máy tính Nghi vấn lớn nhất (từ 16/11: 34/258 phiên máy tính) là các phiên khai Chrome
58/64/70: không có lần di chuột nào, mang hai họ bằng chứng môi trường (GPU, CONTEXT) nhưng chỉ đủ một mâu thuẫn,
nên dừng ở Nghi vấn.

Trên bản sao lưu 17/11 (54.198 phiên):

| Phiên máy tính khai Chrome | Số phiên | Từng là Người | Fingerprint gắn cờ |
| --- | --- | --- | --- |
| ≤ 100 | 297 | 0 | 52/228 (23%) |
| 101–109 (Chrome cuối của Windows 7/8.1) | 69 | 2 | 32/33 |
| 110–130 | 312 | 14 | 73/94 |

295 trên 297 phiên "Chrome ≤ 100" đến từ địa chỉ Mỹ (múi giờ Chicago, New York, Detroit) và 293 phiên vào
Downloader, một trang tiếng Việt. Người dùng thật không thể kẹt ở Chrome 58–70 năm 2026: Windows 7/8.1 còn được
cập nhật tới Chrome 109, macOS 10.11–10.12 tới 103.

Raw capture cho thấy cơ chế (50 phiên khai Chrome ≤ 83):

- Trang có `navigator.userAgentData` (User-Agent Client Hints). Chrome đưa API này vào từ bản 84 (origin trial;
  bật mặc định từ 89/90), nên không bản Chrome 58–83 nào có nó.
- Danh sách brand rỗng, platform rỗng, và không phiên nào gửi header `Sec-CH-UA`. Trong khi đó 890/892 phiên
  Chrome hiện đại có header này. Đây chính là cách Chromium trả lời khi chuỗi user agent bị ghi đè (tham số
  dòng lệnh hoặc DevTools Protocol) mà không kèm metadata client hints: một Chromium đời mới đang giả Chrome cũ.
- Worker báo WebGL renderer khác trang (49/50) và số nhân CPU khác trang (49/50).

## Thay đổi

`ANACHRONISTIC_UA`: user agent máy tính khai Chrome 83 trở xuống nhưng trang có `navigator.userAgentData`. Đây là
thêm một mâu thuẫn trong khung của policy 26–27, giống `UA_API_MISMATCH` của policy 31: một mình nó chỉ chặn kết
luận Người; cùng một mâu thuẫn độc lập khác (ở đây là worker báo GPU khác trang) thì `forged_browser_v1` kết luận
BOT.

- Không phải luật "Chrome cũ là bot": Chrome 70 thật (không có API) giữ nguyên Nghi vấn; Chrome 109 của Windows 7
  có API là hợp lệ, không bị tính.
- Brand rỗng và thiếu header `Sec-CH-UA` không được tính thành mâu thuẫn riêng, vì chúng cùng một nguyên nhân
  (ghi đè user agent) với chính mâu thuẫn trên.
- Chỉ xét máy tính; user agent điện thoại không bao giờ bị tính ở đây.
- Release gate: `CLIENT_FORGERY_RULE_GATE_V44` đóng băng cho policy 42–44; 4 fixture mới (Chrome 70 + API + worker
  khác GPU → BOT; Chrome 70 + API một mình → Nghi vấn; Chrome 70 không có API → Nghi vấn như cũ; Chrome 109 + API →
  Nghi vấn như cũ).

## Kết quả trên replay

Cùng 3.674 phiên có raw capture:

| | Policy 44 | Policy 45 |
| --- | --- | --- |
| Máy tính được kết luận (1.124) | 77,0% | 81,3% |
| Máy tính có tham chiếu Fingerprint được kết luận (482) | 66,4% | 76,1% |
| Khớp Fingerprint trên phần được kết luận | 99,4% | 88,6% |
| Điện thoại | không đổi | không đổi |

Chỉ 49 phiên đổi kết quả, tất cả từ Nghi vấn sang BOT, đều là đàn này. Mức khớp với Fingerprint giảm vì Fingerprint
chỉ gắn cờ 7/47 phiên: nó bỏ sót đàn ghi đè user agent này. Fingerprint không phải nhãn thật. Mỗi phiên bị kết
luận mang hai mâu thuẫn mà không trình duyệt thật nào tạo ra, cộng với bối cảnh nhất quán (toàn bộ ở Mỹ, không di
chuột, chưa từng là Người).

Trên production từ 16/11, khoảng 18 phiên Nghi vấn thuộc nhóm này (Chrome 58/64/70). Tỉ lệ kết luận máy tính ước
tăng từ 71% lên khoảng 78% khi đàn này quay lại.

## Còn mở

- `rejudge` (chấm lại phiên đã lưu) chỉ đọc fingerprint đã lưu, không có client hints của trang, nên không áp dụng
  mã này cho phiên cũ; phiên mới được chấm ngay.
- Phiên khai Chrome 84–100 với brand rỗng (1 phiên) không bị tính: Chrome 84+ có API thật, và người dùng extension
  đổi user agent cũng tạo ra brand rỗng.
