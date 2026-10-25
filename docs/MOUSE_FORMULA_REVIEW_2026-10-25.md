# Công thức phát hiện bot qua hành vi chuột: tổng hợp và benchmark

Ngày: 2026-10-25. Bổ sung cho [tổng quan tài liệu ngày 24/10](MOUSE_PROFILE_LITERATURE_REVIEW_2026-10-24.md).
Kết quả máy đọc: [MOTOR_FEATURE_BENCHMARK_2026-10-25.json](MOTOR_FEATURE_BENCHMARK_2026-10-25.json).
Mã: [`core_ml/features/motor_features.py`](../core_ml/features/motor_features.py),
[`core_ml/experiments/motor_feature_benchmark.py`](../core_ml/experiments/motor_feature_benchmark.py).

Module và benchmark là **offline**; policy v10 và bundle đang chạy không đổi.

## 1. Kết luận

Không có một "công thức tốt nhất" dùng chung cho mọi loại bot. Mỗi họ đặc trưng
bắt được một kiểu bộ sinh chuột khác nhau, và điểm yếu chung là **bộ sinh chưa gặp
khi train**. Trên benchmark giữ lại từng họ bot (mục 4), bổ sung tốt nhất cho 20 đặc
trưng hiện có là **4 đặc trưng về cách sự kiện được sinh ra**:

| Đặc trưng | Công thức (mục 3.4) |
|---|---|
| `tim_dt_p50` | trung vị khoảng thời gian giữa hai sự kiện move |
| `tim_dt_entropy` | entropy Shannon của histogram Δt (bin 2 ms, 0–200 ms) |
| `tim_dt_mode_share` | tỷ lệ Δt (làm tròn ms) rơi vào giá trị phổ biến nhất |
| `tim_zero_step_frac` | tỷ lệ sự kiện move không dịch chuyển (Δx = Δy = 0) |

| Bộ đặc trưng | AUC TB (3 họ bot OS) | Recall @ FPR 1% TB | Recall họ yếu nhất | Recall họ GAN |
|---|---:|---:|---:|---:|
| 20 đặc trưng hiện tại | 0,956 | 0,645 | 0,297 (pynput) | 0,337 |
| **20 hiện tại + 4 Δt** | **0,995** | **0,929** | **0,794** (pynput) | **0,594** |
| Chỉ 4 Δt | 0,989 | 0,786 | 0,624 | 0,512 |

Hai họ đặc trưng nổi tiếng trong tài liệu **không** giúp ích trong phép thử này:
thống kê phân phối động học (Ahmed & Traore, Shen) và đặc trưng neuromotor xấp xỉ
(số đỉnh vận tốc, khớp lognormal từng nét, LDLJ, SPARC). Thêm chúng vào thậm chí làm
giảm recall trên họ bot chưa gặp. Bộ sinh NaturalMouseMotion vốn được thiết kế theo
mô hình điều khiển vận động, nên đặc trưng dựa trên hình dạng chuyển động dễ bị nó vượt qua.

## 2. Giới hạn của kết luận

- Dữ liệu là **vẽ hình tròn** của DELBOT-Mouse, không phải duyệt web. Mỗi mẫu là
  một lần vẽ, không phải một người: nhiều mẫu đến từ cùng người/máy.
- Bot pynput, pyHM, NaturalMouseMotion điều khiển con trỏ thật của hệ điều hành và
  được ghi qua **cùng trình ghi JavaScript** với người thật, nên đặc trưng không thể
  thắng bằng cách nhận ra một công cụ ghi khác. Nhưng bot có thể đã chạy trên một số
  máy cụ thể, nên Δt có thể phản ánh một phần **thiết bị** (tần số quét chuột, máy ảo)
  chứ không chỉ "người/bot". Có người dùng máy ảo và touchpad trong tập người, giúp
  giảm, chưa loại bỏ được nhiễu này.
- Bot GAN không đi qua trình duyệt; tọa độ đã được làm tròn về pixel nguyên, thời gian
  do mô hình sinh ra. Coi đây là họ tham khảo yếu.
- Bot Playwright/Puppeteer qua CDP (loại của SilkMoon) không có trong benchmark này.
- Ngưỡng chọn để đạt FPR 1% trên khoảng 170 lần vẽ của người ở validation; FPR thật
  trên test khoảng 2%. Khoảng tin cậy rộng.
- Đặc trưng Δt **phụ thuộc trình ghi và thiết bị**. Ngưỡng hay mô hình học trên DELBOT
  **không được** chuyển thẳng sang collector DATACAT; phải học lại trên dữ liệu người
  thật thu bằng chính collector.

