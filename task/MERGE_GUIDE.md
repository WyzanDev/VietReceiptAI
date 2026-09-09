# Nhận bài và gộp dữ liệu theo member/dataset/split

## Sổ đối chiếu

`assignment_registry.jsonl` là danh sách giao việc cố định gồm 3.631 ảnh:
2.142 UIT-MLReceipts và 1.489 MC-OCR. Mỗi dòng ghi dataset, split gốc, image_id,
task_id, member, thư mục gói, kích thước và SHA-256 ảnh. Người nhận bài quản lý file này;
member không sửa registry/manifest để làm cho bài nộp vượt kiểm tra.

Khóa ảnh: `(dataset, source_split, image_id)`. Không ghép chỉ theo tên file hoặc member.
Giữ cả `task_id` để truy ngược người/đợt thực hiện. Đợt 2 có tiền tố `r2-`.

## Cấu trúc hiện tại

- Mỗi gói nằm ở `task/memberN/<dataset>/<source_split>/`.
- UIT: member1–2 có train; member3 có val; member4–5 có test; member8 có train.
- MC-OCR: cả 8 member có train; riêng member6–7 có thêm validation.

Mỗi thư mục lá chứa `images`, `annotations.jsonl`, `manifest.csv`, tài liệu và công cụ.
Các gói bổ sung giữ `source_annotations.jsonl` để đối chiếu bản nháp ban đầu.
Không nối JSONL của các dataset/split để chạy OCR chung ở thư mục member.
`task/assignment_summary.csv`, `task/build_report.json` và registry bao phủ toàn bộ 3.631 ảnh.
`round` trong registry và tiền tố `r2-` trong task_id chỉ là thông tin lịch sử; không đổi ID.
Không tạo lại thư mục công việc theo đợt. Bản dự phòng trước chuyển cấu trúc nằm trong
`reference/task-layout-backup-*/task/` ở máy người tổng hợp, không push lên GitHub.

## Đang làm trên cấu trúc cũ thì chuyển thế nào?

Commit hoặc sao lưu bài đang làm trước khi cập nhật nhánh. Không chạy lại OCR hay tạo lại task.
Git có thể nhận ra thao tác di chuyển, nhưng không mặc định rằng merge sẽ tự xử lý đúng mọi file.

| Vị trí cũ | Vị trí mới |
|---|---|
| `task/member1/`, `task/member2/` (gói UIT cũ) | `task/memberN/UIT-MLReceipts/train/` |
| `task/member3/` (gói UIT cũ) | `task/member3/UIT-MLReceipts/val/` |
| `task/member4/`, `task/member5/` (gói UIT cũ) | `task/memberN/UIT-MLReceipts/test/` |
| `task/member6/`, `task/member7/` (gói MC cũ) | `task/memberN/MC-OCR/validation/` |
| `task/round2/memberN/MC-OCR/train/` | `task/memberN/MC-OCR/train/` |
| `task/round2/member8/UIT-MLReceipts/train/` | `task/member8/UIT-MLReceipts/train/` |

Nếu merge conflict, giữ phiên bản annotation đã verify và đặt nó tại đúng gói mới,
đối chiếu theo task_id; không chọn ghi đè toàn bộ thư mục một cách máy móc.
Chuyển cả file kết quả liên quan như `aligned_annotations.jsonl`, `alignment_qc.csv` nếu đã có.
Nếu có hai bản cùng task_id khác nhau thì người tổng hợp cần so sánh, không tự nối thành hai mẫu.
`image_file=images/...` vẫn giữ nguyên và tính tương đối từ gói mới; chỉ cập nhật cấu hình
đường dẫn ngoài JSONL của công cụ cá nhân nếu trước đó đã dùng đường dẫn tuyệt đối.

## Quy tắc giữ nguyên nội dung

