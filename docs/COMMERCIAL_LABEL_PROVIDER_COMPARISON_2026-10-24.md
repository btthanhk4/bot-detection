# Khảo sát nhà cung cấp nhãn tham khảo cho DATACAT

Ngày: 24/10/2026. Phạm vi: 24 sản phẩm/dòng dịch vụ liên quan, dựa trên tài liệu công khai chính thức. Không phải danh mục đầy đủ mọi hãng trên thế giới, không phải benchmark độ chính xác; chưa sử dụng tài khoản trả phí hoặc gọi API thật trong lượt khảo sát này.

## Kết quả lựa chọn

Đối với DATACAT hiện tại, shortlist kỹ thuật là **Fingerprint, Castle, IPQS Device Fingerprint và DataDome**. SEON là ứng viên bổ sung nếu cần phân tích gian lận rộng hơn. Thứ tự này phản ánh khả năng tích hợp và loại kết quả có thể lấy, không xếp hạng năng lực bắt bot nâng cao.

- Fingerprint: lựa chọn triển khai gọn, ghép event rõ ràng, giá khởi điểm công khai.
- Castle: rất đáng thử cùng Fingerprint vì trả Bot Score và có phân tích tương tác theo tài liệu; có quota đánh giá nhỏ miễn phí.
- IPQS: cần đúng sản phẩm Device Fingerprint và quyền trường bot_status, không mua nhầm API tra IP.
- DataDome: phù hợp nếu có ngân sách/tài trợ và quyền backend/CDN; cần quyền log enrichment cụ thể.

Chưa xác nhận nhà cung cấp nào cho phép dự án này dùng đầu ra để huấn luyện sản phẩm tương tự. Khả năng truy xuất API và quyền dùng đầu ra làm dataset là hai điều kiện độc lập. Quyết định mua chỉ nên thực hiện khi cả hai được đáp ứng và có phép thử trên bot/người có nhãn độc lập.

## 1. Những gì một dịch vụ cần đáp ứng

1. Trả kết quả cho từng event/request, không chỉ biểu đồ tổng hợp.
2. Có ID và timestamp để ghép đúng site, phiên và mốc quan sát DATACAT.
3. Backend xác minh được kết quả; không tin nhãn do browser tự gửi lên.
4. Cho phép quan sát mà vẫn thu được hành vi cần nghiên cứu; cấu hình bỏ qua bảo vệ không được vô tình tắt detector.
5. Có thể giữ/export trường kết quả cần thiết với quyền sử dụng rõ ràng.
6. Có ích trên bot vượt DATACAT trong kiểm thử, không chỉ lặp lại bằng chứng WebDriver dễ thấy.
7. Chi phí và tốc độ phù hợp traffic thật; lỗi/quota không cản trở DATACAT.

Ba loại API cần phân biệt: API đánh giá trả verdict/score; API lấy event/log; API quản trị cấu hình. Có API quản trị không chứng minh có API trả nhãn cho từng traffic. Cũng không có cơ sở giả định các hãng nhận trực tiếp JSON quỹ đạo chuột hiện tại của DATACAT để gán nhãn hồi tố; đa số cần SDK/sensor hoặc luồng request được tích hợp từ trước.

## 2. Nhóm tích hợp trực tiếp bằng SDK và API

### 1. Fingerprint Pro Plus Bot Detection

