#!/usr/bin/env python3
"""Create self-contained annotation assignments for VietReceiptAI.

The script is deterministic: assignments are ordered by dataset split and file name,
and each source image is copied to exactly one member package.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
UIT_ROOT = PROJECT_ROOT / "dataset" / "UIT-MLReceipts" / "Clean"
MCOCR_ROOT = PROJECT_ROOT / "dataset" / "MC-OCR" / "clean"
OUTPUT_ROOT = PROJECT_ROOT / "task"
SOURCE_FILES = (
    PROJECT_ROOT / "src" / "05_run_paddleocr.py",
    PROJECT_ROOT / "src" / "06_token_alignment.py",
)

FIELDS = ("SELLER", "ADDRESS", "TIMESTAMP", "TOTAL_COST")
FIELD_DEFINITIONS = {
    "SELLER": "Tên đơn vị/cửa hàng phát hành hóa đơn; không lấy slogan hay tên khách hàng.",
    "ADDRESS": "Địa chỉ của SELLER; có thể gồm nhiều dòng/vùng.",
    "TIMESTAMP": "Ngày hoặc ngày-giờ phát hành/thanh toán của hóa đơn.",
    "TOTAL_COST": "Số tiền cuối cùng khách phải thanh toán; không lấy tạm tính, thuế hay tiền khách đưa.",
}


def json_dump(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rectangle_polygon(box: list[int]) -> list[list[int]]:
    x1, y1, x2, y2 = box
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def empty_field() -> dict[str, Any]:
    return {"present": None, "verified": False, "regions": []}


def base_record(
    *,
    dataset: str,
    source_split: str,
    image_name: str,
    width: int,
    height: int,
    fields: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "task_id": "",
        "dataset": dataset,
        "source_split": source_split,
        "image_id": Path(image_name).stem,
        "image_file": f"images/{image_name}",
        "width": width,
        "height": height,
        "assignment": {
            "member": "",
            "status": "pending",
            "reviewer": None,
        },
        "ocr": {
            "status": "not_run",
            "engine": "PaddleOCR",
            "ocr_version": "PP-OCRv6",
            "language": "vi",
            "runtime_version": None,
            "tokens": [],
        },
        "fields": fields,
        "notes": "",
    }


def load_uit_pending() -> dict[str, list[dict[str, Any]]]:
    pending: dict[str, list[dict[str, Any]]] = {}
    for split in ("train", "val", "test"):
        source = json.loads((UIT_ROOT / f"{split}.json").read_text(encoding="utf-8"))
        category = {item["id"]: item["name"] for item in source["categories"]}
        annotations: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for item in source["annotations"]:
            annotations[item["image_id"]].append(item)

        records = []
        for image in sorted(source["images"], key=lambda item: item["file_name"]):
            source_annotations = annotations[image["id"]]
            if not source_annotations or not all(item.get("text") == "a" for item in source_annotations):
                continue

            fields = {name: empty_field() for name in FIELDS}
            grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for item in source_annotations:
                grouped[category[item["category_id"]]].append(item)

            for field_name in FIELDS:
                items = sorted(grouped[field_name], key=lambda item: item["id"])
                if not items:
                    continue
                fields[field_name]["present"] = True
                for index, item in enumerate(items, start=1):
                    x, y, width, height = item["bbox"]
                    box = [int(x), int(y), int(x + width), int(y + height)]
                    fields[field_name]["regions"].append(
                        {
                            "region_id": f"{field_name}-{index}",
                            "bbox": box,
                            "polygon": rectangle_polygon(box),
                            "raw_text": "",
                            "normalized_value": "",
                            "legibility": "unreviewed",
                            "source_annotation_id": item["id"],
                        }
                    )

            record = base_record(
                dataset="UIT-MLReceipts",
                source_split=split,
                image_name=image["file_name"],
                width=int(image["width"]),
                height=int(image["height"]),
                fields=fields,
            )
            records.append(record)
        pending[split] = records
    return pending


def load_mcocr_pending() -> list[dict[str, Any]]:
    image_root = MCOCR_ROOT / "validation" / "images"
    records = []
    for image_path in sorted(path for path in image_root.iterdir() if path.is_file()):
        with Image.open(image_path) as image:
            width, height = image.size
        records.append(
            base_record(
                dataset="MC-OCR",
                source_split="validation",
                image_name=image_path.name,
                width=width,
                height=height,
                fields={name: empty_field() for name in FIELDS},
            )
        )
    return records


def split_evenly(items: list[dict[str, Any]], count: int) -> list[list[dict[str, Any]]]:
    quotient, remainder = divmod(len(items), count)
    result = []
    start = 0
    for index in range(count):
        size = quotient + (1 if index < remainder else 0)
        result.append(items[start : start + size])
        start += size
    return result


def build_assignments() -> dict[str, list[dict[str, Any]]]:
    uit = load_uit_pending()
    mcocr = load_mcocr_pending()

    # Keep UIT source splits intact wherever possible. MC-OCR validation is split in two
    # because it has no source boxes and is materially slower to annotate.
    train_halves = split_evenly(uit["train"], 2)
    test_halves = split_evenly(uit["test"], 2)
    mcocr_halves = split_evenly(mcocr, 2)
    return {
        "member1": train_halves[0],
        "member2": train_halves[1],
        "member3": uit["val"],
        "member4": test_halves[0],
        "member5": test_halves[1],
        "member6": mcocr_halves[0],
        "member7": mcocr_halves[1],
    }


def schema() -> dict[str, Any]:
    region = {
        "type": "object",
        "required": [
            "region_id",
            "bbox",
            "polygon",
            "raw_text",
            "normalized_value",
            "legibility",
        ],
        "properties": {
            "region_id": {"type": "string", "minLength": 1},
            "bbox": {
                "type": "array",
                "description": "[x_min, y_min, x_max, y_max], pixel coordinates",
                "prefixItems": [{"type": "integer"}] * 4,
                "minItems": 4,
                "maxItems": 4,
            },
            "polygon": {
                "type": "array",
                "items": {
                    "type": "array",
                    "prefixItems": [{"type": "integer"}, {"type": "integer"}],
                    "minItems": 2,
                    "maxItems": 2,
                },
                "minItems": 4,
            },
            "raw_text": {"type": "string"},
            "normalized_value": {"type": "string"},
            "legibility": {
                "enum": ["unreviewed", "clear", "partly_unreadable", "unreadable"]
            },
            "source_annotation_id": {"type": ["integer", "null"]},
        },
        "additionalProperties": False,
    }
    field = {
        "type": "object",
        "required": ["present", "verified", "regions"],
        "properties": {
            "present": {"type": ["boolean", "null"]},
            "verified": {"type": "boolean"},
            "regions": {"type": "array", "items": region},
        },
        "additionalProperties": False,
    }
    token = {
        "type": "object",
        "required": [
            "token_id",
            "raw_text",
            "verified_text",
            "confidence",
            "bbox",
            "polygon",
            "field",
            "bio_label",
        ],
        "properties": {
            "token_id": {"type": "integer", "minimum": 0},
            "raw_text": {"type": "string"},
            "verified_text": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "bbox": {
                "type": "array",
                "prefixItems": [{"type": "integer"}] * 4,
                "minItems": 4,
                "maxItems": 4,
            },
            "polygon": {
                "type": "array",
                "items": {
                    "type": "array",
                    "prefixItems": [{"type": "integer"}, {"type": "integer"}],
                    "minItems": 2,
                    "maxItems": 2,
                },
                "minItems": 4,
            },
            "field": {"enum": ["O", *FIELDS]},
            "bio_label": {"type": "string"},
            "region_id": {"type": ["string", "null"]},
            "alignment_overlap": {"type": ["number", "null"]},
        },
        "additionalProperties": False,
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://vietreceiptai.local/schemas/receipt-annotation-1.0.0.json",
        "title": "VietReceiptAI unified receipt annotation",
        "type": "object",
        "required": [
            "schema_version",
            "task_id",
            "dataset",
            "source_split",
            "image_id",
            "image_file",
            "width",
            "height",
            "assignment",
            "ocr",
            "fields",
            "notes",
        ],
        "properties": {
            "schema_version": {"const": "1.0.0"},
            "task_id": {"type": "string"},
            "dataset": {"enum": ["UIT-MLReceipts", "MC-OCR", "SROIE"]},
            "source_split": {"type": "string"},
            "image_id": {"type": "string"},
            "image_file": {"type": "string"},
            "width": {"type": "integer", "minimum": 1},
            "height": {"type": "integer", "minimum": 1},
            "assignment": {
                "type": "object",
                "required": ["member", "status", "reviewer"],
                "properties": {
                    "member": {"type": "string", "pattern": "^member[1-7]$"},
                    "status": {"enum": ["pending", "in_progress", "completed", "needs_review"]},
                    "reviewer": {"type": ["string", "null"]},
                },
                "additionalProperties": False,
            },
            "ocr": {
                "type": "object",
                "required": [
                    "status",
                    "engine",
                    "ocr_version",
                    "language",
                    "runtime_version",
                    "tokens",
                ],
                "properties": {
                    "status": {"enum": ["not_run", "generated", "verified"]},
                    "engine": {"const": "PaddleOCR"},
                    "ocr_version": {"const": "PP-OCRv6"},
                    "language": {"const": "vi"},
                    "runtime_version": {"type": ["string", "null"]},
                    "tokens": {"type": "array", "items": token},
                },
                "additionalProperties": False,
            },
            "fields": {
                "type": "object",
                "required": list(FIELDS),
                "properties": {name: field for name in FIELDS},
                "additionalProperties": False,
            },
            "notes": {"type": "string"},
        },
        "additionalProperties": False,
    }


SCHEMA_GUIDE = """# Schema thống nhất VietReceiptAI 1.0.0

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
"""


ANNOTATION_GUIDE = """# Hướng dẫn annotation VietReceiptAI

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
"""


OCR_GUIDE = """# OCR chung: PaddleOCR PP-OCRv6