Không chuẩn hóa bất kỳ giá trị nào: `06:00 pm` vẫn là `06:00 pm`, `150.000 đ`
vẫn là `150.000 đ`. Trường `normalized_value` vẫn tồn tại để tương thích nhưng phải là `""`.
Sửa OCR ở `verified_text`; text trường KIE lưu nguyên văn ở `fields.*.regions[].raw_text`.
Đọc ảnh để sửa; không dùng văn bản đã chuẩn hóa để suy ngược lại nội dung gốc.

## Nhận bài

1. Member commit phần việc trên nhánh annotation riêng rồi lấy cập nhật từ `origin/task`,
   đối chiếu bảng chuyển đường dẫn ở trên nếu đang dùng cấu trúc cũ.
2. Nộp kết quả đúng thư mục được giao. Không đưa môi trường Python/cache/model weights vào Git.
3. Người tổng hợp đối chiếu thay đổi với registry đã chốt trước khi merge PR.
4. Người tổng hợp cài phụ thuộc bằng `python -m pip install Pillow jsonschema`,
   rồi chạy `python src/08_audit_annotation_submissions.py` tại gốc repository.
   Lệnh này kiểm tra cấu trúc/định danh/ảnh và báo số ảnh còn pending; không sửa file.
5. Khi tất cả đã hoàn thành, chạy thêm `--require-completed`. Nếu có lỗi thì xử lý trước khi gộp.
   Kiểm tra tự động không xác nhận được text chép đúng ảnh; vẫn phải review bằng mắt.
6. Token alignment chạy riêng tại từng gói sau khi verify. Đọc cảnh báo, nhất là token phủ cả
   chữ nhãn và giá trị hoặc nhiều field; điều chỉnh vùng/token trước khi đưa vào huấn luyện.

## Gộp cho huấn luyện/đánh giá

Đích dự kiến tách theo `dataset/split`, ví dụ `UIT-MLReceipts/train/annotations.jsonl`
và `MC-OCR/train/annotations.jsonl`. Mỗi ảnh chỉ một bản ghi; đường dẫn `images/<tên ảnh>`
được tính tương đối từ thư mục dataset/split đích. Chép ảnh theo registry, không chép lẫn
thư mục thành viên vào cùng một thư mục ảnh phẳng.

Đây là hướng dẫn đích gộp; script 08 là công cụ kiểm tra, không tự tạo dataset huấn luyện.
Không nối cả `annotations.jsonl`, `source_annotations.jsonl` và `aligned_annotations.jsonl`
thành ba mẫu. Bản đầu là annotation đang làm, bản thứ hai là bản nháp, bản cuối là dữ liệu dẫn xuất.

## Tránh leakage

- Giữ nguyên `train`, `val`/`validation`, `test`. Phân công member không phải chia train/test.
- UIT member3 (đợt 1) là val, member4–5 (đợt 1) là test; MC-OCR member6–7 (đợt 1) là validation.
  Các ảnh này không đi vào train dù cùng member có thêm ảnh train ở đợt 2.
- Mọi crop/token/ảnh xoay dẫn xuất phải theo split của hóa đơn cha. Không random-split crop độc lập.
- Dữ liệu MC-OCR `recognition` và `token_kie` dùng lại hóa đơn train: không tính là ảnh mới.
  Nếu kết hợp các nhánh này, ánh xạ về hóa đơn cha để kiểm tra trước; split recognition cũ
  không tự động trở thành split hợp lệ cho một thí nghiệm kết hợp mới.
- Bản ground truth test dùng chấm điểm, không dùng train OCR/KIE hoặc lựa chọn tham số.
  Khi chấm end-to-end, dùng OCR tự động làm đầu vào và bản verify làm đáp án.
- Đã kiểm tra 3.631 ảnh Clean không trùng byte hoặc pixel hoàn toàn trước khi chia.
  Ảnh gần giống/cùng hóa đơn chụp khác góc vẫn cần kiểm tra thêm khi phát hiện.
