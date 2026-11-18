# Policy 49: autoclick phải là cú ấn của máy

Ngày 19/11/2026. `DECISION_POLICY_VERSION = "49"`, `TOUCH_ANALYSIS_VERSION = "touch_v3"`.
Code: `core_ml/features/touch.py` (`_machine_presses`, `_autoclick_group`, `autoclick_taps_v2`).

## Phát hiện

Luật `autoclick_taps_v1` (policy 19) kết luận BOT khi có từ 5 lần chạm trong phạm vi 0,5 px quanh một điểm, với
khoảng cách giữa các lần đều nhau (CV < 0,10). Luật này được kiểm trên BrainRun (2.070 thiết bị người): không cửa sổ
người nào khớp. Nhưng BrainRun là trò chơi với mục tiêu thay đổi liên tục, không có cảnh một người bấm dồn dập vào
cùng một nút.

Đối chiếu với Fingerprint (replay 3.674 phiên, 18/11): cả 6 phiên luật này kết luận BOT đều ở trang Spin (có nút
quay để bấm liên tục), và Fingerprint thấy sạch cả 6. Xét nhóm chạm khớp luật trong từng phiên:

| Phiên | Kiểu tiếp xúc khác nhau | Thời gian ấn (trung vị, CV) | Nhận định |
| --- | --- | --- | --- |
| 1 | 4 | 95 ms, 0,04 | Người: kích thước tiếp xúc ngón tay đổi theo từng lần |
| 2 | 6 | 78 ms, 0,27 | Người |
| 3 | 3 | 43 ms, 0,15 | Người |
| 4 | 1 (máy không có cảm biến) | 95 ms, 0,22 | Người: thời gian ấn dao động như người |
| 5 | 1 | 79 ms, 0,18 | Người |
| 6 (iPhone) | 1 | 9 ms, 0,13 | Máy: ấn 4–13 ms (người nhanh nhất đo được 47–80 ms) |

Người gõ nhịp đều tự nhiên có CV khoảng 3–8%. Màn hình cảm ứng độ phân giải thấp cho toạ độ trùng nhau, nên chỉ hai
điều kiện "cùng điểm" và "đều nhịp" không đủ phân biệt người với máy.

## Thay đổi

Nhóm chạm cùng điểm, đều nhịp chỉ bị kết luận là autoclick khi các cú ấn **giống máy**. Phải thoả cả hai điều kiện:
1. **Cùng một kiểu tiếp xúc ở mọi lần:** bán kính và lực ấn giống hệt nhau. Ngón tay thật thay đổi ở mọi màn hình có
   báo các giá trị này.
2. **Thời gian ấn của máy:** cố định (CV < 0,05) hoặc dưới 20 ms. Autoclicker trên Android phát cử chỉ giống hệt nhau
   với thời gian ấn chính xác.

Luật cũ chỉ có thể bắt ít đi chứ không bắt thêm. Trên BrainRun, luật cũ không bắt nhầm người nào, nên luật mới cũng
vậy. `touch.metronomic_taps` vẫn ghi lại các nhóm nhịp đều để nghiên cứu.

Release gate: đóng băng `MOBILE_RULE_GATE_V48`, thêm 3 fixture:
- người bấm dồn dập trên máy có cảm biến tiếp xúc → Người;
- người bấm dồn dập trên máy không có cảm biến → Người;
- iPhone ấn 4–13 ms, tiếp xúc cố định, đều nhịp → BOT.

Fixture autoclick cũ (ấn 40 ms cố định) vẫn là BOT.

## Kiểm chứng

Trên 6 phiên Spin: 5 phiên không còn bị coi là autoclick, phiên iPhone vẫn là BOT. Kết quả replay toàn bộ ghi ở commit.

## Không làm

- Không bỏ luật: autoclicker thật (thời gian ấn và tiếp xúc cố định) vẫn bị bắt.
- Không nới các luật chạm tự động khác (`ZERO_TIME_TAPS`, `SYNTHETIC_CONTACT`, `apple_synthetic_touch_v1`).
