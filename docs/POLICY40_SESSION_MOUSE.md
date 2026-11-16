# Policy 40: chấm hành vi chuột trên toàn phiên

Ngày: 16/11/2026. Collector 1.17.0, `DECISION_POLICY_VERSION = "40"`, code chính:
`core_ml/features/session_mouse.py`, `api_service/session_mouse_store.py`, `core_ml/models/ensemble.py`.

## Vấn đề

Đến policy 39, mỗi snapshot được chấm riêng trên phần collector gửi lên: 100 bản ghi cuối. Chuột máy tính
phát khoảng 60 sự kiện/giây, nên đó chỉ là **1,5–2,5 giây cuối** của phiên. Kết quả của snapshot mới nhất
ghi đè kết quả cũ. Kết luận về chuột của một phiên dài một phút vì vậy phụ thuộc vào nét rê chuột cuối.

Ví dụ thật (16/11/2026): ba phiên của cùng một người dùng shop như nhau (`pc1-v2-dung`, `-dung-2`,
`-dung-3`). BiLSTM chấm lần gửi cuối lần lượt 0,46 / 0,32 / 0,04. Phiên đầu bị xếp **Nghi vấn**
(`MODEL_DISAGREEMENT`: trung bình 0,46 ≥ 0,425, phân vị 75 là 0,87 ≥ 0,70, XGBoost 0,003 < 0,45), chỉ vì một
nét rê chuột nhanh cuối cùng.

## Thiết kế

Model **không đổi**: BiLSTM vẫn chấm đoạn 24 bước (bước nhảy 12), XGBoost vẫn chấm 20 chỉ số trên cửa sổ
100 bản ghi theo đúng cách collector gửi (`core_ml.collector_windows.export_window`), tức đúng miền dữ
liệu đã train. Thay đổi nằm ở chỗ một phiên có bao nhiêu đoạn và cửa sổ được chấm.

1. **Collector 1.17** gửi mọi điểm rê chuột kể từ lần gửi được API xác nhận trước đó, kèm 100 điểm ngữ
   cảnh, tối đa 600 điểm mỗi lần. Kèm `mouse.moveBase` (chỉ số của điểm đầu tiên trong khung toạ độ) và
   `frameMoves`. Bản ghi chỉ còn `time, type, source, x, y`, đúng những trường API đọc, nên payload nhỏ đi
   khoảng 70%. Nếu tồn đọng 450 điểm chưa gửi, collector gửi sớm thay vì chờ heartbeat.
2. **Khoá ổn định.** Đoạn LSTM bắt đầu ở các bội số của 12 tính theo khung toạ độ, cửa sổ XGBoost kết thúc ở
   mỗi điểm thứ 50. Khoá có dạng `trang:khung:m<chỉ số>` / `w<chỉ số>`. Hai snapshot chồng lên nhau cho ra
   đúng cùng khoá, nên gửi lại, retry hay đến sai thứ tự đều không đếm trùng. Collector cũ (1.16) góp cửa sổ
   của chính nó, khoá theo thời gian.
3. **Kho theo phiên** (`session_mouse`, mỗi phiên một document, `$set` từng khoá nên các snapshot đồng thời
   không ghi đè nhau; tối đa 1.500 đoạn và 300 cửa sổ; tự hết hạn sau 2 ngày; xoá theo phiên). API đọc kho
   trước khi chấm, truyền vào `_session_mouse`, rồi lưu phần mới của snapshot sau khi chấm.
4. **Quy tắc lai.** Khi phiên có ít nhất 12 đoạn và 2 cửa sổ (khoảng gấp đôi một cửa sổ đơn):
   - điểm cả phiên (trung bình và phân vị 75 của mọi đoạn, trung bình XGBoost mọi cửa sổ) quyết định giữa
     Người và Nghi vấn, với đúng các ngưỡng của policy 39, và cũng có thể tự đạt BOT;
   - snapshot nào tự đạt BOT trên cửa sổ của nó thì vẫn là BOT; hai snapshot như vậy vẫn khoá phiên
     (policy 24).

   Lý do phải lai: trên tập held-out, lấy trung bình thuần làm một số phiên bot tụt từ BOT xuống Nghi vấn,
   vì phần lộ rõ là bot bị các đoạn khác làm loãng (xem bảng kết quả).

Mọi luật theo snapshot (tự động hoá, môi trường, nhịp bấm, điện thoại…) vẫn đọc cửa sổ 100 bản ghi như cũ.
Một snapshot đơn lẻ từ collector cũ, và mọi lần replay offline từng payload riêng, cho đúng kết quả policy 39
(có test kiểm chứng).

## Các trường hợp biên đã xét

