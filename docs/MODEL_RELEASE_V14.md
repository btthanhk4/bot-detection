# Model release v14

Bundle: `e34b19cc251d4c4bb5a22ce3ab0e9b2f`. Policy: `14`. Collector: 1.3.0 (không đổi).
Ngưỡng và tham số mô hình chuột không đổi so với v10–v13.

## Nguồn thay đổi

Sau khi bật HTTPS (2026-10-26), SilkMoon nhận một phiên từ `34.90.165.170`:
Chrome 153 trên Linux, WebGL là **SwiftShader** (rasteriser bằng CPU), `navigator.connection.rtt = 0`,
không có khung trình duyệt, múi giờ Europe/Rome, 0 lần di chuột. XGBoost chấm 0,999 nhưng
policy 13 chỉ cho SUSPECT: thiếu chuột nên không dùng mô hình, và luật môi trường chỉ đếm được
1 nhóm (HEADLESS_ENV). Địa chỉ này thuộc dải Google Cloud `34.90.0.0/15` (europe-west4).

## Thay đổi

1. **Nhóm NETWORK** (mới): địa chỉ client nằm trong dải IP công bố chính thức của Google Cloud,
   AWS, Oracle Cloud, DigitalOcean, Linode, Vultr (`core_ml/data/cloud_ip_ranges.json`,
   tra cứu nhị phân trong `core_ml/features/network.py`). VPN có thể dùng các dải này nên
   NETWORK **không bao giờ là nhóm neo** và không tự quyết định.
2. **GPU phần mềm** vào nhóm GPU: renderer chứa SwiftShader, llvmpipe, softpipe, Mesa offscreen
   hoặc Microsoft Basic Render. GPU của hypervisor (VirtualBox, VMware) bị loại vì người dùng
   máy ảo là hợp lệ.
3. API ghi nhà cung cấp cloud vào `server_headers.datacenter` của mỗi phiên.

Luật `environment_tampering_v1` giữ nguyên: ≥ 3 nhóm độc lập, có ít nhất một nhóm neo
(HEADLESS_ENV, GPU, PERMISSION). Phiên trên giờ có GPU + HEADLESS_ENV + NETWORK nên là BOT.

Release gate tăng từ 11 lên 15 fixture: 1 ca BOT (đúng mẫu phiên trên) và 3 ca không được
kết luận BOT (chỉ IP cloud; VirtualBox + rtt 0 + IP cloud; llvmpipe + IP cloud). Gate của
policy 13 được đóng băng.

## Kiểm chứng

- Replay 27 phiên thật đã lưu: 25 phiên người không có nhóm nào; 4 IP của người dùng
  (nhà mạng Việt Nam) không thuộc dải cloud nào; phiên Google Cloud chuyển thành BOT; hai
  phiên bot cũ vẫn BOT như trước.
- Train lại: mọi số liệu replay giống v13, chỉ khác số policy.

## Rà soát khác trong đợt này (không đổi mô hình)

| Kiểm tra | Kết quả | Quyết định |
|---|---|---|
| Collector chỉ gửi 100 điểm chuột/lần | Replay 150 phiên held-out với giới hạn 100/200/300: AUC 1,000 cả ba; tỉ lệ bắt bot theo lần gửi 87,5% / 87,4% / 87,4%; 0/38 người bị gán BOT | Giữ 100 |
| XGBoost dùng đặc trưng nào | 20/50 (toàn bộ là thống kê chuột); 30 cột môi trường không được dùng vì hằng số trong dữ liệu train | Giữ; cần dữ liệu thật có môi trường |
| Profile shadow | 0 tín hiệu trên 27 phiên thật, kể cả 3 phiên bot | Đã được luật bằng chứng v12–v14 thay thế |
| Hiệu chỉnh xác suất | `score_calibrated = false` | Cần dữ liệu thật có nhãn |

## Cập nhật danh sách IP cloud

```powershell
python -m core_ml.refresh_cloud_ranges   # tải lại từ nguồn chính thức, giữ bản cũ nếu nguồn lỗi
```

Azure chưa có trong danh sách vì Microsoft không cung cấp URL tải cố định.

## Tái hiện

```powershell
python -m core_ml.train --dataset-root "../Tuần 3/repos/web_bot_detection_dataset" --weights-dir bot-lab/release-v14/weights --device cpu
python -m pytest -q
```

Bundle v13 được giữ trong `bot-lab/rollback-v13/` (không commit).
