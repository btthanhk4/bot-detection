# Policy 52: thử mọi hướng tối ưu còn lại, giữ những gì qua kiểm chứng

Ngày 20/11/2026. `DECISION_POLICY_VERSION = "52"`.

## Tiêu chí giữ một thay đổi

Một ứng viên chỉ được giữ khi thỏa đủ cả bốn điều kiện:
1. **Tham chiếu:** trên các phiên nó bắt, Fingerprint gắn cờ ở mức cao (≥ 85–90%).
2. **Người thật:** không dính phiên người thật đã biết nào (52 phiên).
3. **Lập luận:** có lý do vật lý hoặc theo đặc tả, không chỉ là tương quan.
4. **Mô phỏng:** mức trùng với Fingerprint và κ không giảm.

Mọi phép đo đều chỉ đọc trên production (55.7k phiên; 4.236 phiên còn dữ liệu thô) và chỉ in số tổng hợp.

## Kết quả từng hướng

| # | Hướng | Đo được | Quyết định |
| --- | --- | --- | --- |
| A1 | Tín hiệu độc lập cho điện thoại chạm 1–2 lần đang NGHI VẤN (777 phiên có tham chiếu) | Quét mọi đặc trưng đã lưu. Chỉ một ngưỡng đạt 90%: con quay gần như đứng yên (30–52 phiên), nhưng dính 141 phiên HUMAN sạch (máy đặt trên bàn), và đứng yên không phải bằng chứng tự động hóa | Loại |
| A2 | User-Agent mâu thuẫn Client Hints trên máy tính, đi cùng nhóm môi trường "neo" | 149 phiên NGHI VẤN, Fingerprint gắn cờ 39/39, 0 người thật. Đứng một mình: người có thể có (tiện ích đổi User-Agent) | **Giữ:** `ua_hints_anchor_v1` |
| A3 | Bấm chuột mà trước đó không di chuyển | Dính 6 phiên người thật đã biết | Loại |
| A4 | Cuộn đều như máy | 0 phiên khớp ngưỡng chặt; ngưỡng nới thì dính phiên Fingerprint coi là sạch (0/7) | Loại |
| A5 | 10–24 lần di chuột thẳng tuyệt đối, bước đều | 2 phiên, cả hai đã là BOT | Loại (không thêm gì) |
| B1 | Thêm nhãn người thật trên máy tính | Cần người khác test | Chờ bạn |
| B2 | Bot cấp hệ điều hành (pyautogui) và chạm bơm qua ADB trên máy thật | Script đã sẵn sàng ở `bot-lab/os_mouse_bot.py`, `bot-lab/adb_tap_bot.ps1` | Chờ bạn chạy |
| C1 | Dấu vết TLS của máy khách | Gateway ghi cipher, curve, protocol vào header; API lưu `server_headers.tls_client` (GREASE đã lọc, có chữ ký) | **Đã bật, chỉ thu thập.** Chưa luật nào dùng; cần vài ngày dữ liệu |
| C2 | Danh sách IP VPN, datacenter, blocklist công khai | Phiên HUMAN trong dải datacenter: Fingerprint gắn cờ 13% (máy tính), 44% (điện thoại). Phần lớn là người dùng VPN | Loại (trái nguyên tắc IP đám mây không quyết định một mình) |
| C3 | Cụm cấu hình máy tính không tương tác | Bắt 96 phiên HUMAN, nhưng không phiên nào có tham chiếu để kiểm | Tạm gác |

## `ua_hints_anchor_v1`

Luật áp cho máy tính. Kết luận BOT khi có đủ hai điều kiện:
- **User-Agent mâu thuẫn Client Hints:** User-Agent khai một phiên bản Chrome khác với `navigator.userAgentData`, hoặc khác với header HTTP `User-Agent`.
- **Độc lập với điều trên, có một nhóm môi trường "neo":** headless, GPU hoặc quyền thông báo mâu thuẫn.

