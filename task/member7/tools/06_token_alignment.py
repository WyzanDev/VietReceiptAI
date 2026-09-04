#!/usr/bin/env python3
"""Align verified OCR tokens to KIE regions and assign BIO labels."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


FIELDS = ("SELLER", "ADDRESS", "TIMESTAMP", "TOTAL_COST")


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


def area(box: list[int]) -> int:
    x1, y1, x2, y2 = box
    return max(0, x2 - x1) * max(0, y2 - y1)


def intersection_area(left: list[int], right: list[int]) -> int:
    return max(0, min(left[2], right[2]) - max(left[0], right[0])) * max(
        0, min(left[3], right[3]) - max(left[1], right[1])
    )


def center_inside(token_box: list[int], region_box: list[int]) -> bool:
    x = (token_box[0] + token_box[2]) / 2
    y = (token_box[1] + token_box[3]) / 2
    return region_box[0] <= x <= region_box[2] and region_box[1] <= y <= region_box[3]


def reading_key(token: dict[str, Any]) -> tuple[float, int, int]:
    box = token["bbox"]
    return ((box[1] + box[3]) / 2, box[0], token["token_id"])


def add_qc(
    rows: list[dict[str, Any]],
    record: dict[str, Any],
    level: str,
    code: str,
    detail: str,
) -> None:
    rows.append(
        {
            "task_id": record["task_id"],
            "dataset": record["dataset"],
            "image_file": record["image_file"],
            "level": level,
            "code": code,
            "detail": detail,
        }
    )


def validate_record(record: dict[str, Any], qc: list[dict[str, Any]]) -> None:
    width, height = record["width"], record["height"]
    if record["assignment"]["status"] != "completed":
        add_qc(qc, record, "error", "document_not_completed", record["assignment"]["status"])
    if record["ocr"]["status"] != "verified":
        add_qc(qc, record, "error", "ocr_not_verified", record["ocr"]["status"])
    for field_name in FIELDS:
        field = record["fields"][field_name]
        if field["present"] is None or not field["verified"]:
            add_qc(qc, record, "error", "field_not_verified", field_name)
        if field["present"] is False and field["regions"]:
            add_qc(qc, record, "error", "absent_field_has_regions", field_name)
        if field["present"] is True and not field["regions"]:
            add_qc(qc, record, "error", "present_field_has_no_region", field_name)
        for region in field["regions"]:
            box = region["bbox"]
            if len(box) != 4 or area(box) == 0:
                add_qc(qc, record, "error", "invalid_region_bbox", f"{field_name}:{box}")
            elif not (0 <= box[0] < box[2] <= width and 0 <= box[1] < box[3] <= height):
                add_qc(qc, record, "error", "region_outside_image", f"{field_name}:{box}")
            if region["legibility"] == "unreviewed":
                add_qc(qc, record, "error", "region_not_reviewed", region["region_id"])
            if region["raw_text"].strip().lower() == "a":
                add_qc(qc, record, "error", "placeholder_text", region["region_id"])


def align_record(record: dict[str, Any], threshold: float, qc: list[dict[str, Any]]) -> None:
    validate_record(record, qc)
    candidates = []
    for field_name in FIELDS:
        for region in record["fields"][field_name]["regions"]:
            candidates.append((field_name, region["region_id"], region["bbox"]))

    by_region: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for token in record["ocr"]["tokens"]:
        token["field"] = "O"
        token["bio_label"] = "O"
        token["region_id"] = None
        token["alignment_overlap"] = None
        token_box = token["bbox"]
        token_area = area(token_box)
        if token_area == 0:
            add_qc(qc, record, "error", "invalid_token_bbox", str(token_box))
            continue

        matches = []
        for field_name, region_id, region_box in candidates:
            overlap = intersection_area(token_box, region_box) / token_area
            if overlap >= threshold or center_inside(token_box, region_box):
                matches.append((overlap, field_name, region_id))
        if not matches:
            continue
        matches.sort(reverse=True)
        best_overlap, field_name, region_id = matches[0]
        if len(matches) > 1 and abs(matches[0][0] - matches[1][0]) < 0.05:
            add_qc(
                qc,
                record,
                "warning",
                "ambiguous_token_region",
                f"token={token['token_id']}, choices={matches[:2]}",
            )
        token["field"] = field_name
        token["region_id"] = region_id
        token["alignment_overlap"] = round(best_overlap, 6)
        by_region[(field_name, region_id)].append(token)

    for field_name, region_id, _ in candidates:
        tokens = sorted(by_region[(field_name, region_id)], key=reading_key)
        if not tokens:
            region = next(
                item
                for item in record["fields"][field_name]["regions"]
                if item["region_id"] == region_id
            )
            if region["raw_text"].strip():
                add_qc(qc, record, "warning", "region_without_token", f"{field_name}:{region_id}")
            continue
        for index, token in enumerate(tokens):
            prefix = "B" if index == 0 else "I"
            token["bio_label"] = f"{prefix}-{field_name}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--threshold", type=float, default=0.5)
    args = parser.parse_args()
    if not 0 < args.threshold <= 1:
        raise SystemExit("--threshold must be in (0, 1]")

    task_root = args.task_dir.resolve()
    source = task_root / "annotations.jsonl"
    output = task_root / "aligned_annotations.jsonl"
    qc_path = task_root / "alignment_qc.csv"
    records = load_jsonl(source)
    qc: list[dict[str, Any]] = []
    for record in records:
        align_record(record, args.threshold, qc)

    with output.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    fieldnames = ["task_id", "dataset", "image_file", "level", "code", "detail"]
    with qc_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(qc)

    errors = sum(row["level"] == "error" for row in qc)
    warnings = sum(row["level"] == "warning" for row in qc)
    print(f"Wrote {output}")
    print(f"QC: {errors} error(s), {warnings} warning(s) -> {qc_path}")
    if errors:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
