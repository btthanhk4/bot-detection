# Model release v11

Bundle: `22ad0bcbd9a641a098ddcc92a64c85ac`. Policy: `11`. Collector: 1.2.0.
BOT cutoff `0.96`, SUSPECT cutoff `0.45`, tối thiểu 25 move: không đổi.

## Thay đổi

- **Luật `synthetic_click_v1`** (decision basis `synthetic_input`): kết luận `BOT/FINAL`
  khi ít nhất 3 click trên control từ 16 px trở lên **đều** trúng tâm (lệch không quá
  1 px theo cả hai trục), **và** ít nhất 2 trong số đó nhả chuột sau dưới 5 ms. Luật chạy
  độc lập với mô hình chuột, giống luật HeadlessChrome của v10, và xếp sau luật đó.
- Collector 1.2.0 ghi `mouse.clickEvents` (độ lệch so với tâm control, kích thước,
  thời gian giữ), `mouse.counters` và `mouse.pointerStats` (coalesced samples, chỉ có
  trên HTTPS). Không ghi nội dung, id hay text của phần tử. Click bằng bàn phím
  (`detail = 0`) và event giả bằng script (`isTrusted = false`) bị bỏ qua.
- `breakdown.input_provenance` báo cáo số click đo được, số click trúng tâm, số lần nhả
  ngay, thời gian giữ trung vị và thống kê coalesced, kể cả khi luật không kích hoạt.

Hai file model **giống hệt v10 về tham số**: chênh lệch tham số LSTM bằng 0 và dự đoán
trên 1.000 cửa sổ M4D chênh 0. Hash file khác do metadata lúc ghi file. Mọi số liệu
replay cùng nguồn trùng v10: 0 cửa sổ người bị gán BOT, 0 cửa sổ bot bị gán HUMAN, BOT
recall ở snapshot cuối 80,43% (validation) và 90,91% (test). M4D không có dữ liệu click,
nên các số này không đo được tác dụng của luật mới.

## Bằng chứng cho luật mới

| Kiểm tra | Kết quả |
|---|---|
| Release gate: 9 fixture cố định (2 bot, 7 ca giống người) | 9/9 đúng, có trong manifest |
| Đo trên site thật: click mặc định Playwright | Thời gian giữ 0–0,3 ms; lệch tâm tối đa 0,6 px |
| E2E trình duyệt thật: Playwright `page.click()` mặc định | BOT, `synthetic_input` |
| E2E: `page.mouse.click()` vào chính giữa | BOT |
| E2E: Selenium `element.click()` | BOT |
| E2E: Playwright có vị trí ngẫu nhiên + delay 60–140 ms | Không kích hoạt |
| E2E: chỉ có delay, hoặc chỉ lệch tâm, hoặc chỉ 2 click | Không kích hoạt |
| E2E: Selenium Actions có pause 90 ms | Không kích hoạt |
| Mô phỏng 20.000 phiên người (độ phân tán 15% kích thước control, 20% là tap) | 0 lần kích hoạt |
| Mô phỏng 20.000 phiên người rất chính xác (8%), toàn bộ là touchpad tap | ≤ 4 lần (giới hạn trong test) |

## Giới hạn

- Chỉ bắt automation dùng **click mặc định**. Bot có click ngẫu nhiên trong control và
  có thời gian giữ thật (ví dụ ghost-cursor, `click({position, delay})`) không bị bắt.
  Luật này làm tăng chi phí cho kẻ tấn công, không thay thế mô hình chuột.
- Ước lượng nhận nhầm là **mô phỏng theo giả định**, chưa đo trên người thật bằng
  collector. Công cụ trợ năng (điều khiển bằng giọng nói, switch access) có thể click
  đúng tâm và nhả ngay; những người dùng này sẽ bị gán BOT. Giữ chế độ chỉ giám sát,
  không tự động chặn.
- Collector cũ (1.1.0) không gửi `clickEvents`, nên luật không bao giờ kích hoạt với họ.
- Coalesced samples và `pointerrawupdate` chỉ có trên HTTPS; SilkMoon hiện chạy HTTP.

## Tái hiện

```powershell
python -m core_ml.train --dataset-root "../Tuần 3/repos/web_bot_detection_dataset" --weights-dir bot-lab/release-v11/weights --device cpu
python -m pytest -q
cd collector; npm test
```

Bundle v10 được giữ trong `bot-lab/rollback-v10/` (thư mục không được commit). Để
rollback trên server, checkout commit trước release này.
