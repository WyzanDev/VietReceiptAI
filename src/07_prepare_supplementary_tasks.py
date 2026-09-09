#!/usr/bin/env python3
"""Build round 2 without touching round-1 annotation work; freeze a global registry."""
from __future__ import annotations

import ast
import csv
import importlib.util
import json
import shutil
from collections import defaultdict
from pathlib import Path

from PIL import Image
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / "task"
ROUND2 = TASK / "round2"
spec = importlib.util.spec_from_file_location("tasks_v1", ROOT / "src/04_prepare_annotation_tasks.py")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
FIELDS = base.FIELDS


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path, records):
    with path.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def region(label, index, xywh, text, annotation_id=None):
    x, y, w, h = xywh
    bbox = [int(x), int(y), int(x + w), int(y + h)]
    return {"region_id": f"{label}-{index}", "bbox": bbox,
            "polygon": base.rectangle_polygon(bbox), "raw_text": text,
            "normalized_value": "", "legibility": "unreviewed",
            "source_annotation_id": annotation_id}


def new_record(dataset, name, fields):
    path = source_path(dataset, "train", name)
    with Image.open(path) as im:
        width, height = im.size
    return base.base_record(dataset=dataset, source_split="train", image_name=name,
                            width=width, height=height, fields=fields)


def source_path(dataset, split, name):
    if dataset == "UIT-MLReceipts":
        return ROOT / "dataset/UIT-MLReceipts/Clean" / split / name
    if dataset == "MC-OCR":
        return ROOT / "dataset/MC-OCR/clean" / split / "images" / name
    raise ValueError(dataset)


def load_uit():
    data = json.loads((ROOT / "dataset/UIT-MLReceipts/Clean/train.json").read_text())
    labels = {c["id"]: c["name"] for c in data["categories"]}
    by_image = defaultdict(list)
    for annotation in data["annotations"]:
        by_image[annotation["image_id"]].append(annotation)
    result = []
    for im in sorted(data["images"], key=lambda r: r["file_name"]):
        annotations = by_image[im["id"]]
        if not annotations or all(a.get("text") == "a" for a in annotations):
            continue
        if any(a.get("text") == "a" for a in annotations):
            raise ValueError(f"Unexpected mixed transcript record {im['file_name']}")
        fields = {f: base.empty_field() for f in FIELDS}
        for a in annotations:
            label = labels[a["category_id"]]
            field = fields[label]
            field["present"] = True
            field["regions"].append(region(label, len(field["regions"])+1, a["bbox"], a["text"], a["id"]))
        result.append(new_record("UIT-MLReceipts", im["file_name"], fields))
    if len(result) != 249:
        raise ValueError(f"UIT selection changed: {len(result)}")
    return result


