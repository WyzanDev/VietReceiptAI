#!/usr/bin/env python3
"""Build the verified UIT-MLReceipts Clean split from Original.

The script is intentionally conservative: it refuses to overwrite a non-empty
Clean directory and verifies all five confirmed cross-split duplicate pairs
before changing the copied dataset.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections import defaultdict
from pathlib import Path

from PIL import Image


DATASET_ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = DATASET_ROOT / "Original"
DESTINATION_ROOT = DATASET_ROOT / "Clean"
BUILD_ROOT = DATASET_ROOT / ".Clean_building"
SPLITS = ("train", "val", "test")

# The user visually confirmed that the train copy should be removed in each pair.
CONFIRMED_LEAKS = (
    ("000819.jpg", "val", "000985.jpg"),
    ("000304.jpg", "val", "001032.jpg"),
    ("000701.jpg", "val", "001337.jpg"),
    ("000075.jpg", "test", "001392.jpg"),
    ("000746.jpg", "test", "001756.jpg"),
)

EXPECTED_INVALID_ANNOTATIONS = {
    ("train", 5873, "000990.jpg"),
    ("val", 1226, "001212.jpg"),
    ("val", 1668, "001286.jpg"),
    ("test", 2406, "001759.jpg"),
}


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, value: dict) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def ensure_safe_destination() -> None:
    if not SOURCE_ROOT.is_dir():
        raise FileNotFoundError(f"Missing source directory: {SOURCE_ROOT}")
    if BUILD_ROOT.exists():
        raise RuntimeError(
            f"Temporary build directory already exists: {BUILD_ROOT}. "
            "Inspect or remove it before rebuilding."
        )
    if DESTINATION_ROOT.exists() and any(DESTINATION_ROOT.iterdir()):
        raise RuntimeError(
            f"Refusing to overwrite non-empty destination: {DESTINATION_ROOT}"
        )


def verify_confirmed_leaks() -> list[dict]:
    verified = []
    for train_file, other_split, other_file in CONFIRMED_LEAKS:
        train_path = SOURCE_ROOT / "train" / train_file
        other_path = SOURCE_ROOT / other_split / other_file
        train_digest = sha256_file(train_path)
        other_digest = sha256_file(other_path)
        if train_digest != other_digest:
            raise RuntimeError(
                f"Confirmed pair is no longer identical: train/{train_file} "
                f"and {other_split}/{other_file}"
            )
        verified.append(
            {
                "removed_from_train": train_file,
                "kept_in_split": other_split,
                "kept_file": other_file,
                "sha256": train_digest,
            }
        )
    return verified


def build_clean_dataset() -> dict:
    ensure_safe_destination()
    verified_leaks = verify_confirmed_leaks()
    removed_train_files = {item[0] for item in CONFIRMED_LEAKS}

    BUILD_ROOT.mkdir(parents=False)
    for split in SPLITS:
        shutil.copytree(SOURCE_ROOT / split, BUILD_ROOT / split)

    source_data = {
        split: read_json(SOURCE_ROOT / f"{split}.json") for split in SPLITS
    }
    clean_data = {}
    report = {
        "source": "Original",
        "destination": "Clean",
        "id_policy": "Original image and annotation IDs are preserved; gaps are intentional.",
        "text_policy": "All retained annotation text fields are unchanged.",
        "verified_cross_split_leaks": verified_leaks,
        "removed_invalid_annotations": [],
        "updated_image_dimensions": [],
        "splits": {},
    }

    detected_invalid = set()

    for split in SPLITS:
        data = source_data[split]
        original_images = data["images"]
        original_annotations = data["annotations"]
        image_by_id = {image["id"]: image for image in original_images}

        removed_image_ids = set()
        if split == "train":
            removed_image_ids = {
                image["id"]
                for image in original_images
                if image["file_name"] in removed_train_files
            }
            found_files = {
                image["file_name"]
                for image in original_images
                if image["id"] in removed_image_ids
            }
            if found_files != removed_train_files:
                raise RuntimeError(
                    f"Train JSON does not contain the expected files: "
                    f"{sorted(removed_train_files - found_files)}"
                )

        retained_images = [
            dict(image) for image in original_images if image["id"] not in removed_image_ids
        ]

        retained_annotations = []
        removed_with_images = 0
        for annotation in original_annotations:
            if annotation["image_id"] in removed_image_ids:
                removed_with_images += 1
                continue

            x, y, width, height = annotation["bbox"]
            if width <= 0 or height <= 0:
                image_info = image_by_id[annotation["image_id"]]
                invalid_key = (split, annotation["id"], image_info["file_name"])
                detected_invalid.add(invalid_key)
                report["removed_invalid_annotations"].append(
                    {
                        "split": split,
                        "annotation_id": annotation["id"],
                        "image_id": annotation["image_id"],
                        "file_name": image_info["file_name"],
                        "bbox": annotation["bbox"],
                        "text": annotation.get("text"),
                    }
                )
                continue

            retained_annotations.append(dict(annotation))

        for image in retained_images:
            image_path = BUILD_ROOT / split / image["file_name"]
            with Image.open(image_path) as actual_image:
                actual_width, actual_height = actual_image.size
            old_size = (image["width"], image["height"])
            new_size = (actual_width, actual_height)
            if old_size != new_size:
                report["updated_image_dimensions"].append(
                    {
                        "split": split,
                        "image_id": image["id"],
                        "file_name": image["file_name"],
                        "old_size": list(old_size),
                        "new_size": list(new_size),
                    }
                )
                image["width"], image["height"] = new_size

        clean_split = dict(data)
        clean_split["images"] = retained_images
        clean_split["annotations"] = retained_annotations
        clean_data[split] = clean_split

        for file_name in sorted(removed_train_files if split == "train" else ()):
            copied_path = BUILD_ROOT / split / file_name
            if not copied_path.is_file():
                raise FileNotFoundError(f"Expected copied train image is missing: {copied_path}")
            copied_path.unlink()

        report["splits"][split] = {
            "images_before": len(original_images),
            "images_after": len(retained_images),
            "annotations_before": len(original_annotations),
            "annotations_after": len(retained_annotations),
            "images_removed_as_leaks": len(removed_image_ids),
            "annotations_removed_with_leaked_images": removed_with_images,
            "invalid_annotations_removed": sum(
                item["split"] == split
                for item in report["removed_invalid_annotations"]
            ),
        }

    if detected_invalid != EXPECTED_INVALID_ANNOTATIONS:
        raise RuntimeError(
            "Invalid bbox set differs from the four visually verified annotations. "
            f"Detected: {sorted(detected_invalid)}"
        )

    if len(report["updated_image_dimensions"]) != 10:
        raise RuntimeError(
            "Expected 10 dimension corrections, found "
            f"{len(report['updated_image_dimensions'])}."
        )

    # Verify text did not change for every retained annotation before writing.
    for split in SPLITS:
        original_text = {
            annotation["id"]: annotation.get("text")
            for annotation in source_data[split]["annotations"]
        }
        for annotation in clean_data[split]["annotations"]:
            if annotation.get("text") != original_text[annotation["id"]]:
                raise RuntimeError(
                    f"Text changed unexpectedly in {split}, annotation {annotation['id']}"
                )

        write_json(BUILD_ROOT / f"{split}.json", clean_data[split])

    report["summary"] = {
        "train_images_removed": len(removed_train_files),
        "annotations_removed_with_train_images": report["splits"]["train"][
            "annotations_removed_with_leaked_images"
        ],
        "invalid_annotations_removed": len(report["removed_invalid_annotations"]),
        "image_dimensions_updated": len(report["updated_image_dimensions"]),
        "annotation_text_values_changed": 0,
    }
    write_json(BUILD_ROOT / "cleaning_report.json", report)

    if DESTINATION_ROOT.exists():
        DESTINATION_ROOT.rmdir()
    BUILD_ROOT.rename(DESTINATION_ROOT)
    return report


if __name__ == "__main__":
    result = build_clean_dataset()
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    for split, counts in result["splits"].items():
        print(split, json.dumps(counts, ensure_ascii=False))
