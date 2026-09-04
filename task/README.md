# Phân công annotation VietReceiptAI

Tổng cộng **2.282 ảnh** cần ground truth bốn trường và OCR đã kiểm tra:

- UIT-MLReceipts: 1.893 ảnh (bbox có sẵn, text đang là placeholder `a`).
- MC-OCR validation: 389 ảnh (chưa có ground truth, cần tạo bbox và text).

Phân công theo độ khó, không chỉ theo số ảnh: member1–5 chỉ làm UIT-MLReceipts;
member6–7 chỉ làm MC-OCR. Không thành viên nào nhận ảnh của cả hai dataset.

`common/` chứa schema và hướng dẫn chuẩn. Mỗi `memberN/` là một gói công việc độc lập
để giao cho thành viên. `assignment_summary.csv` là bảng kiểm soát chung.

Phần MC-OCR `token_kie` còn thiếu transcript là backlog riêng, không nằm trong 2.282 ảnh này.
