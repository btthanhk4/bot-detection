# Model release v25: người thật trên site thật, bot tìm kiếm, IP dùng chung

Bundle: `e9ac58496c9246db87b28570dd0396cb`. Policy: `25`. Collector: 1.11.1. Mô hình chuột train lại cùng dữ liệu và seed.

Xuất phát từ rà soát trường hợp góc trên production (2026-10-29). Mỗi kịch bản người thật dùng
Chrome thật không tự động hóa, chuột điều khiển ở mức hệ điều hành (SendInput 125 Hz), gắn đúng
thẻ khách hàng (`data-datacat`, async). Script: scratchpad `audit/fp_matrix.js`.

## 1. Người thật bị bắt nhầm (đã sửa)

| Trường hợp | Trước (policy 24) | Nguyên nhân | Sau |
|---|---|---|---|
| Site có Sentry (thư viện theo dõi lỗi phổ biến) | NGHI VẤN (`ENVIRONMENT_EVIDENCE`, `CDP_ATTACHED`) | Sentry bọc `console.debug` và đọc `Error#name` khi ghi breadcrumb, nên đầu dò CDP thấy 2 lần đọc như khi có DevTools. Sentry còn sửa `Function.prototype.toString`, nên nhóm NATIVE_PATCH bật | HUMAN |
| Chrome tắt tăng tốc phần cứng (Windows) | NGHI VẤN (`ENVIRONMENT_EVIDENCE`) | WebGL chạy qua WARP ("Microsoft Basic Render Driver"), vốn bị tính là GPU phần mềm | HUMAN |
| Người mở nhiều tab sản phẩm (≥ 30 trong một giờ) | NGHI VẤN (`DEVICE_VELOCITY`) | Mỗi tab là một phiên; luật đếm phiên | Đếm trình duyệt, không đếm tab |

Với gateway SilkMoon, hai trường hợp đầu còn bị chặn ở endpoint nghiêm (chat AI, AR).

### Cách sửa

- **Collector 1.11, `pristine.js`:** lấy `console`, `Function.prototype.toString` và
  `requestAnimationFrame` từ một iframe trống cùng origin tạo tạm rồi gỡ ngay. Thư viện của trang
  không chạm tới các bản này.
  - Đầu dò CDP vẫn bắt Playwright/Puppeteer (3 lần đọc).
  - Kiểm tra hàm gốc nhìn xuyên qua `toString` bị sửa, nên stealth giấu bản vá navigator kém đi.
  - Đo khung hình gọi `requestAnimationFrame` sạch trên cửa sổ chính, nên script bọc
    `requestAnimationFrame` để giả màn 144 Hz không né được luật khóa khung hình.
  - Trang bị `sandbox` không tạo được iframe thì dùng bản của trang như trước.
- **`toStringPatched` không còn là bằng chứng:** Sentry và zone.js (Angular) đều sửa hàm này.
  `inputApiPatched` chỉ còn xét `getCoalescedEvents`; `requestAnimationFrame` bị bọc chỉ ghi
  nhận (`rafWrapped`).
- **WARP:** dưới User-Agent Windows là bình thường. Dưới User-Agent khác (mâu thuẫn) hoặc từ IP
  cloud thì vẫn tính như trước (`CLOUD_SOFTWARE_GPU`).
- **`DEVICE_VELOCITY`:** collector lưu một mã ngẫu nhiên trong localStorage của site
  (`datacat_device`). API đếm số mã khác nhau, tức số trình duyệt, theo dấu vân tay và IP trong
  một giờ. Các tab của một trình duyệt tính là một; farm xóa dữ liệu sau mỗi lượt vẫn tăng đều.

## 2. Bot tìm kiếm và IP không nên chặn (mới)

Trên production đã có 2 phiên Googlebot thật (66.249.64.x), và lý do hiển thị khi đó là "GPU phần mềm".

- Dải IP công bố chính thức của Google, Bing, Apple, OpenAI và Perplexity được tải về
  `core_ml/data/crawler_ip_ranges.json` (`python -m core_ml.refresh_crawler_ranges`).
- Crawler tự khai có IP thuộc dải của nhà vận hành: "Googlebot (đã xác minh)". Tự khai nhưng IP
  ở ngoài dải: "Giả danh Googlebot". Kết luận vẫn là BOT.
- Báo cáo:
  - Lý do có hai dòng riêng: bot tìm kiếm đã xác minh, và giả danh.
  - Bảng "IP bot nhiều nhất" ghi chú IP crawler thật, và IP có cả phiên người thật (CGNAT của nhà
    mạng, văn phòng).
  - Nút "Sao chép danh sách IP" bỏ hai loại này, để khách dán vào tường lửa không chặn nhầm
    Googlebot hay chặn cả khách thật.

## 2b. Sửa thêm (cùng bản phát hành, sau rà soát lần hai)