## 3. Công thức đã tổng hợp

Ký hiệu: điểm $p_i = (x_i, y_i)$ tại thời điểm $t_i$ (ms); $\Delta t_i = t_i - t_{i-1}$;
$d_i = \lVert p_i - p_{i-1} \rVert$; tốc độ $v_i = d_i / \Delta t_i$.

### 3.1 Hình học và động học (đang có trong DATACAT)

Nguồn: DELBOT-Mouse; Ahmed & Traore 2007; Chu et al. 2013; khảo sát Khan et al. 2022.

- Gia tốc $a_i = (v_i - v_{i-1})/\Delta t_i$, jerk $j_i = (a_i - a_{i-1})/\Delta t_i$.
- Độ thẳng (straightness) $= \lVert p_n - p_0 \rVert / \sum_i d_i$.
- Độ cong rời rạc $\kappa_i = |\Delta\theta_i| / d_i$, với $\theta_i = \operatorname{atan2}(\Delta y_i, \Delta x_i)$.
- Entropy góc: entropy Shannon của histogram 8 hướng của $\theta_i$.
- Tự tương quan vận tốc bậc 1, độ lệch (skewness) tốc độ, tỷ lệ dừng.

Đây là 20 đặc trưng `STATISTICAL_FEATURE_NAMES` hiện tại.

### 3.2 Neuromotor: sigma-lognormal (Plamondon; BeCAPTCHA-Mouse)

Tốc độ một nét là một lognormal, quỹ đạo là tổng nhiều nét:

$$|v_i(t)| = \frac{D_i}{\sqrt{2\pi}\,\sigma_i\,(t - t_{0i})}\exp\!\left(-\frac{(\ln(t - t_{0i}) - \mu_i)^2}{2\sigma_i^2}\right),\qquad |v(t)| = \sum_{i=1}^{N} |v_i(t)|$$

