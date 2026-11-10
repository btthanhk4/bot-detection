# Model release v28: phần cứng máy chủ là một mâu thuẫn nữa

Bundle: `40823b69b4984e6381d15330d51b0435`. Policy: `28`. Collector: 1.11.1 (không đổi). Mô hình chuột train lại cùng dữ liệu và seed.

## 1. Những phiên policy 27 còn để NGHI VẤN hoặc chưa đủ dữ liệu

Bản này xuất phát từ việc rà các phiên Downloader mà policy 27 chưa kết luận BOT (2026-11-10).
Đếm lại toàn bộ phiên đã lưu, chia theo bằng chứng mỗi nhóm có:

| Nhóm | Số phiên | Bằng chứng | Xử lý |
|---|---|---|---|
| Máy tính báo 640 nhân CPU, WebGL chạy SwiftShader (GPU phần mềm), IP gia đình, không di chuột | 370 | `SERVER_CPU` + nhóm môi trường GPU | **BOT (policy 28)** |
| WebView "Android TV" (BRAVIA, MiTV, AQUOS, SWTV...) có chạm 0 ms | 512 | `WEBDRIVER_TAMPERED` + `ZERO_TIME_TAPS` | Chờ kiểm chứng trên điện thoại thật |
| WebView "Android TV" gần như không thao tác | 399 | Chỉ `WEBDRIVER_TAMPERED` | NGHI VẤN |
| Điện thoại có chạm 0 ms | 197 | `WEBDRIVER_TAMPERED` + `ZERO_TIME_TAPS` | Chờ kiểm chứng trên điện thoại thật |
| Điện thoại gần như không thao tác | 157 | Chỉ `WEBDRIVER_TAMPERED` | NGHI VẤN |
| iPad (Safari chế độ máy tính) với chạm bán kính 1, lực 1 (giá trị mặc định của CDP) | 58 | Chỉ `SYNTHETIC_CONTACT` | NGHI VẤN, chờ kiểm chứng trên iPad thật |
| Máy tính không di chuột, không bằng chứng | khoảng 150 | Không có | Chưa đủ dữ liệu (đúng: không có gì để chấm) |

## 2. Thay đổi

`forged_browser_v1` nay tính thêm nhóm bằng chứng môi trường "neo" làm một mâu thuẫn độc lập.
Nhóm neo gồm headless, GPU và quyền thông báo, giống các nhóm neo của `environment_tampering_v1`.
Phiên có mã này cộng thêm một mã giả mạo (`UA_POINTER_MISMATCH`, `WEBDRIVER_TAMPERED`, `SERVER_CPU`)
thì kết luận BOT.

- **Kiểm chứng trên người thật:** không phiên người thật nào trên site mang bất kỳ nhóm môi
  trường nào, cũng không ai mang mã giả mạo nào. 11 phiên người thật ngày 10/11 cũng vậy.
- **Khi đứng một mình, nhóm neo không đổi gì.** Phiên không thao tác chỉ có bằng chứng môi trường
  vẫn là "chưa đủ dữ liệu", giữ nguyên quy ước của policy 10 và 12. Ví dụ: Linux không có driver
  GPU (SwiftShader, 8 nhân) mà không thao tác thì vẫn chưa đủ dữ liệu.

## 3. Ước tính trên production

Chấm lại toàn bộ phiên đã lưu bằng đúng hàm của policy 28 (chỉ đọc).

**Trang đích:** 4.058 phiên.

| | HUMAN | NGHI VẤN | Chưa đủ dữ liệu | BOT |
|---|---|---|---|---|
| Đang lưu | 335 | 1.247 | 2.282 | 194 |
| Policy 28 | 44 | 1.355 | 246 | 2.413 |

BOT mới đến từ hai luật: `synthetic_pointer_path_v1` 1.407 phiên, `forged_browser_v1` 812 phiên.

**Mọi site khác:** không phiên nào đổi kết luận.

## 4. Việc tiếp theo cần dữ liệu người thật

- **`ZERO_TIME_TAPS`** (ít nhất 2 lần chạm, mỗi lần chạm và nhả cách nhau dưới 1 ms) có thể giải
  quyết khoảng 700 phiên điện thoại và TV. Về vật lý, ngón tay chạm màn hình ít nhất vài chục ms,
  nhưng cờ này chưa được đo trên trình duyệt điện thoại thật. BrainRun có 4% lần chạm 0 ms do cách
  ứng dụng ghi. Cần vài phiên chạm nhanh trên Android và iPhone thật.
- **`SYNTHETIC_CONTACT` trên iPad** cần một phiên trên iPad thật, có và không có Apple Pencil.
- **TV có màn cảm ứng** (User-Agent là TV mà `maxTouchPoints` bằng 5 và có sự kiện chạm) cần một
  Android TV thật để biết TV thật báo gì.

## Kiểm tra

- Gate `client_forgery`: 18 fixture (thêm 2 BOT: máy chủ 640 nhân dùng SwiftShader, webdriver
  cộng màn hình headless; thêm 1 phiên Linux không có driver GPU vẫn chưa đủ dữ liệu). Gate
  policy 27 được đóng băng (`CLIENT_FORGERY_RULE_GATE_V27`). Gate policy 10 và 12 không đổi.
- Mô hình chuột: hai file trọng số giống v27 từng byte; test, rolling test và rolling validation
  không đổi.
- Bộ test Python, test collector và Ruff đạt.
