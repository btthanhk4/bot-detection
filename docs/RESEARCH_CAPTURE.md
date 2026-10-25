# Research capture cho đợt traffic thật

## Phạm vi đã triển khai

Chế độ opt-in lưu từng snapshot hợp lệ của `/api/v1/telemetry` vào MongoDB
`telemetry_captures`, trước khi kiểm tra hoặc chạy model. Dashboard vẫn dùng
`detection_results` như trước; không đổi model, ngưỡng hay ba verdict.

Bản bàn giao SDK 1.1.0 đã có tag tự nhúng, metadata study/site/page và công
cụ export/verify. Xem [hướng dẫn nhúng](../pilot/README.md),
[hướng dẫn vận hành](PILOT_OPERATOR_GUIDE.md) và
[kết quả kiểm chứng](PILOT_HANDOFF_REVIEW_2026-10-19.md).

Đây là nền tảng thu dữ liệu, chưa phải thuật toán phát hiện bot mới, cơ chế
chống giả mạo client hay tích hợp nhãn thương mại. Không áp dụng cho
`/api/v1/detect`, vốn không phải endpoint thu dataset.

## Bật trên môi trường pilot

Đặt hai biến trong `.env` của Docker Compose trên môi trường được phép thu:

```dotenv
BOT_CAPTURE_ENABLED=true
BOT_CAPTURE_RETENTION_DAYS=7
```

Sau khi source và cấu hình được kiểm chứng trên staging, tạo lại container:

```console
docker compose up -d --build bot-detection-core
```

Mặc định là `false`. Không bật tự động trên server hiện tại. Không thay token,
CORS hay thông số model. Tắt cờ ngừng tạo capture mới nhưng hàng đợi capture
cũ vẫn được xử lý; thao tác xóa phiên vẫn xóa cả lịch sử đã thu.

Chỉ thu trên website được chủ sở hữu cho phép, với thông báo/đồng ý phù hợp.
Payload có thể chứa IP, URL/query, fingerprint và hành vi người dùng. Giới hạn
quyền truy cập MongoDB, thời gian giữ và nội dung nhạy cảm trên website trước
khi bật. Chế độ này không tự lọc token hoặc thông tin cá nhân khỏi URL.

## Dữ liệu và định danh

Mỗi document chứa:

| Trường | Ý nghĩa |
| --- | --- |
| `event_id`, `_id` | Khóa snapshot, cũng trả về API dưới tên `capture_id` |
| `payload_json`, `payload_sha256` | JSON sau validation và hash nội dung; không dùng bản rút gọn của dashboard |
| `sessionId`, `visitorId` | ID do collector gửi; chưa phải danh tính được xác thực |
| `study_id`, `site_id`, `page_instance_id` | Metadata collector 1.1.0 để lọc/nối dữ liệu; không phải nhãn hoặc danh tính được chứng thực |
| `received_at`, `client_ip`, `server_user_agent` | Thông tin tại API; giá trị UA vẫn do client khai |
| `capture_bundle_id`, `capture_policy_version` | Phiên bản lúc thu, không chứng minh model đã chạy |
| `analysis_json` | Chỉ xuất hiện sau một lần inference thành công; gồm bundle thực sự tạo kết quả |
| `expires_at` | Thời điểm hết hạn, được MongoDB TTL dọn bất đồng bộ |

Không cắt mất scroll/touch/nested profile trong bản JSON nghiên cứu. Đây vẫn
chỉ là các trường `TelemetryPayload` chấp nhận: trường ngoài schema bị bỏ,
collector vẫn có cửa sổ hữu hạn và có thể bỏ lỡ sự kiện trình duyệt. Không
gọi dữ liệu này là toàn bộ lịch sử tương tác liên tục.

Nếu có cả `timestamp` và `sequence`, hash JSON chuẩn hóa dùng làm định danh.
Retry cùng payload không tạo thêm document, không ghi đè raw/provenance/TTL
đã lưu. Thay nội dung tạo snapshot khác. Thiếu một trong hai trường thì dùng
UUID phía server, vì không đủ cơ sở gộp hai lần gửi giống nhau thành một sự kiện.

Đây là deduplication, **không phải anti-replay có xác thực**: client có thể
thay timestamp/sequence/nội dung. Chưa có token ràng buộc site/session,
nonce hay đối chiếu vendor. Payload giống nhau từ hai nơi gửi vẫn có thể
gộp nếu chúng khai cùng các ID; cần quản lý namespace site khi mở nhiều website.