Mỗi nét có 6 tham số $(D_i, t_{0i}, \mu_i, \sigma_i, \theta_{si}, \theta_{ei})$. BeCAPTCHA lấy
max, min, trung bình của 6 tham số trên mỗi nửa quỹ đạo, cộng số nét $N$: 37 đặc
trưng. Kết hợp với đặc trưng toàn cục, Random Forest đạt khoảng 98–99% trên bot sinh
bằng hàm và GAN trong benchmark của họ, cũng là bot do họ tự sinh
([arXiv:2005.00890](https://arxiv.org/abs/2005.00890)). Thuật toán trích chính xác
hơn là iDeLog ([arXiv:2401.15473](https://www.arxiv.org/pdf/2401.15473)).

DATACAT mới **xấp xỉ**: tách nét tại các cực tiểu tốc độ dưới 15% đỉnh, khớp một
lognormal mỗi nét, lấy $R^2$ và $\sigma$. Chưa cài iDeLog.

### 3.3 Độ mượt và cấu trúc submovement

- **Minimum-jerk** (Flash & Hogan): quỹ đạo tối thiểu
  $\int \lVert \dddot{p}(t)\rVert^2 dt$ cho profile vận tốc hình chuông, đối xứng.
  Người thật có pha phóng nhanh rồi 0–2 submovement hiệu chỉnh khi tiếp cận mục tiêu
  ([arXiv:2110.00443](https://arxiv.org/pdf/2110.00443)).
- **Log dimensionless jerk** (Balasubramanian 2015):
  $\mathrm{LDLJ} = -\ln\!\left(\frac{T^3}{v_{\max}^2}\int_0^T \lVert \dddot{p}(t)\rVert^2 dt\right)$.
- **SPARC**: độ dài cung của phổ biên độ chuẩn hóa của tốc độ, cắt ở 10 Hz.
- **Số submovement, tỷ lệ thời điểm đỉnh** $(t_{\text{peak}} - t_{\text{start}})/T$:
  lognormal cho giá trị dưới 0,5; minimum-jerk cho 0,5. Một patent phát hiện gian lận
  game dùng việc "luôn đúng một submovement có thời lượng gần 0"
  ([US11947742](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11947742)).
- **Định luật Fitts**: $MT = a + b\log_2(1 + D/W)$. Bot đi với thời gian cố định
  bất kể khoảng cách là dấu hiệu, nhưng cần biết kích thước mục tiêu $W$ nên khó dùng
  trên trang web bất kỳ.
- **Tỷ lệ gia tốc gần 0** (Castle mức 2): tỷ lệ mẫu có $|a|\cdot 0{,}1\,\text{s} < 0{,}05\,\bar v$.

### 3.4 Cách sự kiện được sinh ra (khuyến nghị)

Nguồn: Castle (đếm `mousemove`, gia tốc gần 0),
[Choudhary et al. arXiv:2607.26935](https://arxiv.org/abs/2607.26935) (`mouse_event_rate`,
`teleport_click_ratio`, `no_micro_jitter`), cside (đánh giá trên bộ sinh chưa gặp).

- $\text{event\_rate} = n / (t_n - t_0)$.
- $\text{dt\_p50} = \operatorname{median}\{\Delta t_i > 0\}$.
- $\text{dt\_entropy} = -\sum_k q_k \log_2 q_k$, với $q_k$ là tỷ lệ $\Delta t$ rơi vào bin $k$ (2 ms, 0–200 ms).
- $\text{dt\_mode\_share} = \max_v \#\{i : \operatorname{round}(\Delta t_i) = v\} / n$.
- $\text{zero\_step\_frac} = \#\{i : d_i = 0\} / n$.
- $\text{teleport\_frac} = \#\{i : d_i > 100\,\text{px} \wedge \Delta t_i < 50\,\text{ms}\}/n$.
- $\text{teleport\_click\_ratio}$: tỷ lệ click có cú nhảy trên 100 px trong dưới 50 ms
  trong 100 ms trước đó. Bài báo báo tỷ lệ này bằng 0 với mọi phiên agent Playwright.
- $\text{micro\_jitter}$: tỷ lệ bước $|\Delta x|,|\Delta y| \le 1$ có đổi chiều.

Giải thích vật lý: chuột thật tạo sự kiện theo tần số quét của thiết bị và nhịp
khung hình của trình duyệt, nên $\Delta t$ có phân phối đặc trưng và nhiều mức.
Bot dừng theo lệnh `sleep` cố định hoặc ngẫu nhiên theo phân phối đơn giản, nên phân
phối $\Delta t$ hẹp hoặc lệch so với phần cứng. Hình dạng đường đi có thể giả rất giống,
còn nhịp sinh sự kiện thì khó giả hơn nếu bot không mô phỏng phần cứng.

## 4. Benchmark

**Dữ liệu:** DELBOT-Mouse (MIT), có sẵn trong `Tuần 3/repos/DELBOT-Mouse/python`.

| Nguồn | Số lần vẽ | Ghi chú |
|---|---:|---|
| Người: pc1, pc2, pc2_pad (touchpad), vm (máy ảo), fast | 187, 459, 62, 140, 9 | Bỏ `tel` (cảm ứng), ngoài miền mô hình chuột |
| Bot pynput | 408 | Điều khiển con trỏ hệ điều hành |
| Bot pyHM | 55 | Thư viện "human mouse" |
| Bot NaturalMouseMotion | 234 | Mô phỏng điều khiển vận động |
| Bot GAN | 1.899 | Không qua trình duyệt; giới hạn 400 mẫu khi train |

**Giao thức:**
- Giữ lại một họ bot hoàn toàn khỏi train.
- Người chia 60/20/20 theo từng nguồn thiết bị.
- XGBoost 200 cây, sâu 4, lr 0,05; trọng số cân bằng lớp.
- Ngưỡng là phân vị 99 điểm của người ở validation.
- 3 seed (bộ đề xuất cuối: 5 seed).

**Toàn bộ bộ đặc trưng** (AUC TB / recall TB trên 3 họ bot OS / recall họ yếu nhất / recall GAN):

| Bộ | Số đặc trưng | AUC | Recall | Yếu nhất | GAN |
|---|---:|---:|---:|---:|---:|
| current20 | 20 | 0,956 | 0,645 | 0,297 | 0,337 |
| kinematic | 19 | 0,871 | 0,205 | 0,075 | 0,127 |
| neuromotor | 13 | 0,746 | 0,109 | 0,004 | 0,220 |
| timing (10) | 10 | 0,957 | 0,561 | 0,313 | 0,258 |
| current20 + kinematic | 39 | 0,944 | 0,542 | 0,322 | 0,431 |
| current20 + neuromotor | 33 | 0,950 | 0,419 | 0,286 | 0,279 |
| current20 + timing | 30 | 0,984 | 0,708 | 0,427 | 0,356 |
| current20 + click_gap | 21 | 0,956 | 0,567 | 0,313 | 0,382 |
| current20 + event_timing (9) | 29 | 0,992 | 0,862 | 0,680 | 0,330 |
| tất cả | 62 | 0,966 | 0,656 | 0,359 | 0,520 |
| **current20 + 4 Δt** (5 seed) | 24 | **0,995** | **0,929** | **0,794** | **0,594** |

**Ablation trong nhóm event_timing** (bỏ một hoặc chỉ thêm một vào current20):

- `tim_dt_p50` đóng góp nhiều nhất: bỏ đi, recall giảm 0,862 → 0,741 và họ yếu nhất
  0,680 → 0,348.
- `tim_dt_entropy` và `tim_zero_step_frac` đóng góp thêm.
- Các đặc trưng còn lại (event_rate, dt_cv, teleport, max_step_ratio, micro_jitter)
  không giúp; bỏ ra còn nhích lên một chút. Vì vậy bộ đề xuất chỉ giữ 4 đặc trưng.
- Khoảng cách click so với move cuối (`click_gap`) làm giảm recall: trong tác vụ vẽ,
  nó không mang tín hiệu như trong bài báo về agent.

## 5. Áp dụng vào DATACAT

1. **Collector schema v2:**
   - Gửi timestamp với độ phân giải dưới 1 ms (hiện đang làm tròn ms).
   - Giữ các move trùng vị trí (hiện tại vẫn ghi lại).
   - Thêm bộ đếm tích lũy và số coalesced sample. Phép thử ngày 25/10 cho thấy
     Playwright luôn có `getCoalescedEvents().length = 1`; chưa đo người thật.
2. **Thu người thật bằng chính collector trên SilkMoon** trước khi học Δt. Không dùng
   ngưỡng học từ DELBOT hoặc M4D.
3. **Candidate XGBoost = 20 đặc trưng hiện tại + 4 Δt**, train theo protocol (chia theo
   người và họ bot). So sánh với baseline trên cùng tập test bị khóa. Đổi feature contract
   nên phải tăng phiên bản policy và bundle.
4. **Kiểm tra độ nhạy thiết bị:** báo cáo riêng kết quả theo chuột rời, touchpad, máy
   ảo/RDP, trình duyệt; đây là chỗ Δt dễ nhận nhầm người thật nhất.
5. **Neuromotor (sigma-lognormal đầy đủ, iDeLog)** giữ là hướng nghiên cứu. Bản xấp xỉ
   ở đây không cải thiện; chưa đủ cơ sở kết luận bản đầy đủ cũng vậy.

## 6. Tái hiện

```powershell
python -m core_ml.experiments.motor_feature_benchmark `
  --delbot-dir "../Tuần 3/repos/DELBOT-Mouse/python" `
  --output docs/MOTOR_FEATURE_BENCHMARK_2026-10-25.json
```

Chạy khoảng 5 phút trên CPU. Bộ "current20 + 4 Δt" với 5 seed và ablation từng đặc
trưng được chạy bằng cách thay `FEATURE_SETS` trong cùng module; số liệu ở mục 4.

## 7. Nguồn

- Acien et al., BeCAPTCHA-Mouse, Pattern Recognition 2022 — [arXiv:2005.00890](https://arxiv.org/abs/2005.00890)
- Ferrer et al., iDeLog — [arXiv:2401.15473](https://www.arxiv.org/pdf/2401.15473)
- Khan et al., Mouse Dynamics Behavioral Biometrics: A Survey — [arXiv:2208.09061](https://arxiv.org/pdf/2208.09061)
- Choudhary et al., What Does It Take to Detect an AI Agent? — [arXiv:2607.26935](https://arxiv.org/abs/2607.26935)
- Castle, phát hiện chuyển động chuột tự động — [blog](https://blog.castle.io/bot-or-not-can-you-spot-the-automated-mouse-movements/)
- cside, cursor_v2 — [blog](https://cside.com/blog/catching-bots-by-how-they-move)
- Optimal feedback control cho tương tác người–máy — [arXiv:2110.00443](https://arxiv.org/pdf/2110.00443)
- Patent phát hiện gian lận bằng submovement — [US11947742](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11947742)
- Chu et al., Blog or block, Computer Networks 2013 — [PDF](https://www.eecis.udel.edu/~hnw/paper/comnet13.pdf)
- SigmaDrift (bộ sinh dùng sigma-lognormal + Fitts) — [GitHub](https://github.com/ck0i/SigmaDrift)
- DELBOT-Mouse — [GitHub](https://github.com/chrisgdt/DELBOT-Mouse)
