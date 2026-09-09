# Phân công annotation VietReceiptAI

**3.631 ảnh — 8 thành viên — 16 gói dataset/split.** Phần cũ và bổ sung đã được gom về từng member;
không còn thư mục công việc `round2`. Không chia lại ảnh, không thay người phụ trách hoặc split.

```text
task/
├── README.md
├── MERGE_GUIDE.md
├── assignment_registry.jsonl   # Danh sách giao việc cố định
├── assignment_summary.csv    # Toàn bộ 16 gói hiện tại
├── build_report.json
├── common/                   # Schema và hướng dẫn chuẩn
└── member1/ ... member8/
    ├── README.md
    └── <dataset>/<split>/
        ├── README.md, hướng dẫn, schema, requirements-ocr.txt
        ├── images/
        ├── annotations.jsonl
        ├── manifest.csv
        ├── source_annotations.jsonl  # Chỉ có ở gói bổ sung, nếu đã được tạo
        └── tools/
```

## Tổng phần việc mỗi người

| Member | UIT train | UIT val | UIT test | MC train | MC validation | Tổng |
|---|---:|---:|---:|---:|---:|---:|
| [member1](member1/README.md) | 373 | 0 | 0 | 138 | 0 | 511 |
| [member2](member2/README.md) | 373 | 0 | 0 | 138 | 0 | 511 |
| [member3](member3/README.md) | 0 | 358 | 0 | 138 | 0 | 496 |
| [member4](member4/README.md) | 0 | 0 | 395 | 138 | 0 | 533 |
| [member5](member5/README.md) | 0 | 0 | 394 | 137 | 0 | 531 |
| [member6](member6/README.md) | 0 | 0 | 0 | 137 | 195 | 332 |
| [member7](member7/README.md) | 0 | 0 | 0 | 137 | 194 | 331 |
| [member8](member8/README.md) | 249 | 0 | 0 | 137 | 0 | 386 |

## Cách làm

Mở README của member, chọn gói dataset/split rồi làm theo README tại đó.
Ví dụ từ gốc repository: `cd task/member1/MC-OCR/train` trước khi chạy lệnh trong hướng dẫn.
Mỗi gói có tài liệu/công cụ riêng để có thể giao độc lập; `common/` là bản chuẩn do người tổng hợp quản lý.

- Giữ cấu hình đã thống nhất: PaddleOCR **3.7.0**, PP-OCRv6, `lang="vi"`.
- Verify **OCR toàn trang và bốn trường KIE**, sau đó chạy token alignment.
- **Không chuẩn hóa nội dung**: giữ `06:00 pm`, ngày tháng, số tiền, đơn vị và chính tả trên ảnh.
  `normalized_value` luôn là `""`.
- Giữ nguyên ảnh, ID và split. Tiền tố `r2-` chỉ để truy vết lần giao cũ, không phải đường dẫn mới.
- Cấu trúc mới không chứng minh annotation đã hoàn thành; nhãn nguồn và pre-OCR vẫn cần verify.

## Nhận bài và cập nhật từ cấu trúc cũ

Đọc [MERGE_GUIDE.md](MERGE_GUIDE.md) trước khi cập nhật nhánh hoặc nhận bài.
`assignment_registry.jsonl` là sổ đối chiếu toàn bộ 3.631 ảnh; không sửa để làm bài nộp vượt kiểm tra.
Script `src/08_audit_annotation_submissions.py` kiểm tra cấu trúc/ảnh/split, không chạy OCR hoặc tự gộp nhãn.
Script `src/09_restructure_member_tasks.py` chuyển cấu trúc; script 04/07 là bước tạo gói lịch sử,
không chạy lại lên dữ liệu đang annotation.
