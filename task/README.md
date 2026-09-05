# Phân công annotation VietReceiptAI

## Cập nhật cấu hình OCR — 05/09/2026

Cả nhóm sử dụng **PaddleOCR 3.7.0 + PP-OCRv6**, ngôn ngữ `vi`.
Cấu hình cũ khóa PaddleOCR 3.5.x không tương thích với PP-OCRv6.
Các file requirements và hướng dẫn của cả 7 member đã được cập nhật.

Sau khi lấy bản cập nhật, kích hoạt môi trường OCR, vào thư mục member của mình và chạy:

```bash
python -m pip install --upgrade -r requirements-ocr.txt
python -m pip show paddleocr
python -m pip check
```

Phiên bản hiển thị phải là `3.7.0`. Xem thêm hướng dẫn cập nhật nhánh tại
[OCR_GUIDE.md](common/OCR_GUIDE.md).

## Phân công

Tổng cộng **2.282 ảnh** cần ground truth bốn trường và OCR đã kiểm tra:

- UIT-MLReceipts: 1.893 ảnh (bbox có sẵn, text đang là placeholder `a`).
- MC-OCR validation: 389 ảnh (chưa có ground truth, cần tạo bbox và text).

Phân công theo độ khó, không chỉ theo số ảnh: member1–5 chỉ làm UIT-MLReceipts;
member6–7 chỉ làm MC-OCR. Không thành viên nào nhận ảnh của cả hai dataset.

`common/` chứa schema và hướng dẫn chuẩn. Mỗi `memberN/` là một gói công việc độc lập
để giao cho thành viên. `assignment_summary.csv` là bảng kiểm soát chung.

Phần MC-OCR `token_kie` còn thiếu transcript là backlog riêng, không nằm trong 2.282 ảnh này.
