# Đề cương tóm tắt gửi giảng viên hướng dẫn

**Tên đề tài đề xuất:** Phát hiện bot trên website dựa trên dấu hiệu trình
duyệt và hành vi chuột.

**Mục tiêu:** Xây dựng prototype DATACAT nhúng vào một website và đánh giá
việc kết hợp heuristic trình duyệt, XGBoost và BiLSTM để phân biệt người thật
với các nhóm bot mục tiêu. Hệ thống trả HUMAN/SUSPECT/BOT và thông tin hỗ trợ
giải thích. SUSPECT biểu thị chưa đủ cơ sở kết luận, được đánh giá riêng.

**Phạm vi:** Chrome/Chromium desktop, bot chạy JavaScript; ba họ hành vi gồm
di chuyển tuyến tính, di chuyển theo mẫu lặp và macro click/cuộn theo tác vụ.
Các họ có thể dùng chung bộ sinh chuyển động nên phải ghi rõ cấu hình và
nguồn gốc. Không cam kết phát hiện mọi stealth bot, HTTP crawler, mobile hoặc
xác định mục đích gian lận quảng cáo.

**Câu hỏi nghiên cứu:** Sự kết hợp các thành phần có cải thiện khả năng phát
hiện trong phạm vi trên so với từng thành phần riêng, đồng thời kiểm soát
nhận nhầm người thật và tỷ lệ chưa kết luận được không? Model chuột đóng
góp bao nhiêu khi không cung cấp dấu hiệu automation?

**Phương pháp:** Dùng dataset có sẵn làm baseline/development và thu dữ liệu
trên website thực. Mục tiêu pilot là 15 người x 6 phiên và ba họ bot x 60
lượt. Nhãn lấy từ người tham gia/runner biết nguồn, không từ dự đoán model.
Chia người/config block trước khi tạo cửa sổ; khóa test mới trước khi đánh
giá cuối. Traffic tự nhiên chưa rõ nguồn giữ nhãn UNKNOWN; vendor trial là
nguồn đối chiếu tùy chọn, không là nhãn đúng tuyệt đối.

**Đánh giá:** So sánh heuristic, XGBoost, BiLSTM, fusion baseline và candidate.
Báo ma trận nhãn thật 2 lớp x kết luận 3 trạng thái, lỗi vận hành, BOT recall,
nhận nhầm người/bot, precision, SUSPECT/coverage và diễn tiến theo phiên.
Phân tích từng họ và công bố ca thất bại; không tính các cửa sổ cùng phiên
thành nhiều người độc lập. Kết quả pilot không suy rộng thành chứng nhận production.

**Sản phẩm bàn giao:** Script nhúng để thầy chạy traffic; pipeline lưu/export
và manifest nhãn; benchmark có protocol; model/bundle có phiên bản; báo cáo
thực nghiệm tái hiện được; dashboard/demo; luận văn, slide và tài liệu nguồn.

**Việc cần thống nhất:** Tên và phạm vi đề tài; website/tác vụ; hỗ trợ tiếp
cận người tham gia; tiêu chí chấm và thời hạn khi có. Dự kiến 14-20 ngày
công cho phần lõi, phụ thuộc lịch thu dữ liệu. Các số mẫu và mục tiêu model
là kế hoạch, chưa phải kết quả đạt được.

Chi tiết: [kế hoạch thực hiện](THESIS_COMPLETION_PLAN_2026-10-19.md) và
[protocol benchmark](THESIS_BENCHMARK_PROTOCOL_V1.md).
