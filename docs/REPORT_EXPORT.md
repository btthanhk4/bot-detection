# Xuất báo cáo

Mục **Báo cáo** của dashboard xuất ba dạng, cùng kỳ (24 giờ, 7 ngày, 30 ngày) và cùng phạm vi
trang đang chọn:

| Nút | Tệp | Dùng khi |
|---|---|---|
| In / Lưu PDF | Báo cáo A4 (chọn "Lưu dưới dạng PDF" trong hộp thoại in) | Gửi khách hàng, trình ký, lưu hồ sơ |
| Xuất Excel | `DC-BC-<ngày>-<phạm vi>-<kỳ>.xlsx`, nhiều sheet có định dạng | Phân tích, đối chiếu với log của nhà mạng |
| Tải CSV | Mọi phiên của kỳ, một dòng một phiên | Nạp vào công cụ khác |

## Báo cáo PDF

Bố cục theo kiểu báo cáo quản trị (MIS) của ngân hàng và tổ chức lớn:

- **Bảng kiểm soát tài liệu.** Mã báo cáo, kỳ báo cáo, phạm vi, ngày lập, phiên bản mô hình
  (policy và bộ mô hình), phân loại **Nội bộ**.
- **1. Tóm tắt điều hành.** Các ô chỉ tiêu chính, nhận định chính được viết tự động từ số liệu, và
  Bảng 1 so sánh với kỳ liền trước cùng độ dài. Mũi tên ▲/▼ cho biết tăng hay giảm, màu đỏ là biến
  động bất lợi, ví dụ bot tăng.
- **2. Diễn biến lưu lượng.** Hình 1 (biểu đồ cột chồng, dạng vector) và Bảng 2 số phiên theo ngày,
  hoặc theo giờ với kỳ 24 giờ. Ngày giờ theo múi giờ của người xem.
- **3. Nguyên nhân phiên bị đánh dấu.**
- **4. Nguồn phát sinh bot.** Theo quốc gia, theo nhà mạng, và IP bot nhiều nhất, kèm khuyến nghị
  chặn hay không chặn. Không chặn khi đó là crawler đã xác minh, hoặc IP dùng chung có người thật.
- **5. Click quảng cáo theo Token 1.** Chỉ có khi trang mang tham số `clickid`/`t1`.
- **Phương pháp, định nghĩa và giới hạn.**
- **Khối ký duyệt.** Người lập, Người kiểm tra, Phê duyệt.

**Quy ước chung:**
- Bảng và hình được đánh số, có đơn vị tính.
- Đầu trang (từ trang 2) có tên báo cáo và mã báo cáo. Chân trang có "Tài liệu nội bộ", thời điểm
  lập và "Trang X / Y".

## Tệp Excel

| Sheet | Nội dung |
|---|---|
| Tóm tắt | Chỉ tiêu kỳ này, kỳ trước, thay đổi; nhận định chính |
| Theo ngày / Theo giờ | Số phiên theo kết luận, dòng Cộng |
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
