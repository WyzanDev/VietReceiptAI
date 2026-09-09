#!/usr/bin/env python3
"""Populate VietReceiptAI annotation JSONL files with PaddleOCR tokens."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid JSON at {path}:{line_number}: {error}") from error
    return records


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    temporary.replace(path)


def unwrap_result(result: Any) -> dict[str, Any]:
    data = result.json
    if callable(data):
        data = data()
    if not isinstance(data, dict):
        raise TypeError(f"Unexpected PaddleOCR result type: {type(data)!r}")
    # PaddleOCR/PaddleX releases have used both a direct payload and {"res": payload}.
    if isinstance(data.get("res"), dict):
        data = data["res"]
    return data


def integer_polygon(value: Any) -> list[list[int]]:
    if hasattr(value, "tolist"):
        value = value.tolist()
    return [[int(round(float(x))), int(round(float(y)))] for x, y in value]


def polygon_box(polygon: list[list[int]]) -> list[int]:
    xs = [point[0] for point in polygon]
    ys = [point[1] for point in polygon]
    return [min(xs), min(ys), max(xs), max(ys)]


def result_tokens(result: Any) -> list[dict[str, Any]]:
    data = unwrap_result(result)
    texts = list(data.get("rec_texts", []))
    scores = list(data.get("rec_scores", []))
    polygons = list(data.get("rec_polys", data.get("dt_polys", [])))
    boxes = list(data.get("rec_boxes", []))
    if not (len(texts) == len(scores) == len(polygons)):
        raise ValueError(
            "PaddleOCR returned inconsistent rec_texts/rec_scores/rec_polys lengths: "
            f"{len(texts)}/{len(scores)}/{len(polygons)}"
        )

    tokens = []
    for token_id, (text, score, polygon_value) in enumerate(zip(texts, scores, polygons)):
        polygon = integer_polygon(polygon_value)
        if token_id < len(boxes):
            box_value = boxes[token_id].tolist() if hasattr(boxes[token_id], "tolist") else boxes[token_id]
            box = [int(round(float(number))) for number in box_value]
        else:
            box = polygon_box(polygon)
        tokens.append(
            {
                "token_id": token_id,
                "raw_text": str(text),
                "verified_text": str(text),
                "confidence": float(score),
                "bbox": box,
                "polygon": polygon,
                "field": "O",
                "bio_label": "O",
                "region_id": None,
                "alignment_overlap": None,
            }
        )
    return tokens


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--device", default="cpu", help="cpu, gpu:0, ...")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--force", action="store_true", help="Re-run records that already contain OCR")
    parser.add_argument("--save-every", type=int, default=10)
    args = parser.parse_args()

    task_root = args.task_dir.resolve()
    annotation_path = task_root / "annotations.jsonl"
    if not annotation_path.is_file():
        raise SystemExit(
            "Không tìm thấy annotations.jsonl. Hãy chọn đúng gói dataset/split, "
            "ví dụ --task-dir task/member1/MC-OCR/train; không chọn gốc task/member1."
        )

    try:
        import paddleocr
        from paddleocr import PaddleOCR
    except ImportError as error:
        raise SystemExit(
            "PaddleOCR is not installed. Follow OCR_GUIDE.md using a Python 3.11 environment."
        ) from error

    records = load_jsonl(annotation_path)
    pipeline = PaddleOCR(
        lang="vi",
        ocr_version="PP-OCRv6",
        device=args.device,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )

    processed = 0
    for record in records:
        if not args.force and record["ocr"]["status"] != "not_run" and record["ocr"]["tokens"]:
            continue
        if args.limit is not None and processed >= args.limit:
            break
        image_path = task_root / record["image_file"]
        if not image_path.is_file():
            raise FileNotFoundError(image_path)
        results = list(pipeline.predict(str(image_path)))
        if len(results) != 1:
            raise RuntimeError(f"Expected one OCR result for {image_path}, found {len(results)}")
        record["ocr"].update(
            {
                "status": "generated",
                "engine": "PaddleOCR",
                "ocr_version": "PP-OCRv6",
                "language": "vi",
                "runtime_version": paddleocr.__version__,
                "tokens": result_tokens(results[0]),
            }
        )
        processed += 1
        print(f"[{processed}] {record['task_id']}: {len(record['ocr']['tokens'])} tokens")
        if processed % max(1, args.save_every) == 0:
            write_jsonl(annotation_path, records)
    write_jsonl(annotation_path, records)
    print(f"Saved {processed} OCR result(s) to {annotation_path}")


if __name__ == "__main__":
    main()
