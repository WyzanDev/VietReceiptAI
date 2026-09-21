"""Canonical OCR-only annotation schema and geometry validation."""

import hashlib
import json
import math
from pathlib import Path

from jsonschema import Draft202012Validator
from shapely.geometry import Polygon


def obj(properties, required=None):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties) if required is None else required,
        "additionalProperties": False,
    }


TEXT = {"type": "string"}
POLYGON = {
    "type": "array",
    "minItems": 3,
    "maxItems": 512,
    "items": {
        "type": "array",
        "minItems": 2,
        "maxItems": 2,
        "items": {"type": "number"},
    },
}
REGION = obj(
    {
        "id": {"type": "string", "minLength": 1},
        "polygon": POLYGON,
        "text": TEXT,
        "legibility": {"enum": ["unreviewed", "clear", "partial", "unreadable"]},
    }
)

SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    **obj(
        {
            "id": {"type": "string", "minLength": 1},
            "image": TEXT,
            "width": {"type": "integer", "minimum": 1},
            "height": {"type": "integer", "minimum": 1},
            "source": obj(
                {
                    "dataset": {"enum": ["UIT-MLReceipts", "MC-OCR"]},
                    "image_id": TEXT,
                    "split": {"enum": ["train", "val", "validation", "test"]},
                }
            ),
            "split": {"enum": ["train", "val", "test"]},
            "ocr": {"type": "array", "items": REGION},
            "review": obj(
                {
                    "status": {
                        "enum": [
                            "pending",
                            "in_progress",
                            "needs_review",
                            "completed",
                            "excluded",
                        ]
                    },
                    "reviewer": {"type": ["string", "null"]},
                    "ocr_confirmed": {"type": "boolean"},
                    "exclusion_reason": {
                        "enum": [
                            None,
                            "unreadable",
                            "cropped",
                            "overexposed",
                            "underexposed",
                            "not_receipt",
                            "duplicate",
                            "corrupted",
                        ]
                    },
                }
            ),
        }
    ),
}
VALIDATOR = Draft202012Validator(SCHEMA)


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def identity(dataset, split, image_id):
    return f"{dataset}:{split}:{image_id}"


def box(polygon):
    return [
        math.floor(min(p[0] for p in polygon)),
        math.floor(min(p[1] for p in polygon)),
        math.ceil(max(p[0] for p in polygon)),
        math.ceil(max(p[1] for p in polygon)),
    ]


def rectangle(x, y, w, h):
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


def blank(dataset, split, name, width, height):
    return {
        "id": identity(dataset, split, Path(name).stem),
        "image": "images/" + name,
        "width": width,
        "height": height,
        "source": {"dataset": dataset, "split": split, "image_id": Path(name).stem},
        "split": "val" if split == "validation" else split,
        "ocr": [],
        "review": {
            "status": "pending",
            "reviewer": None,
            "ocr_confirmed": False,
            "exclusion_reason": None,
        },
    }


def validate(record):
    VALIDATOR.validate(record)
    expected = identity(
        record["source"]["dataset"],
        record["source"]["split"],
        record["source"]["image_id"],
    )
    if record["id"] != expected:
        raise ValueError("ID does not match source identity")
    if record["split"] != {"validation": "val"}.get(
        record["source"]["split"], record["source"]["split"]
    ):
        raise ValueError("Source split must be preserved")
    path = Path(record["image"])
    if path.is_absolute() or ".." in path.parts or "\\" in record["image"]:
        raise ValueError("Unsafe image path")
    regions = record["ocr"]
    if len({r["id"] for r in regions}) != len(regions):
        raise ValueError("Duplicate region ID")
    for region in regions:
        points = region["polygon"]
        if any(not math.isfinite(v) for p in points for v in p):
            raise ValueError("Non-finite polygon")
        if any(
            not (0 <= x <= record["width"] and 0 <= y <= record["height"])
            for x, y in points
        ):
            raise ValueError("Polygon outside image")
        area = sum(
            p[0] * q[1] - q[0] * p[1] for p, q in zip(points, points[1:] + points[:1])
        )
        if abs(area) < 0.01:
            raise ValueError("Polygon has no area")
        if not Polygon(points).is_valid:
            raise ValueError("Polygon intersects itself or has invalid edges")
    review = record["review"]
    if review["status"] == "excluded" and not review["exclusion_reason"]:
        raise ValueError("Excluded image needs an exclusion reason")
    if review["status"] != "excluded" and review["exclusion_reason"] is not None:
        raise ValueError("Only excluded images may have an exclusion reason")
