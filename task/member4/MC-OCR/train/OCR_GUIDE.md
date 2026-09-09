# OCR chung: PaddleOCR PP-OCRv6

Nhóm dùng duy nhất PaddleOCR 3.7.0, pipeline PP-OCRv6 và `lang="vi"`. Model tiếng Việt này
cũng đọc được phần lớn chuỗi Latin/Anh trên hóa đơn. Không dùng OCR web vì khác phiên bản,
khó tái lập và có thể đưa dữ liệu ảnh ra ngoài.

## Môi trường thống nhất

Khuyến nghị Python 3.11 trong môi trường mới. Tại thư mục gói `task/memberN/<dataset>/<split>/` có `annotations.jsonl`:

```bash
python3.11 -m venv .venv-ocr
source .venv-ocr/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-ocr.txt
```

Máy Windows kích hoạt bằng `.venv-ocr\Scripts\activate`. Nếu PaddlePaddle không cài được
theo file requirements (đặc biệt với GPU), cài đúng bản PaddlePaddle 3.2.0 theo bộ chọn lệnh
chính thức của PaddlePaddle rồi chạy lại lệnh cài requirements.

## Cập nhật nếu đã cài theo hướng dẫn cũ

PaddleOCR 3.5.0 không chấp nhận `ocr_version="PP-OCRv6"`. Cấu hình cũ
`paddleocr>=3.5,<3.6` đã được thay bằng `paddleocr==3.7.0`.
Sau khi lấy bản cập nhật từ nhóm, mở terminal tại thư mục gói `<dataset>/<split>/` và kích hoạt
môi trường OCR đang sử dụng, rồi chạy:

```bash
python -m pip install --upgrade -r requirements-ocr.txt
python -m pip show paddleocr
python -m pip check
```

Kiểm tra kết quả hiển thị `Version: 3.7.0`. Nếu đang làm trên nhánh annotation riêng,
hãy commit phần việc đang làm rồi lấy cập nhật bằng `git fetch origin` và
`git merge origin/task` trước khi cài lại.

Nguồn: [mã nguồn PaddleOCR 3.5.0](https://github.com/PaddlePaddle/PaddleOCR/blob/v3.5.0/paddleocr/_pipelines/ocr.py)
và [bản phát hành PaddleOCR 3.7.0](https://pypi.org/project/paddleocr/3.7.0/).

## Chạy OCR

```bash
python tools/05_run_paddleocr.py --task-dir . --device cpu
```

Model tải một lần ở lần chạy đầu. Có thể kiểm tra 3 ảnh trước:

```bash
python tools/05_run_paddleocr.py --task-dir . --device cpu --limit 3
```

Chỉ thêm `--force` khi chủ động muốn chạy lại và ghi đè OCR đã có; tùy chọn này
có thể thay thế text token đã được sửa tay.

Nếu có GPU Paddle tương thích, đổi thành `--device gpu:0`. Script giữ nguyên tọa độ ảnh gốc,
ghi OCR vào `annotations.jsonl` và có thể chạy tiếp để bỏ qua ảnh đã OCR.

## OCR không phải ground truth

Phải nhìn ảnh và sửa `verified_text`. `raw_text` là kết quả máy để truy vết; không ghi đè nó.
Sau khi kiểm tra hết token của một ảnh, đặt `ocr.status="verified"`.

## Vị trí gói công việc

Mỗi gói nằm ở `task/memberN/<dataset>/<source_split>/`. Lệnh dùng `--task-dir .` phải chạy tại thư mục này, không tại gốc member.
`r2-` trong task_id và `round` trong registry chỉ là dấu vết lần giao việc cũ; giữ nguyên, không đổi ID và không tạo thư mục theo đợt.
