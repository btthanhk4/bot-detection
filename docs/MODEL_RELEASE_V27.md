# Model release v27: kiểm chứng trên quỹ đạo chuột người thật

Bundle: `de33b2659f084240ab8707db36346ec8`. Policy: `27`. Collector: 1.11.1 (không đổi). Mô hình chuột train lại cùng dữ liệu và seed.

Bản này xuất phát từ 11 phiên chuột người thật trên trang đích "Downloader" và trên shop
(2026-11-10, khoảng 5–6 máy, Chrome trên Windows, macOS và Linux, màn 60 Hz và 144 Hz). Dữ liệu
được so với 1.358 phiên bot của trang đích, là những phiên có từ hai mâu thuẫn trình duyệt trở
lên và ít nhất 10 lần di chuột.

## 1. Người thật khác bot thế nào

| Đặc trưng | Người (thấp nhất – cao nhất) | Bot (p10 / p50 / p90) | Tỉ lệ bot lọt vào khoảng của người |
|---|---|---|---|
| Độ đổi hướng giữa hai bước (trung vị) | 2° – 10° | 61° / 124° / 147° | 2% |
| Bước dài (p90, tỉ lệ màn hình) | 0,004 – 0,29 | 0,65 / 0,80 / 0,94 | 0% |
| Tỉ lệ khoảng cách < 20 ms | 0,76 – 0,96 | 0 / 0 / 0,39 | 0% |
| Khoảng cách thời gian (trung vị) | 4 – 17 ms | 48 / 76 / 162 ms | 2% |
| Mẫu coalesced mỗi sự kiện | 1,09 – 3,5 | 0,06 / 0,14 / 0,25 | 0% |
| Số lần di chuột mỗi phiên | 42 – 100 | 11 / 20 / 49 | 13% |

Chuột thật gửi 60–250 mẫu mỗi giây, mỗi bước khoảng 1% màn hình và chỉ đổi hướng vài độ, nên
đường đi cong mềm. Bot gửi khoảng 13 điểm mỗi giây, mỗi điểm cách điểm trước gần nửa màn hình và
gần như quay ngược hướng. Vì vậy trên dashboard đường của bot trông như những nét thẳng dài.

## 2. Thay đổi

| Thay đổi | Lý do | Kiểm chứng |
|---|---|---|
| `UNALIGNED_POINTER` không còn chặn kết luận HUMAN, chỉ còn là cờ nghiên cứu (`research_flags`) | Cùng một laptop (AMD Radeon 780M, Chrome trên Windows) giao sự kiện chuột mỗi 17 ms ở hai phiên, nhưng mỗi 4 ms ở phiên thứ ba khi rê chuột tự do (1,33 mẫu mỗi sự kiện, khung hình đo được 60 Hz). Giả định "Chrome chỉ giao chuột một lần mỗi khung hình" không đúng | Trên toàn bộ production chỉ có đúng 1 phiên mang mã này, và đó là phiên người thật. Mã này chưa bắt được con bot thật nào |
| Luật nhảy ngẫu nhiên (`RANDOM_POINTER_JUMPS`) xét từ 10 lần di chuột thay vì 25 | Bot trên trang đích di chuột trung vị 20 lần, nên với ngưỡng 25 phần lớn chưa bao giờ được xét | Balabit (10 người, 1.676 phiên): 0 khớp trong 51.863 lần xuất có từ 10 lần di chuột trở lên. 11 người thật: 0 (tỉ lệ bước dài cao nhất 0,24, tỉ lệ quay đầu cao nhất 0,09) |
| Phiên chưa đủ 25 lần di chuột nhưng có con trỏ nhảy ngẫu nhiên thành NGHI VẤN, kết luận FINAL (`client_forgery`, bằng chứng nằm ở `client_forgery.evidence`) | Bằng chứng hành vi vẫn có giá trị trên phiên ngắn | Như dòng trên |
| `forged_browser_v1` (BOT): hai mâu thuẫn trình duyệt độc lập (`UA_POINTER_MISMATCH`, `WEBDRIVER_TAMPERED`, `SERVER_CPU`) | Ba mã đến từ ba nguồn khác nhau: User-Agent so với sự kiện thực nhận, đối tượng navigator, và phần cứng. Trình duyệt thật không tạo ra mã nào | Không người nào trên site thật mang dù chỉ một mã. 11 người thật: 0 |

