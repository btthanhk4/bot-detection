# Rà soát điểm yếu (2026-10-28)

Rà theo bốn nhóm: kẻ tấn công biết luật, người thật dễ bị bắt nhầm, tích hợp và kiến trúc,
logic quyết định. Mỗi mục ghi rõ đã thử thật hay chỉ suy luận từ code. Kịch bản thử nằm trong
scratchpad (`realworld.js`, `prov_probe.js`) và được ghi lại thành fixture phát hành khi có sửa.

## 1. Đã sửa trong policy 23 (collector 1.9.0)

| Điểm yếu | Cách thử | Trước | Sau |
|---|---|---|---|
| Script sửa `getCoalescedEvents` để trả về chính sự kiện hai lần | Playwright + init script, chuột giống người | HUMAN | NGHI VẤN (`POINTER_API_TAMPERED`) |
| Script xóa `getCoalescedEvents` | như trên | HUMAN | NGHI VẤN (`POINTER_API_TAMPERED`) |
| Di chuột thưa (mỗi bước 110–160 ms) không còn khoảng cách để đo nên luật khóa khung hình bỏ qua | patchright | NGHI VẤN (do LSTM, may mắn) | NGHI VẤN (`FRAME_LOCKED_POINTER`) |
| Gửi payload "người thật" bằng script, không có trình duyệt | Python `urllib` tới `/api/v1/detect` | HUMAN | NGHI VẤN (`NON_BROWSER_REQUEST`) |
| Trang tải nặng làm khung hình đo được dài ra, có thể khiến người thật trên máy yếu bị gắn `UNALIGNED_POINTER` | suy luận; test đơn vị với 1/3 khung 50 ms | (rủi ro) | đo phân vị 25% thay cho trung vị |
| Listener bị gọi lặp để thổi phồng số `pointerrawupdate` | test đơn vị | (rủi ro) | bỏ trùng theo thời gian sự kiện |

Cơ sở của bản vá `getCoalescedEvents`: đo bằng input hệ điều hành trên Chrome, mọi mẫu gộp đều là
sự kiện trusted, không bao giờ là chính sự kiện gốc, và có thời gian tăng dần (khoảng 1% trùng
mốc thời gian). JavaScript trên trang không tạo được sự kiện trusted mới. Collector 1.9 chỉ đếm
mẫu trusted mới hơn mẫu trước, đếm riêng mẫu trùng sự kiện gốc, và báo khi `getCoalescedEvents`
hoặc `requestAnimationFrame` không còn là hàm gốc.

## 2. Đã kiểm tra, không có vấn đề

| Trường hợp | Kết quả |
|---|---|
| Cốc Cốc (input hệ điều hành) | HUMAN, 1,73–2,52 mẫu gộp, không mã rủi ro |
| MacBook M4 trên site thật, Chrome Energy Saver 30 khung/giây | HUMAN, 3,56 mẫu gộp, khoảng cách chuột 33 ms bằng khung hình |
| Edge trên Windows (site thật) | HUMAN, 2,20 mẫu gộp |
| 5 biến thể patchright giống người, 2 cách bơm dồn | NGHI VẤN |
| Script gõ phím (Playwright, Puppeteer, Selenium, có hoặc không có delay) | BOT; người thật theo Aalto: 0 ở hai mã mới |
| Chạm-để-click trên touchpad (Mendeley, phiên Mac) | Không bắn luật click giả, nhờ điều kiện trúng tâm |
| Người thật độc lập (Balabit, 1.676 phiên) | 98,6% cửa sổ HUMAN, không phiên nào kết thúc BOT |

## 3. Còn mở: cần thiết kế hoặc thêm dữ liệu

Xếp theo mức nghiêm trọng.