def load_mcocr():
    with (ROOT / "dataset/MC-OCR/clean/train/annotations.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = sorted(csv.DictReader(stream), key=lambda r: r["img_id"])
    result = []
    for row in rows:
        polygons = ast.literal_eval(row["anno_polygons"])
        texts = row["anno_texts"].split("|||")
        labels = row["anno_labels"].split("|||")
        if not len(polygons) == len(texts) == len(labels) == int(row["anno_num"]):
            raise ValueError(f"Malformed annotations: {row['img_id']}")
        fields = {f: base.empty_field() for f in FIELDS}
        for index, (poly, text, label) in enumerate(zip(polygons, texts, labels)):
            field = fields[label]
            field["present"] = True
            # Source segmentation uses fractional vertices. Preserve them exactly;
            # the shared schema supports real-valued polygon coordinates.
            item = region(label, len(field["regions"])+1, poly["bbox"], text, index)
            segmentation = poly.get("segmentation", [])
            if segmentation:
                if any(len(coords) % 2 or len(coords)<6 for coords in segmentation):
                    raise ValueError(f"Unexpected segmentation: {row['img_id']}")
                item["source_segmentation"] = segmentation
                if len(segmentation)==1 and len(segmentation[0])>=8:
                    coords = segmentation[0]
                    item["polygon"] = [coords[i:i+2] for i in range(0,len(coords),2)]
            field["regions"].append(item)
        record = new_record("MC-OCR", row["img_id"], fields)
        multipart = [r['region_id'] for f in fields.values() for r in f['regions']
                     if len(r.get('source_segmentation',[]))>1]
        if multipart:
            record['notes'] = ('Nguồn có nhiều polygon chung một transcript; polygon làm việc tạm dùng bbox nguồn. '
                               'Xem source_segmentation và tách vùng/text theo ảnh khi verify: '+', '.join(multipart))
        result.append(record)
    if len(result) != 1100:
        raise ValueError(f"MC-OCR selection changed: {len(result)}")
    return result


def registry_row(record, package, round_name):
    image = package / record["image_file"]
    original = source_path(record["dataset"], record["source_split"], image.name)
    image_hash = base.sha256(image)
    if image_hash != base.sha256(original):
        raise ValueError(f"Image changed relative to Clean: {image}")
    with Image.open(image) as im:
        if im.size != (record["width"], record["height"]):
            raise ValueError(f"Image dimension mismatch: {image}")
    return {"round": round_name, "task_id": record["task_id"],
            "member": record["assignment"]["member"], "dataset": record["dataset"],
            "source_split": record["source_split"], "image_id": record["image_id"],
            "image_file": record["image_file"], "width": record["width"], "height": record["height"],
            "package": package.relative_to(TASK).as_posix(),
            "source_image": original.relative_to(ROOT).as_posix(), "sha256": image_hash}


def package_readme(member, dataset, count):
    return f'''# Đợt 2 — {member} — {dataset} / train

Số ảnh: **{count}**. Giữ nguyên split **train** cho mọi ảnh trong gói này.
Nhãn bốn trường đã được nạp từ Clean làm bản nháp; chưa phải nhãn nhóm đã verify.
Thực hiện OCR và verify **toàn trang**, kiểm tra bbox/text/nhãn bốn trường, rồi token alignment.

1. Đọc `ANNOTATION_GUIDE.md`, `DATASET_SCHEMA.md`, `OCR_GUIDE.md`.
2. Kích hoạt môi trường OCR, mở terminal ngay tại thư mục chứa README này.
3. Cài `python -m pip install -r requirements-ocr.txt` (PaddleOCR 3.7.0).
4. Chạy thử `python tools/05_run_paddleocr.py --task-dir . --device cpu --limit 3`.
5. Chạy toàn bộ bằng cùng lệnh, bỏ `--limit 3`. Không dùng `--force` trên dữ liệu đã verify.
6. Sửa `annotations.jsonl`: giữ text hóa đơn nguyên văn, không chuẩn hóa;
   mọi `normalized_value` để `""`. Kiểm tra các token ngoài bốn trường, chúng nhận nhãn `O`.
7. Khi đã kiểm tra xong, đặt trạng thái theo hướng dẫn và chạy
   `python tools/06_token_alignment.py --task-dir .`.
8. Nộp `annotations.jsonl`, `aligned_annotations.jsonl`, `alignment_qc.csv` đúng thư mục này.

`source_annotations.jsonl` là bản nháp ban đầu để đối chiếu; không chỉnh sửa.
Giữ nguyên ảnh, manifest, task_id, image_id, dataset, source_split và kích thước ảnh.
Ảnh có text nguồn nhãn như “Ngày”, “Giờ”, “Tổng cộng” vẫn phải được xem lại:
giá trị KIE chỉ chọn phần giá trị theo quy ước chung, chữ nhãn vẫn giữ trong OCR toàn trang.

Mỗi dataset có một gói độc lập. Không gộp file bằng cách chép đè theo tên ảnh.
Xem `task/MERGE_GUIDE.md` để đối chiếu sổ đăng ký khi nhóm nhận kết quả.
'''


def main():
    registry_path = TASK / "assignment_registry.jsonl"
    if registry_path.exists() or (ROUND2.exists() and any(p.name != "README.md" for p in ROUND2.iterdir())):
        raise SystemExit("Refusing to overwrite round2 or its assignment registry. Keep existing member work.")
    schema = json.loads((TASK / "common/annotation_schema.json").read_text())
    validator = Draft202012Validator(schema)
    registry = []
    for member in range(1,8):
        package = TASK / f"member{member}"
        with (package / "manifest.csv").open(encoding="utf-8", newline="") as stream:
            manifest = {r["task_id"]: r for r in csv.DictReader(stream)}
        for record in read_jsonl(package / "annotations.jsonl"):
            entry = registry_row(record, package, "round1")
            source = manifest.pop(record["task_id"])
            for key in ("dataset", "source_split", "image_file", "sha256"):
                if source[key] != entry[key]:
                    raise ValueError(f"Round-1 manifest mismatch: {record['task_id']} {key}")
            registry.append(entry)
        if manifest:
            raise ValueError(f"Missing round-1 records in {package}")
    mc_chunks = base.split_evenly(load_mcocr(),8)
    plans = [(f"member{i+1}","MC-OCR",chunk) for i,chunk in enumerate(mc_chunks)]
    plans.append(("member8","UIT-MLReceipts",load_uit()))
    old_keys = {(r["dataset"],r["source_split"],r["image_id"]) for r in registry}
    new_keys = [(r["dataset"],r["source_split"],r["image_id"]) for _,_,rs in plans for r in rs]
    if len(set(new_keys))!=1349 or old_keys.intersection(new_keys) or len(registry)!=2282:
        raise ValueError("Unexpected assignment overlap or coverage")
    summaries = []
    for member,dataset,records in plans:
        package = ROUND2 / member / dataset / "train"
        (package / "images").mkdir(parents=True)
        (package / "tools").mkdir()
        for path in (TASK / "common").iterdir():
            if path.is_file():
                shutil.copy2(path, package / path.name)
        for name in ("05_run_paddleocr.py","06_token_alignment.py"):
            shutil.copy2(ROOT / "src" / name, package / "tools" / name)
        rows = []
        for record in records:
            record["task_id"] = f"r2-{member}-{dataset}-train-{record['image_id']}"
            record["assignment"]["member"] = member
            validator.validate(record)
            original = source_path(dataset,"train",Path(record["image_file"]).name)
            shutil.copy2(original,package / record["image_file"])
            row = registry_row(record,package,"round2")
            rows.append(row)
            registry.append(row)
        write_jsonl(package / "annotations.jsonl",records)
        write_jsonl(package / "source_annotations.jsonl",records)
        with (package / "manifest.csv").open("w",encoding="utf-8",newline="") as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]))
            writer.writeheader(); writer.writerows(rows)
        (package / "README.md").write_text(package_readme(member,dataset,len(records)),encoding="utf-8")
        summaries.append({"member":member,"dataset":dataset,"source_split":"train",
                          "images":len(records),"package":package.relative_to(TASK).as_posix()})
    hashes = defaultdict(list)
    for row in registry:
        hashes[row["sha256"]].append(row["task_id"])
    duplicates = [v for v in hashes.values() if len(v)>1]
    if duplicates:
        raise ValueError(f"Exact duplicate images detected; review before release: {duplicates[:5]}")
    expected = set()
    for dataset,splits in (("UIT-MLReceipts",("train","val","test")),("MC-OCR",("train","validation"))):
        for split in splits:
            folder=source_path(dataset,split,"placeholder").parent
            expected.update((dataset,split,p.stem) for p in folder.glob("*.jpg"))
    observed={(r["dataset"],r["source_split"],r["image_id"]) for r in registry}
    if expected!=observed:
        raise ValueError("Assignment coverage does not match both Clean datasets")
    write_jsonl(registry_path,registry)
    with (ROUND2 / "assignment_summary.csv").open("w",encoding="utf-8",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=list(summaries[0]))
        writer.writeheader(); writer.writerows(summaries)
    for i in range(1,9):
        own=[r for r in summaries if r["member"]==f"member{i}"]
        lines=[f"# Member{i} — đợt bổ sung", "", "Đây là phần bổ sung; phần đợt 1 vẫn giữ nguyên.", ""]
        for row in own:
            relative=f"{row['dataset']}/train"
            lines.append(f"- [{row['dataset']} / train]({relative}/README.md): {row['images']} ảnh; chạy OCR/alignment tại `{relative}/`.")
        lines.extend(["", "Không chuẩn hóa text. Không trộn ảnh/split giữa các gói.","Không đưa ảnh val/test đã làm ở đợt 1 vào train của đợt này.",""])
        (ROUND2 / f"member{i}" / "README.md").write_text("\n".join(lines),encoding="utf-8")
    report={"round":"round2","new_images":1349,"all_rounds_images":3631,
            "new_dataset_counts":{"UIT-MLReceipts":249,"MC-OCR":1100},"packages":summaries,
            "checks":{"disjoint_from_round1":True,"complete_clean_coverage":True,
                      "duplicate_byte_hash_groups":0,"source_image_hashes_match":True},
            "leakage_limit":"Byte-identical duplicates checked. This does not rule out near duplicates or repeated receipts photographed differently.",
            "text_policy":"verbatim; normalized_value is empty", "ocr_run":False}
    base.json_dump(ROUND2 / "build_report.json",report)
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
