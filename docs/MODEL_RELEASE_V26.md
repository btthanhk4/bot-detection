# Model release v26: chuột nhảy ngẫu nhiên và trình duyệt tự mâu thuẫn

Bundle: `af5221be5dc14e2a836e87c4bd06a62a`. Policy: `26`. Collector: 1.11.1 (không đổi). Mô hình chuột train lại cùng dữ liệu và seed.

Bản này xuất phát từ phân tích traffic "Downloader" (2026-11-10). Đây là trang đích quảng cáo
"FILE READY / YOUR FILE IS READY TO DOWNLOAD", traffic đến từ các mạng quảng cáo pop/redirect.

## 1. Vì sao policy 25 bỏ sót

Lúc phân tích có 3.283 phiên. Policy 25 kết luận HUMAN 294 phiên, trong đó 265 phiên mang ít nhất
một dấu hiệu dưới đây.

| Dấu hiệu | Trang đích | Người thật trên shop |
|---|---|---|
| Khoảng cách thời gian giữa hai lần di chuột (trung vị) | 80 ms | 17 ms |
| Độ dài một bước (trung vị, theo tỉ lệ màn hình) | 0,44 | 0,01 |
| Tỉ lệ bước dài hơn 15% màn hình | 87% | 1,4% |
| Số mẫu coalesced mỗi lần di chuột | 0,16 | 2,06 |

Ba nguyên nhân:

- **Mô hình chuột không nhận ra kiểu bot này.** Con trỏ không đi theo đường mà nhảy giữa các
  điểm ngẫu nhiên. Đây là kiểu dữ liệu không có trong tập huấn luyện. Trên các phiên HUMAN sai,
  BiLSTM cho trung vị 0,085, XGBoost cho 0,007.
- **`POINTER_API_TAMPERED` chỉ xét Chromium.** Bot tự khai Safari 9 nên lọt qua.
- **`navigator.webdriver` bị sửa không chặn được HUMAN.** Nhóm `NATIVE_PATCH` không phải nhóm
  neo, nên một mình nó không giữ lại kết luận HUMAN.

## 2. Tín hiệu mới (`core_ml/features/client_forgery.py`)

| Mã | Điều kiện | Kiểm chứng trên người thật |
|---|---|---|
| `RANDOM_POINTER_JUMPS` | Một lần xuất có ít nhất 25 lần di chuột, và ít nhất 40% số bước dài hơn 15% màn hình. Thêm nữa, phải có ít nhất 5 cặp bước dài liền nhau, và ít nhất một nửa số cặp đó quay ngược hướng (góc giữa hai bước lớn hơn 90°) | **Balabit**: 10 người, 1.676 phiên Remote Desktop lấy mẫu khoảng 10 Hz, phát lại thành 41.899 lần xuất của collector. Kết quả: 0 lần khớp. Bỏ điều kiện quay đầu thì 15 phiên khớp (chỉ xét bước dài ≥ 30%). Người thật trên shop: 0 |
| `UA_POINTER_MISMATCH` | User-Agent khai Safari < 13 hoặc Chrome < 55 (những bản chưa có Pointer Events), nhưng collector vẫn nhận `pointermove` thật (`isTrusted`, `pointerType = mouse`) | Trình duyệt cũ không phát ra được sự kiện mình không hỗ trợ. Polyfill chỉ tạo được sự kiện `isTrusted = false`, mà collector bỏ qua loại này. WebView Android, Chrome/Firefox trên iOS có token `Version/` cũ nhưng không bị tính. Người thật trên shop: 0 |
| `WEBDRIVER_TAMPERED` | `navigator.webdriver` bị định nghĩa lại trên chính đối tượng navigator, hoặc bị gán getter không phải hàm gốc, hoặc bị xóa trên Chromium | Plugin stealth làm việc này để giấu dấu vết tự động hóa; trình duyệt thật không làm. Extension cũng có thể làm, nên mã này chỉ chặn HUMAN chứ không kết luận BOT. Người thật trên shop: 0 |
| `SERVER_CPU` | Máy tính báo hơn 64 nhân logic | Trang đích có 371 phiên, tất cả là Linux x86_64 báo 640 nhân. Máy trạm 128 luồng có tồn tại, nên mã này không kết luận BOT. Người thật trên shop: 0 |

Không mã nào đủ để kết luận BOT khi đứng một mình. Mỗi mã chỉ chặn kết luận HUMAN, kết quả là
NGHI VẤN (`desktop_risk`, hoặc `mobile_risk` trên điện thoại).

## 3. Luật quyết định mới

- **`synthetic_pointer_path_v1` (BOT).** Điều kiện: con trỏ nhảy ngẫu nhiên, và đồng thời trình
  duyệt tự mâu thuẫn. "Tự mâu thuẫn" nghĩa là có một trong ba mã còn lại, hoặc có bất kỳ nhóm bằng
  chứng môi trường nào trừ IP cloud. Hai bằng chứng này độc lập với nhau: một bên là hành vi,
  một bên là môi trường. Luật nằm ngay sau các luật input giả lập (`decision_basis = synthetic_input`).
