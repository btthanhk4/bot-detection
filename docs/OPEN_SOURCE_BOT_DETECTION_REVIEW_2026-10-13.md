# Khảo sát repository bot detection cho DATACAT

Ngày khảo sát: 2026-10-13.

## 1. Kết luận

Giữ BiLSTM + XGBoost + heuristic hiện tại. Ưu tiên bổ sung **tín hiệu có thể kiểm chứng**, không ghép nhiều thư viện thành một cuộc bỏ phiếu BOT/HUMAN.

Thứ tự đề xuất:

1. Đối chiếu detector hiện tại với BotD upstream để biết phần nào thực sự còn thiếu.
2. Thử chọn lọc kiểm tra khác biệt giữa Page/Worker/iframe từ FPScanner và CreepJS trong môi trường kiểm thử, sau đó chạy shadow trên website được phép thu thập.
3. Tham khảo bot-signal để thiết kế đặc trưng liên kết chuột, click, scroll và touch. Không dùng nguyên điểm tổng hợp làm xác suất bot.
4. Thu traffic có nhãn, rồi huấn luyện và đánh giá lại XGBoost/BiLSTM với các đặc trưng phù hợp. Không cần thêm GNN.
5. Khi có quyền truy cập log website, bổ sung phân tích request theo thời gian theo hướng CrowdSec/Baskerville.

Đây là đề xuất kiến trúc sau khi đọc nguồn, **chưa phải kết quả benchmark**. Chưa có bằng chứng rằng thêm bất kỳ repo nào dưới đây sẽ làm tăng độ chính xác trên traffic của DATACAT.

## 2. Phạm vi và giới hạn

- Khảo sát 18 repository liên quan đến browser automation, mouse dynamics, request analytics, fingerprinting và challenge. Không thể khẳng định bao quát toàn bộ GitHub.
- Đọc README, thông tin giấy phép và một số file triển khai quan trọng. Không audit từng dòng của tất cả 18 repo.
- Chỉ dùng nguồn chính thức của dự án; không dùng ảnh minh họa trong danh sách ban đầu để xác định repository. AdTruth và Trench là hai dự án riêng.
- Các URL nhánh mặc định có thể thay đổi. Trước khi thử nghiệm cần chốt commit/package version, license và dependency lockfile.
- GitHub API trả 403 trong lần khảo sát này; không đưa ra kết luận về ngày commit gần nhất hoặc trạng thái bảo trì chỉ từ metadata chưa lấy được.
- Không cài hay thực thi dependency bên thứ ba; không gửi telemetry đến các dịch vụ này; không sửa model, ngưỡng hoặc triển khai production.

## 3. Sáu repo trong danh sách ban đầu

