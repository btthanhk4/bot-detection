# Model release v12

Bundle: `ee8f73f6056d4a4eb769a8493e1db2d8`. Policy: `12`. Collector: 1.3.0.
Ngưỡng và tham số mô hình chuột không đổi so với v10/v11; replay cùng nguồn giữ nguyên
(0 cửa sổ người bị gán BOT, 0 cửa sổ bot bị gán HUMAN).

## Thay đổi

Collector 1.3.0 thêm `collector/src/automation.js` (BotD v2), gửi `botd.automation`:
probe đồng bộ (biến của Playwright/Selenium, getter `navigator` bị vá, GPU so với hệ điều
hành, Client Hints, màn hình headless 800×600, `productSub`, `appVersion`…), cùng hai
probe bất đồng bộ: quyền thông báo so với Permissions API, và so sánh trang với Worker
(CPU, UA, platform, webdriver, WebGL renderer). API ghi thêm header quan sát được
(`Accept-Language`, `sec-ch-ua`). Không có probe nào thay đổi trạng thái trang.

Hai luật mới, đứng sau luật HeadlessChrome của v10 và trước luật click giả lập của v11:

| Luật | Kết luận BOT khi |
|---|---|
| `automation_marker_v1` | `navigator.webdriver` true (trang hoặc Worker), `cdc_` của ChromeDriver, biến Selenium/PhantomJS, binding của Playwright `exposeFunction`, thuộc tính automation trên `<html>` |
| `environment_tampering_v1` | Mâu thuẫn ở ≥ 3 nhóm độc lập (HEADLESS_ENV, GPU, PERMISSION, CONTEXT, NATIVE_PATCH, CLIENT_HINTS, HTTP), trong đó có ít nhất một nhóm HEADLESS_ENV, GPU hoặc PERMISSION |

Thay đổi hành vi có chủ đích: `webdriver = true` hoặc `cdc_` trước đây chỉ cho SUSPECT,
nay cho BOT/FINAL kể cả khi không có chuột.

## Bằng chứng

**Ma trận probe** (Edge 156, Chrome 155, Windows 11, 2026-10-26). Trình duyệt thật được
mở như tiến trình thường, không CDP, profile trống:

| Môi trường | v11 | v12 | Bằng chứng |
|---|---|---|---|
| Chrome thật / Edge thật | SUSPECT | SUSPECT | Không tín hiệu nào |
| Playwright headless, initScript, exposeFunction | BOT | BOT | HeadlessChrome + webdriver |
| Playwright có giao diện | SUSPECT | **BOT** | webdriver |
| Puppeteer headless | BOT | BOT | HeadlessChrome |
| Puppeteer + stealth | SUSPECT | **BOT** | CONTEXT, GPU, HEADLESS_ENV, PERMISSION |
| Selenium Edge / Chrome | SUSPECT | **BOT** | webdriver + `cdc_` |
| Patchright có giao diện | SUSPECT | SUSPECT | Không tín hiệu môi trường |
| Patchright headless | SUSPECT | SUSPECT | Chỉ HEADLESS_ENV |

Với Puppeteer stealth, các dấu vết đo được: WebGL renderer "Intel Iris OpenGL Engine"
(chuỗi của macOS) trên UA Windows; `permissions.query` trả `denied` khi
`Notification.permission` là `default`; CPU 4 ở trang nhưng 8 trong Worker; WebGL trong
Worker khác trang; màn hình 800×600 không trừ taskbar.

Release gate: 8 fixture mới (4 BOT, 4 ca không được kết luận BOT, gồm extension đổi
User-Agent và dữ liệu sai định dạng), cộng các gate cũ của v10/v11.

## Giới hạn

- Đối chứng người thật mới gồm **2 trình duyệt trên 1 máy**. Extension bảo vệ quyền riêng
  tư, Brave, máy ảo, Remote Desktop và trình duyệt di động chưa được đo; chúng có thể tạo
  tín hiệu ở nhóm NATIVE_PATCH, CONTEXT hoặc GPU.
- Patchright, nodriver, Camoufox ở chế độ có giao diện là trình duyệt thật bị điều khiển;
  không heuristic môi trường nào bắt được chúng. Chỉ hành vi (click giả lập v11, mô hình
  chuột) còn tác dụng.
- `webdriver = true` cũng xuất hiện ở công cụ kiểm thử hợp lệ (CI, kiểm thử tự động của
  chính chủ website). Chúng là automation, nhưng không nhất thiết độc hại.
- Mọi tín hiệu do client gửi lên và có thể bị sửa. Luật làm tăng chi phí cho bot, không
  phải bằng chứng không thể giả.

## XGBoost: đánh giá và quyết định không thay đổi

Train trên M4D theo đúng pipeline, chọn ngưỡng trên validation M4D, đo trên dữ liệu chưa
thấy: AUC trên DELBOT chỉ 0,44–0,53 với mọi cấu hình thử (sâu 6/3/2, regularize, bỏ đặc
trưng nhạy tần số lấy mẫu); 2–7% lần vẽ của người DELBOT vượt ngưỡng; bot Playwright trên
SilkMoon chỉ bị bắt 3–6%. Train gộp M4D + DELBOT cải thiện trong từng dataset nhưng vẫn chỉ
bắt 3–5% bot SilkMoon. Kết luận: điểm nghẽn là dữ liệu cùng website, không phải siêu tham
số; mô hình XGBoost hiện tại được giữ nguyên.

## Tái hiện

```powershell
python -m core_ml.train --dataset-root "../Tuần 3/repos/web_bot_detection_dataset" --weights-dir bot-lab/release-v12/weights --device cpu
python -m pytest -q
cd collector; npm test
```

Bundle v11 được giữ trong `bot-lab/rollback-v11/` (không commit).