| Vấn đề | Sửa |
|---|---|
| `/detect` trả `risk_score` 0,9989 cùng kết luận HUMAN cho iPhone thật (điểm tabular ngoài miền) | `risk_score` là `null` khi kết luận đến từ luật hoặc chưa đủ dữ liệu; `bot_probability` giữ nguyên cho client cũ |
| Site có CSP cấm Worker `blob:` hoặc bắt Trusted Types nhận một báo cáo vi phạm CSP mỗi lượt tải trang | Collector nhớ lần bị từ chối 24 giờ trong localStorage (`datacat_worker_blocked`) và bỏ đầu dò Worker; đo: lượt đầu 1–2 lỗi, các lượt sau 0 |
| Bút cảm ứng (Surface Pen, Wacom) sinh sự kiện chuột tương thích, bị mô hình chuột chấm dù ngoài miền huấn luyện | Nét bút không vào quỹ đạo chuột, chạm bút không vào phân tích click (`pointerStats.penEvents` ghi nhận); đo bằng CDP: chuột 40 điểm, bút 0 |

## 3. Đã kiểm tra, không có vấn đề

| Trường hợp | Kết quả |
|---|---|
| Angular (zone.js sửa `toString`, `requestAnimationFrame`, `addEventListener`) | HUMAN |
| Sentry tải sau collector | HUMAN |
| Gắn thẻ hai lần | HUMAN, một phiên |
| Chỉ dùng bàn phím (Tab, Enter, Space), click bằng bàn phím | HUMAN; click `detail = 0` không bị xét |
| Dán email bằng Ctrl+V | HUMAN |
| Zoom 150%, toàn màn hình, múi giờ UTC, tiếng Anh | HUMAN |
| iCloud Private Relay, Edge Secure Network | Không bị coi là IP cloud (danh sách cloud không có Akamai/Cloudflare/Fastly) |
| CSP `frame-src 'none'`, Trusted Types | Iframe tạm vẫn tạo được; không để lại iframe |
| CSP `sandbox` | Dùng bản của trang như trước |
| Firefox, Firefox `resistFingerprinting`, WebKit (nhân Safari) | Không nhóm bằng chứng nào (bỏ dấu vết của chính Playwright) |
| Đồng hồ máy khách lệch | Thời điểm bị kẹp vào [server − 24 giờ, server + 5 phút], thứ tự phiên giữ được |

## 4. Giới hạn còn lại

- Không sửa được ở phía trình duyệt: bot dùng input hệ điều hành trên máy thật, farm điện thoại
  thật, người chơi thuê, và kẻ tấn công dựng lại trọn giao thức với dữ liệu chuột người. Cần tín
  hiệu ngoài trình duyệt (dấu vân tay TLS ở edge, attestation thiết bị, thử thách).
- Remote Desktop/UltraViewer/TeamViewer giao chuột theo nhịp thấp, một mẫu mỗi khung: NGHI VẤN
  (`FRAME_LOCKED_POINTER`). Đây là người điều khiển từ xa, chấp nhận được.
- Đồng hồ máy khách bị lùi giữa phiên: telemetry có mốc thời gian cũ hơn bị bỏ cho tới khi đồng
  hồ vượt mốc trước (NTP chỉ chỉnh vài mili giây, nên chấp nhận).
- Bot có thể gửi sự kiện CDP dạng bút để tránh mô hình chuột; phiên khi đó "chưa đủ dữ liệu"
  chứ không thành HUMAN.
- Chưa thử được: Brave, Safari trên macOS thật, trình duyệt trong app
  Facebook/Zalo/TikTok (các app này chèn script bọc `console`; collector 1.11 đã miễn nhiễm với
  kiểu này).
- Kẻ tấn công sửa cả `requestAnimationFrame` của iframe mới tạo làm bộ đo khung hình trống; trang
  đã di chuột ≥ 25 lần trong ≥ 10 giây mà không đo được khung nào bị tính `POINTER_API_TAMPERED`
  (đo bằng Playwright: bộ đo không còn bị lừa ra 6,9 ms).

## Kiểm tra

- Số liệu val/test của mô hình chuột giống hệt v24 (cùng dữ liệu, cùng seed). Gate
  `desktop_risk` 33 fixture (thêm 4); gate v24 được đóng băng.
- Ma trận người thật (Chrome thật, input hệ điều hành, server policy 25): 11/11 HUMAN.
  Gồm: trang thường, Sentry, Sentry tải muộn, zone.js, thẻ gắn hai lần, bàn phím, dán, tắt GPU,
  zoom 150%, toàn màn hình, UTC.
- Ma trận bot cũ (15 kịch bản), không đổi so với v24:
  - patchright các kiểu: NGHI VẤN.
  - Script sửa hoặc xóa `getCoalescedEvents`: NGHI VẤN (`POINTER_API_TAMPERED`).
  - Puppeteer-stealth (headed, headless mới) và Selenium: BOT.
  - Chrome và Cốc Cốc input hệ điều hành: HUMAN.
- Dưới Playwright (CDP), collector 1.11 vẫn báo `cdpRuntime` qua console của realm mới.
- CSP: `frame-src 'none'` và Trusted Types vẫn tạo được realm; `sandbox` quay về bản của trang.
- 892 test Python, test collector và Ruff đạt.