| Repository và nguồn | Thực chất | Cách dùng phù hợp với DATACAT | Giới hạn / giấy phép |
|---|---|---|---|
| [FingerprintJS BotD](https://github.com/fingerprintjs/BotD) | Bộ phát hiện dấu vết automation trong browser | Đối chiếu sources, detectors và tests với heuristic tự viết | MIT; OSS tập trung bot cơ bản, README nêu hướng duy trì ổn định. Không bảo đảm bắt stealth browser |
| [AdTruth](https://github.com/papa-torb/adtruth) | SDK theo dõi traffic quảng cáo, fingerprint và hành vi | Tham khảo schema và cách thu metric; không đưa thẳng vào pipeline | Package khai báo MIT. Chưa xác minh được một pipeline Isolation Forest tự host đầy đủ kèm dữ liệu/weights để tái lập kết quả |
| [FingerprintJS](https://github.com/fingerprintjs/fingerprintjs) | Nhận diện trình duyệt qua tập thuộc tính | Tham khảo collector hoặc đánh giá lại visitor matching nếu có nhu cầu rõ | Không phải classifier BOT/HUMAN; fingerprint không phải danh tính chắc chắn. LICENSE của master kiểm tra được là MIT; phải kiểm tra đúng phiên bản sử dụng |
| [CrowdSec](https://github.com/crowdsecurity/crowdsec) | Engine phát hiện hành vi qua log, quyết định và remediation | Chạy riêng phía server, tiếp nhận alert như một nguồn ngữ cảnh | Core MIT. Cần log website và cấu hình phù hợp; không thay model chuột |
| [Baskerville](https://github.com/deflect-ca/baskerville) | Phân tích web request theo host/IP và cửa sổ thời gian, novelty detection | Học cách tổng hợp đặc trưng request, thử baseline nhỏ trước | Stack Spark/Kafka/Postgres khá nặng; tài liệu có yêu cầu runtime cũ. LICENSE có điều khoản riêng, không ghi giản lược là MIT |
| [SKG24/ML-Anomaly-Detection](https://github.com/SKG24/ML-Anomaly-Detection) | Notebook Isolation Forest/LOF trên traffic mạng | Tài liệu học anomaly detection, ưu tiên thấp | NetFlow không tương đương dữ liệu chuột. Chưa thấy LICENSE trong danh sách file gốc đã kiểm tra; cần làm rõ trước khi sao chép |

Nguồn giấy phép đối chiếu: [FingerprintJS LICENSE](https://raw.githubusercontent.com/fingerprintjs/fingerprintjs/master/LICENSE), [AdTruth package.json](https://raw.githubusercontent.com/papa-torb/adtruth/main/package.json), [CrowdSec LICENSE](https://raw.githubusercontent.com/crowdsecurity/crowdsec/master/LICENSE), [Baskerville LICENSE](https://raw.githubusercontent.com/deflect-ca/baskerville/master/LICENSE).

### AdTruth: phân biệt SDK công khai và backend

File tracker yêu cầu API key, mặc định gửi dữ liệu về `api.adtruth.io` và cho phép đổi endpoint. Các import đã đọc là session, URL, fingerprint và behavior tracking; phần chú thích giao một số phân tích cho backend. Vì vậy chưa đủ căn cứ để gọi SDK này là model Isolation Forest hoàn chỉnh có thể tải về train ngay. Không tích hợp nguyên SDK nếu chưa kiểm tra luồng gửi dữ liệu. [Nguồn tracker](https://raw.githubusercontent.com/papa-torb/adtruth/main/src/core/tracker.js).

Nhận định fingerprint không thể bị bot giả là quá mạnh; không dùng tuyên bố quảng bá đó làm giả định thiết kế. Việc một repo có nhắc ML không thay thế được bằng chứng về mã train, dữ liệu, model artifact và đánh giá độc lập.

### Baskerville: học phương pháp, chưa cần bê nguyên stack

Dự án tổng hợp các đặc trưng như độ sâu đường dẫn, số query khác nhau, tỷ lệ request HTML so với tài nguyên. Với DATACAT, có thể thử một pipeline nhỏ trên log trước khi cân nhắc hạ tầng phân tán. Anomaly score chỉ nói dữ liệu khác baseline, không tự chứng minh bot. [Nguồn kiến trúc](https://github.com/deflect-ca/baskerville#overview).

## 4. Mười hai repo bổ sung

| Repository và nguồn | Giá trị có thể lấy | Đánh giá tích hợp |
|---|---|---|
| [antoinevastel/fpscanner](https://github.com/antoinevastel/fpscanner) | Tín hiệu automation và đối chiếu Page/Worker/iframe | MIT. Ưu tiên nghiên cứu code; chỉ dùng detector được kiểm chứng, không dùng trực tiếp boolean tổng |
| [abrahamjuliot/creepjs](https://github.com/abrahamjuliot/creepjs) | Kiểm tra API bị can thiệp, prototype và tính nhất quán | Code MIT, có chính sách thương hiệu riêng. Mục tiêu là nghiên cứu fingerprint/privacy, không phải SDK bot classifier production |
| [okasi/bot-signal](https://github.com/okasi/bot-signal) | Thiết kế tín hiệu browser, hành vi, server; có mouse/touch/scroll/click | MIT. Ứng viên benchmark; kiểm tra từng signal, không coi trọng số/độ tin cậy có sẵn là đã được hiệu chuẩn cho DATACAT |
| [chrisgdt/DELBOT-Mouse](https://github.com/chrisgdt/DELBOT-Mouse) | Pipeline mouse dynamics, train và sinh quỹ đạo để nghiên cứu | MIT cho code. Prototype TensorFlow.js; không gắn nguyên weights vào PyTorch hiện tại |
| [BiDAlab/BeCAPTCHA-Mouse](https://github.com/BiDAlab/BeCAPTCHA-Mouse) | Benchmark quỹ đạo tổng hợp và nghiên cứu mouse dynamics | Repo hướng dẫn xin dữ liệu, không phải SDK tự do sử dụng ngay. Cần thỏa thuận dữ liệu; theo README, người ký phải là thành viên thường trực của cơ sở nghiên cứu, không phải sinh viên |
| [trytrench/trench](https://github.com/trytrench/trench) | Thu sự kiện và điều tra fraud/abuse | AGPL-3.0 theo README; đang phát triển. Học kiến trúc event/điều tra, không thay mouse classifier |
| [FoxIO-LLC/ja4](https://github.com/FoxIO-LLC/ja4) | Fingerprint ở lớp TLS/network | JA4 TLS là BSD-3-Clause; các phần JA4+ khác có FoxIO License riêng. Chỉ xem xét khi quan sát được TLS phía client tại edge |
| [TecharoHQ/anubis](https://github.com/TecharoHQ/anubis) | Reverse proxy/challenge giảm scraping tự động | MIT. Công cụ mitigation, không phải nguồn nhãn HUMAN chắc chắn |
| [altcha-org/altcha](https://github.com/altcha-org/altcha) | Challenge proof-of-work có thể tự host | MIT của repo này. Không đồng nhất widget OSS với mọi sản phẩm của nhà cung cấp; vượt challenge không chứng minh người thật |
| [tiagozip/cap](https://github.com/tiagozip/cap) | Challenge proof-of-work và instrumentation | Apache-2.0. Lựa chọn mitigation về sau, không cần chạy đồng thời nhiều CAPTCHA |
| [omrilotan/isbot](https://github.com/omrilotan/isbot) | Danh sách/pattern User-Agent của crawler | Unlicense. Hữu ích phân nhóm crawler khai báo danh tính, không giải quyết bot đổi UA |
| [JayBizzle/Crawler-Detect](https://github.com/JayBizzle/Crawler-Detect) | Nhận diện crawler từ header trong PHP | MIT. Tham khảo dữ liệu/pattern; không thêm PHP vào DATACAT chỉ để dùng thư viện này |

Lưu ý dữ liệu BeCAPTCHA: README mô tả file quỹ đạo x/y và tham số neuromotor. Phải kiểm tra định dạng thật trước khi sử dụng các đặc trưng vận tốc/gia tốc; không tự tạo timestamp rồi coi đó là dữ liệu đo được. [Nguồn benchmark](https://github.com/BiDAlab/BeCAPTCHA-Mouse).

## 5. Các phát hiện khi đọc code ứng viên

### 5.1 Không dùng nguyên quyết định FPScanner

Trong nguồn đã đọc, cờ tổng bật khi bất kỳ detector nào bật, bao gồm cả detector được gắn severity thấp. Vì thế không ánh xạ thẳng cờ này thành BOT của DATACAT. [Nguồn tổng hợp](https://raw.githubusercontent.com/antoinevastel/fpscanner/master/src/index.ts).

Ví dụ cụ thể:

- Detector màn hình gắn cờ nếu screen, available screen hoặc inner viewport bằng 800x600. Kích thước cửa sổ như vậy không đủ chứng minh automation. [Nguồn detector](https://raw.githubusercontent.com/antoinevastel/fpscanner/master/src/detections/hasHeadlessChromeScreenResolution.ts).
- Detector CPU gắn cờ khi số logical CPU lớn hơn 70. Đây không phải bằng chứng độc lập người dùng là bot. [Nguồn detector](https://raw.githubusercontent.com/antoinevastel/fpscanner/master/src/detections/hasHighCPUCount.ts).
- Probe CDP thay `Error.prepareStackTrace`, nhưng không khôi phục hook trong hàm đã đọc. Cần kiểm tra tác động lên website và không sao chép nguyên probe vào collector. [Nguồn probe](https://raw.githubusercontent.com/antoinevastel/fpscanner/master/src/signals/cdp.ts).
- Ví dụ giải mã trong README dùng XOR với khóa lặp. Không coi cơ chế che giấu dữ liệu phía browser là xác thực nguồn telemetry hoặc chống sửa payload. [Nguồn ví dụ](https://raw.githubusercontent.com/antoinevastel/fpscanner/master/README.md).

Phần đáng học là cách tổ chức tín hiệu và kiểm tra chéo. Độ chính xác và mức an toàn của từng probe vẫn phải được kiểm thử riêng.

### 5.2 bot-signal: có tín hiệu đáng học, không sao chép điểm tổng

Collector có liên kết mouse/click/scroll/keyboard/touch, lưu thuộc tính sự kiện và dùng cửa sổ lưu mẫu giới hạn theo thời gian. Đây là hướng phù hợp để bổ sung đặc trưng tương tác. [Nguồn collector](https://raw.githubusercontent.com/okasi/bot-signal/main/src/behavioral/index.ts).

Scoring kết hợp trọng số theo dạng bù của tích các phần bù. Với nhiều detector cùng phản ánh một nguyên nhân, điểm có thể bị khuếch đại. Suy luận cho DATACAT: cần gom nhóm tín hiệu trùng và hiệu chuẩn trên validation, không gọi điểm này là xác suất bot đã được chứng minh. [Nguồn scoring](https://raw.githubusercontent.com/okasi/bot-signal/main/src/behavioral/scoring.ts).

Giữ phân biệt sự kiện không trusted, automation và hành vi độc hại. Không coi thiếu sự kiện chuột hay không có cờ automation là bằng chứng HUMAN.

### 5.3 Fingerprint và challenge không thay thế classifier

Fingerprint hỗ trợ liên kết ngữ cảnh, nhưng trùng fingerprint không đồng nghĩa cùng người; khác fingerprint không đồng nghĩa bot. CreepJS còn cố tình kiểm tra các trình duyệt bảo vệ riêng tư, nên cờ chống fingerprint không thể mặc định là BOT. [Nguồn mục tiêu CreepJS](https://github.com/abrahamjuliot/creepjs).

Với PoW, kết quả thành công chỉ xác nhận client giải được challenge. Đề xuất cho DATACAT: lưu thành một loại bằng chứng riêng, không tự động gắn nhãn người thật để train.

UA có tên crawler cũng chỉ là khai báo. Khi cần cho phép crawler đáng tin cậy, xác minh nguồn độc lập thay vì whitelist theo chuỗi UA.

## 6. Đối chiếu với code DATACAT hiện tại

Repository được đối chiếu: `bot-detection-core`, GitNexus repo `bot-detection`, index ngày 2026-10-12, commit `c2c9790c3e6ea0e5d5248414e67397102e014806`. Các file liên quan đã được đọc trực tiếp trong working tree; index không thay thế nguồn hiện tại và cây làm việc có thay đổi chưa commit.

- [collector/package.json](../collector/package.json) mô tả collector tự viết, lấy cảm hứng từ FingerprintJS/BotD/DELBOT. Không nên trình bày nó là đang import đầy đủ ba thư viện upstream.
- [profile_consistency.py](../core_ml/features/profile_consistency.py) đã có kiểm tra Page/Worker/Client Hints ở chế độ shadow, chưa phê duyệt ảnh hưởng verdict.
- [interaction_features.py](../core_ml/features/interaction_features.py) đã có đặc trưng tương tác ở chế độ measurement-only, chưa phê duyệt release.
- [ensemble.py](../core_ml/models/ensemble.py) trả hai nhóm phân tích trên riêng biệt. Thêm repo chỉ để lặp lại chúng có thể không đem lại tín hiệu mới.

Đề xuất là mở rộng có chọn lọc các module đang có, không tạo một ensemble gồm hàng loạt boolean từ thư viện khác nhau.

## 7. Kế hoạch thực hiện đề xuất

### Bước 1: Chốt baseline và danh mục tín hiệu

Chụp phiên bản collector/model/dataset hiện tại. Lập bảng từng tín hiệu: nguồn, availability, cách tính, họ tín hiệu, điều kiện browser hỗ trợ và tình huống nhận nhầm. Đối chiếu BotD upstream trước khi viết detector mới. Mỗi tín hiệu webdriver chỉ được tính một lần dù nhiều thư viện phát hiện.

Đầu ra: danh sách khoảng 5-10 tín hiệu thực sự mới để thử, không phải cài tất cả repo.

### Bước 2: Benchmark trong lab

Chốt commit và license của ứng viên. Thử BotD làm baseline độc lập; chọn probe FPScanner/CreepJS và feature bot-signal. Không để code thử nghiệm gửi dữ liệu ra ngoài, thay global hook, chặn trang hoặc thu nội dung người dùng nhập.

Nhóm kiểm thử cần có:

- Người thật: Chrome, Firefox, Safari; touchpad, chuột, touch, chỉ keyboard; trình duyệt bảo vệ riêng tư và môi trường mở DevTools.
- Bot: kịch bản đang bỏ sót, automation không dùng chuột, automation có chuột, các biến thể tốc độ/viewport/gián đoạn.
- Collector: CSP chặn Worker/iframe, API không hỗ trợ, timeout, tab nền, trang đóng sớm, sự kiện lặp và request gửi lại.

Nếu chưa thu được người thật có nhãn, chỉ xác nhận khả năng phát hiện thêm trên bot lab; chưa xác nhận tỷ lệ nhận nhầm người thật.

### Bước 3: Thu traffic thật ở chế độ quan sát

Nhúng collector trên website được cho phép. Lưu feature có phiên bản, tình trạng dữ liệu thiếu, thời gian và verdict hiện tại; giới hạn dung lượng, thời hạn lưu và quyền truy cập. Không thu nội dung form, mật khẩu hoặc query nhạy cảm.

Tách nguồn nhãn: bot do mình chạy, người thật tham gia có xác nhận, nhận xét của dịch vụ thương mại, nhãn suy đoán. Đầu ra thư viện hoặc dịch vụ không phải ground truth. Bất đồng giữa các hệ thống là mẫu cần kiểm tra, không tự động dùng majority vote làm nhãn.

### Bước 4: Học từ tín hiệu mới

So sánh các phiên bản: baseline; baseline + profile; baseline + interaction; baseline + cả hai. Nếu thử Isolation Forest, dùng như detector ngoài phân phối/bất thường trong shadow, không tự quyết định BOT.

Không nối thêm cột vào model đã train rồi sử dụng trực tiếp. Khi đổi feature schema phải train, version và kiểm thử lại; xử lý missingness phải thống nhất giữa train/inference. Profile classifier, nếu cần, nên được đánh giá riêng trước khi fusion để không ép model thống kê chuột xử lý miền dữ liệu khác.

Chia tập theo phiên/người tham gia/họ bot và thời gian trước khi tạo cửa sổ. Giữ lại họ bot chưa gặp, tránh cùng bộ sinh quỹ đạo xuất hiện cả train và test chỉ với seed khác nhau. Không điều chỉnh ngưỡng nhiều lần trên tập test cuối cùng.

### Bước 5: Tín hiệu server sau khi có quyền log

Học CrowdSec/Baskerville để tạo đặc trưng nhịp request, thứ tự endpoint, lỗi, mức lặp. Tính từ log request thật của website, không nhầm với tần suất collector gửi telemetry. Tách website/session; không suy luận cả IP là bot vì có nhiều người dùng sau NAT.

JA4 chỉ có ích khi có dữ liệu TLS client tại điểm kết thúc TLS. Không lấy được tín hiệu đó từ JavaScript thông thường. Nếu CDN kết thúc TLS thì backend có thể chỉ thấy kết nối proxy; cần cơ chế truyền metadata đáng tin cậy. Không nhận header JA4 do client tùy ý gửi. Repo JA4 cung cấp cách biểu diễn fingerprint, không tự cung cấp danh tiếng bot cho mọi fingerprint. [Nguồn JA4](https://github.com/FoxIO-LLC/ja4/blob/main/README.md).

### Bước 6: Điều kiện đưa vào quyết định production

- Giảm bot bị kết luận HUMAN trên họ bot giữ lại độc lập, không chỉ trên dữ liệu đã dùng để sửa model.
- Không tăng người thật bị kết luận BOT vượt mức chấp nhận đã thống nhất; báo khoảng bất định và số phiên thực tế, không chỉ một phần trăm.
- Báo riêng recall BOT, tỷ lệ SUSPECT, coverage đủ dữ liệu và thời gian tới kết luận. Giảm SUSPECT bằng ép nhãn không được tính là cải thiện.
- Kiểm tra theo browser/input type; đo CPU, payload và độ trễ của collector trên thiết bị yếu.
- Chạy shadow trước, có cờ tắt và rollback. Quyết định allow/challenge/block tách khỏi việc phân loại tự động hay người thật.

## 8. Quyết định nên làm ngay

**Chọn một thử nghiệm nhỏ: BotD upstream làm đối chứng, thêm tín hiệu kiểm tra chéo được chọn từ FPScanner/CreepJS, và đánh giá đặc trưng tương tác lấy ý tưởng từ bot-signal.** Kết quả được lưu ở shadow cùng raw telemetry đã được cho phép thu.

Chưa đưa nguyên FPScanner, AdTruth hay bot-signal vào vị trí quyết định cuối. Chưa triển khai Spark/Kafka chỉ để dùng Baskerville. Chưa thêm GNN hoặc challenge chỉ để tăng số công nghệ trong hệ thống.

Ưu tiên cao nhất vẫn là bộ dữ liệu traffic thật có nguồn nhãn rõ và phép đánh giá chống rò rỉ. Repo mới giúp tạo giả thuyết và tín hiệu mới; không tự giải quyết được thiếu dữ liệu người thật hoặc bot nâng cao chưa từng quan sát.
