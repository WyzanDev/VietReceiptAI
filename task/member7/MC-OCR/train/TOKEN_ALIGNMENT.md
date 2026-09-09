# Token alignment và nhãn BIO

Token alignment là bước ghép mỗi token OCR với một trong bốn vùng KIE dựa trên hình học.
Thành viên không cần tự đặt `B-`/`I-` bằng tay.

Sau khi hoàn tất OCR và field annotation:

```bash
python tools/06_token_alignment.py --task-dir .
```

Quy tắc mặc định:

- token có tâm nằm trong field region, hoặc ít nhất 50% diện tích token nằm trong region,
  được gán vào field có độ phủ lớn nhất;
- token đầu của mỗi region là `B-FIELD`, các token sau là `I-FIELD`;
- token không thuộc bốn trường là `O`;
- xung đột hoặc field có text nhưng không nhận được token được ghi vào `alignment_qc.csv`.

Ví dụ `150.000 đ` nằm trong vùng `TOTAL_COST`: token đầu là `B-TOTAL_COST`, token tiếp theo
là `I-TOTAL_COST`. Kết quả nằm ở `aligned_annotations.jsonl`; file annotation gốc không bị ghi đè.

## Vị trí gói công việc

Mỗi gói nằm ở `task/memberN/<dataset>/<source_split>/`. Lệnh dùng `--task-dir .` phải chạy tại thư mục này, không tại gốc member.
`r2-` trong task_id và `round` trong registry chỉ là dấu vết lần giao việc cũ; giữ nguyên, không đổi ID và không tạo thư mục theo đợt.
