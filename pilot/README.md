# DATACAT: gói nhúng thu traffic nghiên cứu

Gói này thu snapshot trình duyệt/chuột cho đợt nghiên cứu có cho phép.
SDK không chặn truy cập, không gán ground truth và không cần token giám sát
trong HTML. Các model hiện có phục vụ quan sát; chưa cam kết phát hiện mọi bot.

## 1. Trước khi nhúng

Người vận hành cần cung cấp địa chỉ API hoạt động, đã bật
`BOT_CAPTURE_ENABLED=true`, có MongoDB/spool lưu bền vững và CORS cho origin
website. Với website HTTPS, dùng API HTTPS hoặc reverse proxy cùng origin.
Không dùng trực tiếp API HTTP từ một trang HTTPS.

Website phải cho phép thêm script vào HTML/template hoặc Tag Manager. CSP
cần cho phép tải SDK (`script-src`) và kết nối API (`connect-src`). Worker
blob là tín hiệu bổ sung: nếu CSP không cho phép, profile có thể thiếu phần
worker nhưng việc thu snapshot vẫn phải được kiểm tra qua receipt.
Không thể tự nhúng vào website bên thứ ba khi không có quyền chỉnh sửa.

## 2. Mã nhúng

Thay `API_HOST` bằng địa chỉ API do người vận hành cung cấp. Dùng cùng
`data-study-id` cho một đợt thu, `data-site-id` riêng cho từng website.
ID chỉ gồm chữ ASCII, số, dấu `_` hoặc `-`, tối đa 64 ký tự.

```html
<script async src="https://API_HOST/bot-collector.js"
        data-datacat
        data-study-id="thesis_pilot_01"
        data-site-id="site_01"></script>
```

Chỉ nhúng một cách. Nếu trang đã có `new BotCollector(...)` / `window._bc`,
gỡ cách khởi tạo cũ trước khi dùng tag tự chạy này. Nhúng lặp tag cùng cấu
hình không tạo thêm collector. Không dùng SDK trong gói này cùng một SDK
phiên bản khác trên cùng trang.

Nếu tự host file SDK trên website, chỉ rõ địa chỉ API:

```html
<script async src="/assets/bot-collector.js"
        data-datacat data-study-id="thesis_pilot_01" data-site-id="site_01"
        data-endpoint="https://API_HOST/api/v1/telemetry"></script>
```

SDK mặc định gửi mỗi 15 giây khi có thay đổi và khoảng 60 giây khi không
có thay đổi. `data-interval-ms` có thể đặt trong khoảng 1000-60000; giữ mặc
định cho pilot để tránh tăng traffic không cần thiết. Tên endpoint không đổi.

## 3. Xác nhận đã thu được

Mở DevTools Console trên trang đã nhúng:

```javascript
await window.DatacatPilot.ready;
window.DatacatPilot.getStatus();
```

Kiểm tra `studyId`, `siteId`, `stopped: false` và một `lastReceipt.captureId`
không rỗng. `lastReceipt.persisted: true` nghĩa là raw đã vào MongoDB;
`buffered: true` nghĩa là raw đã được API nhận vào spool và cần phục hồi/kiểm
tra phía vận hành. `ready` chỉ xác nhận SDK khởi tạo xong, không chứng minh
snapshot đã lưu. Receipt chỉ có `captureId: null` nghĩa là endpoint có thể
chỉ lưu bản tổng hợp, chưa bật capture hoặc server chưa đúng phiên bản.

`lastDelivery.acknowledged: true` nói về phản hồi fetch có `recorded:true`.
Beacon lúc rời trang chỉ có thể xác nhận đã xếp hàng trong trình duyệt, chưa
chứng minh server đã nhận. Người vận hành phải kiểm tra capture/export.

Người chỉ đọc trang hoặc dùng bàn phím vẫn được thu phiên, không bắt buộc
di đủ 25 điểm. Không sửa dự đoán thành nhãn người thật chỉ vì phiên không có chuột.

## 4. Khi cần ngừng thu

```javascript
window.DatacatPilot.stop();
```

Lệnh dừng collector trong trang hiện tại. Gỡ tag khỏi template/Tag Manager
để ngừng trên các lượt tải trang mới; reload trang sau khi thay cấu hình.

## 5. Gắn nhãn phục vụ khóa luận

Traffic bình thường chưa xác định người/bot giữ nhãn `UNKNOWN`. Với người
tham gia hoặc runner có kiểm soát, ghi nguồn nhãn, mã người giả danh hoặc
cấu hình bot và `captureId`/`sessionId` để người vận hành đối chiếu export.
Không gửi nhãn vào feature và không lấy verdict DATACAT làm ground truth.
Chrome mở bằng automation chỉ là đối chứng chuột nếu người dùng thao tác;
đối chứng profile người thật phải dùng browser mở thông thường.

Raw có URL, fingerprint và hành vi; chỉ thu trên website được phép và giữ
export riêng. Gói nhúng không chứa dữ liệu thật hoặc token API quản trị.

## 6. Báo lỗi cần những gì

Gửi thời điểm, URL trang đã nhúng, `studyId`/`siteId`, trạng thái HTTP của
request telemetry và kết quả `getStatus()`. Không gửi token, cookie, nội dung
form hay toàn bộ fingerprint qua kênh trao đổi công khai.
Các lỗi thường gặp: CSP/mixed content, CORS sai origin, API chưa bật capture,
SDK cũ trong cache, chèn cùng cả snippet thủ công và tự động, HTTP 429 hoặc
MongoDB/spool không ghi được.
