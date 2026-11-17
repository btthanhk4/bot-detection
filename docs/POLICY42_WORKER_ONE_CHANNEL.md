# Policy 42: lệch giữa trang và worker trên Android chỉ là một mâu thuẫn

Ngày 17/11/2026. `DECISION_POLICY_VERSION = "42"`. Code: `core_ml/features/client_forgery.py`
(`worker_only_android`, `contradictions`, `forged_browser_fires`).

## Phát hiện

Đối chiếu DATACAT với Fingerprint trên 910 phiên sau khi xoá dữ liệu (17/11), có 5 phiên DATACAT kết luận BOT
mà Fingerprint thấy sạch. 3 trong số đó là Samsung Internet trên Android, bị `forged_browser_v1` kết luận
vì hai "mâu thuẫn": worker báo `navigator.platform` khác trang (`PLATFORM_SPOOFED`, policy 32) và worker
báo WebGL renderer khác trang (họ GPU, tính là neo môi trường, policy 28).

Hai mâu thuẫn đó đến từ **cùng một quan sát**: một dedicated worker trả lời khác trang. Một trình duyệt xử lý
worker khác Chrome là sinh ra cả hai cùng lúc. Trên dữ liệu lịch sử (bản sao lưu 17/11, 54.198 phiên), 745
phiên bị kết luận BOT chỉ dựa vào cặp này:

| Nhóm | Số phiên | Fingerprint cũng gắn cờ | Có từ 3 lần chạm thật |
| --- | --- | --- | --- |
| "iPhone" (GPU Apple) | 403 | 231/245 (94%) | |
| Android, Samsung Internet | 55 | 0/21 (0%) | 6 |
| Android, Chrome | 287 | 38/111 (34%) | 66 |
| Đối chiếu: BOT có thêm bằng chứng khác | 11.981 | 745/887 (84%) | |

Các phiên Samsung bị kết luận đều báo `Linux armv8l` và GPU Qualcomm Adreno ở trang; các phiên Samsung được
kết luận Người báo `Linux armv81` và GPU Mali, worker khớp với trang. Không tìm được tài liệu nào mô tả cơ chế
phía Samsung, nên chưa thể khẳng định đây là tính năng của trình duyệt. Nhưng Fingerprint (thứ đã gắn cờ 99%
số BOT của DATACAT) không gắn cờ phiên nào trong nhóm này, và một phần đáng kể có tương tác thật.

## Thay đổi

Trên Android, khi neo môi trường duy nhất là worker báo renderer khác trang và `PLATFORM_SPOOFED` cũng có
mặt, hai điều đó chỉ tính là **một** mâu thuẫn. Kết quả: phiên vẫn bị chặn kết luận Người (Nghi vấn, hoặc
Nghi vấn chốt khi quá ít tương tác), nhưng không còn đủ để kết luận BOT. Có thêm một mâu thuẫn độc lập (webdriver
bị sửa, font máy tính, chạm 0 ms, một họ môi trường khác…) thì vẫn kết luận như cũ. iPhone giữ nguyên
policy 32 (94% khớp với Fingerprint).

Ước lượng trên lịch sử: khoảng 342 phiên Android chuyển từ BOT sang Nghi vấn, trong đó Fingerprint chỉ gắn cờ
38/132 phiên có kết quả tham chiếu. Độ chính xác của mức BOT tăng; các phiên này vẫn không được coi là người.

## Còn mở

Cần kiểm chứng trên một máy Samsung thật bằng Samsung Internet
(`https://silkmoon.datacat.io.vn/?dc_study=samsung-test-1`): nếu phiên đó báo đúng cặp lệch này thì đây là
hành vi của trình duyệt, và có thể cân nhắc bỏ hẳn tín hiệu này cho Samsung Internet.
