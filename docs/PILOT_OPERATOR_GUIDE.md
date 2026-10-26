# Vận hành bản bàn giao thu traffic thật

Tài liệu này áp dụng cho SDK 1.3.0 và source pilot cùng gói. Phân biệt sẵn
sàng thu dữ liệu với chứng nhận độ chính xác model. Chưa có website cụ thể;
mỗi website cần kiểm tra thực tế sau khi nhúng.

## Triển khai API

Nếu dùng server hiện có, giữ compose/network/MongoDB hiện hữu, bật
`BOT_CAPTURE_ENABLED=true`, đặt thời hạn giữ capture và origin website.
Build/deploy source đã kiểm chứng, không chạy một stack mới lên cổng đang dùng.

Nếu dựng môi trường pilot mới, dùng `docker-compose.pilot.yml`, độc lập
SilkMoon và có MongoDB riêng. Tạo `.env.pilot` theo `.env.pilot.example`,
thay hai token, origin và cổng trước khi chạy:

```console
docker compose --env-file .env.pilot -f docker-compose.pilot.yml config --quiet
docker compose --env-file .env.pilot -f docker-compose.pilot.yml up -d --build
docker compose --env-file .env.pilot -f docker-compose.pilot.yml ps
```

Hai token chỉ đặt trên API host và công cụ vận hành, không đưa vào mã HTML.
Nếu máy đã dùng cổng 8000, đổi `BOT_PILOT_PORT` sang cổng còn trống. MongoDB
trong stack pilot không publish cổng ra host. Health HTTP và volume spool
được giữ như image hiện có. Không dùng `down -v` với dữ liệu nghiên cứu.

API cần được website truy cập qua giao thức phù hợp: HTTPS API cho HTTPS
website, hoặc reverse proxy cùng origin. Nếu proxy SDK ở `/datacat/`, proxy
cả `/datacat/api/v1/telemetry` tới API, hoặc dùng `data-endpoint` rõ ràng.
TLS/domain của website cuối chưa được cấu hình/kiểm chứng trong bản local.

## Kiểm tra trước khi mời thu traffic

1. `/health` trả database ready, `research_capture.enabled:true` và model
   bundle/policy như bản đã chọn. Model lỗi vẫn có thể trả 202 và lưu raw;
   ghi rõ đây là thu dữ liệu thiếu analysis, không tuyên bố model hoạt động.
2. Nhúng tag trong [hướng dẫn giáo viên](../pilot/README.md). Kiểm tra Console
   và Network trên origin thực; request JSON preflight phải qua.
3. Init không có chuột cũng có `capture_id`; profile/version/study/site/page
   còn nguyên trong raw. Đối chiếu một capture_id với MongoDB/export.
4. Di chuột, click, wheel, reload và rời trang. Không chỉ dựa vào SDK trả
   `ready` hoặc `sendBeacon:true` để xác nhận lưu.
5. Kiểm tra một lần mất mạng/retry trên staging, không ngắt dịch vụ đang thu
   thật. Khôi phục và đối chiếu ID, không tạo thêm nhãn do replay.
6. Export và verify một bộ nhỏ, bảo đảm không trộn study/site khác; chỉ khi
   các bước trên qua mới xác nhận cấu hình website đó sẵn sàng pilot.

`BOT_RATE_LIMIT_PER_MINUTE` tính theo IP. Với lớp học dùng chung NAT, dự
trù số người x tần suất gửi và theo dõi 429/Retry-After. Không tắt mọi giới
hạn hoặc tăng worker tùy ý; hiện spool/maintenance được thiết kế cho một worker.

## Xuất dataset trước TTL

Mặc định capture hết hạn sau 7 ngày. Export hằng ngày, giữ backup riêng và
verify; chỉ sao lưu `detection_results` không giữ được lịch sử snapshot.
TTL xóa bất đồng bộ; không coi việc chưa bị xóa là đã có backup.

Ví dụ cho stack pilot, thay thời gian, study/site và tên thư mục theo đợt thu:

```console
docker compose --env-file .env.pilot -f docker-compose.pilot.yml exec api python -m core_ml.dataset.export_captures --study-id thesis_pilot_01 --site-id site_01 --since 2026-10-19T00:00:00+07:00 --until 2026-10-20T00:00:00+07:00 --output /app/var/exports/site_01_2026-10-19
docker compose --env-file .env.pilot -f docker-compose.pilot.yml exec api python -m core_ml.dataset.export_captures --verify /app/var/exports/site_01_2026-10-19
docker compose --env-file .env.pilot -f docker-compose.pilot.yml cp api:/app/var/exports/site_01_2026-10-19 ./site_01_2026-10-19
```

