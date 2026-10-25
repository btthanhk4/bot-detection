# Kiểm chứng bản bàn giao thu traffic DATACAT

Ngày: 2026-10-19. Phạm vi: bản source/SDK chuẩn bị để nhúng và thu snapshot
cho nghiên cứu, không chứng nhận phát hiện mọi bot hoặc nghiệm thu host production.

## Kết quả và phạm vi sẵn sàng

Bản code đã qua kiểm thử cục bộ của luồng browser → API → MongoDB/SQLite →
export/verify, gồm sự cố và restart. Đủ cơ sở bàn giao source và SDK để cấu
hình pilot. Website cuối chưa được chọn, chưa kiểm tra TLS/CSP/CORS của
website đó và chưa deploy bản mới lên server cloud trong lượt này.

## Các vấn đề đã xử lý

| Vấn đề trước rà soát | Bản bàn giao |
| --- | --- |
| Chưa có công cụ xuất snapshot nghiên cứu có manifest | CLI lọc study/site/thời gian, kiểm tra raw hash, xuất JSONL + template UNKNOWN + manifest và lệnh verify |
| SDK cần đoạn khởi tạo thủ công, dễ trùng collector | Tag tự chạy opt-in, kiểm tra cấu hình, dedup tag, cảnh báo khi có `_bc` thủ công |
| Thiếu phiên bản/site/study/page trong raw | SDK 1.1.0, metadata qua validation, capture giữ nguyên và có trường index để lọc |
| Khó biết request chỉ gửi được hay đã ghi dữ liệu | Receipt từ fetch có recorded/capture_id; tách raw persisted/buffered và beacon chỉ queued |
| Đã nhận HTTP headers nhưng body phản hồi bị treo có thể giữ collector bận vô hạn | Timeout bao trùm cả đọc JSON; kiểm thử abort, dọn controller và gửi tiếp sau phục hồi |
| Không biết khung tọa độ/thời điểm recorder reset | Metadata coordinateFrame gồm kích thước, recording ID, origin gần đúng và độ phân giải timestamp/tọa độ |
| Exporter từ chối BSON Int64 dù timestamp hợp lệ | Chấp nhận integer BSON, từ chối boolean, có regression test và kiểm thử với MongoDB thật |
| Stack mặc định phụ thuộc SilkMoon | Compose pilot độc lập, MongoDB và spool có volume riêng |
| Dễ đưa `.env.pilot`/dependency vào image hoặc gói giao | Ignore cấu hình thật, builder loại credential/runtime/dependency và kiểm tra checksum SDK đã test |

Những điều giữ nguyên: weights bundle `e3dd550e4d40453db0e17a743da7e992`,
policy phân loại, threshold và luồng sử dụng thủ công `new BotCollector`.
Metadata/capture không tạo ground truth. Candidate profile và model thử
nghiệm không được bật mặc định trong bản bàn giao.

## Kiểm thử thực hiện

- Python: **517 passed**, một cảnh báo deprecation của Starlette TestClient.
- Ruff: qua.
- `npm test` trong collector: lifecycle, passive profile và pilot/receipt qua.
- `docker compose --env-file .env.pilot.example -f docker-compose.pilot.yml config --quiet`: qua.
- Browser thực qua Playwright 1.63.0, Chromium 153.0.8010.12, MongoDB Community
  7.0.45 tạm trên loopback. MongoDB archive được tải từ nguồn chính thức và
  kiểm tra SHA256 trước chạy. Docker daemon chưa hoạt động trên máy này,
  nên không tuyên bố đã build/chạy image container ở lượt kiểm tra này.

Smoke cuối kiểm tra 10 nhóm:

1. Nhúng SDK từ origin API khác origin website, JSON preflight qua.
2. Init chưa có chuột vẫn lưu snapshot.
3. Mousemove, click và wheel thực sự tới collector và server.
4. Tag nhúng trùng không tạo phiên init thứ hai.
5. Server đã lưu nhưng mất response: retry cùng body chỉ có một raw capture.
6. Điều hướng sinh page/session mới, pagehide cross-origin có bản ghi thật.
7. MongoDB dừng: API xác nhận raw đã vào spool, không báo persisted sai.
8. Dừng API trong outage, restart MongoDB/API: raw đã ACK được phục hồi đúng ID.
9. Export và verify JSONL/manifest thành công.
10. TTL MongoDB thật xóa một probe thử nghiệm đã hết hạn.

Kết quả: **6 snapshot / 2 phiên**, API healthy, không phải sáu người dùng độc
lập hoặc phép đo accuracy. Browser automation chỉ dùng kiểm tra tích hợp,
không dùng làm nhãn profile người thật.

SDK đã test: SHA256
`7e02e1f499b2238e48062bdd17c2a9e1826b72d53128f308f707ef3e5c9caf4a`.
Chứng cứ cục bộ:
`C:/Users/Admin/bot-detection-research/pilot-runtime/handoff-smoke-release/evidence.json`.
Raw export và MongoDB thử nghiệm nằm ngoài source; không đưa vào gói giáo viên.
Script `pilot/smoke-test.cjs` cho phép lặp lại; các tiến trình thử do script
tạo đã được dừng khi hoàn tất.

## Gói bàn giao

Builder `pilot/build_release.py` tạo hai loại archive ngoài source:

- Teacher embed: SDK, đoạn nhúng, README, evidence và release manifest.
- Operator source: source đã chọn lọc, sample env/compose, tài liệu, weights,
  test và manifest; không chứa `.git`, `.env` thật, raw export, MongoDB,
  browser binary, node_modules hoặc thư mục nghiên cứu ngoài repo.

Builder yêu cầu checksum SDK khớp một smoke thành công. Manifest ghi hash
từng file và snapshot hiện tại; HEAD Git chưa bao gồm mọi sửa đổi trong
worktree nên không lấy riêng commit cũ làm định danh source bàn giao.
Checksum kiểm tra toàn vẹn, không phải chữ ký chứng thực nguồn phát hành.

## Việc cần làm trên website thật

1. Chọn API host/URL và cổng, cấu hình giao thức phù hợp website.
2. Bật research capture trên API, cấu hình origin và thời hạn giữ, xác minh volume.
3. Đặt study/site ID và nhúng SDK; kiểm tra receipt capture_id qua Console/Network.
4. Đối chiếu capture với MongoDB/export; chạy pilot nhỏ trước đợt traffic chính.
5. Export/verify định kỳ trước TTL; gắn nhãn từ nguồn biết rõ và giữ UNKNOWN
   cho traffic chưa xác định.

Không dùng tỷ lệ BOT/HUMAN/SUSPECT trên traffic chưa có nhãn để tự kết luận
độ chính xác. Không tăng ngưỡng hoặc đổi nhãn để làm demo trông tốt hơn.
