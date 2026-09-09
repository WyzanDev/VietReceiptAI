# Hướng dẫn annotation VietReceiptAI

## Mục tiêu

Kiểm tra OCR toàn trang và gán ground truth cho bốn trường `SELLER`, `ADDRESS`,
`TIMESTAMP`, `TOTAL_COST`. OCR chỉ là bản nháp; ảnh mới là nguồn sự thật.

## Trình tự bắt buộc cho từng ảnh

1. Mở ảnh đúng theo `image_file`.
2. Kiểm tra từng OCR token: sửa `verified_text` theo ảnh; token OCR thừa thì xóa, thiếu thì thêm.
3. Kiểm tra vùng của bốn trường. UIT và MC-OCR train có nhãn nguồn làm bản nháp; MC-OCR validation phải tạo vùng mới.
4. Điền `raw_text` nguyên văn, `legibility`, `present`; để `normalized_value=""`, rồi đặt `verified=true` cho từng trường.
5. Khi cả OCR và bốn trường đã kiểm tra, đặt `ocr.status="verified"` và
   `assignment.status="completed"`.
6. Chạy script căn chỉnh token và xử lý hết các dòng lỗi trong `alignment_qc.csv`.

## Cách chọn bốn trường

- `SELLER`: lấy tên cửa hàng/đơn vị phát hành nổi bật và cụ thể nhất. Không lấy logo slogan,
  tên nhân viên, khách hàng, ngân hàng hay ứng dụng thanh toán.
- `ADDRESS`: lấy địa chỉ của đúng `SELLER`; có thể tạo nhiều region theo từng dòng. Không lấy
  địa chỉ giao hàng/khách hàng. Nếu hóa đơn không in địa chỉ, đặt `present=false`.
- `TIMESTAMP`: ưu tiên ngày-giờ phát hành hoặc thanh toán. Không lấy ngày hết hạn, ngày giao hàng
  hay mã giao dịch. Nếu chỉ có ngày thì vẫn ghi đúng phần nhìn thấy.
- `TOTAL_COST`: lấy tổng cuối cùng khách phải thanh toán. Không lấy subtotal/tạm tính, VAT,
  tiền khách đưa, tiền thừa hoặc số dư.

## Chép nguyên văn — không chuẩn hóa (áp dụng cho mọi gói)

- `raw_text`: chép nguyên văn, giữ dấu tiếng Việt, chữ hoa/thường, dấu phân cách và ký hiệu tiền.
- Giữ `06:00 pm` đúng như ảnh, không đổi thành `18:00`. Giữ `01/08/2020`,
  không đổi sang ISO. Giữ `150.000 đ`, không bỏ dấu phân cách hay đơn vị.
- Không tự sửa chính tả trên hóa đơn, viết tắt, chữ hoa/thường hoặc dấu câu.
- `fields.*.regions[].raw_text` là nội dung vùng KIE đã kiểm tra bằng mắt.
- `ocr.tokens[].raw_text` giữ kết quả máy; sửa ở `verified_text` theo đúng ảnh.
- `normalized_value` chỉ giữ để tương thích schema cũ; luôn để chuỗi rỗng `""`.
  Nếu đã chuẩn hóa theo hướng dẫn cũ, đối chiếu ảnh để khôi phục text nguyên văn trước khi nộp;
  không tự động suy ngược từ giá trị đã chuẩn hóa.
- Không đoán ký tự không đọc được. Chọn `partly_unreadable` hoặc `unreadable` và mô tả ở `notes`.

## Quy tắc vùng

- Bbox ôm sát toàn bộ giá trị, không chỉ nhãn như `TỔNG CỘNG`.
- Nếu nhãn và giá trị nằm cùng một dòng, trường phải bao phủ phần giá trị cần trích xuất;
  `raw_text` không chứa tên nhãn nếu có thể tách rõ.
- Địa chỉ nhiều dòng có thể dùng nhiều region. Mỗi region có text riêng theo đúng dòng.
- Trường không xuất hiện: `present=false`, `regions=[]`, `verified=true`.
- Trường có xuất hiện nhưng không đọc được: `present=true`, giữ bbox, `raw_text=""`,
  `legibility="unreadable"`, ghi lý do ở `notes`.

## Tự kiểm tra trước khi nộp

- Không còn `assignment.status="pending"`.
- Không còn field có `present=null`, `verified=false` hoặc `legibility="unreviewed"`.
- Không còn text giả `a`.
- Mọi ảnh có OCR tokens đã được kiểm tra.
- Mọi `normalized_value` đều để trống. Không chạy lại OCR với `--force` lên text đã verify.
- `alignment_qc.csv` không còn mức `error`; cảnh báo phải được đọc và giải thích trong `notes`.
- Không đổi tên ảnh, `task_id`, `dataset`, `source_split`, kích thước hoặc manifest.

## Vị trí gói công việc

Mỗi gói nằm ở `task/memberN/<dataset>/<source_split>/`. Lệnh dùng `--task-dir .` phải chạy tại thư mục này, không tại gốc member.
`r2-` trong task_id và `round` trong registry chỉ là dấu vết lần giao việc cũ; giữ nguyên, không đổi ID và không tạo thư mục theo đợt.
