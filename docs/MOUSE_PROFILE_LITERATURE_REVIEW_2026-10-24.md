# Tổng quan tài liệu: phân tích hành vi chuột và profile traffic

Ngày khảo sát: 2026-10-24. Tài liệu này bổ sung hai bản trước:
[nghiên cứu thương mại](COMMERCIAL_BOT_DETECTION_RESEARCH_2026-10-12.md), gồm Cloudflare,
DataDome, Fingerprint, Kasada, HUMAN và Akamai, và
[khảo sát repo mã nguồn mở](OPEN_SOURCE_BOT_DETECTION_REVIEW_2026-10-13.md), gồm 18 repo.
Phần dưới đây không lặp lại hai bản đó. Trọng tâm là: (1) bài báo khoa học và dataset về
chuột, (2) nghiên cứu profile/traffic, (3) các công bố năm 2026 về AI browser agent,
(4) thêm một số sản phẩm thương mại và công cụ né tránh.

**Mức độ tin cậy của nguồn:**

- **[P]**: bài báo đã qua phản biện.
- **[A]**: preprint arXiv. Phần lớn mình chỉ đọc abstract, chưa đọc toàn văn.
- **[V]**: vendor tự công bố, chưa có kiểm chứng độc lập.
- **[S]**: nguồn thứ cấp.

Không có số liệu nào dưới đây là kết quả của DATACAT. Mọi con số phải được trích kèm
điều kiện thí nghiệm gốc.

## 1. Kết luận chính

1. **Tín hiệu mạnh nhất hiện nay đến từ cách công cụ automation sinh event, không phải
   từ hình dạng đường đi.** Nhiều nguồn độc lập cùng chỉ ra điều này:
   - Castle: bot "nhảy" con trỏ chỉ sinh khoảng 4 event `mousemove`, người thật sinh 378.
   - arXiv 2607.26935: chỉ hai đặc trưng `mouse_event_rate` và `teleport_click_ratio`
     đã bắt được 100% agent trong benchmark.
   - FP-Agent: hành vi phân biệt agent tốt hơn browser fingerprint.

   Collector của DATACAT chỉ giữ khoảng 80 move gần nhất và **không gửi tổng số event,
   tần suất event hay mối liên hệ giữa click và move trước đó**. Đây là khoảng trống rẻ
   nhất để lấp.
2. **Các thư viện humanize (đường Bézier, WindMouse, GAN, diffusion) qua được kiểm tra
   hình học đơn giản, nhưng khó qua được các đặc trưng neuromotor.** Ví dụ: tuân theo
   định luật Fitts, cấu trúc submovement, mô hình sigma-lognormal. BeCAPTCHA-Mouse
   và một preprint dùng 17 đặc trưng động học đều cho thấy điều này. Thông số chuyển động
   ở mức trung bình (giống DATACAT đang dùng) dễ bị giả hơn.
3. **Môi trường thực thi quan trọng hơn hành vi khi đối thủ dùng trình duyệt thật.**
   - Broken Gates (2026): hai agent có hành vi gần như giống hệt nhưng kết quả trái ngược,
     do khác nhau về môi trường thực thi.
   - FP-Inconsistent: kiểm tra chéo các thuộc tính fingerprint giảm được 45–48% lượt né.
   - Gundelach et al. (2026): 75% lượt chặn chỉ nhắm vào headless Chromium đến từ HTTP header.

   Nhánh profile cần được đẩy lên, nhưng phải có nhóm người thật đối chứng.
4. **AI agent là lớp thứ ba, không phải "bot" cũng không phải "người".** Theo arXiv
   2607.26935, phân loại nhị phân gán HUMAN cho 35–39% agent thật. Phân loại 3 lớp xử lý
   được vấn đề này. Akamai cũng chỉ ra recall cấp phiên chỉ 52,6% vì nhiều phiên
   không đủ event. DATACAT nên báo cáo coverage ngang hàng với accuracy.
5. **Sản phẩm thương mại đều tách phân loại khỏi hành động và ra quyết định dần theo
   cả phiên.** cside chỉ hành động sau nhiều movement liên tiếp có điểm bot. Cloudflare
   làm ổn định điểm theo cookie. reCAPTCHA trả điểm kèm reason code. Không sản phẩm nào
   dựa vào một snapshot đơn lẻ.

## 2. Phân tích hành vi chuột: bài báo khoa học

