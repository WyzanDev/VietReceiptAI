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

`raw_text` luôn chép đúng chữ nhìn thấy trên ảnh. `normalized_value` là bản chuẩn hóa phục vụ
so sánh và huấn luyện. Không sửa `raw_text` cho "đẹp" và không đặt text giả như `a`.

## Quy ước tọa độ

- `bbox = [x_min, y_min, x_max, y_max]`, đơn vị pixel trên ảnh gốc.
- `polygon` là các điểm `[x, y]` theo chu vi vùng chữ.
- Mọi tọa độ phải nằm trong ảnh, `x_min < x_max`, `y_min < y_max`.
- Không resize, crop, xoay hoặc ghi đè ảnh trong gói công việc.