**Đã xác minh:** JS agent cung cấp event_id, backend lấy kết quả qua Events API; các nhóm good, bad, not_detected. Cần Pro Plus hoặc entitlement Enterprise. bad thể hiện automation chưa được xác minh là được cho phép, không tự đồng nghĩa gian lận. [Tài liệu](https://docs.fingerprint.com/docs/bot-detection/overview)

**Vào DATACAT:** giữ session nội bộ, gắn mã observation vào event, worker truy vấn server rồi lưu evidence riêng. Phù hợp website chưa muốn chuyển CDN. Chỉ đường JS không bao phủ request không chạy JS.

**Chi phí công bố:** Pro Plus từ 99 USD/tháng cho 20.000 identification; thêm 4 USD/1.000; trial Pro Plus 14 ngày. Cần xác nhận quota thực tế, thuế và gia hạn. [Giá](https://fingerprint.com/pricing/)

**Đánh giá:** shortlist số một cho sự gọn nhẹ, nhưng phải được phép dùng đầu ra cho nghiên cứu/huấn luyện. Không coi not_detected là nhãn HUMAN mạnh.

### 2. Castle

**Đã xác minh:** Filter API và Risk API cung cấp Bot Score; tài liệu mô tả phân tích tương tác, môi trường và bất thường. Filter phù hợp traffic trước xác thực; Risk cho luồng ứng dụng. API cần request_token từ tích hợp client, không chỉ một IP. [Bot detection](https://docs.castle.io/docs/bot-detection), [token/API](https://docs.castle.io/docs/test-tokens), [scores](https://docs.castle.io/changelog/scores-available-in-api-response)

**Vào DATACAT:** thêm SDK, backend gọi đánh giá với token và ngữ cảnh thật. Với website chỉ xem trang, thử Filter trước; không tạo tài khoản/ngữ cảnh đăng nhập giả để ép Risk API hoạt động. Lưu phản hồi lúc đánh giá thay vì giả định gói nào cũng cho truy vấn lịch sử.

**Chi phí công bố:** Free có 5 USD API budget/tháng, tương đương 1.000 Risk/Filter calls nếu không dùng chung budget cho IP; Pro 200 USD/tháng gồm 40.000 Risk/Filter calls. Quota dùng chung, Free giới hạn tốc độ và lịch sử ngắn; Querying API ở bảng giá chỉ có Enterprise. [Giá](https://castle.io/pricing/)

**Đánh giá:** có lý do kỹ thuật để thử bot giả chuột, nhưng chưa có bằng chứng tốt hơn Fingerprint/DATACAT. Điều khoản hạn chế benchmark/cạnh tranh cần thỏa thuận nghiên cứu trước.

### 3. IPQualityScore (IPQS) Device Fingerprint

**Đã xác minh:** tracker JS và callback cho kết quả fingerprint; tài liệu response có request_id, device_id, fraud_chance và bot_status. bot_status được đánh dấu Premium và bao gồm bot, thiết bị giả mạo hoặc request không phải người. [Tích hợp](https://www.ipqualityscore.com/documentation/device-fingerprint-api/overview), [response](https://www.ipqualityscore.com/documentation/device-fingerprint-api/response-parameters)

**Vào DATACAT:** dùng tracking variable để tương quan phiên, yêu cầu cách backend xác minh/nhận kết quả được hỗ trợ cho gói mua. Không chỉ nhận JSON callback từ trình duyệt rồi coi là nhãn đáng tin. Chưa kiểm chứng flow server confirmation trên một tài khoản thật.

**Đánh giá:** shortlist có điều kiện. fraud_chance là rủi ro gian lận rộng hơn bot; bot_status=false không chứng minh HUMAN. Chưa xác nhận giá/trial cho đúng entitlement Device Fingerprint Premium, không lấy hạn mức miễn phí IP lookup để suy ra.

### 4. SEON Device Intelligence + Fraud API

**Đã xác minh:** JS agent tạo session mã hóa đưa vào Fraud API; API kết hợp thiết bị và nhiều nguồn gian lận. Tài liệu nói khởi tạo agent ở page load giúp thu behavioral signals; migration v6 đề cập bot/automation flags. [Fraud API](https://docs.seon.io/api-reference/fraud-api), [Migration](https://docs.seon.io/api-reference/migration-guides)

**Vào DATACAT:** lấy session token rồi backend gọi Fraud API; lưu đúng các flags automation và rule liên quan, không biến fraud_score chung thành xác suất bot. Cần payload mẫu thật của gói lựa chọn để khóa schema và xác nhận trường nào có sẵn.

**Đánh giá:** phù hợp nếu mở rộng tài khoản/giao dịch; xếp sau shortlist chính cho bài toán chuột. Chưa xác nhận giá/trial/quyền train cho trường hợp này.

## 3. Nhóm bot management cần tích hợp hạ tầng

### 5. DataDome Bot Protect

**Đã xác minh:** có server integration và JS tag. Custom Protection API yêu cầu Premium/Enterprise theo tài liệu; API trả action, còn log enrichment có isbot, botname, score, riskscore và sessionid, tùy gói. riskscore chỉ dựa trên server-side fingerprint, khác score khi khớp detection model. [Protection API](https://docs.datadome.co/reference/validate-request), [Log enrichment](https://docs.datadome.co/js/docs/logs-integration)

**Vào DATACAT:** tích hợp tại website/proxy/CDN, đưa enrichment vào pipeline tham khảo, ghép request với phiên bằng ID. Không chỉ gửi traffic từ server DATACAT như thể đó là browser thật. Hỏi rõ quyền xuất cả traffic được cho qua, không chỉ bot bị chặn.

**Đánh giá:** nguồn evidence giàu thông tin nếu có đúng entitlement. Action allow/challenge khác nhãn human/bot; isbot là dự đoán của hãng, chưa là ground truth. Giá và quyền sử dụng cần báo giá/xác nhận.

### 6. Cloudflare Bot Management

**Đã xác minh:** Enterprise add-on cung cấp bot score 1-99, đọc qua Workers/Logs. Điểm cao nghiêng về người, điểm 0 là chưa được đánh giá. [Sản phẩm](https://developers.cloudflare.com/bots/get-started/bot-management/), [score](https://developers.cloudflare.com/bots/concepts/bot-score/)

**Vào DATACAT:** đưa website qua zone được cấp quyền; Worker hoặc logs truyền kết quả với request ID. Không phải REST API nhận tùy ý chuột rồi trả nhãn. Chống giả mạo header từ client trước khi tin evidence.

**Đánh giá:** tốt nếu thầy đã có Enterprise; không đề xuất mua/chuyển hạ tầng chỉ để thử khóa luận. Cloudflare Free, Super Bot Fight Mode và Turnstile không đồng nhất với API bot score này.

### 7. AWS WAF Bot Control

**Đã xác minh:** Common và Targeted, Targeted thêm kỹ thuật browser/behavior và ML tùy chọn. Bot category/name và detection labels xuất trong WAF logs/CloudWatch. [Tài liệu](https://docs.aws.amazon.com/waf/latest/developerguide/waf-bot-control.html)

**Vào DATACAT:** website cần resource được WAF bảo vệ, thu log theo request, ghép phiên. Chọn phạm vi kiểm tra phù hợp; chỉ chế độ Common không đại diện cùng phạm vi bot nâng cao với Targeted.

**Đánh giá:** nên dùng khi đã chạy AWS. Label rule là bằng chứng tham khảo; request không có bot label không tự trở thành HUMAN. Có thêm phí Bot Control và hạ tầng/log, cần tính tổng chi phí.

### 8. HUMAN Bot Defender

**Đã xác minh:** kiến trúc Sensor + Detector + Enforcer. Enforcer hỗ trợ xuất score header; cookie v3 có score 0-100. [Kiến trúc](https://docs.humansecurity.com/applications/bd-overview), [Score header](https://docs.humansecurity.com/applications/enforcer-configuration), [Risk cookie](https://docs.humansecurity.com/applications/about-enforcers)

**Vào DATACAT:** cần sensor trên website và enforcer ở ứng dụng/proxy/CDN; lấy score từ nguồn server đã xác thực. Không tự decode cookie browser rồi tin kết quả. Chọn monitor mode có detection, vì Bypass có thể tắt detection và đưa score về 0. [Policy](https://docs.humansecurity.com/applications/bot-defender-policy-settings)

**Đánh giá:** ứng viên doanh nghiệp đáng thử nếu có hỗ trợ. Chưa xác nhận quyền score/export/trial và train trong hợp đồng của người dùng.

### 9. Akamai Bot Manager Premier

**Đã xác minh:** bot score 0-100, cao nghiêng bot. SIEM có botData.botScore/responseSegment khi có Premier và request khớp resource purpose bật bot protection. EdgeWorkers có các response segment. [Bot handling](https://techdocs.akamai.com/cloud-security/docs/handle-adversarial-bots), [SIEM](https://techdocs.akamai.com/siem-integration/docs/siem-splunk-connector)

**Vào DATACAT:** lấy logs của website chạy Akamai, không giả định mỗi request đều có score. **Đánh giá:** phù hợp nếu hạ tầng/tài khoản đã có; nặng cho pilot độc lập, cần entitlement và quyền dataset.

### 10. F5 Distributed Cloud Bot Defense

**Đã xác minh:** thu telemetry JS/mobile, inference nhận diện automation; security events có trường bot_defense.automation_type. [Overview](https://docs.cloud.f5.com/docs-v2/bot-defense/concepts/about-bot-defense), [Events](https://docs.cloud.f5.com/docs-v2/platform/reference/security-events-reference)

**Vào DATACAT:** tích hợp theo deployment F5, lấy event/request evidence. API cấu hình riêng không phải API gán nhãn. **Đánh giá:** khả thi có điều kiện, cần demo chính xác export cả người và bot, latency và key ghép phiên; không ưu tiên khi chưa dùng F5.

### 11. Kasada

**Đã xác minh:** hãng công bố các mô hình tích hợp và bot detection API. [Integration](https://www.kasada.io/integration)

**Chưa xác minh:** schema per-event cho khách hàng, entitlement score/export, mode phù hợp thu dataset và quyền huấn luyện. **Đánh giá:** mời demo nếu có tài trợ; chưa đủ thông tin để cam kết chỉ cần API key là ghép vào dashboard được. Không suy diễn độ chính xác từ nội dung marketing.

### 12. Radware Bot Manager

**Đã xác minh:** tài liệu monitor mode mô tả API bất đồng bộ, active mode trả action codes. Bài chi tiết cập nhật năm 2022 nên cần xác nhận phiên bản hiện tại. [Monitor/Active](https://support.radware.com/app/answers/answer_view/a_id/1018904/~/what-is-the-difference-between-active-and-monitor-mode-integration%3F-which-one)

**Vào DATACAT:** cần tích hợp server và lấy kết quả theo phiên, không coi allow/block là ground truth. **Đánh giá:** có đường tích hợp, còn phải xác minh API/schema/export của gói hiện hành; xếp sau các ứng viên có tài liệu event rõ hơn.

### 13. Imperva Advanced Bot Protection (Thales)

**Đã xác minh ở mức sản phẩm:** có Advanced Bot Protection; tài liệu Cloud WAF có tích hợp export event sang SIEM. [ABP](https://www.imperva.com/resources/datasheets/imperva-advanced-bot-protection.pdf), [SIEM release](https://docs-cybersec.thalesgroup.com/bundle/cloud-application-security/page/release-notes/2024-02-25.htm)

**Chưa xác minh đầy đủ:** schema ABP từng request, log có bao phủ request được cho qua và quyền gói cụ thể. **Đánh giá:** khảo sát khi đã có Imperva; không lấy API quản trị site hoặc WAF attack logs làm bằng chứng rằng có nhãn cho mọi traffic.

### 14. Fastly Bot Management / Next-Gen WAF

**Đã xác minh:** Next-Gen WAF có suspected/verified bot signals, đa số bot signals yêu cầu Edge WAF. API Bot Management/ContentGuard hiện chủ yếu cấu hình policy/categories và protection mode. [Signals](https://www.fastly.com/documentation/guides/next-gen-waf/signals/using-system-signals/), [Management API](https://www.fastly.com/documentation/reference/api/bot-management/)

**Vào DATACAT:** cần event/log API của đúng sản phẩm triển khai và ID request. **Đánh giá:** dùng nếu đã chạy Fastly; không gọi API categories rồi coi là classifier của một phiên mới.

## 4. Nhóm token/challenge/risk assessment

### 15. Google reCAPTCHA / reCAPTCHA Enterprise

**Đã xác minh:** frontend tạo token, backend tạo assessment; có valid, action, score, reasons. Score cao nghĩa rủi ro thấp. [Assessment](https://docs.cloud.google.com/recaptcha/docs/interpret-assessment-website)

**Vào DATACAT:** quan sát ở action/mốc được định nghĩa, lưu assessment kèm phiên. **Đánh giá:** nguồn risk bổ sung đáng cân nhắc, không tự xác nhận human/bot; invalid token có thể là lỗi tích hợp/hết hạn. Điểm phải kiểm chứng trên website và không diễn giải thành xác suất bot chính xác. Cần xác nhận gói và quyền train trước khi dùng.

### 16. hCaptcha Enterprise

**Đã xác minh:** siteverify xác minh token; Enterprise có score bổ sung. [Developer guide](https://docs.hcaptcha.com/), [Score migration](https://docs.hcaptcha.com/switch)

**Vào DATACAT:** lưu score/score_reason nếu entitlement cung cấp; kiểm tra chiều score theo schema, không copy logic ngưỡng reCAPTCHA. **Đánh giá:** evidence bổ sung; pass CAPTCHA không là nhãn HUMAN mạnh. Gói miễn phí không tương đương Enterprise scoring.

### 17. Arkose Labs Bot Manager

**Đã xác minh:** Verify API có thể trả session_risk gồm global/custom score 0-100; phải bật quyền Risk Score. [Risk Score](https://developer.arkoselabs.com/docs/risk-score), [Verify](https://developer.arkoselabs.com/docs/verify-api-v4)

**Vào DATACAT:** ghép Arkose session token, giữ score và risk category, tách trước/sau challenge. **Đánh giá:** có API per-session rõ nhưng cần onboarding/gói phù hợp; phù hợp luồng bảo vệ hành động hơn mọi page view. Không coi challenge failure là bot chắc chắn.

### 18. Cloudflare Turnstile

**Đã xác minh:** Siteverify trả kết quả xác minh token và metadata, không phải Bot Management score 1-99. [Siteverify](https://developers.cloudflare.com/turnstile/get-started/server-side-validation/)

**Đánh giá:** hữu ích làm tín hiệu xác minh bổ sung hoặc challenge, không chọn làm giáo viên chính để dán nhãn dataset người/bot. Lỗi token và bot là hai việc khác nhau.

### 19. GeeTest Device Fingerprinting / DeepKnow

**Đã xác minh:** có API device risk và hệ thống risk code cho yêu cầu verify. [Device API](https://docs.geetest.com/g5/Integration/API), [DeepKnow risk codes](https://docs.geetest.com/deepknow/overview/riskcode)

**Vào DATACAT:** chọn đúng sản phẩm risk/device, ghép token/event, kiểm tra từng mã; không nhầm CAPTCHA v4 với device risk API. **Đánh giá:** có thể khảo sát, nhưng còn phải xác nhận phạm vi browser bot/chuột giả, entitlement, khu vực và quyền dữ liệu.

### 20. Tencent Cloud CAPTCHA

**Đã xác minh:** tài liệu chế độ không gây gián đoạn đề cập EvilLevel trong ticket verification. [Tài liệu chính thức](https://cloud.tencent.com/document/product/1110/83666)

**Đánh giá:** rủi ro/verification tham khảo, chưa chứng minh có thể dùng làm nhãn bot chuột. Cần xác nhận mode và quyền theo khu vực/tài khoản; không ưu tiên cho DATACAT hiện tại.

## 5. Nhóm khác cần phân biệt phạm vi

### 21. Alibaba Cloud WAF Bot Management

**Đã xác minh:** sản phẩm WAF có bot management; phiên bản mới/legacy khác nhau, một số edition có trial 7 ngày theo trang sản phẩm. [Tài liệu](https://www.alibabacloud.com/help/en/waf/web-application-firewall-3-0/bot-management/)

**Vào DATACAT:** phải đi qua WAF và xác nhận schema log/ID cho phiên bản cụ thể. **Đánh giá:** tương tự lựa chọn hạ tầng, không phải SDK thu chuột độc lập; chỉ ưu tiên khi website đã ở Alibaba Cloud.

### 22. Fraudlogix Bot & Fraud API

**Đã xác minh:** endpoint công khai tra IP, trả risk và các cờ proxy/VPN/datacenter/search-engine bot. [API](https://www.fraudlogix.com/wp-content/uploads/2025/02/fraudlogix_BOT-FRAUD-API.pdf)

**Đánh giá:** dùng làm IP intelligence bổ sung. API này không phân tích quỹ đạo chuột hay xác nhận nhãn cho từng người dùng chung IP. Không chọn làm giáo viên duy nhất; kết luận chỉ áp dụng API đã khảo sát, không phải mọi sản phẩm của hãng.

### 23. CHEQ ClickCease

**Đã xác minh:** có xuất dữ liệu Clicks Report và Bot Zapping monitoring mode. [Export](https://support.clickcease.com/hc/en-us/articles/11197260934801-How-to-Export-the-Clicks-Report-Data), [Monitoring](https://support.clickcease.com/hc/en-us/articles/11197130036497-Monitoring-Mode-in-Bot-Zapping)

**Chưa xác minh:** API đánh giá từng session với timestamp/join key đủ cho DATACAT. **Đánh giá:** gần bài toán quảng cáo nhưng invalid click có thể đến từ người, không chỉ bot. Chỉ đưa vào shortlist khi hãng xác nhận export/schema/quyền phù hợp, không giả định báo cáo click là ground truth bot.

### 24. fraud0

**Đã xác minh:** script onsite hỗ trợ customer user ID để hỗ trợ liên kết dữ liệu backend. [Customer IDs](https://help.fraud0.com/1-onsite/f-customer-user-ids/customeruserids01/)

**Chưa xác minh:** API verdict từng event, trường bot/human, mode và entitlement export đáp ứng yêu cầu train. **Đánh giá:** đáng hỏi vì sát invalid traffic, nhưng hiện chưa đủ tài liệu đã kiểm tra để cam kết tích hợp classifier. Tên miền api trong script không chứng minh có REST API nhãn cho khách hàng.

## 6. Quyền dùng kết quả để huấn luyện

| Nhà cung cấp | Điều xác minh được | Quyết định trước thu dataset |
| --- | --- | --- |
| Fingerprint | Mục 1.ii(f) hạn chế benchmarking và phát triển sản phẩm tương tự/cạnh tranh. Trang hiện ghi hiệu lực 01/11/2026, sau ngày khảo sát | Xác nhận hợp đồng áp dụng và ngoại lệ nghiên cứu/huấn luyện bằng văn bản |
| Castle | Mục 4.5 hạn chế sử dụng bởi đối thủ và benchmarking/competitive purposes | Cần thỏa thuận nghiên cứu cho mục đích cụ thể |
| IPQS | Đã mở terms, chưa xác nhận được quyền train model từ kết quả | Hỏi rõ quyền và điều khoản gói; không suy ra được phép chỉ vì không tìm thấy từ khóa |
| Các bên khác | Chưa hoàn tất kiểm tra hợp đồng/entitlement cho mục đích này | Không tuyên bố đã có quyền; yêu cầu xác nhận trước |

Nguồn: [Fingerprint terms](https://docs.fingerprint.com/docs/terms-of-service), [Castle terms](https://castle.io/terms/), [IPQS terms](https://www.ipqualityscore.com/terms-of-service).

Đây là điểm cần xác nhận với nhà cung cấp, không phải kết luận pháp lý cho một hợp đồng chưa ký. Nếu không được phép, dự án vẫn có thể tiếp tục thu raw do mình kiểm soát và dùng nhãn người tham gia/bot có run log.

## 7. Cách xếp shortlist phù hợp nguồn lực

| Tình huống | Ưu tiên kỹ thuật | Lý do |
| --- | --- | --- |
| Website thông thường, muốn gắn ít thành phần | Fingerprint | Event API và luồng agent/backend rõ |
| Cần thử thêm nguồn đánh giá tương tác/chuột | Castle | Có Bot Score, token API và mô tả phân tích tương tác |
| Muốn nguồn thiết bị/gian lận bổ sung | IPQS Device Fingerprint | Có bot_status, nhưng cần Premium và xác minh server |
| Có thầy/trường hỗ trợ dịch vụ doanh nghiệp | DataDome hoặc HUMAN | Evidence request/score có tài liệu; cần tích hợp và entitlement |
| Website đã có Cloudflare Enterprise/AWS/Akamai | Dịch vụ đang có | Tận dụng quyền và request log, giảm chi phí chuyển hạ tầng |
| Chỉ có ngân sách/khả năng thêm CAPTCHA | reCAPTCHA hoặc Turnstile như nguồn phụ | Thu tín hiệu verification; chưa giải quyết nhãn mạnh |

Khuyến nghị thay cho việc tích hợp mọi hãng: hỏi quyền và demo payload của Fingerprint, Castle, IPQS trước; nếu có tài trợ thì thêm DataDome. Chọn một nguồn chính và tối đa một nguồn đối chiếu sau thử nghiệm. Không thể chọn hãng bắt bot giả chuột tốt nhất chỉ từ API docs.

## 8. Phép thử trước quyết định mua hoặc train

1. Cùng website và protocol, chạy các bot có nguồn nhãn độc lập: automation phổ thông, giả chuột có quy luật, giả chuột phức tạp đang vượt DATACAT; có người đối chứng dùng chuột, touchpad và ít chuột.
2. Lưu raw collector thực nhận, verdict DATACAT, evidence nhà cung cấp, số điểm và thời gian quan sát; phân biệt sự kiện đầu phiên với cuối phiên.
3. Đo BOT -> HUMAN, BOT -> SUSPECT, HUMAN -> BOT của DATACAT; đo phát hiện/bỏ sót của provider theo đúng ngữ nghĩa nhãn, độ phủ, lỗi và chi phí mỗi phiên sử dụng được.
4. Không biến not_detected/score thấp/allow thành HUMAN mạnh. Không có evidence hoặc SDK bị chặn thì UNKNOWN, không tự gán bot.
5. Lấy mẫu cả phiên DATACAT đang HUMAN, không chỉ SUSPECT; giữ các trường hợp bất đồng để review.
6. SDK thương mại có thể ảnh hưởng timing và hành vi; thử A/B tải SDK, tránh challenge cưỡng bức trong cohort thu chuột tự nhiên. Không gắn tất cả sensor cùng lúc rồi bỏ qua tác động đó.
7. Nếu không có người đối chứng mới, chỉ kết luận hiệu quả trên bot có kiểm soát; chưa có căn cứ chọn threshold để chặn người dùng thật.

## 9. Ghép vào sản phẩm hiện tại

Reference adapter chạy ở backend/worker, không nằm bên trong forward của BiLSTM/XGBoost. Gắn evidence với study/site/session/page-load/observation và provider event ID; không join bằng IP đơn độc. Xác minh nguồn response, origin/thời gian, xử lý retry và không cho một event bị gắn sang phiên khác.

Giữ ba trường riêng trên dashboard: `DATACAT verdict`, `provider observation`, `dataset label`. Nhà cung cấp hết quota hoặc lỗi thì model nội bộ tiếp tục hoạt động. Dataset label giữ nguồn, revision và mức bằng chứng, không ghi đè verdict AI.

Loader hiện mặc định bỏ commercial_tool là hợp lý. Sau khi có quyền và dữ liệu kiểm chứng mới bổ sung nhánh nhãn yếu có trọng số, version dataset và split theo người/run/bot family trước tạo cửa sổ. Không dùng provider score/ID làm feature của model muốn chạy độc lập. Với phiên không có chuột, không thể train model chuột chỉ nhờ có một nhãn BOT.

## 10. Những câu cần yêu cầu trả lời trước khi đăng ký

- Gói nào trả bot verdict/score cho từng event, và có response mẫu của phiên người/bot/không đánh giá được không?
- Có API server hoặc log export cho cả traffic được cho qua không; độ trễ, rate limit, retention và giá thực tế?
- Có monitor mode giữ detection hoạt động, không challenge/block làm mất hành vi cần thu không?
- Có khóa tương quan tùy chỉnh/session ID, timestamp và cơ chế chống replay event không?
- Có cho phép lưu kết quả làm nhãn yếu, train model riêng, công bố benchmark khóa luận và giữ model sau khi dừng dịch vụ không?
- Có gói nghiên cứu/tài trợ, quy định dữ liệu được chia sẻ và giới hạn sử dụng hay không?

**Quyết định hiện tại:** chưa mua hoặc mở nhiều trial. Chuẩn bị adapter và benchmark; chọn nhà cung cấp thực sự cho phép nghiên cứu, xuất được evidence đúng phiên và tạo giá trị bổ sung trên bộ kiểm thử độc lập của DATACAT.