1. **Toàn vẹn phía client (cao).** Collector là JavaScript trên trang và được chèn với biến toàn
   cục `_bc`. Kẻ tấn công có thể sửa instance, hook `fetch`/`sendBeacon` để viết lại payload,
   hoặc tự gửi payload kèm đủ header. Bản vá ở mục 1 chỉ loại các cách rẻ nhất. Hướng xử lý của
   sản phẩm thương mại: collector được làm rối và có kiểm tra toàn vẹn, payload có chữ ký thay đổi
   theo phiên, đối chiếu phía server (dấu vân tay TLS JA4 của request telemetry so với trình duyệt
   tự khai, thời điểm telemetry so với log request trang).
2. **Fail-open khi tích hợp (cao).** SilkMoon chỉ giám sát, không dùng kết quả để chặn. Bot chặn
   `bot-collector.js` hoặc request telemetry thì không bao giờ có phiên. Hướng: đối chiếu log nginx
   (lượt xem trang) với phiên telemetry để đếm lượt truy cập "không giám sát được"; hành động nhạy
   cảm (đặt hàng, đăng ký) đòi token kết luận do server ký.
3. **Bot dùng input hệ điều hành trên máy thật (cao với click fraud).** pyautogui, thiết bị phần
   cứng giả chuột, phone farm điều khiển bằng ADB với cử chỉ ngẫu nhiên: input là thật, trình duyệt
   là thật. Chỉ mô hình hành vi và tín hiệu nhiều phiên mới bắt được. Hiện chưa có tín hiệu
   tần suất (số phiên theo fingerprint thiết bị, IP, ASN theo thời gian) hay phát hiện phát lại
   quỹ đạo giữa các phiên.
4. **`/api/v1/detect` trả kết luận cho người gọi ẩn danh (trung bình).** Chế độ `minimal` giấu điểm
   và bằng chứng nhưng vẫn trả `verdict`, nên bot có thể thử đi thử lại để dò cách né (giới hạn
   bởi rate limit theo IP). Hướng: không trả kết luận cho trình duyệt; backend của site hỏi kết
   luận bằng thông tin xác thực. `BOT_TELEMETRY_ORIGINS` cũng chưa được đặt trên production.
5. **Luật khóa khung hình chỉ xét Windows (trung bình).** Bot CDP giống người chạy trên máy
   Linux hoặc Mac thật, không sửa API và không bơm dồn, vẫn có thể được HUMAN. Phiên Mac thật
   (3,56 mẫu) cho thấy có thể mở rộng sang macOS; cần thêm vài phiên Mac và Linux ở màn ≤ 83 Hz.
6. **Bot chỉ cuộn, chỉ gõ, hoặc dùng `fill()` (thấp).** Luôn "chưa đủ dữ liệu", giống người không
   di chuột. Đây là thiếu phạm vi chứ không phải kết luận sai.
7. **Một cửa sổ BOT khóa cả phiên (thấp).** Trên Balabit có 1/1.676 phiên người từng có một cửa sổ
   BOT (đoạn ghi qua Remote Desktop ở 9 Hz). Trên production, kết luận BOT của ensemble bị khóa cho
   cả phiên.
8. **Script gõ phím đặt delay 12–40 ms hoặc ngẫu nhiên từng phím (thấp).** Không bị luật gõ phím
   bắt; dựa vào các tín hiệu khác.
9. **Trang sau ghi đè NGHI VẤN (thấp).** Một trang có kết luận HUMAN thay thế NGHI VẤN của trang
   trước trong cùng phiên. Với policy 23, mọi trang có ít nhất 25 lần di chuột đều được xét lại
   bằng cùng các luật, nên bot khó tạo một trang HUMAN.
10. **Nhóm người chưa thử.** Brave (làm nhiễu fingerprint, có thể tạo mâu thuẫn giữa trang và Worker),
    Firefox với `resistFingerprinting`, Safari desktop, Remote Desktop, máy ảo, Linux ở 60 Hz. Mã
    `desktop_risk` được lưu cho mọi phiên để theo dõi.
11. **IP.** Chỉ nhận diện dải IP của nhà cung cấp cloud; proxy dân cư không bị phát hiện. Chưa đối
    chiếu múi giờ trình duyệt với vị trí IP (bắt nhầm người dùng VPN nếu dùng làm luật).
