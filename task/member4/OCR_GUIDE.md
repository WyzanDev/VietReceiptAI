# OCR chung: PaddleOCR PP-OCRv6

Nhóm dùng duy nhất PaddleOCR 3.5.x, pipeline PP-OCRv6 và `lang="vi"`. Model tiếng Việt này
cũng đọc được phần lớn chuỗi Latin/Anh trên hóa đơn. Không dùng OCR web vì khác phiên bản,
khó tái lập và có thể đưa dữ liệu ảnh ra ngoài.

## Môi trường thống nhất

Khuyến nghị Python 3.11 trong môi trường mới. Tại thư mục member:

```bash
python3.11 -m venv .venv-ocr
source .venv-ocr/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-ocr.txt
```

Máy Windows kích hoạt bằng `.venv-ocr\Scripts\activate`. Nếu PaddlePaddle không cài được
theo file requirements (đặc biệt với GPU), cài đúng bản PaddlePaddle 3.2.0 theo bộ chọn lệnh
chính thức của PaddlePaddle rồi chạy lại lệnh cài requirements.

## Chạy OCR

```bash
python tools/05_run_paddleocr.py --task-dir . --device cpu
```

Model tải một lần ở lần chạy đầu. Có thể kiểm tra 3 ảnh trước:

```bash
python tools/05_run_paddleocr.py --task-dir . --device cpu --limit 3 --force
```

Nếu có GPU Paddle tương thích, đổi thành `--device gpu:0`. Script giữ nguyên tọa độ ảnh gốc,
ghi OCR vào `annotations.jsonl` và có thể chạy tiếp để bỏ qua ảnh đã OCR.

## OCR không phải ground truth

Phải nhìn ảnh và sửa `verified_text`. `raw_text` là kết quả máy để truy vết; không ghi đè nó.
Sau khi kiểm tra hết token của một ảnh, đặt `ocr.status="verified"`.