Phiên có nhịp chuột thưa kiểu Remote Desktop không bị xét theo nhịp. Tỉ lệ khoảng cách < 20 ms tách
được 100% trên dữ liệu này, nhưng người dùng Remote Desktop cũng có nhịp thưa như vậy, nên không
dùng làm luật. Luật nhảy chỉ dựa vào hình học của đường đi.

## 3. Test trên 11 phiên người thật

Chạy lại từ dữ liệu đã lưu qua detector policy 27. Điểm BiLSTM/XGBoost khớp đúng giá trị đã lưu.

| | Policy 26 | Policy 27 |
|---|---|---|
| HUMAN | 9 | 10 |
| NGHI VẤN | 2 | 1 |
| BOT | 0 | 0 |

Phiên NGHI VẤN còn lại (`88c0101b`, múi giờ Asia/Krasnoyarsk, chưa xác nhận là của người dùng)
do hai mô hình chuột bất đồng: BiLSTM 0,43, XGBoost 0,001. Đây là vùng ranh giới của mô hình,
không phải lỗi của luật.

## 4. Ước tính trên production

Chấm lại mọi phiên đã lưu bằng đúng hàm của policy 27 (chỉ đọc).

**Trang đích:** 3.663 phiên.

| | HUMAN | NGHI VẤN | Chưa đủ dữ liệu | BOT |
|---|---|---|---|---|
| Đang lưu (policy cũ) | 334 | 986 | 2.271 | 72 |
| Policy 27 | 43 | 1.664 | 235 | 1.721 |

BOT mới đến từ hai luật: `synthetic_pointer_path_v1` 1.276 phiên, `forged_browser_v1` 373 phiên.
Trong 43 phiên HUMAN có khoảng 10 phiên của người dùng.

**Mọi site khác:** 226 phiên, không phiên nào đổi kết luận.

## 5. Giới hạn

- Mới có 11 phiên người thật, đều là Chrome trên máy tính. Chưa có Firefox, Safari hay điện thoại.
- Bot chuyển động tại chỗ hoặc bắn sự kiện qua CDP mỗi 4 ms mà không để lộ dấu hiệu nào khác giờ
  không còn bị `UNALIGNED_POINTER` giữ lại. Bot dùng Playwright hoặc Puppeteer vẫn lộ `CDP_ATTACHED`.
- Khoảng 1.200 phiên điện thoại trên trang đích chỉ có một mâu thuẫn (webdriver bị sửa, có khi kèm
  chạm 0 ms), nên vẫn là NGHI VẤN. `ZERO_TIME_TAPS` chưa được kiểm chứng trên người thật nên không
  dùng để kết luận BOT.
- Bot báo `getCoalescedEvents` có nhưng gần như luôn trả rỗng (0,14 mẫu mỗi sự kiện). Bot lại khai
  Safari, mà chưa có phiên Safari thật nào để kiểm chứng, nên chưa dùng làm luật.

## Kiểm tra

- Gate:
  - `desktop_risk`: 43 fixture. Fixture `UNALIGNED_POINTER` chuyển sang HUMAN, thêm phiên laptop 4 ms.
  - `synthetic_device`: 20 fixture, thêm BOT có 15 lần di chuột.
  - `client_forgery`: 15 fixture, thêm 3 BOT `forged_browser_v1`, phiên ngắn có nhảy ngẫu nhiên
    và tay nhanh lấy mẫu thưa.
  - Gate của policy 26 được đóng băng (`*_V26`).
- Mô hình chuột: hai file trọng số giống v26 từng byte; test, rolling test và rolling validation
  không đổi (precision 1,000, recall 0,909, FPR 0, 0 phiên người bị gán BOT).
- 981 test Python, test collector và Ruff đạt.
