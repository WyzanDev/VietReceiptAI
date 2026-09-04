#!/usr/bin/env python3
"""Build a normalized, deduplicated MC-OCR dataset from dataset/MC-OCR/original."""

from __future__ import annotations

import ast
import csv
import hashlib
import json
import shutil
from collections import defaultdict
from pathlib import Path

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET_ROOT = PROJECT_ROOT / "dataset" / "MC-OCR"
SOURCE_ROOT = DATASET_ROOT / "original"
DESTINATION_ROOT = DATASET_ROOT / "clean"
BUILD_ROOT = DATASET_ROOT / ".clean_building"

TRAIN_IMAGE_ROOT = SOURCE_ROOT / "train_images" / "train_images"
VALIDATION_IMAGE_ROOT = SOURCE_ROOT / "val_images" / "val_images"
TRAIN_CSV = SOURCE_ROOT / "mcocr_train_df.csv"
VALIDATION_TEMPLATE_CSV = SOURCE_ROOT / "mcocr_val_sample_df.csv"
RECOGNITION_CROP_ROOT = (
    SOURCE_ROOT / "text_recognition_mcocr_data" / "text_recognition_mcocr_data"
)
RECOGNITION_TRAIN_MANIFEST = SOURCE_ROOT / "text_recognition_train_data.txt"
RECOGNITION_VALIDATION_MANIFEST = SOURCE_ROOT / "text_recognition_val_data.txt"
TOKEN_KIE_ROOT = SOURCE_ROOT / "kie_data" / "kie_data"
TOKEN_KIE_IMAGE_ROOT = TOKEN_KIE_ROOT / "images"
TOKEN_KIE_ANNOTATION_ROOT = TOKEN_KIE_ROOT / "boxes_and_transcripts"

REQUIRED_LABELS = {"SELLER", "ADDRESS", "TIMESTAMP", "TOTAL_COST"}
ZERO_ANNOTATION_REMOVALS = {
    "mcocr_public_145014iwhec.jpg": "Severe motion blur; no reliable source annotation.",
    "mcocr_public_145014jndnz.jpg": "Rotated receipt with no trusted source annotation; excluded instead of fabricating labels.",
}
KNOWN_TOKEN_KIE_MISSING = {
    "mcocr_public_145013uqtmx",
    "mcocr_public_145014iwhec",
    "mcocr_public_145014jndnz",
    "mcocr_public_145014mwhyh",
}


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_safe_target() -> None:
    required = (
        TRAIN_IMAGE_ROOT,
        VALIDATION_IMAGE_ROOT,
        TRAIN_CSV,
        VALIDATION_TEMPLATE_CSV,
        RECOGNITION_CROP_ROOT,
        RECOGNITION_TRAIN_MANIFEST,
        RECOGNITION_VALIDATION_MANIFEST,
        TOKEN_KIE_IMAGE_ROOT,
        TOKEN_KIE_ANNOTATION_ROOT,
    )
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing MC-OCR source paths: {missing}")
    if BUILD_ROOT.exists():
        raise RuntimeError(f"Temporary build directory already exists: {BUILD_ROOT}")
    if DESTINATION_ROOT.exists() and any(DESTINATION_ROOT.iterdir()):
        raise RuntimeError(f"Refusing to overwrite non-empty destination: {DESTINATION_ROOT}")


def load_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, value: object) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def split_field(value: str) -> list[str]:
    return value.split("|||") if value else []


def annotation_score(row: dict[str, str]) -> tuple[int, int, int, float]:
    """Prefer label coverage, more annotated regions/text, then source quality."""
    labels = ["TOTAL_COST" if item == "TOTAL_TOTAL_COST" else item for item in split_field(row["anno_labels"])]
    texts = split_field(row["anno_texts"])
    coverage = len(set(labels) & REQUIRED_LABELS)
    annotation_count = int(row["anno_num"])
    transcript_characters = sum(len(item.strip()) for item in texts)
    return coverage, annotation_count, transcript_characters, float(row["anno_image_quality"])


