# member2 — MC-OCR / train

Gói này có **138 ảnh**. Dataset và split được giữ cố định, không chuyển ảnh sang gói khác.
Đường dẫn từ repository: `task/member2/MC-OCR/train/`.

## Thực hiện tại đúng thư mục này

1. Đọc `ANNOTATION_GUIDE.md`, `DATASET_SCHEMA.md`, `OCR_GUIDE.md` và `TOKEN_ALIGNMENT.md`.
2. Kích hoạt môi trường OCR chung, cài `python -m pip install -r requirements-ocr.txt`.
3. Chạy thử `python tools/05_run_paddleocr.py --task-dir . --device cpu --limit 3`.
   Khi chạy đủ gói thì bỏ `--limit 3`. Không dùng `--force` với kết quả đã verify.
4. Verify OCR **toàn trang**, gồm cả token ngoài bốn trường; kiểm tra bbox và giá trị bốn trường KIE.
   UIT và MC-OCR train có nhãn nguồn làm bản nháp; MC-OCR validation cần tạo nhãn.
   Chữ `a` placeholder không phải đáp án. Nhãn nguồn có transcript thật vẫn cần kiểm tra theo ảnh.
5. Sửa text máy ở `ocr.tokens[].verified_text`; chép giá trị KIE nguyên văn ở `fields.*.regions[].raw_text`.
   Không chuẩn hóa giờ/ngày/số tiền/chính tả. Giữ `06:00 pm`; mọi `normalized_value` để `""`.
6. Đặt trạng thái hoàn thành theo hướng dẫn, chạy `python tools/06_token_alignment.py --task-dir .`.
   Đọc và xử lý cảnh báo/lỗi; căn chỉnh tự động không thay thế kiểm tra text bằng mắt.
7. Nộp `annotations.jsonl`, `aligned_annotations.jsonl`, `alignment_qc.csv` tại đúng gói này.

Giữ nguyên `task_id`, `image_id`, `image_file`, `dataset`, `source_split`, ảnh và manifest.
`source_annotations.jsonl` (nếu có) chỉ là bản nháp nguồn để đối chiếu, không chỉnh sửa/nộp như mẫu mới.
Các đường dẫn `images/...` tính từ thư mục này. Không chạy OCR/alignment tại gốc member.
Hướng dẫn tổng hợp: [MERGE_GUIDE.md](../../../MERGE_GUIDE.md).