Nhóm dùng duy nhất PaddleOCR 3.5.x, pipeline PP-OCRv6 và `lang="vi"`. Model tiếng Việt này
cũng đọc được phần lớn chuỗi Latin/Anh trên hóa đơn. Không dùng OCR web vì khác phiên bản,
khó tái lập và có thể đưa dữ liệu ảnh ra ngoài.

## Môi trường thống nhất

Khuyến nghị Python 3.11 trong môi trường mới. Tại thư mục member:

```bash
python3.11 -m venv .venv-ocr
source .venv-ocr/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-ocr.txt
```

Máy Windows kích hoạt bằng `.venv-ocr\\Scripts\\activate`. Nếu PaddlePaddle không cài được
theo file requirements (đặc biệt với GPU), cài đúng bản PaddlePaddle 3.2.0 theo bộ chọn lệnh
chính thức của PaddlePaddle rồi chạy lại lệnh cài requirements.

## Chạy OCR

```bash
python tools/05_run_paddleocr.py --task-dir . --device cpu
```

Model tải một lần ở lần chạy đầu. Có thể kiểm tra 3 ảnh trước:

```bash
python tools/05_run_paddleocr.py --task-dir . --device cpu --limit 3 --force
```

Nếu có GPU Paddle tương thích, đổi thành `--device gpu:0`. Script giữ nguyên tọa độ ảnh gốc,
ghi OCR vào `annotations.jsonl` và có thể chạy tiếp để bỏ qua ảnh đã OCR.