Stack hiện hữu dùng tên service `bot-detection-core` và compose hiện hữu
thay cho `api`/`docker-compose.pilot.yml` ở trên. Chạy trực tiếp bằng Python
thì đặt `MONGO_URI`/`MONGO_DB` trong môi trường vận hành, không đặt credential
trong CLI. Exporter không ghi hoặc sửa MongoDB.

Output gồm:

- `snapshots.jsonl`: payload JSON gốc, hash, capture ID, metadata server,
  analysis đúng phiên bản nếu có và run_id để nối nhãn. IP mặc định không
  xuất; `--include-client-ip` là tùy chọn rõ ràng. Raw vẫn có dữ liệu trình duyệt.
- `labels-template.csv`: một dòng mỗi cặp session/page trong đợt/site, mọi
  nhãn ban đầu UNKNOWN. run_id là khóa opaque; raw client ID không thành ô
  spreadsheet có thể chạy công thức. Không tự diễn giải mỗi dòng là người độc lập.
- `manifest.json`: phạm vi nhận `[since, until)`, số snapshot/run, số thiếu
  analysis và checksum/kích thước hai file. Đây là kiểm tra toàn vẹn, không
  phải chữ ký chứng thực danh tính/nhãn hoặc Mongo transaction snapshot.

Thư mục output phải mới. Sai hash, ID lặp, dữ liệu ngoài phạm vi hoặc không
có capture đều thất bại; thư mục partial không có manifest thành công.
Không trộn partial với export hoàn tất. Giữ template nguyên để verify;
ghi nhãn vào bản làm việc riêng, nối bằng run_id/capture_id và giữ nguồn nhãn.
Nhãn participant/runner/vendor không thuộc feature huấn luyện.

Nhãn HUMAN/BOT chỉ xác nhận khi biết nguồn. Người bình thường có thể ít
chuột; không loại họ chỉ vì không đủ input cho LSTM. Profile người thật không
được thu trong browser do Playwright mở để rồi dùng đánh giá như Chrome native.

## Theo dõi khi thu

Dashboard đã có [STT, gán nhãn và xuất dataset thủ công](MANUAL_LABELING.md).
Nhãn được giữ riêng với dự đoán AI; không tự động huấn luyện khi lưu nhãn.

Kiểm tra định kỳ health, receipt, queue/drop count, dung lượng MongoDB/spool,
capture mỗi study/site và ngày export mới nhất. Snapshot được ACK vào SQLite
vẫn cần phục hồi/backup; mất volume/đĩa vẫn có thể mất dữ liệu.
Không đổi schema/model/rule giữa một đợt thu mà thiếu phiên bản. Ghi thời
điểm deploy và giữ checksum collector/model cùng dataset.

## Lặp lại kiểm thử browser và MongoDB thật

Không dùng database production. Smoke test tự tạo database và tiến trình
MongoDB/API riêng trên loopback, rồi dừng các tiến trình do nó tạo.

```console
npm --prefix collector test
npm --prefix pilot ci
```

Cài browser đúng phiên bản bằng `npx playwright install chromium` trong
thư mục `pilot` nếu máy chưa có. Đặt `DATACAT_TEST_MONGOD` tới binary MongoDB
Community cục bộ; `DATACAT_TEST_PYTHON` tùy chọn nếu executable không là `python`.
Đặt `DATACAT_SMOKE_DIR` tới thư mục mới để giữ chứng cứ, rồi chạy
`npm --prefix pilot run smoke`. Binary MongoDB tải từ nguồn chính thức và
kiểm tra checksum trước khi chạy; không kèm binary/browser trong gói source.

Smoke test kiểm tra nhúng khác origin, phiên không chuột, movement/click/wheel,
tag trùng, mất phản hồi và retry cùng ID, pagehide, Mongo outage, restart API
với spool cũ, export/verify và TTL thật. `evidence.json` ghi checksum SDK và
bundle đã chạy. Đây là test tích hợp tự động, không phải đối chứng người thật
hay phép đo accuracy của model.