def load_recognition_manifest(path: Path) -> list[tuple[str, str]]:
    entries = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if "\t" not in line:
            raise ValueError(f"Malformed recognition manifest line {path}:{line_number}")
        entries.append(tuple(line.split("\t", 1)))
    return entries


def parent_receipt(crop_name: str) -> str:
    return crop_name.rsplit("_", 1)[0] + ".jpg"


def image_hash_groups(paths: dict[str, Path]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for name, path in paths.items():
        groups[sha256_file(path)].append(name)
    return groups


def create_directories() -> None:
    for relative in (
        "train/images",
        "validation/images",
        "recognition/images",
        "token_kie/images",
        "token_kie/annotations",
        "review",
    ):
        (BUILD_ROOT / relative).mkdir(parents=True, exist_ok=False)


def audit_main_annotation(row: dict[str, str], image_path: Path) -> None:
    polygons = ast.literal_eval(row["anno_polygons"])
    texts = split_field(row["anno_texts"])
    labels = split_field(row["anno_labels"])
    expected = int(row["anno_num"])
    if not (len(polygons) == len(texts) == len(labels) == expected):
        raise ValueError(f"Annotation length mismatch for {row['img_id']}")
    with Image.open(image_path) as image:
        actual_size = image.size
    for polygon, text, label in zip(polygons, texts, labels):
        if not text.strip():
            raise ValueError(f"Empty transcript in {row['img_id']}")
        if label not in REQUIRED_LABELS:
            raise ValueError(f"Unexpected label {label!r} in {row['img_id']}")
        bbox = polygon["bbox"]
        x, y, width, height = bbox
        if width <= 0 or height <= 0:
            raise ValueError(f"Degenerate bbox in {row['img_id']}: {bbox}")
        if x < 0 or y < 0 or x + width > actual_size[0] or y + height > actual_size[1]:
            raise ValueError(f"Out-of-bounds bbox in {row['img_id']}: {bbox}")
        if (polygon["width"], polygon["height"]) != actual_size:
            raise ValueError(f"Image-size mismatch in {row['img_id']}")


def build() -> dict:
    ensure_safe_target()
    fieldnames, train_rows = load_csv(TRAIN_CSV)
    _, validation_template_rows = load_csv(VALIDATION_TEMPLATE_CSV)
    train_row_by_name = {row["img_id"]: row for row in train_rows}
    validation_order = {
        row["img_id"]: index for index, row in enumerate(validation_template_rows)
    }

    train_images = {
        path.name: path for path in TRAIN_IMAGE_ROOT.glob("*.jpg")
    }
    validation_images = {
        path.name: path for path in VALIDATION_IMAGE_ROOT.glob("*.jpg")
    }
    if len(train_images) != 1155 or set(train_images) != set(train_row_by_name):
        raise RuntimeError("Expected exactly 1,155 paired train images/CSV rows.")
    if len(validation_images) != 391 or set(validation_images) != set(validation_order):
        raise RuntimeError("Expected exactly 391 validation images/template rows.")

    recognition_train = load_recognition_manifest(RECOGNITION_TRAIN_MANIFEST)
    recognition_validation = load_recognition_manifest(RECOGNITION_VALIDATION_MANIFEST)
    recognition_train_receipts = {parent_receipt(name) for name, _ in recognition_train}
    recognition_validation_receipts = {
        parent_receipt(name) for name, _ in recognition_validation
    }
    if recognition_train_receipts & recognition_validation_receipts:
        raise RuntimeError("Original recognition manifests share receipt stems unexpectedly.")

    train_hash_groups = image_hash_groups(train_images)
    validation_hash_groups = image_hash_groups(validation_images)
    cross_hashes = set(train_hash_groups) & set(validation_hash_groups)
    if len([items for items in train_hash_groups.values() if len(items) > 1]) != 31:
        raise RuntimeError("Expected 31 duplicate groups inside train.")
    if sum(len(items) - 1 for items in train_hash_groups.values()) != 33:
        raise RuntimeError("Expected 33 redundant train image files.")
    if len([items for items in validation_hash_groups.values() if len(items) > 1]) != 2:
        raise RuntimeError("Expected two duplicate groups inside validation.")
    if len(cross_hashes) != 20:
        raise RuntimeError("Expected 20 train-validation image leaks.")

    report: dict[str, object] = {
        "source": "original",
        "destination": "clean",
        "selection_policy": (
            "For duplicate train receipts, keep a recognition-validation member when a group "
            "crosses the recognition split; otherwise maximize label coverage, annotation count, "
            "transcript length, then annotation image-quality score."
        ),
        "removed_train_duplicates": [],
        "removed_validation_duplicates": [],
        "removed_train_validation_leaks": [],
        "removed_zero_annotation_receipts": [],
        "label_corrections": [],
        "token_kie_exclusions": [],
        "excluded_derived_sources": [
            "data0.7",
            "data0_or_180",
            "dataset/text_detector (duplicate of text_detector/text_detector)",
            "preprocessor",
            "rotation_corrector",
            "rotation_corrector_kie",
            "text_detector",
            "visualize_imgs",
            "post_dict.pkl and pre_dict.pkl",
            "results.csv (identical placeholder submission template)",
        ],
    }

    removed_train_duplicates: set[str] = set()
    for digest, names in sorted(train_hash_groups.items()):
        if len(names) <= 1:
            continue
        candidates = sorted(names)
        validation_side = [
            name for name in candidates if name in recognition_validation_receipts
        ]
        train_side = [name for name in candidates if name in recognition_train_receipts]
        candidate_pool = validation_side if validation_side and train_side else candidates
        kept = max(
            candidate_pool,
            key=lambda name: (*annotation_score(train_row_by_name[name]), name),
        )
        removed = sorted(set(candidates) - {kept})
        removed_train_duplicates.update(removed)
        report["removed_train_duplicates"].append(
            {
                "sha256": digest,
                "kept": kept,
                "removed": removed,
                "recognition_split_crossing": bool(validation_side and train_side),
                "kept_score": list(annotation_score(train_row_by_name[kept])),
            }
        )

    removed_validation_duplicates: set[str] = set()
    for digest, names in sorted(validation_hash_groups.items()):
        if len(names) <= 1:
            continue
        kept = min(names, key=lambda name: validation_order[name])
        removed = sorted(set(names) - {kept})
        removed_validation_duplicates.update(removed)
        report["removed_validation_duplicates"].append(
            {"sha256": digest, "kept": kept, "removed": removed}
        )

    removed_train_validation_leaks = {
        name for digest in cross_hashes for name in train_hash_groups[digest]
    }
    for digest in sorted(cross_hashes):
        report["removed_train_validation_leaks"].append(
            {
                "sha256": digest,
                "removed_from_train": sorted(train_hash_groups[digest]),
                "kept_in_validation": sorted(validation_hash_groups[digest]),
            }
        )

    for name, reason in ZERO_ANNOTATION_REMOVALS.items():
        row = train_row_by_name[name]
        if int(row["anno_num"]) != 0:
            raise RuntimeError(f"Expected zero annotations for {name}")
        report["removed_zero_annotation_receipts"].append(
            {"file": name, "reason": reason}
        )

    removed_train = (
        removed_train_duplicates
        | removed_train_validation_leaks
        | set(ZERO_ANNOTATION_REMOVALS)
    )
    retained_train_names = sorted(set(train_images) - removed_train)
    retained_validation_names = sorted(
        set(validation_images) - removed_validation_duplicates,
        key=lambda name: validation_order[name],
    )

    create_directories()

    clean_train_rows = []
    for name in retained_train_names:
        row = dict(train_row_by_name[name])
        labels = split_field(row["anno_labels"])
        corrected_labels = [
            "TOTAL_COST" if label == "TOTAL_TOTAL_COST" else label for label in labels
        ]
        if corrected_labels != labels:
            report["label_corrections"].append(
                {
                    "file": name,
                    "from": labels,
                    "to": corrected_labels,
                }
            )
            row["anno_labels"] = "|||".join(corrected_labels)
        audit_main_annotation(row, train_images[name])
        shutil.copy2(train_images[name], BUILD_ROOT / "train" / "images" / name)
        clean_train_rows.append(row)
    write_csv(BUILD_ROOT / "train" / "annotations.csv", fieldnames, clean_train_rows)

    validation_pending_rows = []
    for name in retained_validation_names:
        shutil.copy2(
            validation_images[name], BUILD_ROOT / "validation" / "images" / name
        )
        validation_pending_rows.append(
            {
                "img_id": name,
                "annotation_status": "pending_ocr_and_human_verification",
                "anno_image_quality": "",
                "anno_texts": "",
            }
        )
    write_csv(
        BUILD_ROOT / "validation" / "annotations_pending.csv",
        ["img_id", "annotation_status", "anno_image_quality", "anno_texts"],
        validation_pending_rows,
    )

    clean_recognition_train = [
        entry
        for entry in recognition_train
        if parent_receipt(entry[0]) in set(retained_train_names)
    ]
    clean_recognition_validation = [
        entry
        for entry in recognition_validation
        if parent_receipt(entry[0]) in set(retained_train_names)
    ]
    for filename, entries in (
        ("train.tsv", clean_recognition_train),
        ("validation.tsv", clean_recognition_validation),
    ):
        (BUILD_ROOT / "recognition" / filename).write_text(
            "".join(f"{name}\t{text}\n" for name, text in entries), encoding="utf-8"
        )
    recognition_crop_names = {
        name for name, _ in clean_recognition_train + clean_recognition_validation
    }
    for name in sorted(recognition_crop_names):
        source = RECOGNITION_CROP_ROOT / name
        if not source.is_file():
            raise FileNotFoundError(f"Missing recognition crop: {source}")
        shutil.copy2(source, BUILD_ROOT / "recognition" / "images" / name)

    source_token_images = {
        path.stem: path for path in TOKEN_KIE_IMAGE_ROOT.glob("*.jpg")
    }
    source_token_annotations = {
        path.stem: path for path in TOKEN_KIE_ANNOTATION_ROOT.glob("*.tsv")
    }
    actual_missing = set(source_token_images) - set(source_token_annotations)
    if actual_missing != KNOWN_TOKEN_KIE_MISSING:
        raise RuntimeError(f"Unexpected token-KIE missing set: {sorted(actual_missing)}")

    retained_train_stems = {Path(name).stem for name in retained_train_names}
    token_kie_stems = sorted(retained_train_stems & set(source_token_annotations))
    token_kie_missing_after_cleaning = sorted(
        retained_train_stems - set(source_token_annotations)
    )
    if token_kie_missing_after_cleaning != [
        "mcocr_public_145013uqtmx",
        "mcocr_public_145014mwhyh",
    ]:
        raise RuntimeError(
            "Unexpected retained receipts without token-KIE TSV: "
            f"{token_kie_missing_after_cleaning}"
        )
    for stem in token_kie_missing_after_cleaning:
        report["token_kie_exclusions"].append(
            {
                "file": f"{stem}.jpg",
                "reason": (
                    "Receipt-level fields remain available in train/annotations.csv, but the "
                    "source lacks full token OCR/OTHER annotations; excluded from token_kie "
                    "instead of generating incomplete ground truth."
                ),
            }
        )
    (BUILD_ROOT / "review" / "token_kie_missing_annotations.txt").write_text(
        "\n".join(f"{stem}.jpg" for stem in token_kie_missing_after_cleaning) + "\n",
        encoding="utf-8",
    )

    token_image_list = []
    blank_token_transcripts = 0
    blank_target_transcripts = 0
    token_lines = 0
    for index, stem in enumerate(token_kie_stems, start=1):
        shutil.copy2(
            source_token_images[stem], BUILD_ROOT / "token_kie" / "images" / f"{stem}.jpg"
        )
        annotation_source = source_token_annotations[stem]
        annotation_text = annotation_source.read_text(encoding="utf-8-sig")
        for line_number, line in enumerate(annotation_text.splitlines(), start=1):
            left, label = line.rsplit(",", 1)
            parts = left.split(",", 9)
            if len(parts) != 10:
                raise ValueError(f"Malformed token KIE line {annotation_source}:{line_number}")
            transcript = parts[9]
            token_lines += 1
            if not transcript.strip():
                blank_token_transcripts += 1
                if label != "OTHER":
                    blank_target_transcripts += 1
        (BUILD_ROOT / "token_kie" / "annotations" / f"{stem}.tsv").write_text(
            annotation_text, encoding="utf-8"
        )
        token_image_list.append(
            {"id": index, "document_type": "receipt", "file_name": f"{stem}.jpg"}
        )
    write_csv(
        BUILD_ROOT / "token_kie" / "image_list.csv",
        ["id", "document_type", "file_name"],
        token_image_list,
    )

    report["counts"] = {
        "train_images_before": 1155,
        "train_duplicate_files_removed": len(removed_train_duplicates),
        "train_validation_leaks_removed_from_train": len(
            removed_train_validation_leaks
        ),
        "zero_annotation_train_images_removed": len(ZERO_ANNOTATION_REMOVALS),
        "train_images_after": len(retained_train_names),
        "validation_images_before": 391,
        "validation_duplicate_files_removed": len(removed_validation_duplicates),
        "validation_images_after": len(retained_validation_names),
        "recognition_train_crops_after": len(clean_recognition_train),
        "recognition_validation_crops_after": len(clean_recognition_validation),
        "recognition_crop_images_after": len(recognition_crop_names),
        "token_kie_documents_after": len(token_kie_stems),
        "token_kie_lines_after": token_lines,
        "token_kie_blank_transcripts_preserved": blank_token_transcripts,
        "token_kie_blank_target_transcripts_preserved": blank_target_transcripts,
    }

    write_json(BUILD_ROOT / "cleaning_report.json", report)
    (BUILD_ROOT / "README.md").write_text(
        "# MC-OCR Clean\n\n"
        "Generated from `../original` by `src/03_clean_mcocr.py`.\n\n"
        "- `train/images`: deduplicated, labeled receipt images\n"
        "- `train/annotations.csv`: bbox, transcript, and four-field labels\n"
        "- `validation/images`: deduplicated images awaiting OCR/human annotation\n"
        "- `validation/annotations_pending.csv`: explicit pending-annotation manifest\n"
        "- `recognition/images`: cropped text regions referenced by the two TSV manifests\n"
        "- `token_kie`: processed images and available full-token annotations\n"
        "- `review`: retained receipt-level samples missing token-KIE TSV\n"
        "- `cleaning_report.json`: full provenance and removal decisions\n\n"
        "Derived/duplicated pipeline folders are intentionally not copied. Token-KIE blank "
        "transcripts are preserved because automatically deleting them would discard labeled "
        "regions; re-OCR and human verification are still required for that optional branch.\n",
        encoding="utf-8",
    )

    if DESTINATION_ROOT.exists():
        DESTINATION_ROOT.rmdir()
    BUILD_ROOT.rename(DESTINATION_ROOT)
    return report


if __name__ == "__main__":
    result = build()
    print(json.dumps(result["counts"], ensure_ascii=False, indent=2))