## OCR không phải ground truth

Phải nhìn ảnh và sửa `verified_text`. `raw_text` là kết quả máy để truy vết; không ghi đè nó.
Sau khi kiểm tra hết token của một ảnh, đặt `ocr.status="verified"`.
"""


ALIGNMENT_GUIDE = """# Token alignment và nhãn BIO

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
"""


ROOT_README = """# Phân công annotation VietReceiptAI

Tổng cộng **2.282 ảnh** cần ground truth bốn trường và OCR đã kiểm tra:

- UIT-MLReceipts: 1.893 ảnh (bbox có sẵn, text đang là placeholder `a`).
- MC-OCR validation: 389 ảnh (chưa có ground truth, cần tạo bbox và text).

Phân công theo độ khó, không chỉ theo số ảnh: member1–5 chỉ làm UIT-MLReceipts;
member6–7 chỉ làm MC-OCR. Không thành viên nào nhận ảnh của cả hai dataset.

`common/` chứa schema và hướng dẫn chuẩn. Mỗi `memberN/` là một gói công việc độc lập
để giao cho thành viên. `assignment_summary.csv` là bảng kiểm soát chung.

Phần MC-OCR `token_kie` còn thiếu transcript là backlog riêng, không nằm trong 2.282 ảnh này.
"""


def source_image(record: dict[str, Any]) -> Path:
    if record["dataset"] == "UIT-MLReceipts":
        return UIT_ROOT / record["source_split"] / Path(record["image_file"]).name
    if record["dataset"] == "MC-OCR":
        return MCOCR_ROOT / "validation" / "images" / Path(record["image_file"]).name
    raise ValueError(record["dataset"])


def member_readme(member: str, records: list[dict[str, Any]]) -> str:
    datasets = sorted({record["dataset"] for record in records})
    splits = sorted({record["source_split"] for record in records})
    scope = (
        "Bbox KIE đã được nạp từ dữ liệu sạch. Kiểm tra/chỉnh bbox, điền text thật và kiểm tra OCR."
        if datasets == ["UIT-MLReceipts"]
        else "Validation chưa có ground truth. Chạy OCR, tạo bbox và text thật cho đủ bốn trường."
    )
    return f"""# Gói công việc {member}