| Trường hợp | Cách xử lý |
| --- | --- |
| Snapshot gửi lại, retry, đến sai thứ tự | Khoá theo vị trí trong khung toạ độ, không phụ thuộc thứ tự đến |
| Hai snapshot của cùng phiên được xử lý đồng thời | `$set` từng đường dẫn khoá riêng, không mất dữ liệu |
| Gia tốc của bước đầu tiên một đoạn phụ thuộc bước trước | Tính đặc trưng trên cả export rồi mới cắt đoạn, nên cùng đoạn cho cùng giá trị |
| Phiên nhiều trang (SPA hoặc tải lại trang) | Khoá gồm mã trang và mã khung; điểm cả phiên gộp mọi trang |
| Cửa sổ trình duyệt phóng to (khung toạ độ mới) | Collector đếm lại từ 0, khoá mang mã khung mới |
| Collector cũ còn trong cache hoặc site tự host bản cũ | Nhánh tương thích khoá theo thời gian; snapshot đơn lẻ giữ nguyên policy 39 |
| Phiên rất dài | Tối đa 1.500 đoạn và 300 cửa sổ được lưu; snapshot hiện tại vẫn luôn được tính |
| Bot lộ rõ chỉ trong vài cửa sổ | BOT của từng snapshot vẫn giữ (quy tắc lai), hai lần thì khoá |
| Bot độn dữ liệu người giả để làm loãng | Không phải bề mặt tấn công mới: dưới policy 39 bot cũng có thể gửi một cửa sổ giả; mọi luật môi trường và tự động hoá vẫn áp dụng |
| Điện thoại, iPad có trackpad, chạm | Không đọc hay ghi kho (không có điểm rê chuột hợp lệ, hoặc ngoài miền model chuột) |
| Kho lỗi hoặc DB mất kết nối | Không làm hỏng request: snapshot được chấm riêng như policy 39 |
| Beacon khi rời trang vượt 60 KB | Cắt còn 200 rồi 40 điểm mới nhất, cập nhật lại `moveBase` |
| Xoá phiên / xoá theo site / xoá hết | Xoá luôn điểm theo phiên |

## Kết quả

### Tập held-out của benchmark

Giao thức: các phiên validation và test của `web_bot_detection_dataset` (chia bằng `assign_real_session_splits`,
replay toàn bộ quỹ đạo), mỗi 50 điểm rê chuột gửi một snapshot, cùng bundle `0bece0e6`. Cách cũ (policy 39):
mỗi snapshot chấm riêng trên cửa sổ của nó, kết quả cuối là của snapshot cuối, hai snapshot BOT thì khoá.
Cách mới (policy 40): giả lập export của collector 1.17 và kho theo phiên, chạy qua đúng code ensemble.
Chạy lại: `python -m core_ml.evaluate_session_mouse <dataset_root> val|test 50 <out.json>`. Số liệu đầy đủ:
`docs/policy40_session_ab.json`.

| Chỉ số | Validation, cũ | Validation, mới | Test, cũ | Test, mới |
| --- | --- | --- | --- | --- |
| Kết quả cuối của người (Người) | 14/14 | 14/14 | 24/24 | 24/24 |
| Kết quả cuối của bot (BOT) | 46/46 | 46/46 | 66/66 | 66/66 |
| Snapshot người bị Nghi vấn | 183/3.011 (6,1%) | **0** | 269/4.597 (5,9%) | **0** |
| Phiên người từng bị Nghi vấn giữa chừng | 9/14 | **0/14** | 19/24 | **0/24** |
| Snapshot bot ra BOT | 6.342/7.456 (85,1%) | **7.122 (95,5%)** | 7.990/9.259 (86,3%) | **8.853 (95,6%)** |
| Phiên bot từng bị xếp Người | 0 | 0 | 0 | 0 |

Trên benchmark, kết quả cuối vốn đã đúng hết với cả hai cách. Policy 40 bỏ được hoàn toàn các lần gửi giữa
phiên mà người bị xếp Nghi vấn chỉ vì một nét chuột (khoảng 6% số snapshot của người), và bot bị kết luận BOT
sớm hơn, đều hơn. Lấy trung bình thuần, không có quy tắc lai, đã làm 5/46 phiên bot validation tụt xuống Nghi
vấn trong một lần thử trước (lần đó đoạn LSTM còn bị cắt còn 100 bản ghi cuối, nên chỉ mang tính định hướng);
quy tắc lai giữ đủ 46/46.

### Phiên người thật có nhãn (collector 1.16, chỉ có kho theo phiên)

Replay 5 phiên máy tính có nhãn `known_human` (16/11/2026) theo đúng thứ tự snapshot:

| Phiên | Policy 39 | Policy 40 | Ghi chú |
| --- | --- | --- | --- |
| `pc1-v2-dung` | Nghi vấn | **Người** | lần gửi cuối: BiLSTM 0,46 / p75 0,87; cả phiên (36 đoạn, 7 cửa sổ): 0,086 / 0,057 |
| `pc1-v2-dung-2` | Người | Người | lần gửi cuối 0,32 / 0,63, cả phiên 0,087 / 0,033 |
| `pc1-v2-dung-3` | Người | Người | |
| `pc1-v2-doc` | Người | Người | 46 điểm: chưa đủ 12 đoạn, giữ cách chấm cũ |
| `pc1-v2-yen` | Chưa đủ dữ liệu | Chưa đủ dữ liệu | không rê chuột |

Với collector 1.16, kho chỉ có các cửa sổ của từng lần gửi (có khoảng trống giữa các lần gửi). Collector
1.17 phủ kín cả phiên.

### Giới hạn

- Benchmark là dữ liệu cùng nguồn với lúc train; số trên không phải kiểm định độc lập.
- Mới có 5 phiên người thật có nhãn trên máy tính, cần thêm sau khi collector 1.17 chạy thật.
- Ngưỡng 12 đoạn / 2 cửa sổ chọn theo kích thước một cửa sổ (6 đoạn), chưa được tối ưu.