- **`client_forgery` (NGHI VẤN, FINAL).** Áp dụng cho phiên chưa đủ thao tác để chấm hành vi mà
  trình duyệt lại tự mâu thuẫn. Trước đây phiên kiểu này là "chưa đủ dữ liệu", giờ thành NGHI VẤN
  có kết luận. IP cloud đứng một mình không được tính.
- **Gateway SilkMoon.** Ở endpoint nghiêm (chat AI, AR), `client_forgery` bị chặn giống
  `desktop_risk` và `mobile_risk`.

## 4. Ước tính trên production

Chấm lại toàn bộ phiên đã lưu bằng đúng hàm của policy 26 (chỉ đọc, dùng các trường đã lưu).

**Trang đích:** 3.410 phiên.

| Policy 25 | Policy 26 | Số phiên |
|---|---|---|
| Chưa đủ dữ liệu | NGHI VẤN (`client_forgery`) | 1.948 |
| NGHI VẤN | NGHI VẤN | 724 |
| HUMAN | BOT (`synthetic_pointer_path_v1`) | 239 |
| Chưa đủ dữ liệu | Chưa đủ dữ liệu | 227 |
| NGHI VẤN | BOT | 159 |
| BOT | BOT | 45 |
| HUMAN | NGHI VẤN | 36 |
| HUMAN | HUMAN | 32 |

Tổng cộng: HUMAN giảm từ 307 xuống 32, BOT tăng từ 45 lên 443.

**Mọi site khác:** 226 phiên. Không phiên HUMAN nào mang mã mới. Có 10 phiên mang `SERVER_CPU`
hoặc `WEBDRIVER_TAMPERED`, và cả 10 đều đã là BOT từ trước.

## 5. Loại trang có ảnh hưởng gì

- **Shop (SilkMoon).** Người dùng ở lại nhiều phút, di chuột liên tục giữa sản phẩm, giỏ hàng và
  form. Mô hình chuột có đủ dữ liệu để chấm.
- **Trang đích quảng cáo.** Phiên kéo dài trung vị 1 giây, trang chỉ có một nút. Đa số phiên không
  đủ 25 lần di chuột, nên trước đây chỉ dừng ở mức "chưa đủ dữ liệu". Với loại trang này, bằng chứng
  từ môi trường trình duyệt quan trọng hơn hành vi. Vì vậy policy 26 cho phép kết luận NGHI VẤN
  ngay cả khi không có hành vi để chấm.

## 6. Giới hạn

- Bot nhảy con trỏ nhưng môi trường sạch, hoặc chỉ dùng IP cloud: chỉ là NGHI VẤN, không thành BOT.
- Bot đi theo đường liền (Bézier, ghost-cursor) thì không khớp `RANDOM_POINTER_JUMPS`. Loại này
  vẫn do mô hình chuột và các luật input chấm.
- Múi giờ lệch với quốc gia của IP (40% phiên IP Mỹ trên trang đích) chưa được dùng, vì người dùng
  VPN cũng lệch như vậy.
- Kiểm chứng trên người thật cho ba mã môi trường mới dựa vào phiên trên shop, nên mẫu còn nhỏ
  (11 phiên HUMAN tại thời điểm đo). Riêng `RANDOM_POINTER_JUMPS` được kiểm chứng trên Balabit
  (1.676 phiên).

## Kiểm tra

- Gate mới và gate thay đổi:
  - `desktop_risk`: 42 fixture (thêm 9). Gồm người thật nhanh tay lấy mẫu thưa kiểu Balabit,
    Safari 17 và máy 64 nhân, cả ba vẫn HUMAN.
  - `synthetic_device`: 19 fixture (thêm 3 BOT `synthetic_pointer_path_v1`).
  - `mobile`: 27 fixture (thêm 2).
  - `client_forgery`: 9 fixture, gate mới.
  - Các gate của policy 25 được đóng băng (`*_V25`, `*_V24`, `*_V22`).
- Mô hình chuột: train lại cùng dữ liệu, cùng seed, ra `behavioral_lstm.pt` và `tabular_model.joblib`
  giống v25 từng byte. Chỉ manifest đổi.
- Số liệu không đổi so với v25:
  - Test: precision 1,000, recall 0,909, FPR 0.
  - Rolling test: 0 phiên người bị gán BOT, 0 phiên bot bị gán HUMAN, 1.255/24.000 cửa sổ của
    người là NGHI VẤN.
  - Rolling validation: 413/14.000 cửa sổ của người là NGHI VẤN.

  M4D không có con trỏ nhảy, cũng không có dấu hiệu môi trường giả, nên luật mới không chạm tới.
- 969 test Python, test collector và Ruff đạt.