- Dataset duy nhất: **{', '.join(datasets)}**
- Split: **{', '.join(splits)}**
- Số ảnh: **{len(records)}**
- Phạm vi: {scope}

## Các bước

1. Đọc lần lượt `DATASET_SCHEMA.md`, `ANNOTATION_GUIDE.md`, `OCR_GUIDE.md`.
2. Chạy OCR theo `OCR_GUIDE.md` và kiểm tra token trên từng ảnh.
3. Điền/sửa `annotations.jsonl`; không sửa `manifest.csv` hay đổi tên ảnh.
4. Chạy `python tools/06_token_alignment.py --task-dir .`.
5. Sửa mọi lỗi trong `alignment_qc.csv`, kiểm tra lại và nộp toàn bộ thư mục này.

Mỗi dòng JSONL tương ứng một dòng trong manifest qua `task_id`. Lưu file bằng UTF-8.
Không thêm ảnh ngoài gói và không chuyển ảnh cho member khác nếu chưa báo người tổng hợp.
"""


def write_common_files(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    json_dump(root / "annotation_schema.json", schema())
    (root / "DATASET_SCHEMA.md").write_text(SCHEMA_GUIDE, encoding="utf-8")
    (root / "ANNOTATION_GUIDE.md").write_text(ANNOTATION_GUIDE, encoding="utf-8")
    (root / "OCR_GUIDE.md").write_text(OCR_GUIDE, encoding="utf-8")
    (root / "TOKEN_ALIGNMENT.md").write_text(ALIGNMENT_GUIDE, encoding="utf-8")
    (root / "requirements-ocr.txt").write_text(
        "paddleocr>=3.5,<3.6\npaddlepaddle==3.2.0\nPillow>=10,<13\n", encoding="utf-8"
    )


def build_package(member: str, records: list[dict[str, Any]], common: Path) -> dict[str, Any]:
    member_root = OUTPUT_ROOT / member
    image_root = member_root / "images"
    tools_root = member_root / "tools"
    image_root.mkdir(parents=True)
    tools_root.mkdir(parents=True)

    for name in (
        "annotation_schema.json",
        "DATASET_SCHEMA.md",
        "ANNOTATION_GUIDE.md",
        "OCR_GUIDE.md",
        "TOKEN_ALIGNMENT.md",
        "requirements-ocr.txt",
    ):
        shutil.copy2(common / name, member_root / name)
    for source in SOURCE_FILES:
        if not source.exists():
            raise FileNotFoundError(f"Missing required tool: {source}")
        shutil.copy2(source, tools_root / source.name)

    manifest_rows = []
    dataset_counts: dict[str, int] = defaultdict(int)
    split_counts: dict[str, int] = defaultdict(int)
    annotation_path = member_root / "annotations.jsonl"
    with annotation_path.open("w", encoding="utf-8", newline="\n") as annotation_stream:
        for index, record in enumerate(records, start=1):
            task_id = f"{member}-{index:04d}"
            record["task_id"] = task_id
            record["assignment"]["member"] = member
            source = source_image(record)
            destination = image_root / source.name
            if not source.is_file():
                raise FileNotFoundError(source)
            shutil.copy2(source, destination)
            digest = sha256(source)
            regions = sum(len(value["regions"]) for value in record["fields"].values())
            manifest_rows.append(
                {
                    "task_id": task_id,
                    "dataset": record["dataset"],
                    "source_split": record["source_split"],
                    "image_file": record["image_file"],
                    "width": record["width"],
                    "height": record["height"],
                    "prefilled_kie_regions": regions,
                    "sha256": digest,
                }
            )
            dataset_counts[record["dataset"]] += 1
            split_counts[record["source_split"]] += 1
            annotation_stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    with (member_root / "manifest.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(manifest_rows[0]))
        writer.writeheader()
        writer.writerows(manifest_rows)
    (member_root / "README.md").write_text(member_readme(member, records), encoding="utf-8")

    return {
        "member": member,
        "image_count": len(records),
        "dataset": "+".join(sorted(dataset_counts)),
        "source_splits": "+".join(sorted(split_counts)),
        "prefilled_kie_regions": sum(row["prefilled_kie_regions"] for row in manifest_rows),
    }


def audit(assignments: dict[str, list[dict[str, Any]]], summaries: list[dict[str, Any]]) -> None:
    all_records = [record for records in assignments.values() for record in records]
    if len(all_records) != 2282:
        raise RuntimeError(f"Expected 2282 records, found {len(all_records)}")
    if sum(record["dataset"] == "UIT-MLReceipts" for record in all_records) != 1893:
        raise RuntimeError("UIT-MLReceipts pending count changed")
    if sum(record["dataset"] == "MC-OCR" for record in all_records) != 389:
        raise RuntimeError("MC-OCR pending count changed")

    identities = [(record["dataset"], record["source_split"], record["image_id"]) for record in all_records]
    if len(identities) != len(set(identities)):
        raise RuntimeError("An image was assigned more than once")
    for member, records in assignments.items():
        if len({record["dataset"] for record in records}) != 1:
            raise RuntimeError(f"{member} mixes datasets")
        member_root = OUTPUT_ROOT / member
        if len(list((member_root / "images").iterdir())) != len(records):
            raise RuntimeError(f"Image count mismatch in {member}")
        if sum(1 for line in (member_root / "annotations.jsonl").read_text(encoding="utf-8").splitlines() if line) != len(records):
            raise RuntimeError(f"JSONL count mismatch in {member}")
    if sum(item["image_count"] for item in summaries) != 2282:
        raise RuntimeError("Summary total mismatch")


def main() -> None:
    global OUTPUT_ROOT
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing non-empty output directory.",
    )
    args = parser.parse_args()
    OUTPUT_ROOT = args.output.resolve()

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    existing = list(OUTPUT_ROOT.iterdir())
    if existing and not args.force:
        raise SystemExit(
            f"Refusing to replace non-empty {OUTPUT_ROOT}. "
            "Use --force only before annotation starts or choose a new --output directory."
        )
    if args.force:
        for child in existing:
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()

    (OUTPUT_ROOT / "README.md").write_text(ROOT_README, encoding="utf-8")
    common = OUTPUT_ROOT / "common"
    write_common_files(common)
    assignments = build_assignments()
    summaries = [build_package(member, records, common) for member, records in assignments.items()]
    audit(assignments, summaries)

    with (OUTPUT_ROOT / "assignment_summary.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(summaries[0]))
        writer.writeheader()
        writer.writerows(summaries)
    json_dump(
        OUTPUT_ROOT / "build_report.json",
        {
            "schema_version": "1.0.0",
            "total_images": 2282,
            "dataset_counts": {"UIT-MLReceipts": 1893, "MC-OCR": 389},
            "assignment_strategy": "Five UIT-only members and two MC-OCR-only members, weighted by annotation difficulty.",
            "members": summaries,
            "excluded_backlog": {
                "MC-OCR_token_kie": "Blank token transcripts are a separate repair task and are not counted here."
            },
        },
    )
    print(json.dumps({"output": str(OUTPUT_ROOT), "members": summaries}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
