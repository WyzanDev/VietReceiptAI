# VietReceiptAI

VietReceiptAI là dự án trích xuất bốn trường thông tin chính từ ảnh hóa đơn:
`SELLER`, `ADDRESS`, `TIMESTAMP` và `TOTAL_COST`.

## Cấu trúc repository

```text
.
├── dataset/
│   └── link_dataset.txt       # Liên kết tải dataset; ảnh không lưu trong Git
├── notebook/                  # Notebook kiểm tra và trực quan hóa dữ liệu
├── report/                    # Đề cương và báo cáo của nhóm
├── src/                       # Mã làm sạch, chia task, OCR và token alignment
└── task/                      # Gói annotation; chỉ có trên nhánh task
```

Thư mục `reference/` chứa paper và biểu mẫu tham khảo, chỉ lưu cục bộ và không được
đưa lên GitHub. Các dataset gốc/sạch cũng không được commit vì dung lượng lớn và có
thể chịu điều kiện cấp phép riêng.

## Nhánh

- `dev`: mã nguồn, notebook, báo cáo và liên kết dataset.
- `task`: kế thừa `dev` và bổ sung các gói giao việc annotation.

## Tạo lại dữ liệu

Các script được chạy theo thứ tự tên file trong `src/`. Trước khi chạy, tải dataset
theo `dataset/link_dataset.txt` và đặt đúng cấu trúc mà từng script yêu cầu.

