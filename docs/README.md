# Tài liệu

Mục lục các tài liệu trong thư mục này, mới nhất đứng đầu mỗi nhóm.
Tổng quan hệ thống và cách chạy nằm ở [README](../README.md).

## Vận hành và triển khai

- [DEPLOYMENT.md](DEPLOYMENT.md): Triển khai production
- [PILOT_OPERATOR_GUIDE.md](PILOT_OPERATOR_GUIDE.md): Vận hành bản bàn giao thu traffic thật
- [PILOT_HANDOFF_REVIEW_2026-10-19.md](PILOT_HANDOFF_REVIEW_2026-10-19.md): Kiểm chứng bản bàn giao thu traffic DATACAT
- [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md): Production readiness audit
- [RESEARCH_CAPTURE.md](RESEARCH_CAPTURE.md): Research capture cho đợt traffic thật
- [MANUAL_LABELING.md](MANUAL_LABELING.md): Đánh số traffic và gán nhãn dataset
- [TOUCH_DATA.md](TOUCH_DATA.md): Dữ liệu cảm ứng từ traffic thật (collector 1.7.0)
- [TRAINING.md](TRAINING.md): Model Training
- [CASTLE_DASHBOARD_CONTRACT.md](CASTLE_DASHBOARD_CONTRACT.md): Castle dashboard preparation

## Phát hành mô hình

- [POLICY_HISTORY.md](POLICY_HISTORY.md): Lịch sử policy và kết quả thí nghiệm
- [MODEL_RELEASE_V27.md](MODEL_RELEASE_V27.md): Model release v27: kiểm chứng trên quỹ đạo chuột người thật
- [MODEL_RELEASE_V26.md](MODEL_RELEASE_V26.md): Model release v26: chuột nhảy ngẫu nhiên và trình duyệt tự mâu thuẫn
- [MODEL_RELEASE_V25.md](MODEL_RELEASE_V25.md): Model release v25: người thật trên site thật, bot tìm kiếm, IP dùng chung
- [MODEL_RELEASE_V24.md](MODEL_RELEASE_V24.md): Model release v24 — đóng các lỗ "fail-open" bằng gateway của shop
- [MODEL_RELEASE_V23.md](MODEL_RELEASE_V23.md): Model release v23 — vá các cách né luật input của policy 21
- [MODEL_RELEASE_V22.md](MODEL_RELEASE_V22.md): Model release v22 — luật gõ phím kiểm chứng trên 168.593 người
- [MODEL_RELEASE_V21.md](MODEL_RELEASE_V21.md): Model release v21 — bot điều khiển Chrome thật qua CDP
- [MODEL_RELEASE_V20.md](MODEL_RELEASE_V20.md): Model release v20 — trình duyệt tự khai HeadlessChrome
- [MODEL_RELEASE_V19.md](MODEL_RELEASE_V19.md): Model release v19 — phát hiện gian lận trên điện thoại (iPhone và Android)
- [MODEL_RELEASE_V18.md](MODEL_RELEASE_V18.md): Model release v18 — kết luận NGƯỜI THẬT cho điện thoại
- [MODEL_RELEASE_V17.md](MODEL_RELEASE_V17.md): Model release v17 — tối ưu theo khoảng cách với sản phẩm thương mại
- [MODEL_RELEASE_V16.md](MODEL_RELEASE_V16.md): Model release v16 — rà soát tình huống biên
- [MODEL_RELEASE_V15.md](MODEL_RELEASE_V15.md): Model release v15
- [MODEL_RELEASE_V14.md](MODEL_RELEASE_V14.md): Model release v14
- [MODEL_RELEASE_V13.md](MODEL_RELEASE_V13.md): Model release v13
- [MODEL_RELEASE_V12.md](MODEL_RELEASE_V12.md): Model release v12
- [MODEL_RELEASE_V11.md](MODEL_RELEASE_V11.md): Model release v11
- [MODEL_RELEASE_V10.md](MODEL_RELEASE_V10.md): Model release v10
- [MODEL_RELEASE_V9.md](MODEL_RELEASE_V9.md): Model release v9
- [MODEL_RELEASE_V8.md](MODEL_RELEASE_V8.md): Model release v8
- [MODEL_RELEASE_V7.md](MODEL_RELEASE_V7.md): Model release v7
- [RELEASE_REVIEW_V8.md](RELEASE_REVIEW_V8.md): Policy v8 release review
- [RELEASE_REVIEW_POLICY_V6.md](RELEASE_REVIEW_POLICY_V6.md): Policy v6 release review

## Rà soát và đánh giá

