# Model release v22 — luật gõ phím kiểm chứng trên 168.593 người

Bundle: `5f98e7cbfe9f4931ae733aa4abba510a`. Policy: `22`. Collector: 1.8.0 (không đổi). Mô hình chuột train lại cùng dữ liệu và seed: số liệu val/test giống hệt v21.

## Vấn đề

Luật gõ phím giả (`synthetic_typing_v1`, policy 15) đặt ngưỡng theo CMU: 51 người cùng gõ một
mật khẩu. Đo lại trên Aalto 136M (168.593 người gõ câu tự nhiên trên trình duyệt, xem
[kiểm chứng dữ liệu ngoài](EXTERNAL_DATA_VALIDATION_2026-10-28.md)), luật này kết luận BOT
(và khóa phiên) với:

- 4.097 người (2,4%) chỉ vì nhịp gõ đều: CV khoảng cách < 0,10 trong 11 phím. Người gõ giỏi làm được điều này.
- 303 người (0,18%) chỉ vì thời gian giữ phím trung vị < 12 ms. Một số bàn phím và driver báo
  key-up cùng lúc key-down, trong khi người đó vẫn gõ với tốc độ bình thường.

## Thay đổi

Script chỉ lộ ra khi các dấu hiệu đi cùng nhau:

| Mã | Điều kiện | Người thật (Aalto) | Bot đo 2026-10-28 |
|---|---|---|---|
| `TYPING_METRONOME` | 11 phím: CV khoảng cách **và** CV thời gian giữ đều < 0,02 | 0 (thấp nhất 0,027) | `type(text, {delay})` Playwright/Puppeteer/patchright 0,004–0,009 |
| `TYPING_INSTANT_HOLD` | 8 phím: giữ trung vị **và** khoảng cách trung vị đều < 12 ms | 153: gõ 8 phím trong 0–12 ms, là công cụ tự gõ hoặc dữ liệu lỗi | `type()` không delay, Selenium `sendKeys`: 0,3–1,9 ms |
| `TYPING_INSTANT_METRONOME` (mới) | 11 phím: giữ trung vị < 12 ms và CV khoảng cách < 0,05 | 0 (thấp nhất 0,090) | Selenium gõ từng ký tự rồi chờ cố định: 0,017 |

Báo cáo thêm `fastest_median_interval_ms`, `lowest_rhythm_cv`, `lowest_instant_interval_cv`
(`input_provenance_v3`). Lý do hiển thị trên dashboard nêu đúng dấu hiệu đã khớp.

Gate `synthetic_device_rule_gate`: thêm 3 fixture. Hai ca người mà luật cũ kết tội (người gõ
đều với thời gian giữ của người; bàn phím báo giữ 0 ms nhưng gõ tốc độ người) phải là NGHI VẤN.
Selenium gõ từng ký tự phải là BOT. Gate của policy 16–21 được đóng băng. Các gate khác như v21.

## Kiểm tra

- Aalto, toàn bộ 168.593 người (123 triệu phím) qua code policy 22: `TYPING_METRONOME` 0 người,
  `TYPING_INSTANT_METRONOME` 0 người, `TYPING_INSTANT_HOLD` 153 người. Luật cũ: 4.097 + 303.
- Script đo 2026-10-28 (Chrome 156): Playwright `type()` / Puppeteer `type()` / Selenium `sendKeys`
  → `TYPING_INSTANT_HOLD`; Playwright `type`/`pressSequentially` với delay 90–120 ms, patchright
  delay 60 ms, Puppeteer delay 100 ms → `TYPING_METRONOME`; Selenium gõ từng ký tự rồi chờ 110 ms →
  `TYPING_INSTANT_METRONOME`; `fill()` → chỉ `BULK_TEXT_INSERT` (không kết luận, như trước).
- Bộ e2e điền form (8 kịch bản) và bộ mô phỏng thực tế: kết quả như v21.

## Giới hạn

Script đặt `delay` 12–40 ms hoặc ngẫu nhiên hóa từng phím không bị luật gõ phím bắt. Trường hợp
này dựa vào các tín hiệu khác: chuột CDP (policy 21), dấu vết tự động hóa, môi trường.

## Tái hiện

```powershell
python -m core_ml.train --dataset-root "../Tuần 3/repos/web_bot_detection_dataset" --weights-dir bot-lab/release-v22/weights --device cpu
python -m pytest -q
```
