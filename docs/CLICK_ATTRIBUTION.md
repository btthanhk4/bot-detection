# Theo dõi click quảng cáo (clickid, t1)

Bổ sung theo yêu cầu của nhà mạng quảng cáo chạy trang đích "Downloader" (2026-11-10).

Mỗi lượt xem trang gắn với một click quảng cáo. Nhà mạng cần biết hai điều:
- từng click là người hay bot;
- bot đến từ nguồn (zone) nào.

## 1. Gắn tham số vào URL trang đích

Nhà mạng thêm hai tham số vào URL trang đích:

```
https://toprewards4u7.online/Download/Downloader/index.html?clickid={clickid}&t1={t1}
```

| Tham số | Ý nghĩa | Trường lưu trong phiên |
|---|---|---|
| `clickid` | Mã nhà mạng gán cho click | `click_id` |
| `t1` | Nguồn (trang web hoặc zone) mà click đến từ đó | `click_source` |

Không cần sửa thẻ script, vì collector đã gửi nguyên URL của trang. Server làm phần còn lại:

- **Lấy từ trang đầu tiên của phiên.** Khách đi sang trang khác thì phiên vẫn giữ click ban đầu.
  Nếu trang đầu không có tham số, server lấy từ trang đầu tiên có tham số.
- **Bỏ giá trị chưa thay.** Macro nhà mạng quên thay (`{clickid}`), hoặc giá trị không phải mã gồm
  chữ, số và `._~:@+-`, hoặc dài hơn 128 ký tự, thì bị bỏ qua.
- **Đổi tên tham số được.** Đặt biến môi trường `BOT_CLICK_ID_PARAMS` và `BOT_CLICK_SOURCE_PARAMS`,
  ví dụ `BOT_CLICK_ID_PARAMS=clickid,click_id`. Tên không phân biệt hoa thường.
- **Phiên cũ được điền lại một lần.** Những phiên lưu trước khi có tính năng này được điền
  `click_id`/`click_source` từ `landing_url` một lần khi API khởi động. Mốc
  `click_attribution_backfill_v1` trong `service_control` đánh dấu đã chạy, nên không quét lại.

## 2. Xem kết quả

**Báo cáo** (dashboard, mục Báo cáo, kỳ 24 giờ, 7 ngày hoặc 30 ngày):
- **Click quảng cáo theo nguồn (t1):** với mỗi nguồn, số phiên Bot, Nghi vấn, Người thật, Chưa đủ
  dữ liệu, và tỉ lệ bot. Nguồn nhiều bot nhất xếp đầu.
- **Click gần đây:** 100 click mới nhất, mỗi dòng gồm clickid, t1, kết luận, lý do, thời gian.
- **Tải CSV click:** chỉ các phiên có click. Cột: clickid, t1, kết luận, lý do, thời gian, IP,
  quốc gia, nhà mạng, thiết bị, mã phiên. Nhà mạng dùng file này để đối chiếu với log click của mình.

**Các chỗ khác:**
- CSV đầy đủ của báo cáo có thêm hai cột `clickid` và `t1`.
- Khung chi tiết phiên hiện "Click quảng cáo: clickid … · t1 …".

**API tra cứu một click** (quyền xem; tài khoản khách hàng chỉ thấy website của mình):

```
GET /api/v1/clicks/{clickid}
```

```json
{"click_id": "dbpj8r797ugs73fe0jng", "click_source": "28628-5fe41363", "verdict": "BOT",
 "sessions": [{"sessionId": "…", "site_id": "downloader", "verdict": "BOT",
               "decision_basis": "forged_browser", "automation_rule": "forged_browser_v1",
               "created_at": "2026-11-10T14:58:07+00:00", "updated_at": "…"}]}
```

- `verdict` nhận một trong bốn giá trị: `BOT`, `SUSPECT`, `HUMAN`, `INSUFFICIENT_EVIDENCE`.
- Một click có thể mở trang nhiều lần, tạo nhiều phiên. Khi đó click lấy kết luận nặng nhất:
  BOT, rồi đến SUSPECT, rồi HUMAN.
- Không tìm thấy click: trả 404. Mã click sai định dạng: trả 422.

## 3. Lưu ý khi đọc số liệu

- Báo cáo đếm **phiên**, không đếm click duy nhất. Click mở trang hai lần được đếm hai phiên.
- "Chưa đủ dữ liệu" nghĩa là khách rời trang trước khi có đủ thao tác để kết luận. Nhóm này không
  phải người, cũng không phải bot.
- Kết luận theo click dùng chung mô hình và luật với mọi phiên khác (policy hiện hành). Mỗi luật có
  mức kiểm chứng riêng, xem tài liệu `MODEL_RELEASE_V*.md`.
