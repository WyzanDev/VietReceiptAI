# VietReceiptAI - Annotation

Bộ mã này dành cho member kiểm tra và sửa annotation OCR của hóa đơn. Member không cần cài PaddleOCR, Ollama hoặc chạy script xử lý dữ liệu.

## Cài đặt

Cần Python 3.11, `uv` và Git LFS:

```bash
git lfs install
git clone -b annotation https://github.com/WyzanDev/VietReceiptAI.git
cd VietReceiptAI
git lfs pull
uv venv --python 3.11 .venv
uv pip install --python .venv -r requirements.txt
```

## Chạy app

```bash
uv run python -m uvicorn annotation_app.app:app --host 127.0.0.1 --port 8000
```

Mở `http://127.0.0.1:8000`, đăng nhập bằng MSSV/password được cấp. App tự mở đúng batch của member, không cần chọn task thủ công.

## Kiểm tra OCR

Với mỗi ảnh:

1. Xem toàn trang và các vùng OCR.
2. Sửa, thêm hoặc xóa vùng OCR khi cần.
3. Giữ nguyên nội dung nhìn thấy: dấu tiếng Việt, hoa/thường, chính tả, số, ngày giờ, dấu câu và ký hiệu.
4. Mặc định vùng đã có là `Đọc rõ`; chỉ đổi sang `Đọc được một phần` hoặc `Không đọc được` khi ảnh thực tế yêu cầu.
5. Không đoán chữ mờ. Nếu ảnh không thể xác minh, dùng **Loại ảnh** và chọn lý do.
6. Xác nhận toàn trang rồi hoàn tất ảnh.

Kết quả được tự động lưu trong batch. Không sửa `config.json`, không xóa ảnh và không đổi ID vùng.

## Nộp kết quả

Sau khi xử lý batch, bấm **Xuất JSONL** và gửi file:

```text
batch_XX-completed.jsonl
```

File export chứa cả ảnh đã hoàn tất và ảnh đã loại. Chỉ gửi file JSONL này cho người tổng hợp; không gửi `.venv`, database hoặc file tạm.
