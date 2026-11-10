# Xuất báo cáo

Mục **Báo cáo** của dashboard xuất ba dạng, cùng kỳ (24 giờ, 7 ngày, 30 ngày) và cùng phạm vi
trang đang chọn:

| Nút | Tệp | Dùng khi |
|---|---|---|
| In / Lưu PDF | Báo cáo A4 (chọn "Lưu dưới dạng PDF" trong hộp thoại in) | Gửi khách hàng, lưu hồ sơ |
| Xuất Excel | `DC-BC-<ngày>-<phạm vi>-<kỳ>.xlsx`, nhiều sheet có định dạng | Phân tích, đối chiếu với log của nhà mạng |
| Tải CSV | Mọi phiên của kỳ, một dòng một phiên | Nạp vào công cụ khác |

## Báo cáo PDF

Mọi thông tin đều ở dạng bảng. Thứ tự từ trên xuống:

1. Logo, tiêu đề, kỳ báo cáo và phạm vi.
2. Các ô tổng hợp.
3. So với kỳ trước: kỳ này, kỳ trước, thay đổi. Màu đỏ là thay đổi bất lợi.
4. Lưu lượng theo ngày (theo giờ với kỳ 24 giờ): biểu đồ cột chồng và bảng.
5. Theo trang: số phiên theo kết luận của từng trang. Chỉ có khi xem tất cả trang và có từ hai
   trang trở lên.
6. Theo thiết bị: số phiên theo kết luận của từng hệ điều hành.
7. Nguyên nhân bị đánh dấu.
8. Nguồn bot: theo quốc gia, theo nhà mạng, theo địa chỉ IP. Cột ghi chú chỉ xuất hiện khi có IP
   không nên chặn: crawler đã xác minh, hoặc IP có cả người thật.
9. Click theo Token 1, khi trang có tham số `clickid` hoặc `t1`.
10. Danh sách click: thời gian, Click ID, Token 1, kết luận, lý do, IP. Mới nhất trước.
11. Danh sách phiên bot và nghi vấn: thời gian, kết luận, lý do, IP, quốc gia, nhà mạng, thiết bị.

Hai danh sách cuối in tối đa 1.000 dòng mỗi danh sách. Nếu dài hơn, dòng cuối ghi số dòng còn lại;
các dòng đó có trong tệp Excel. Danh sách dài được chia sang trang sau và lặp lại dòng tiêu đề.

Chân trang chỉ có số trang.

## Tệp Excel

| Sheet | Nội dung |
|---|---|
| Tóm tắt | Chỉ tiêu kỳ này, kỳ trước, thay đổi |
| Theo ngày / Theo giờ | Số phiên theo kết luận, dòng Cộng |
| Theo trang | Số phiên theo kết luận của từng trang (khi xem tất cả trang) |
| Theo thiết bị | Số phiên theo kết luận của từng hệ điều hành |
| Nguyên nhân | Nguyên nhân bị đánh dấu, tỉ trọng |
| IP bot | IP bot nhiều nhất, khuyến nghị; bot theo quốc gia và nhà mạng |
| Theo Token 1 | Kết luận theo Token 1 (khi có click) |
| Danh sách click | Từng click: Click ID, Token 1, kết luận, lý do, thời gian, IP |
| Chi tiết phiên | Mọi phiên của kỳ, tối đa 50.000 |

**Định dạng:**
- Mỗi sheet mở đầu bằng tiêu đề và thông tin tài liệu.
- Số có phân cách hàng nghìn, tỉ lệ dạng phần trăm. Ngày giờ là kiểu ngày của Excel, theo múi giờ
  người xem.
- Dòng tiêu đề được cố định; bảng dài có bộ lọc.
- Bảng rộng in ngang trang, vừa một trang chiều ngang. Chân trang có số trang.

PDF và Excel dùng chung danh sách phiên của kỳ (`GET /api/v1/reports/sessions`), chỉ tải một lần
cho mỗi lần xem báo cáo.

Tệp được tạo ngay trên trình duyệt bằng ExcelJS 4.4.0. Thư viện tải từ jsdelivr ở lần xuất đầu
tiên, nên server không cần thêm thư viện.

## Số liệu

Dashboard lấy số liệu từ `GET /api/v1/reports/summary?days=&site=&utc_offset_minutes=`. Ngoài các
số của kỳ, endpoint trả thêm:

| Trường | Nội dung |
|---|---|
| `previous_totals` | Kỳ liền trước |
| `timeline` | Theo ngày, hoặc theo giờ với kỳ 24 giờ |
| `generated_at` | Thời điểm lập |
| `decision_policy_version`, `model_bundle_id` | Phiên bản mô hình |
