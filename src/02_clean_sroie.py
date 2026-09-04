#!/usr/bin/env python3
"""Build a normalized and audited SROIE dataset from dataset/SROIE/Original."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections import defaultdict
from pathlib import Path

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET_ROOT = PROJECT_ROOT / "dataset" / "SROIE"
SOURCE_ROOT = DATASET_ROOT / "Original"
DESTINATION_ROOT = DATASET_ROOT / "Clean"
BUILD_ROOT = DATASET_ROOT / ".Clean_building"

TRAIN_OCR_ROOT = SOURCE_ROOT / "0325updated.task1train(626p)"
TRAIN_KIE_ROOT = SOURCE_ROOT / "0325updated.task2train(626p)"
TEST_IMAGE_ROOT = SOURCE_ROOT / "task1&2_test(361p)"
TEST_OCR_ROOT = SOURCE_ROOT / "text.task1&2-test（361p)"
TASK3_IMAGE_ROOT = SOURCE_ROOT / "task3-test 347p) -" / "task3-test（347p)"

VARIANT_SUFFIX = re.compile(r"\(\d+\)$")

# Keep the more conventional/canonical filename for each exact-image duplicate.
TRAIN_DUPLICATES = (
    ("X51005453804", "X51009453804"),
    ("X51005301661", "X51005303661"),
    ("X51005268262", "X51005301659"),
    ("X51006401723", "X51007135037"),
    ("X51005453801", "X51009453801"),
)
TEST_DUPLICATES = (
    ("X51005447842", "X51009447842"),
    ("X51005684949", "X510056849111"),
    ("X51005268275", "X51005301666"),
)

# The test copy is retained; the matching training record is removed.
TRAIN_TEST_LEAKS = (
    ("X51006008095", "X51009008095"),
    ("X51006332575", "X51006328967"),
    ("X51005453729", "X51009453729"),
    ("X51007135247", "X51006401853"),
    ("X51006008091", "X51009008091"),
    ("X51006328913", "X51006329388"),
    ("X51005568881", "X51009568881"),
    ("X51006329399", "X51006328937"),
)

MISSING_TEST_IMAGE = "X51006619570"
SPECIAL_ENCODING_FILE = "X51006619503.txt"
DEGENERATE_BBOX_FILE = "X51006008092.txt"
DEGENERATE_BBOX_TEXT = "TOTAL RM"
DEGENERATE_BBOX_OLD = [144, 1398, 145, 1398, 145, 1398, 144, 1398]
DEGENERATE_BBOX_NEW = [43, 1323, 185, 1323, 185, 1355, 43, 1355]


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def primary_files(directory: Path, suffix: str) -> dict[str, Path]:
    return {
        path.stem: path
        for path in directory.glob(f"*{suffix}")
        if not VARIANT_SUFFIX.search(path.stem)
    }


def read_json(path: Path) -> dict:
    with path.open(encoding="utf-8-sig") as handle:
        return json.load(handle)


def write_json(path: Path, value: object) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def verify_exact_pair(first: Path, second: Path) -> str:
    first_hash = sha256_file(first)
    second_hash = sha256_file(second)
    if first_hash != second_hash:
        raise RuntimeError(f"Expected exact duplicates differ: {first} and {second}")
    return first_hash


def ensure_safe_build_target() -> None:
    required = (
        TRAIN_OCR_ROOT,
        TRAIN_KIE_ROOT,
        TEST_IMAGE_ROOT,
        TEST_OCR_ROOT,
        TASK3_IMAGE_ROOT,
    )
    missing = [str(path) for path in required if not path.is_dir()]
    if missing:
        raise FileNotFoundError(f"Missing source directories: {missing}")
    if BUILD_ROOT.exists():
        raise RuntimeError(f"Temporary build directory already exists: {BUILD_ROOT}")
    if DESTINATION_ROOT.exists() and any(DESTINATION_ROOT.iterdir()):
        raise RuntimeError(f"Refusing to overwrite non-empty destination: {DESTINATION_ROOT}")


def decode_ocr(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    if path.name == SPECIAL_ENCODING_FILE:
        return raw.decode("gb18030"), "gb18030"
    return raw.decode("utf-8-sig"), "utf-8-sig"


def normalize_ocr(
    source: Path,
    destination: Path,
    image_size: tuple[int, int],
    split: str,
    changes: list[dict],
) -> int:
    text, source_encoding = decode_ocr(source)
    width, height = image_size
    output_lines = []

    if source_encoding != "utf-8-sig":
        changes.append(
            {
                "type": "encoding",
                "split": split,
                "file": source.name,
                "from": source_encoding,
                "to": "utf-8",
                "note": "GB18030 bytes A3 AC decode to the full-width comma '，'.",
            }
        )

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip():
            changes.append(
                {
                    "type": "blank_line_removed",
                    "split": split,
                    "file": source.name,
                    "line": line_number,
                }
            )
            continue

        parts = raw_line.split(",", 8)
        if len(parts) != 9:
            raise ValueError(f"Malformed OCR line {source}:{line_number}: {raw_line!r}")
        coordinates = [int(value) for value in parts[:8]]
        transcript = parts[8]

        if (
            source.name == DEGENERATE_BBOX_FILE
            and transcript == DEGENERATE_BBOX_TEXT
            and coordinates == DEGENERATE_BBOX_OLD
        ):
            coordinates = list(DEGENERATE_BBOX_NEW)
            changes.append(
                {
                    "type": "degenerate_bbox_reannotated",
                    "split": split,
                    "file": source.name,
                    "line": line_number,
                    "text": transcript,
                    "old_bbox": DEGENERATE_BBOX_OLD,
                    "new_bbox": DEGENERATE_BBOX_NEW,
                    "note": "Manually verified against the visible TOTAL RM text.",
                }
            )

        clamped = list(coordinates)
        for index in range(0, 8, 2):
            clamped[index] = min(max(clamped[index], 0), width - 1)
            clamped[index + 1] = min(max(clamped[index + 1], 0), height - 1)
        if clamped != coordinates:
            changes.append(
                {
                    "type": "bbox_clamped_to_image",
                    "split": split,
                    "file": source.name,
                    "line": line_number,
                    "text": transcript,
                    "old_bbox": coordinates,
                    "new_bbox": clamped,
                    "image_size": [width, height],
                }
            )
            coordinates = clamped

        xs = coordinates[0::2]
        ys = coordinates[1::2]
        if max(xs) <= min(xs) or max(ys) <= min(ys):
            raise ValueError(
                f"Degenerate bbox remains in {source}:{line_number}: {coordinates}"
            )
        output_lines.append(",".join([*(str(value) for value in coordinates), transcript]))

    destination.write_text("\n".join(output_lines) + "\n", encoding="utf-8")
    return len(output_lines)


def create_directories() -> None:
    for relative in (
        "train/images",
        "train/ocr",
        "train/kie",
        "test/images",
        "test/ocr",
        "manifests",
    ):
        (BUILD_ROOT / relative).mkdir(parents=True, exist_ok=False)


def build() -> dict:
    ensure_safe_build_target()

    train_images = primary_files(TRAIN_OCR_ROOT, ".jpg")
    train_ocr = primary_files(TRAIN_OCR_ROOT, ".txt")
    train_kie_images = primary_files(TRAIN_KIE_ROOT, ".jpg")
    train_kie = primary_files(TRAIN_KIE_ROOT, ".txt")
    if not (
        len(train_images) == 626
        and set(train_images) == set(train_ocr) == set(train_kie_images) == set(train_kie)
    ):
        raise RuntimeError("The four canonical training stem sets are not the expected 626 pairs.")

    for stem in train_images:
        with Image.open(train_images[stem]) as task1_image, Image.open(
            train_kie_images[stem]
        ) as task2_image:
            if task1_image.size != task2_image.size:
                raise RuntimeError(f"Task 1/task 2 image sizes differ for {stem}")

    report = {
        "source": "Original",
        "destination": "Clean",
        "structure": {
            "train/images": "Canonical task-1 images used with OCR boxes.",
            "train/ocr": "UTF-8 quadrilateral OCR annotations.",
            "train/kie": "Four-field KIE JSON annotations.",
            "test/images": "Unified task-1/2 test images, including recovered image.",
            "test/ocr": "UTF-8 quadrilateral OCR annotations.",
            "manifests/task3_test_files.txt": "Clean test files belonging to task 3.",
        },
        "policy": {
            "variants": "Only unsuffixed canonical files are used; suffix variants are redundant.",
            "duplicate_selection": "Keep the explicitly listed canonical filename and remove its exact-image duplicate.",
            "train_test_leak": "Keep test and remove the matching training record.",
            "task1_task2_images": "Use task-1 image versions so OCR coordinates stay aligned.",
        },
        "removed_train_duplicates": [],
        "removed_test_duplicates": [],
        "removed_train_test_leaks": [],
        "recovered_files": [],
        "ocr_changes": [],
        "kie_changes": [],
    }

    for kept, removed in TRAIN_DUPLICATES:
        digest = verify_exact_pair(train_images[kept], train_images[removed])
        report["removed_train_duplicates"].append(
            {"kept": kept, "removed": removed, "sha256": digest}
        )

    test_images = {path.stem: path for path in TEST_IMAGE_ROOT.glob("*.jpg")}
    test_ocr = {path.stem: path for path in TEST_OCR_ROOT.glob("*.txt")}
    if set(test_ocr) - set(test_images) != {MISSING_TEST_IMAGE}:
        raise RuntimeError(
            "Unexpected test image/OCR mismatch: "
            f"{sorted(set(test_ocr) - set(test_images))}"
        )
    recovered_source = TASK3_IMAGE_ROOT / f"{MISSING_TEST_IMAGE}.jpg"
    if not recovered_source.is_file():
        raise FileNotFoundError(f"Missing recovery image: {recovered_source}")
    test_images[MISSING_TEST_IMAGE] = recovered_source
    report["recovered_files"].append(
        {
            "file": f"{MISSING_TEST_IMAGE}.jpg",
            "from": str(recovered_source.relative_to(SOURCE_ROOT)),
            "reason": "OCR annotation exists in the 361-page test set but its image was only present in task 3.",
        }
    )

    for kept, removed in TEST_DUPLICATES:
        digest = verify_exact_pair(test_images[kept], test_images[removed])
        report["removed_test_duplicates"].append(
            {"kept": kept, "removed": removed, "sha256": digest}
        )

    for train_stem, test_stem in TRAIN_TEST_LEAKS:
        digest = verify_exact_pair(train_images[train_stem], test_images[test_stem])
        report["removed_train_test_leaks"].append(
            {
                "removed_from_train": train_stem,
                "kept_in_test": test_stem,
                "sha256": digest,
            }
        )

    removed_train = {removed for _, removed in TRAIN_DUPLICATES} | {
        train_stem for train_stem, _ in TRAIN_TEST_LEAKS
    }
    removed_test = {removed for _, removed in TEST_DUPLICATES}
    retained_train = sorted(set(train_images) - removed_train)
    retained_test = sorted(set(test_ocr) - removed_test)

    create_directories()

    train_ocr_lines = 0
    for stem in retained_train:
        source_image = train_images[stem]
        destination_image = BUILD_ROOT / "train" / "images" / f"{stem}.jpg"
        shutil.copy2(source_image, destination_image)
        with Image.open(source_image) as image:
            image_size = image.size
        train_ocr_lines += normalize_ocr(
            train_ocr[stem],
            BUILD_ROOT / "train" / "ocr" / f"{stem}.txt",
            image_size,
            "train",
            report["ocr_changes"],
        )

        kie = read_json(train_kie[stem])
        if stem == "X51005663280" and "address" not in kie:
            kie["address"] = ""
            report["kie_changes"].append(
                {
                    "file": f"{stem}.json",
                    "field": "address",
                    "old": "<missing>",
                    "new": "",
                    "reason": "No postal/street address is printed on the receipt; do not hallucinate one.",
                }
            )
        if stem == "X51005433522" and kie.get("total") == "":
            kie["total"] = "8.20"
            report["kie_changes"].append(
                {
                    "file": f"{stem}.json",
                    "field": "total",
                    "old": "",
                    "new": "8.20",
                    "reason": "Receipt visibly shows 'TOTAL AMOUNT: $8.20' and 'NETT TOTAL: $8.20'.",
                }
            )
        required_fields = {"company", "date", "address", "total"}
        if set(kie) != required_fields or any(
            not isinstance(kie[field], str) for field in required_fields
        ):
            raise ValueError(f"Invalid KIE schema for {stem}: {kie}")
        write_json(BUILD_ROOT / "train" / "kie" / f"{stem}.json", kie)

    test_ocr_lines = 0
    for stem in retained_test:
        source_image = test_images[stem]
        destination_image = BUILD_ROOT / "test" / "images" / f"{stem}.jpg"
        shutil.copy2(source_image, destination_image)
        with Image.open(source_image) as image:
            image_size = image.size
        test_ocr_lines += normalize_ocr(
            test_ocr[stem],
            BUILD_ROOT / "test" / "ocr" / f"{stem}.txt",
            image_size,
            "test",
            report["ocr_changes"],
        )

    original_task3 = {path.stem for path in TASK3_IMAGE_ROOT.glob("*.jpg")}
    clean_task3 = sorted(original_task3 & set(retained_test))
    (BUILD_ROOT / "manifests" / "task3_test_files.txt").write_text(
        "\n".join(f"{stem}.jpg" for stem in clean_task3) + "\n",
        encoding="utf-8",
    )

    report["counts"] = {
        "canonical_train_before": 626,
        "train_after": len(retained_train),
        "train_ocr_lines_after": train_ocr_lines,
        "test_with_recovered_image_before_deduplication": len(test_ocr),
        "test_after": len(retained_test),
        "test_ocr_lines_after": test_ocr_lines,
        "task3_manifest_after": len(clean_task3),
    }

    write_json(BUILD_ROOT / "cleaning_report.json", report)
    (BUILD_ROOT / "README.md").write_text(
        "# SROIE Clean\n\n"
        "This directory is generated from `../Original` by `src/clean_sroie.py`.\n\n"
        "- `train/images`: canonical receipt images\n"
        "- `train/ocr`: UTF-8 OCR quadrilateral annotations\n"
        "- `train/kie`: KIE annotations stored as JSON\n"
        "- `test/images`: unified and deduplicated test images\n"
        "- `test/ocr`: UTF-8 OCR quadrilateral annotations\n"
        "- `manifests/task3_test_files.txt`: task-3 membership without duplicating images\n"
        "- `cleaning_report.json`: complete provenance and change log\n\n"
        "Original IDs/stems are retained. Test KIE labels are not present in the source dataset.\n",
        encoding="utf-8",
    )

    if DESTINATION_ROOT.exists():
        DESTINATION_ROOT.rmdir()
    BUILD_ROOT.rename(DESTINATION_ROOT)
    return report


if __name__ == "__main__":
    result = build()
    print(json.dumps(result["counts"], indent=2))
    print("OCR changes:", len(result["ocr_changes"]))
    print("KIE changes:", len(result["kie_changes"]))