Mỗi dấu hiệu đứng một mình vẫn chỉ chặn HUMAN, như các release gate trước đã quy định:
- tiện ích đổi User-Agent → NGHI VẤN;
- lệch Client Hints đi cùng chuột người → HUMAN.

Một lời nói dối về User-Agent chỉ được đếm một lần. Vì vậy luật không ghép lệch Client Hints với `UA_API_MISMATCH` hay `ANACHRONISTIC_UA`, vì cả hai đều là cùng một lời nói dối nhìn từ chỗ khác. Luật cũng không ghép với `PLATFORM_SPOOFED`, vì tiện ích đổi User-Agent cũng có thể gây ra dấu hiệu này. Các trường hợp đó giữ nguyên luật cũ.

Dấu hiệu "neo" không được suy ra từ chính chuỗi User-Agent. Lần train đầu đã trượt release gate của policy 20:
khi chuỗi `HeadlessChrome` chỉ có ở một trong hai User-Agent, sự việc đó sinh ra cả `detectors.headlessUa` (nhóm
HEADLESS_ENV) lẫn `server.http_ua_mismatch` (nhóm CLIENT_HINTS). Đó là cùng một lời nói dối nhưng bị đếm thành hai.
Đã sửa bằng `ua_independent_anchors`. Cả 149 phiên trên production vẫn khớp luật, vì dấu hiệu "neo" của chúng là GPU
phần mềm (123), `rttZero` (26) hoặc `headlessScreen` (11).

Phiên đã lưu được áp bằng `manage rejudge` (lệnh này chỉ kết tội).

Release gate: đóng băng `CLIENT_FORGERY_RULE_GATE_V51`; thêm 5 fixture (2 BOT, tiện ích đổi User-Agent, chuột người, điện thoại), tổng 59 ca.

## Dấu vết TLS

- **Gateway:** nginx (`silkmoon-gateway`) gửi `X-DC-TLS-Ciphers`, `X-DC-TLS-Curves`, `X-DC-TLS-Proto` (`$ssl_ciphers`, `$ssl_curves`, `$ssl_protocol`) cho `api.datacat.io.vn` và đường telemetry của SilkMoon. Nginx tự đặt các header này, ghi đè header cùng tên mà máy khách gửi lên. Sao lưu cấu hình: `/var/www/silkmoon/nginx/nginx.conf.bak-20261120-tls`.
- **API:** `tls_client()` lọc GREASE, tính chữ ký 16 ký tự và lưu kèm danh sách. Chưa luật nào đọc dữ liệu này.
- **Bước tiếp theo:** khi có vài trăm phiên, so chữ ký TLS với trình duyệt mà trang tự khai (Chrome, Safari, Firefox). Một User-Agent Chrome đi qua TLS của Python, Node hay curl là mâu thuẫn mà JavaScript không che được.

## Kết quả trên production (20/11/2026)

Deploy commit 18b5aca, bundle `f00152cd` (tensor giống policy 51). Sao lưu trước khi ghi:
`/root/backups/detection_results-20261120-pre-rejudge52.archive.gz` (55.796 phiên, sha256 `f11443f7…`).

`manage rejudge --apply`: 149 phiên NGHI VẤN → BOT, tất cả theo `ua_hints_anchor_v1`, không phiên HUMAN nào bị đổi.
Chạy lại lần hai: 0.

| Chỉ số (phiên có tham chiếu Fingerprint) | Trước | Sau |
| --- | --- | --- |
| Tỷ lệ có kết luận dứt khoát | 91,4% | 91,6% |
| Trùng với Fingerprint (phần đã quyết định) | 96,49% | 96,50% |
| κ | 0,884 | 0,885 |
| HUMAN bị Fingerprint gắn cờ | 164/17.112 | 164/17.112 |
| Tập có nhãn (52 người / 30 bot) | 50 HUMAN, 2 NGHI VẤN / 28 BOT, 2 NGHI VẤN | không đổi |

Không chỉ số nào giảm, nên giữ luật. Dấu vết TLS đã có trong telemetry mới (TLS 1.3, 15 cipher, curve gồm
X25519MLKEM768 của Chrome mới).
