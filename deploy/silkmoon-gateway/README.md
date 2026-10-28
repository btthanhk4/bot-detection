# Gateway SilkMoon ↔ DATACAT (policy 24)

Cấu hình nginx của SilkMoon (`silkmoon-gateway`) để DATACAT không còn "fail-open":

| Cơ chế | Tác dụng |
|---|---|
| `mirror` mọi lượt tải trang HTML tới `/api/v1/pageview` + cookie HttpOnly `__dc_pv` | Telemetry phải đến từ đúng trình duyệt đã tải trang; lượt tải trang không chạy collector thành phiên "không telemetry" trên dashboard |
| `auth_request` tới `/api/v1/gate` cho các request ghi bị lạm dụng (đăng nhập, đăng ký, OTP, quên mật khẩu, đặt hàng, đánh giá, bình luận, newsletter, mã giảm giá, chat AI, AR) | Chặn phiên BOT, request gọi thẳng API không tải trang, trang không chạy collector, telemetry giả mạo; chat AI và AR còn chặn NGHI VẤN có bằng chứng |
| Collector ở đường dẫn trung tính `/_dc/c.js`, `/_dc/t`, nhúng không có biến toàn cục | Khó bị adblock chặn theo tên; script trên trang không sửa được instance |
| Cổng 5175 (admin) qua TLS | Mật khẩu admin không còn đi dạng rõ |

Nếu API DATACAT lỗi, chậm (quá 2 giây) hoặc chưa bật gateway, request vẫn được cho qua.

## Cài đặt trên server

```bash
# 1. Bí mật dùng chung (chỉ trên server)
SECRET=$(openssl rand -hex 32)
cd /opt/bot-detection-core
printf 'BOT_GATEWAY_SECRET=%s\nBOT_PAGEVIEW_HOSTS=silkmoon.datacat.io.vn\n' "$SECRET" >> .env
docker compose up -d                      # hoặc để CI deploy
sed "s/REPLACE_WITH_THE_SHARED_SECRET/$SECRET/" datacat-gateway.conf.example \
  > /var/www/silkmoon/nginx/datacat-gateway.conf

# 2. Cấu hình gateway (giữ bản cũ để rollback)
cd /var/www/silkmoon
cp nginx/nginx.conf nginx/nginx.conf.bak && cp docker-compose.override.yml docker-compose.override.yml.bak
cp /opt/bot-detection-core/deploy/silkmoon-gateway/nginx.conf nginx/nginx.conf
cp /opt/bot-detection-core/deploy/silkmoon-gateway/docker-compose.override.yml docker-compose.override.yml

# 3. Kiểm tra cú pháp bằng container tạm rồi áp dụng
docker run --rm --network silkmoon-network -v "$PWD/nginx/nginx.conf:/etc/nginx/nginx.conf:ro" \
  -v "$PWD/nginx/datacat-gateway.conf:/etc/nginx/datacat-gateway.conf:ro" \
  -v /etc/letsencrypt:/etc/letsencrypt:ro nginx:alpine nginx -t
docker compose up -d gateway admin
```

Rollback: chép lại hai file `.bak` rồi `docker compose up -d gateway admin`.

## Kiểm thử

`scratchpad/gateway/check_gateway.sh` (42 kiểm tra trên nginx thật với upstream giả) và
`gw_curl.sh`, `gw_e2e.js` (API và MongoDB thật, trình duyệt thật). Kết quả trong
`docs/MODEL_RELEASE_V24.md`.
