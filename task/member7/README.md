# Gói công việc member7

- Dataset duy nhất: **MC-OCR**
- Split: **validation**
- Số ảnh: **194**
- Phạm vi: Validation chưa có ground truth. Chạy OCR, tạo bbox và text thật cho đủ bốn trường.

## Các bước

1. Đọc lần lượt `DATASET_SCHEMA.md`, `ANNOTATION_GUIDE.md`, `OCR_GUIDE.md`.
2. Chạy OCR theo `OCR_GUIDE.md` và kiểm tra token trên từng ảnh.
3. Điền/sửa `annotations.jsonl`; không sửa `manifest.csv` hay đổi tên ảnh.
4. Chạy `python tools/06_token_alignment.py --task-dir .`.
5. Sửa mọi lỗi trong `alignment_qc.csv`, kiểm tra lại và nộp toàn bộ thư mục này.

Mỗi dòng JSONL tương ứng một dòng trong manifest qua `task_id`. Lưu file bằng UTF-8.
Không thêm ảnh ngoài gói và không chuyển ảnh cho member khác nếu chưa báo người tổng hợp.