Raw và prediction được ghi thành hai bước: tiến trình chết giữa hai bước thì
raw còn nhưng chưa có `analysis_json`. Không tự điền HUMAN/SUSPECT/BOT.
Prediction đầu tiên ghi thành công cho event được giữ nguyên; HTTP retry dưới
bundle mới không thay thế prediction đã lưu. Trong cạnh tranh giữa request
trực tiếp và replay, metadata thuộc bản được ghi vào MongoDB trước, không
đảm bảo đó là request đến sớm nhất. Cần giữ điều này trong quy trình nghiên cứu.

## Hành vi API và lỗi

- Khi model chạy bình thường, response cũ được giữ và bổ sung `capture_id`,
  `analysis_available`, `capture_persisted`, `capture_buffered`.
- `persisted`/`buffered` ở response thành công vẫn nói về bản tổng hợp phiên;
  `capture_persisted`/`capture_buffered` nói về snapshot nghiên cứu.
- Khi raw đã nằm trong MongoDB hoặc SQLite nhưng model không sẵn sàng/lỗi,
  API trả HTTP 202, `status: captured`, `recorded: true`,
  `analysis_available: false`. Trong response 202, `persisted`/`buffered`
  chỉ trạng thái raw capture; không có prediction để lưu.
- `captured` là trạng thái thu dữ liệu, không phải verdict thứ tư. Dashboard
  không tự sinh một phiên đã phân tích cho request này. Collector hiện tại
  coi HTTP 202 là thành công và không gửi lại vì lỗi inference.
- Khi MongoDB lỗi, raw/decision đã có được ghi vào SQLite spool hiện hữu.
  Chỉ xác nhận sau commit. Đầy hàng đợi hoặc lỗi đĩa trả 503 và `Retry-After`.
- Recovery chỉ ghi lại capture, không chạy model để tự bổ sung nhãn. Nếu
  chưa phân tích thì giữ thiếu; cần một bước offline có provenance riêng.
- Payload không hợp lệ bị từ chối trước lưu; ingestion đang bị admin tạm
  khóa trả 503. Capture hết hạn/phiên có tombstone bị từ chối với HTTP 409.
- Xóa phiên/xóa tất cả xóa cả MongoDB capture và spool liên quan. Kiểm tra
  tombstone sau ghi bảo vệ tình huống xóa xảy ra đồng thời.

## Dung lượng và giới hạn

MongoDB có index TTL trên `expires_at` và index `(sessionId, received_at)`.
TTL không gia hạn khi cập nhật prediction hoặc retry document còn tồn tại.
Trong maintenance, capture hết hạn trong SQLite được loại bỏ kể cả khi một
event khác bị lỗi DB ở đầu hàng đợi. Đây là xóa logic, không bảo đảm xóa vật
lý khỏi WAL/backup; TTL không chạy khi dịch vụ tương ứng dừng.

Một request khi MongoDB lỗi có thể dùng tối đa ba slot spool: raw capture,
capture kèm prediction và kết quả phiên. Các retry chưa flush cũng có thể
chiếm thêm slot trước khi được MongoDB gộp. `BOT_MAX_TELEMETRY_BUFFER` vẫn
là giới hạn chung, không phải số phiên. Không tăng giới hạn mù quáng.

Trước pilot, đo kích thước document thực tế và số snapshot/ngày. Dự trù:

```text
dung lượng raw ≈ kích thước snapshot trung bình × số snapshot/ngày × số ngày giữ
```

Cần cộng thêm prediction, index, SQLite/WAL và backup. Chỉ TTL chưa phải
quota dung lượng. Cần giám sát dung lượng, lỗi ghi và buffer trước khi mở rộng.

## Những việc tiếp theo

1. Đã kiểm chứng MongoDB thật cục bộ: TTL, index, restart tiến trình,
   outage/recovery. Cần nghiệm thu thêm trên host/container và website cuối.
2. Đã có CLI `core_ml.dataset.export_captures`, JSONL/manifest và template
   nhãn UNKNOWN. Đây là công cụ vận hành trực tiếp, không phải endpoint public
   export raw. Import nhãn vendor/tự động gọi vendor chưa được triển khai.
3. Gắn kết quả vendor với event/request tương ứng; tách nhãn người thật/bot
   biết nguồn khỏi nhãn suy luận thương mại. `analysis_json` không phải ground truth.
4. Chạy pilot đồng thời với vendor; đo các nhóm SUSPECT và độ bao phủ.
5. Thử feature tương tác/profile và retrain trên split theo người/phiên/họ bot.
   Các cửa sổ chồng lặp không được chia ngẫu nhiên sang train và test.