| Công trình | Nội dung chính | Liên quan đến DATACAT |
|---|---|---|
| Iliou et al. 2021, *Digital Threats* [P] ([PDF](https://eprints.bournemouth.ac.uk/36055/1/3447815.pdf)) | Kết hợp web log với chuyển động chuột tốt hơn từng nguồn riêng; bot "advanced" có fingerprint và hành vi giống người | Nguồn của dataset M4D-ITI đang dùng. Luận án tiếp nối của nhóm tác giả bàn về bot dùng RL/GAN để né ([thesis](https://www.didaktorika.gr/eadd/handle/10442/58524?locale=en)) |
| Acien et al., **BeCAPTCHA-Mouse**, *Pattern Recognition* 2022 [P] ([arXiv](https://arxiv.org/abs/2005.00890)) | Đặc trưng neuromotor (sigma-lognormal); sinh quỹ đạo giả bằng hàm heuristic và GAN; khoảng 93% accuracy với chỉ một quỹ đạo; benchmark 15.000 quỹ đạo, 58 người | Gợi ý đặc trưng mới; dataset phải xin quyền (xem bản khảo sát ngày 13/10) |
| Khan et al., *Mouse Dynamics Behavioral Biometrics: A Survey* 2022 [A] ([arXiv](https://arxiv.org/pdf/2208.09061)) | Tổng hợp đặc trưng, dataset, các phương pháp CNN/LSTM | Dùng cho chương 2 của luận văn |
| Wei, Zhao, Cai 2019; Niu et al., *Expert Systems with Applications* 2023 [P] ([Springer](https://link.springer.com/chapter/10.1007/978-3-031-56326-3_6)) | Biểu diễn quỹ đạo thành ảnh rồi phân loại bằng CNN | Đối chứng cho BiLSTM nếu còn thời gian |
| He et al., CCBR 2021 [P] | Học chuỗi trên dữ liệu chuột để phát hiện bot | Cùng hướng với BiLSTM của DATACAT |
| Kovács & Antal [P] ([EMT](https://ojs.emt.ro/enelko-szamokt/article/view/1014)) | Sinh chuột giả bằng Bézier, convolutional autoencoder, TimeGAN; LOF là bộ phát hiện bất thường tốt nhất; autoencoder sinh dữ liệu giống người nhất | Cách tạo họ bot "khó" cho benchmark mà không cần mua bot |
| **DMTG** 2024 [A] ([arXiv](https://arxiv.org/pdf/2410.18233)) | Bot sinh quỹ đạo bằng diffusion (α-DDIM) có điều chỉnh entropy; train trên SapiMouse và Open Images traces; thử với CAPTCHA thương mại | Đại diện cho đối thủ mạnh nhất hiện nay; nên làm họ bot giữ lại khi test |
| 17 đặc trưng động học, generator SigmaDrift 2026 [A, chỉ đọc abstract] ([trang](https://www.synapsesocial.com/papers/69abc1c65af8044f7a4eabbf)) | Bốn nhóm đặc trưng: tuân theo Fitts, hình dạng submovement, độ mượt động học, hình học. Tác giả báo EER ≤ 0,001 khi kiểm tra leave-user-out, và 5 vòng tối ưu Bayes không né được lâu dài | Cần đọc toàn văn trước khi trích dẫn. Lập luận đáng thử: generator tham số khó thỏa cả bốn nhóm cùng lúc |
| Afanasieva & Lozhnikov, TUSUR 2024 [P] ([trang](https://journal.tusur.ru/en/archive/3-2024/datasets-for-bot-detection-using-mouse-behavior)) | Rà soát dataset công khai cho bài toán phát hiện bot bằng chuột | Danh mục dataset |

**Nền tảng lý thuyết nên đưa vào chương 2:**

- Định luật Fitts: thời gian di chuyển tăng theo log(khoảng cách / kích thước mục tiêu).
- Mô hình sigma-lognormal (kinematic theory of rapid human movements): vận tốc người là
  tổng các xung lognormal chồng lên nhau.
- Mô hình minimum-jerk.

Bot dùng Bézier với easing thường tạo một xung vận tốc duy nhất, đối xứng và không có
pha hiệu chỉnh cuối. Người thật thường có submovement khi tiếp cận mục tiêu.

### Dataset chuột

| Dataset | Quy mô | Dùng cho DATACAT |
|---|---|---|
| M4D-ITI Web Bot Detection ([trang](https://m4d.iti.gr/web-bot-detection-dataset/)) | Phase 1 và 2, có người, bot moderate và advanced, kèm web log | Đang dùng. Giấy phép CC BY-NC-SA |
| SapiMouse ([trang](https://www.ms.sapientia.ro/~manyi/sapimouse/sapimouse.html)) | 120 người, thu qua JavaScript trên trình duyệt (2020) | **Ứng viên tốt nhất để bổ sung người thật**: định dạng gần với collector, có timestamp thật |
| BeCAPTCHA-Mouse | 15.000 quỹ đạo, 58 người, kèm bot giả | Phải xin dữ liệu; người ký là cán bộ thường trực của cơ sở nghiên cứu |
| Boğaziçi ([Mendeley](https://data.mendeley.com/datasets/w6cxr8yc7p)) | 24 người, khoảng 2.550 giờ | Hướng xác thực người dùng; dùng làm đối chứng người thật dài hạn |
| Balabit Mouse Challenge (2016) | Ít người, có phiên test rất ngắn | Đối chứng phiên ngắn |
| DELBOT-Mouse (`Tuần 3/repos`) | Có các loại bot GAN, NaturalMouseMotion, pynput, pyhm | Đã có sẵn trong máy; nguồn bot đa họ |

Cảnh báo về miền dữ liệu: các dataset trên dùng tác vụ, thiết bị và tần số lấy mẫu
khác nhau. Không gộp chúng vào cùng tập test với website DATACAT. Chỉ dùng để pretrain
hoặc làm thí nghiệm chuyển miền, và phải báo cáo riêng.

## 3. Phân tích profile và traffic

| Công trình | Nội dung chính | Liên quan đến DATACAT |
|---|---|---|
| **FP-Inconsistent**, Venugopalan et al. (UC Davis) [A, v3 9/2025] ([arXiv](https://arxiv.org/abs/2406.07647)) | Honeysite có DataDome và BotD, 20 dịch vụ bot, khoảng 507 nghìn request. Lượt né trung bình 52,93% với DataDome và 44,56% với BotD. Luật kiểm tra mâu thuẫn theo **không gian** (hai thuộc tính trong một fingerprint) và **thời gian** (một thuộc tính ở hai thời điểm) giảm lượt né 44,95–48,11%, TNR trên người thật 96,84% | Bổ sung trực tiếp cho `profile_consistency.py`. Lưu ý TNR 96,84% nghĩa là khoảng 3% người thật bị gắn cờ, nên chỉ dùng như một bằng chứng, không dùng như luật quyết định |
| **Good Bot, Bad Bot**, Li et al., IEEE S&P 2021 [P] ([PDF](https://www.securitee.org/files/goodbotbadbot_oakland2021.pdf)) | 100 honeysite, 7 tháng, 26,4 triệu request; 86,2% bot khai là Firefox/Chrome nhưng TLS và HTTP cho thấy chúng là thư viện HTTP | Lý do cần tín hiệu phía server (TLS/header), không chỉ JavaScript |
| **Web Runner 2049**, Azad et al., DIMVA 2020 [P] ([PDF](https://par.nsf.gov/servlets/purl/10170537)) | 15 dịch vụ anti-bot. Hơn 75% site chặn được bot cơ bản, nhưng dùng trình duyệt ít phổ biến (Safari Mac, Chrome Android) thì vượt được tới 82% site | Lý do benchmark phải có nhiều trình duyệt và họ bot giữ lại |
| **FP-Crawlers**, Vastel et al., NDSS 2020 [P] ([PDF](https://ndss-symposium.org/wp-content/uploads/2020/02/23010.pdf)) | 291/10K site chặn crawler, 31,96% trong đó dùng fingerprinting. Hiệu quả nhanh nhưng dễ bị vượt bởi đối thủ biết site thu gì | Lý do không công khai `reasons` và `breakdown` cho client (xem mục 6) |
| FP-Scanner, Vastel et al., USENIX Security 2018 [P] ([trang](https://www.usenix.org/conference/usenixsecurity18/presentation/vastel)) | Phát hiện mâu thuẫn fingerprint do công cụ giả mạo gây ra | Cơ sở của FPScanner OSS |
| Jonker, Krumnow, Vlot, ESORICS 2019 [P] ([PDF](https://cs.ou.nl/members/hugo/papers/ESORICS19.pdf)) | Bot detector có mặt trên 12,8% Alexa top 1M | Bối cảnh |
| **Gundelach et al., ARES 2026** [P] ([trang](https://psi.uni-bamberg.de/en/forschung/bot-detection/), [arXiv](https://arxiv.org/pdf/2606.14525)) | 10.000 site, 4 cấu hình trình duyệt. Headless Chromium bị chặn mềm 15,2%, các cấu hình khác 6,8–7,2%. Khoảng 82% lượt chặn do bot detection (Cloudflare 37%, Akamai 26%). **75% lượt chặn chỉ riêng headless đến từ header** | Nên đối chiếu header của request telemetry với UA và Client Hints mà collector báo |
| Akamai, *Passive Fingerprinting of HTTP/2 Clients*, Black Hat EU 2017 [V] ([slides](https://www.blackhat.com/docs/eu-17/materials/eu-17-Shuster-Passive-Fingerprinting-Of-HTTP2-Clients.pdf)) | Fingerprint từ SETTINGS frame, WINDOW_UPDATE, PRIORITY và thứ tự pseudo-header; hơn 10 triệu kết nối | Chỉ làm được ở nơi kết thúc TLS/HTTP2 (Nginx/edge), không làm được trong FastAPI phía sau proxy |
| **Resident Evil**, Mi et al., IEEE S&P 2019 [P] ([PDF](https://cse.buffalo.edu/faculty/xmi/files/resi_paper.pdf)) | Khoảng 6 triệu IP residential proxy, hơn 52 nghìn ISP; nhiều host là máy bị chiếm quyền | IP "nhà mạng" không chứng minh người thật; IP reputation chỉ là tín hiệu phụ |
| JA4+ (FoxIO) | Fingerprint TLS, HTTP, TCP | Đã có trong bản khảo sát ngày 13/10 |

**Ngành quảng cáo:** chuẩn MRC chia invalid traffic thành **GIVT**, lọc bằng danh sách
(IAB/ABC Spiders & Bots List, danh sách data center của TAG), và **SIVT**, cần phân tích
nâng cao (emulator, click farm, proxy, event giả)
([tóm tắt](https://www.pixalate.com/blog/mrc-definitions-sivt-givt-invalid-traffic-detection-filtration),
[MRC về data center](https://www.mediaratingcouncil.org/sites/default/files/News/General-Announcements/RP020817_Invalid%20Data-Center%20Traffic.pdf)).
Nếu luận văn nhắc tới click fraud, dùng thuật ngữ này để đặt DATACAT đúng chỗ: tầng GIVT
dùng UA và danh sách, tầng SIVT dùng hành vi và mâu thuẫn profile.

## 4. AI browser agent (2026): lớp traffic mới

| Công trình | Phát hiện | Áp dụng |
|---|---|---|
| **Choudhary et al., arXiv 2607.26935** (TUM/Kontext, workshop) [A] ([trang](https://arxiv.org/abs/2607.26935)) | Phân loại nhị phân MLP gán HUMAN cho 39,1% agent, SAINT 34,5%; ba lớp (human/bot/agent) đạt agent F1 = 1,000 qua 30 lần chạy. Hai đặc trưng `mouse_event_rate` và `teleport_click_ratio` đủ cho 100% agent recall ở cả 5 mức né (gồm GAN và phát lại chuột người thật), precision 0,994. Tác giả giải thích là Playwright không sinh luồng raw pointer/wheel như thiết bị thật | **Áp dụng trực tiếp được.** Giới hạn: lớp bot là synthetic, agent chỉ dùng Claude qua Playwright/MCP; agent giả lập input ở mức hệ điều hành có thể né |
| **FP-Agent**, UC Davis, arXiv 2605.01247 [A] ([PDF](https://arxiv.org/pdf/2605.01247)) | 7 agent (Atlas, ChatGPT Agent, Claude for Chrome, Comet, Manus, Browser Use, Skyvern) trên honeysite với 3 tác vụ. Fingerprint trình duyệt phân biệt kém; typing/scroll/mouse phân biệt tốt. Cloudflare chỉ bắt được 1/7 agent | Agent chạy trên trình duyệt thật, nên nhánh chuột/tương tác quan trọng hơn nhánh profile cho nhóm này |
| *Whose Agent Are You?*, arXiv 2606.20910 [A] ([PDF](https://arxiv.org/pdf/2606.20910)) | Kết hợp TLS, HTTP và hành vi tốt hơn từng nguồn riêng | Hỗ trợ kiến trúc nhiều nhánh |
| *Known By Their Actions*, Lugoloobi et al., arXiv 2605.14786 [A] ([PDF](https://arxiv.org/pdf/2605.14786)) | Hành động và thời gian UI nhận ra LLM nào điều khiển agent với F1 tới 96% (14 LLM, XGBoost); thêm độ trễ ngẫu nhiên không che được lâu vì model train lại sẽ phục hồi | XGBoost trên đặc trưng thời gian tương tác là baseline hợp lý |
| **Broken Gates**, Ousat et al. (FIU), arXiv 2607.18659 [A] ([PDF](https://arxiv.org/pdf/2607.18659)) | 7 dịch vụ giải CAPTCHA và 6 agent thử với hCaptcha, reCAPTCHA v2/v3 và Turnstile. Challenge gần như vô dụng trước dịch vụ giải. reCAPTCHA v3 chống tốt hơn, nhưng do môi trường thực thi chứ không do hành vi | CAPTCHA không phải nguồn nhãn HUMAN |
| Akamai, *Identifying Agentic Automation*, phần 1 và 2 [V] ([phần 2](https://www.akamai.com/blog/security-research/2026/aug/identifying-agentic-automation-behavioral-telemetry-part-2)) | Masked autoencoder trên chuỗi chuột, ROC-AUC 0,981; recall phiên 97,9% trên phiên đủ dữ liệu nhưng 52,6% trên toàn bộ; agent có quãng nghỉ 2–3 giây khi "suy nghĩ" | Đã tóm tắt trong bản ngày 12/10 |
| Web Bot Auth, IETF draft ([draft](https://datatracker.ietf.org/doc/html/draft-ietf-webbotauth-httpsig-protocol)) | Agent tự ký request (RFC 9421, Ed25519); chữ ký chỉ chứng minh danh tính người giữ khóa, không chứng minh ý định tốt | Nhóm "bot có khai báo" nên tách khỏi BOT độc hại khi gán nhãn |

## 5. Sản phẩm thương mại: bổ sung so với bản ngày 12/10

| Sản phẩm | Cách làm được công bố | Bài học cho DATACAT |
|---|---|---|
| **Castle** [V] ([blog chuột](https://blog.castle.io/bot-or-not-can-you-spot-the-automated-mouse-movements/), [CDP](https://blog.castle.io/why-a-classic-cdp-bot-detection-signal-suddenly-stopped-working-and-nobody-noticed/)) | Ba mức bot chuột: (1) nhảy tức thời → **số event `mousemove` thấp bất thường**; (2) đường thẳng tốc độ đều → **gia tốc gần 0 hầu hết thời gian**; (3) Bézier → cần feature engineering và ML. Tín hiệu CDP `Runtime.enable` (serialize error) **đã ngừng hoạt động** sau một thay đổi của V8 | Mức 1 và 2 là luật rẻ có thể thêm ngay. Mọi probe trong browser đều có thể hết hạn khi trình duyệt cập nhật, nên cần test regression theo phiên bản Chrome |
| **cside** cursor_v2 [V] ([blog](https://cside.com/blog/catching-bots-by-how-they-move)) | Mạng neural khoảng 10,6 nghìn tham số, ONNX, 0,74 ms mỗi movement. Chấm **từng movement** giữa hai điểm, chỉ hành động khi nhiều movement liên tiếp có điểm bot. AUC 0,999 trên họ humanizer chưa gặp (bản trước chỉ 0,920). Họ tối ưu né chỉ bắt được 85,6%. FPR 0% trên 160 movement người | Cách đánh giá đáng học: **họ generator giữ lại** và recall tại FPR ≤ 1%. Model nhỏ chạy ONNX là đủ, không cần model lớn. Mẫu người quá nhỏ để tin con số FPR |
| **reCAPTCHA Enterprise** [V] ([docs](https://docs.cloud.google.com/recaptcha/docs/interpret-assessment-website)) | Điểm 0,0–1,0 (1 là người); reason code `AUTOMATION`, `UNEXPECTED_ENVIRONMENT`…; không có billing chỉ trả 4 mức điểm | **Lượng tử hóa điểm** trả ra ngoài để giảm khả năng dùng làm oracle; tách reason code cho kênh server |
| **Cloudflare** [V] ([detection IDs](https://developers.cloudflare.com/bots/concepts/detection-ids/), [JS detections](https://developers.cloudflare.com/bots/additional-configurations/javascript-detections)) | Detection ID là luật tĩnh "không trùng với người thật" (điểm 1); ML chiếm phần lớn detection; JS detection dùng Picasso fingerprint và chỉ chạy trên HTML page view; kết quả `js_detection.passed = false` không tự chặn | Tách rõ luật chắc chắn (giống luật HeadlessChrome) khỏi điểm ML. Thử Picasso (canvas challenge-response) như một cách chống phát lại profile |
| **F5 Distributed Cloud Bot Defense** (Shape) [V] ([lab](https://clouddocs.f5.com/training/community/f5xc/html/class5/lab1.html)) | JavaScript được làm cứng, telemetry mã hóa, obfuscation dựa trên VM | Chống sửa payload bằng obfuscation tốn chi phí lớn; ngoài phạm vi khóa luận, chỉ nêu ở phần hạn chế |
| **BioCatch** [S] ([Alkami](https://www.alkami.com/integration/biocatch/)) | Behavioral biometrics cho ngân hàng (hàng nghìn tham số, do vendor tự báo); step-up khi rủi ro cao | Mô hình "risk thì step-up", không chặn ngay |
| DataDome [S] | Nguồn thứ cấp mô tả thu click, move, hover, typing, scroll và kết hợp điểm behavior/network/session | Không có tài liệu gốc về phần chuột; không trích như sự thật |

## 6. Công cụ né tránh: dùng làm họ bot trong benchmark

| Nhóm | Công cụ | Họ bot cho protocol |
|---|---|---|
| Humanize chuột | ghost-cursor (Puppeteer) và các bản port cho Playwright/Python, `@extra/humanize` (Bézier), HumanCursor, WindMouse, NaturalMouseMotion (jar đã có trong DELBOT `python/`) | Họ "theo mẫu"; tách theo thư viện để làm họ giữ lại |
| Generator học từ dữ liệu | GAN (BeCAPTCHA, DELBOT), TimeGAN/autoencoder (Kovács & Antal), diffusion (DMTG) | Họ "khó"; chỉ dùng ở test để đo khái quát hóa |
| Stealth môi trường | patchright (Playwright Chromium bỏ `Runtime.enable`), rebrowser-patches, nodriver, Camoufox (Firefox có humanize cursor), CloakBrowser | Tách hai trục khi thiết kế ma trận bot: profile sạch và chuột giả |
| AI agent | Browser Use, Skyvern, Claude for Chrome, Computer Use | Lớp "agent" nếu mở rộng sang 3 lớp |

Chỉ chạy các công cụ này với website của mình hoặc website được phép thử; giữ quy tắc
lượng request thấp như trong `bot-lab/README.md`.

## 7. Đối chiếu với DATACAT và đề xuất thực nghiệm

### 7.1 Khoảng trống so với tài liệu

| Tín hiệu trong tài liệu | DATACAT hiện tại | Khoảng trống |
|---|---|---|
| Tần suất và tổng số event (Castle; 2607.26935) | Chỉ gửi khoảng 80 move cuối; `stats.pointCount` tính trên bộ đệm đã cắt | Chưa có bộ đếm tích lũy từ lúc tải trang |
| Teleport-click: click không có move dẫn tới (2607.26935) | Có `click_to_move_ratio`, nhưng không xét click có nằm gần move trước không | Thiếu khoảng cách và thời gian giữa move cuối và click |
| Raw pointer stream (2607.26935) | Chỉ nghe `mousemove` | Chưa đo `getCoalescedEvents()` / `pointerrawupdate`. **Giả thuyết cần kiểm chứng**: input từ CDP có ít coalesced sample hơn chuột thật |
| Wheel thật và wheel giả | Chỉ lưu `deltaX`/`deltaY` | Thiếu `deltaMode`, mẫu bội số delta (bước bánh xe) và nhịp |
| Gia tốc gần 0 kéo dài (Castle mức 2) | Có `accel_zero_crossing_rate`, `velocity_autocorrelation` | Thiếu tỷ lệ bước có gia tốc gần 0 |
| Neuromotor (Fitts, submovement, sigma-lognormal) | Thống kê trung bình trên cửa sổ | Chưa tách movement thành từng đoạn giữa các điểm dừng/click |
| Chấm từng movement và gộp có trễ (cside) | Chấm theo cửa sổ 24 bước trượt, verdict theo snapshot | Thiếu đơn vị movement và chính sách gộp theo phiên |
| Mâu thuẫn không gian/thời gian (FP-Inconsistent) | `profile_consistency.py`: page/worker, UA và Client Hints | Chưa có kiểm tra theo thời gian giữa các snapshot; chưa đối chiếu header HTTP thật với Client Hints |
| Phân loại 3 lớp | 2 lớp + SUSPECT | Agent hiện sẽ rơi vào HUMAN hoặc SUSPECT |

### 7.2 Thí nghiệm đề xuất, xếp theo chi phí và lợi ích

Mỗi thí nghiệm là một candidate chạy shadow. Không đổi policy v10 cho tới khi đánh giá
trên nhãn độc lập theo [protocol](THESIS_BENCHMARK_PROTOCOL_V1.md).

1. **X1. Bộ đếm event tích lũy** (collector, tăng schema). Gửi thêm:
   - tổng số `mousemove`, `pointermove`, `click`, `wheel` từ lúc tải trang;
   - số coalesced sample trung bình;
   - thời lượng trang có focus.

   Chỉ thêm vài trường số; không cần thay model. Đầu ra đầu tiên: so sánh phân bố trên
   người thật với Playwright, patchright và Selenium.
2. **X2. Đặc trưng click-approach.** Gồm:
   - khoảng cách và thời gian từ move cuối tới click;
   - thời gian giữ chuột (down→up);
   - tỷ lệ teleport-click;
   - độ chậm lại khi tiếp cận mục tiêu (overshoot/hiệu chỉnh).

   Tính từ record đã có (down/up/click), không cần sửa collector.
3. **X3. Luật rẻ kiểu Castle** ở chế độ chỉ quan sát: tỷ lệ bước có gia tốc gần 0, tần
   suất event dưới ngưỡng. Đo incremental recall và nhận nhầm trên người thật trước khi
   xem xét đưa vào policy.
4. **X4. Tách movement và đặc trưng neuromotor.** Cắt quỹ đạo tại các điểm dừng hoặc
   click. Với mỗi đoạn, tính:
   - số đỉnh vận tốc (đếm submovement);
   - độ bất đối xứng của profile vận tốc;
   - tỷ số Fitts (thời gian so với log khoảng cách).

   Thêm vào XGBoost candidate rồi so sánh ablation với bộ 20 đặc trưng hiện có.
5. **X5. Họ generator giữ lại** trong benchmark: train trên Bézier/WindMouse, test trên
   GAN/diffusion/NaturalMouseMotion. Báo cáo recall tại FPR ≤ 1% và AUC trên họ chưa gặp,
   theo cách cside đánh giá.
6. **X6. Kiểm tra chéo profile theo thời gian:** UA, Client Hints và kích thước màn hình
   có đổi giữa các snapshot cùng page instance không; header HTTP của request telemetry
   có khớp Client Hints không.
7. **X7 (mở rộng). Lớp agent:** chạy 1–2 agent (Browser Use) trên site thử nghiệm, thêm
   nhãn `AGENT` vào manifest nhãn. Chỉ thử phân loại 3 lớp khi có đủ phiên.

Thứ tự đề xuất: X1 + X2 trước, vì rẻ và trực tiếp theo hai kết quả mạnh nhất năm 2026.
Tiếp theo là X5 (vì protocol cần nó), rồi X4. X3 và X6 làm song song ở shadow.

### 7.3 Những điều không nên trích sai

- Các con số "100% recall", "AUC 0,999", "EER ≤ 0,001" đều đo trên benchmark có kiểm
  soát và tập người nhỏ. Không dùng để hứa hẹn kết quả của DATACAT.
- Tín hiệu do cách automation sinh event có thể mất khi công cụ cập nhật, giống tín hiệu
  CDP `Runtime.enable` đã ngừng hoạt động. Mọi probe cần test regression theo phiên bản
  trình duyệt và công cụ.
- Agent điều khiển input ở mức hệ điều hành, hoặc người thật thao tác thay bot, nằm ngoài
  phạm vi của mọi kỹ thuật trên.

## 8. Danh sách nguồn chưa đọc toàn văn

Mình chỉ đọc abstract hoặc tóm tắt của: 2607.26935, 2607.18659, 2606.14525, 2606.20910,
2605.01247, 2605.14786, 2410.18233, preprint SigmaDrift, và slide HTTP/2 của Akamai.
Trước khi trích số liệu trong luận văn, cần đọc toàn văn và ghi phiên bản arXiv.
