# Schema thống nhất VietReceiptAI 1.0.0

Mỗi dòng trong `annotations.jsonl` là một JSON độc lập tương ứng đúng một ảnh.
Schema máy đọc đầy đủ nằm trong `annotation_schema.json`.

## Bốn nhãn KIE

| Nhãn | Ý nghĩa |
|---|---|
| `SELLER` | Tên đơn vị/cửa hàng phát hành hóa đơn |
| `ADDRESS` | Địa chỉ của `SELLER` |
| `TIMESTAMP` | Ngày hoặc ngày-giờ phát hành/thanh toán |
| `TOTAL_COST` | Số tiền cuối cùng khách phải trả |

## Ba tầng dữ liệu

1. `ocr.tokens`: từng dòng/token OCR toàn trang, bbox/polygon, text OCR và text đã kiểm tra.
2. `fields`: bbox/polygon và giá trị đúng của bốn trường KIE.
3. Sau căn chỉnh: mỗi token có `field` và `bio_label` (`B-*`, `I-*`, `O`).

Trong `fields`, `raw_text` chép nguyên văn chữ nhìn thấy trên ảnh.
Trong `ocr.tokens`, `raw_text` giữ text máy và `verified_text` giữ text đã sửa theo ảnh.
Nhóm không chuẩn hóa: giữ nguyên giờ 12/24h, ngày tháng, số tiền, đơn vị và chữ hoa/thường.
`normalized_value` là trường tương thích cũ, hiện luôn để `""` và không dùng làm đáp án.
Giá trị có sẵn từ dataset vẫn là bản nháp cho đến khi được kiểm tra bằng mắt.

## Định danh và split khi gộp

Khóa ảnh là bộ ba `(dataset, source_split, image_id)`, không chỉ tên ảnh hoặc member.
`task_id` phải duy nhất giữa các đợt; đợt bổ sung dùng tiền tố `r2-`.
Giữ nguyên split gốc. Phân công cho người nào không thay đổi ảnh thuộc train/val/test.
Sổ đăng ký chung `task/assignment_registry.jsonl` lưu đường dẫn gói, định danh,
kích thước và SHA-256 ảnh để đối chiếu độc lập khi nhận kết quả.

## Quy ước tọa độ

- `bbox = [x_min, y_min, x_max, y_max]`, đơn vị pixel trên ảnh gốc.
- `polygon` là các điểm `[x, y]` theo chu vi vùng chữ; cho phép tọa độ thập phân từ nguồn MC-OCR.
- `source_segmentation` (nếu có) giữ nguyên polygon MC-OCR ban đầu để đối chiếu, không dùng trực tiếp cho alignment.
  Khi nhiều polygon chung một transcript, bản nháp dùng bbox bao ngoài; cần xem ảnh để tách vùng/text hợp lý.
- `source_annotation_id` của UIT là ID annotation gốc; của MC-OCR là vị trí annotation (bắt đầu từ 0) trong dòng nguồn của ảnh.
- Mọi tọa độ phải nằm trong ảnh, `x_min < x_max`, `y_min < y_max`.
- Không resize, crop, xoay hoặc ghi đè ảnh trong gói công việc.

## Vị trí gói công việc

Mỗi gói nằm ở `task/memberN/<dataset>/<source_split>/`. Lệnh dùng `--task-dir .` phải chạy tại thư mục này, không tại gốc member.
`r2-` trong task_id và `round` trong registry chỉ là dấu vết lần giao việc cũ; giữ nguyên, không đổi ID và không tạo thư mục theo đợt.
