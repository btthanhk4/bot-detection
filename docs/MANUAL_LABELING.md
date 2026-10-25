# Đánh số traffic và gán nhãn dataset

## Số thứ tự

Dashboard có STT lưu bền vững trong MongoDB, mỗi `sessionId` một số. Init,
heartbeat, retry và reload dashboard không tạo thêm số cho cùng session.
Phiên mới thường được SDK tạo khi tải trang mới; STT không phải số người
duy nhất, số IP, số request hoặc số click quảng cáo.

Server cấp số trước inference, theo lần đăng ký thành công đầu tiên trong
MongoDB, không tin đồng hồ client. Các phiên cũ còn trong database được
backfill theo thời gian server sớm nhất còn lưu, hòa thì theo session ID.
Không thể phục dựng phiên đã bị xóa/TTL trước khi triển khai tính năng.
Khi MongoDB lỗi, số có thể chưa có cho đến replay; lúc ấy thứ tự là lúc
đăng ký sau phục hồi, không cam kết đúng thứ tự truy cập trên mạng.

Số không tái sử dụng sau xóa. Crash giữa cấp counter và ghi session, hoặc
race giữa các API replica dùng chung DB, có thể để lại khoảng trống; dùng
tổng phiên trên dashboard để đếm, không dùng STT lớn nhất. Hệ thống hiện
chỉ hỗ trợ cấu hình một worker. Phân trang bằng cursor STT, không phải offset
thay đổi theo heartbeat. Thời gian trong bảng là lần đầu server ghi nhận.

STT không tự chứng minh traffic thuộc nhà cung cấp nào. Ghi nguồn/lô đã biết
và đối chiếu thời gian, session, receipt; không mặc định mọi traffic trong
một khoảng STT đều của nhà cung cấp.

## Gán nhãn

1. Bấm biểu tượng clipboard cạnh nút Hồ sơ.
2. Chọn BOT, HUMAN hoặc UNKNOWN để bỏ nhãn khỏi dữ liệu học.
3. Ghi nguồn, mã người/lượt chạy/lô, người gán và bằng chứng.
4. Chỉ xác nhận nguồn độc lập khi thực sự biết, không dựa vào verdict AI.
5. Lưu bằng quyền `BOT_ADMIN_TOKEN`. Quyền đọc không được sửa nhãn.

Nhãn dataset và verdict AI là hai trường khác nhau. Lưu nhãn không thay
điểm, verdict, policy hoặc weights hiện tại. Revision ngăn tab cũ ghi đè
nhãn mới; lỗi/mất phản hồi cần tải lại danh sách trước khi thử lại.
Nhãn chưa xác minh hiển thị `*`. BOT/HUMAN cần raw nghiên cứu còn tồn tại;
phải bật `BOT_CAPTURE_ENABLED=true` trước đợt thu.

Khi lưu BOT/HUMAN, snapshot đang có được giữ vào `labeled_captures`, không
có TTL của raw vận hành. Không ghép hoặc sinh quỹ đạo mới. Snapshot đến
sau không tự động vào bản chọn cũ: đợi hoàn tất run rồi gán hoặc lưu lại
nhãn để bổ sung snapshot mới. Lịch sử sửa nhãn nằm trong `research_sessions`.
Hãy quản lý thời hạn lưu dataset/backup riêng; xóa phiên/xóa tất cả trên
dashboard sẽ xóa cả snapshot dataset và lịch sử nhãn tương ứng. Giữ STT
đã cấp để tránh tái sử dụng, không giữ nội dung nhãn sau thao tác xóa.

## Xuất và kiểm tra

Đặt `MONGO_URI` và `MONGO_DB` đúng môi trường vận hành. Ví dụ:

```console
python -m core_ml.dataset.export_captures --study-id thesis_pilot_01 --site-id site_01 --since 2026-10-23T00:00:00+07:00 --until 2026-10-24T00:00:00+07:00 --labeled-only --output C:/datacat-private/export-2026-10-23
python -m core_ml.dataset.export_captures --verify C:/datacat-private/export-2026-10-23
```

`--labeled-only` đọc snapshot đã giữ. `--include-manual-labels` kèm nhãn khi
xuất raw vận hành thông thường. Ngoài JSONL raw/manifest/template UNKNOWN,
export có `manual-labels.jsonl` với run ID, STT, revision, nguồn, ghi chú và
trạng thái xác nhận. Giữ template UNKNOWN để không phá format export cũ;
nhãn đã gán nằm trong file riêng có checksum. Không chỉnh file rồi bỏ qua verify.

## Dùng trong huấn luyện

`load_manual_training_runs()` đọc export đã verify, bỏ UNKNOWN/chưa xác
nhận và mặc định bỏ nhãn chỉ do nhà cung cấp/công cụ thương mại khẳng định.
Mã nhóm dùng để chia dữ liệu trước khi tạo cửa sổ; không đưa nguồn, nhãn,
reviewer, STT hoặc dự đoán model vào feature. Không đổi nguồn thành manual
review để vượt điều kiện nếu chưa có xác minh độc lập.

Pipeline đã có đầu vào thử nghiệm, yêu cầu chỉ rõ các nhóm được dùng train:

```console
python -m core_ml.train --dataset-root PATH_TO_EXISTING_DATASET --manual-export-dir C:/datacat-private/export-2026-10-23 --manual-train-group bot_config_train_01 --manual-train-group person_train_01 --diagnostic-only --weights-dir C:/datacat-private/candidate-manual
```

Lặp `--manual-train-group` cho nhóm train. Nhóm không chỉ định không được
đưa vào học; cần giữ riêng validation/test mới để đo khả năng tổng quát.
Pipeline vẫn giữ đối chứng và release checks trên dataset cũ. Nhãn mới chỉ
bổ sung mẫu chuột, không biến profile hiện chưa được train thành model mới.
Không có đủ 25 move desktop hợp lệ thì không thể huấn luyện model chuột
bằng nhãn đó. Các snapshot lặp trong một run được khử trùng; không nối
quỹ đạo giữa các snapshot.

Nhánh này chỉ tạo candidate diagnostic trong thư mục riêng, không ghi đè
bundle production. Chưa tự động huấn luyện sau mỗi lần bấm Lưu. Chỉ đổi
model chạy thật sau khi có đủ dữ liệu hai lớp, kiểm chứng trên nhóm độc lập
và xác nhận candidate tốt hơn. Chưa huấn luyện lại weights trong lượt triển
khai tính năng này.
