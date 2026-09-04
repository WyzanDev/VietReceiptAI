# Hướng dẫn annotation VietReceiptAI

## Mục tiêu

Kiểm tra OCR toàn trang và gán ground truth cho bốn trường `SELLER`, `ADDRESS`,
`TIMESTAMP`, `TOTAL_COST`. OCR chỉ là bản nháp; ảnh mới là nguồn sự thật.

## Trình tự bắt buộc cho từng ảnh

1. Mở ảnh đúng theo `image_file`.
2. Kiểm tra từng OCR token: sửa `verified_text` theo ảnh; token OCR thừa thì xóa, thiếu thì thêm.
3. Kiểm tra vùng của bốn trường. UIT đã có bbox nháp; MC-OCR validation phải tạo vùng mới.
4. Điền `raw_text`, `normalized_value`, `legibility`, `present`, rồi đặt `verified=true` cho từng trường.
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

## Chép text và chuẩn hóa

- `raw_text`: chép nguyên văn, giữ dấu tiếng Việt, chữ hoa/thường, dấu phân cách và ký hiệu tiền.
- `normalized_value` của `SELLER`, `ADDRESS`: bỏ khoảng trắng đầu/cuối, gom nhiều khoảng trắng;
  không tự sửa chính tả.
- `normalized_value` của `TIMESTAMP`: dùng `YYYY-MM-DD HH:MM:SS` nếu ảnh thể hiện đủ và rõ;
  thiếu giờ thì `YYYY-MM-DD`. Nếu mơ hồ ngày/tháng, để giống `raw_text` và ghi chú.
- `normalized_value` của `TOTAL_COST`: chỉ giữ giá trị số thập phân dùng dấu chấm, bỏ dấu phân
  cách hàng nghìn và ký hiệu tiền; ví dụ `150.000 đ` thành `150000`.
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
- `alignment_qc.csv` không còn mức `error`; cảnh báo phải được đọc và giải thích trong `notes`.
- Không đổi tên ảnh, `task_id`, `dataset`, `source_split`, kích thước hoặc manifest.
