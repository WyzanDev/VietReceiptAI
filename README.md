# VietReceiptAI

VietReceiptAI là dự án trích xuất thông tin có cấu trúc từ ảnh hóa đơn, tập trung vào bốn trường chính:

- `SELLER`: tên đơn vị hoặc cửa hàng phát hành hóa đơn.
- `ADDRESS`: địa chỉ của đơn vị phát hành.
- `TIMESTAMP`: ngày hoặc thời gian phát hành/thanh toán.
- `TOTAL_COST`: tổng số tiền khách hàng phải thanh toán.

Dự án xây dựng quy trình xử lý dữ liệu hóa đơn từ kiểm tra và làm sạch dataset, OCR toàn trang,
annotation/verify ground truth, token alignment đến trích xuất thông tin khóa (KIE).

## Nhánh repository

- `main`: trang giới thiệu dự án.
- `annotation`: ứng dụng và dữ liệu phân công để thành viên kiểm tra nhãn OCR/KIE.

Để làm nhiệm vụ annotation, xem hướng dẫn chi tiết trên nhánh
[`annotation`](https://github.com/WyzanDev/VietReceiptAI/tree/annotation).

## Nguyên tắc dữ liệu

Dataset ảnh không được lưu trực tiếp trên nhánh `main`. Khi annotation, nội dung phải được chép
nguyên văn theo hóa đơn; không tự chuẩn hóa định dạng ngày giờ, số tiền, đơn vị hoặc chính tả.