- [WEAKNESS_AUDIT_2026-10-28.md](WEAKNESS_AUDIT_2026-10-28.md): Rà soát điểm yếu (2026-10-28)
- [EXTERNAL_DATA_VALIDATION_2026-10-28.md](EXTERNAL_DATA_VALIDATION_2026-10-28.md): Kiểm chứng trên dữ liệu ngoài (2026-10-27/28)
- [MOUSE_FORMULA_REVIEW_2026-10-25.md](MOUSE_FORMULA_REVIEW_2026-10-25.md): Công thức phát hiện bot qua hành vi chuột: tổng hợp và benchmark
- [MOUSE_ACTION_ANALYSIS_2026-10-19.md](MOUSE_ACTION_ANALYSIS_2026-10-19.md): Per-Action Mouse Analysis
- [MOUSE_ABLATION_REVIEW_2026-10-13.md](MOUSE_ABLATION_REVIEW_2026-10-13.md): Mouse Model Ablation Review
- [LOCAL_MOTION_REVIEW_2026-10-13.md](LOCAL_MOTION_REVIEW_2026-10-13.md): Local Motion Feature Review (2026-10-13)
- [PROFILE_POLICY_REVIEW_2026-10-13.md](PROFILE_POLICY_REVIEW_2026-10-13.md): Integrated Profile Policy Experiment
- [PROFILE_SHADOW_REVIEW_2026-10-02.md](PROFILE_SHADOW_REVIEW_2026-10-02.md): Profile Shadow Review: 2026-10-02
- [INTERACTION_REVIEW_2026-10-02.md](INTERACTION_REVIEW_2026-10-02.md): Interaction Measurements Review (2026-10-02)
- [FIELD_BOT_PILOT_2026-09-29.md](FIELD_BOT_PILOT_2026-09-29.md): Browser bot pilot, 2026-09-29
- [PROFILE_FIRST_REVIEW_2026-09-29.md](PROFILE_FIRST_REVIEW_2026-09-29.md): Profile-first decision review, 2026-09-29
- [PRODUCTION_LOGIC_AUDIT_2026-09-26.md](PRODUCTION_LOGIC_AUDIT_2026-09-26.md): Production Logic Audit and Optimization Plan
- [NO_MOUSE_BOT_DECISION.md](NO_MOUSE_BOT_DECISION.md): No-mouse bot decisions

## Kết quả thí nghiệm (JSON)

- [MOTOR_FEATURE_BENCHMARK_2026-10-25.json](MOTOR_FEATURE_BENCHMARK_2026-10-25.json): Kết quả gốc của benchmark đặc trưng vận động
- [INTERACTION_RESULTS_2026-10-13.json](INTERACTION_RESULTS_2026-10-13.json): Kết quả gốc của đo tương tác
- [MOUSE_ABLATION_RESULTS_2026-10-13.json](MOUSE_ABLATION_RESULTS_2026-10-13.json): Kết quả gốc của ablation mô hình chuột
- [PROFILE_CANDIDATE_RESULTS_2026-10-13.json](PROFILE_CANDIDATE_RESULTS_2026-10-13.json): Kết quả gốc của đánh giá profile
- [INTERACTION_RESULTS_2026-10-02.json](INTERACTION_RESULTS_2026-10-02.json): Kết quả gốc của đo tương tác
- [PROFILE_SHADOW_RESULTS_2026-10-02.json](PROFILE_SHADOW_RESULTS_2026-10-02.json): Kết quả gốc của đánh giá profile

## Nghiên cứu và khóa luận

- [THESIS_BENCHMARK_PROTOCOL_V1.md](THESIS_BENCHMARK_PROTOCOL_V1.md): Protocol benchmark khóa luận DATACAT v1
- [THESIS_COMPLETION_PLAN_2026-10-19.md](THESIS_COMPLETION_PLAN_2026-10-19.md): Kế hoạch hoàn thiện khóa luận DATACAT
- [THESIS_PROPOSAL_2026-10-19.md](THESIS_PROPOSAL_2026-10-19.md): Đề cương tóm tắt gửi giảng viên hướng dẫn
- [MOUSE_PROFILE_LITERATURE_REVIEW_2026-10-24.md](MOUSE_PROFILE_LITERATURE_REVIEW_2026-10-24.md): Tổng quan tài liệu: phân tích hành vi chuột và profile traffic
- [COMMERCIAL_TEACHER_PLAN_2026-10-24.md](COMMERCIAL_TEACHER_PLAN_2026-10-24.md): Kế hoạch đối chiếu thương mại và huấn luyện DATACAT độc lập
- [COMMERCIAL_LABEL_PROVIDER_COMPARISON_2026-10-24.md](COMMERCIAL_LABEL_PROVIDER_COMPARISON_2026-10-24.md): Khảo sát nhà cung cấp nhãn tham khảo cho DATACAT
- [OPEN_SOURCE_BOT_DETECTION_REVIEW_2026-10-13.md](OPEN_SOURCE_BOT_DETECTION_REVIEW_2026-10-13.md): Khảo sát repository bot detection cho DATACAT
- [COMMERCIAL_BOT_DETECTION_RESEARCH_2026-10-12.md](COMMERCIAL_BOT_DETECTION_RESEARCH_2026-10-12.md): Nghiên cứu bot detection thương mại và kế hoạch áp dụng vào DATACAT
