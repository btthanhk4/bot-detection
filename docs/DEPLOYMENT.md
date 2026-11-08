# Triển khai production

Tài liệu này mô tả đúng những gì [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml)
và [`docker-compose.yml`](../docker-compose.yml) đang làm. Stack pilot độc lập
(`docker-compose.pilot.yml`) có hướng dẫn riêng ở [PILOT_OPERATOR_GUIDE.md](PILOT_OPERATOR_GUIDE.md).

## Luồng CI/CD

Workflow **Test and deploy** chạy khi push lên `main` hoặc khi bấm *Run workflow*
(`workflow_dispatch`). Mỗi lần chỉ một deploy chạy (`concurrency: production-deploy`).

1. **Test** (ubuntu-latest, Python 3.10)
   - `pip install -r requirements-dev.txt`
   - `python -m ruff check .`
   - `python -m pytest -q` (khi lỗi, 80 dòng cuối log được đưa lên phần annotation)
   - `cd collector && npm test`
   - `git diff --exit-code -- collector/dist/bot-collector.js`: bundle đã commit phải trùng bản vừa build.
2. **Deploy production** (chỉ chạy khi Test qua, environment `production`), SSH vào server và:
   - dừng nếu `DEPLOY_PATH` không phải repo git hoặc có thay đổi chưa commit / file chưa track;
   - `git fetch origin main`, `git checkout --detach <commit vừa test>`;
   - `docker compose up -d --build --remove-orphans`;
   - gọi `curl http://localhost:8000/health` trong container, tối đa 18 lần cách nhau 5 giây;
   - khi `"status": "healthy"`: ghi SHA vào `.git/bot-detection-deployed-sha` và kết thúc;
   - khi lỗi sau lúc đã checkout: checkout lại SHA đã deploy trước đó và chạy lại `docker compose up -d --build`.

## Cấu hình trên GitHub

| Loại | Tên | Dùng cho |
|---|---|---|
| Secret | `DEPLOY_HOST`, `DEPLOY_PORT`, `DEPLOY_USER`, `DEPLOY_PASSWORD`, `DEPLOY_FINGERPRINT` | Kết nối SSH tới server |
| Secret | `DEPLOY_PATH` | Thư mục repo trên server |
| Secret | `BOT_ADMIN_TOKEN`, `BOT_READ_TOKEN` | Token API truyền vào phiên SSH |
| Variable | `BOT_CORS_ORIGINS` | Origin được phép gọi API |

## Cấu hình trên server

- `DEPLOY_PATH` là một bản clone của repo; deploy chỉ chạy khi `git status --porcelain` trống.
- File `.env` cạnh `docker-compose.yml` (đã nằm trong `.gitignore`) chứa các biến của container,
  xem [`.env.example`](../.env.example). Biến không đặt sẽ dùng giá trị mặc định ghi trong
  `docker-compose.yml`.
- Container `bot-detection-api` nghe ở `127.0.0.1:8000` và tham gia network `silkmoon-network`;
  truy cập công khai đi qua gateway HTTPS trên cùng network (API tin `X-Forwarded-*` từ `172.16.0.0/12`).
- Volume `bot_detection_spool` giữ `/app/var`: hàng đợi SQLite khi MongoDB mất kết nối và
  cơ sở dữ liệu GeoIP.

## Khi deploy lỗi

- **Lỗi ở bước cài đặt của GitHub** (ví dụ "Set up Python" hoặc tải action bị 504): không liên quan
  mã nguồn, chạy lại bằng *Re-run failed jobs* trên trang workflow.
- **Health check không đạt:** workflow đã tự quay lại bản trước; xem log container trong bước deploy
  (`docker compose logs --tail=100 bot-detection-core`) rồi sửa và push lại.
- **Quay lại một bản cũ bằng tay** trên server, đúng các lệnh workflow dùng khi rollback:

  ```bash
  cd "$DEPLOY_PATH"
  git checkout --detach <sha>
  docker compose up -d --build --remove-orphans
  docker compose exec -T bot-detection-core curl -fsS http://localhost:8000/health
  ```
