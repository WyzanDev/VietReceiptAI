"""Portable, read-only machine evidence shipped with a member's batch."""

from copy import deepcopy

from jsonschema import ValidationError

from annotation_app.data import read_rows
from annotation_app.schema import blank, validate


def validate_draft(draft, info):
    try:
        if draft["id"] != info["id"] or draft["image_sha256"] != info["sha256"]:
            raise ValueError("Machine draft image identity/checksum mismatch")
        ocr, llm = draft["ocr"], draft["llm"]
        if ocr["status"] not in ("not_run", "success", "error"):
            raise ValueError("Invalid OCR status")
        probe = blank(
            info["source"]["dataset"],
            info["source"]["split"],
            info["source"]["image_id"],
            info["width"],
            info["height"],
        )
        probe["ocr"] = deepcopy(ocr["regions"])
        validate(probe)
        ids = {r["id"] for r in ocr["regions"]}
        if ocr["status"] != "success" and ids:
            raise ValueError("Unsuccessful OCR must not contain regions")
        if llm["status"] not in ("not_run", "success", "partial", "error", "paused"):
            raise ValueError("Invalid LLM status")
        seen = set()
        for result in llm["regions"]:
            rid = result["id"]
            if rid not in ids or rid in seen:
                raise ValueError("Unknown or duplicate machine region ID")
            seen.add(rid)
            if result["status"] not in ("success", "error", "paused", "not_run"):
                raise ValueError("Invalid region result status")
            if result["status"] == "success":
                suggestion = result["suggestion"]
                if (
                    set(suggestion) != {"id", "text", "uncertain"}
                    or suggestion["id"] != rid
                    or not isinstance(suggestion["text"], str)
                    or type(suggestion["uncertain"]) is not bool
                    or not llm["model"]
                    or not llm["settings_hash"]
                ):
                    raise ValueError("Invalid machine suggestion")
        if seen != ids:
            raise ValueError("Missing region processing status")
        if llm["status"] == "success" and (
            not ids or any(r["status"] != "success" for r in llm["regions"])
        ):
            raise ValueError("LLM marked complete with unfinished regions")
    except (KeyError, TypeError, ValidationError) as error:
        raise ValueError("Malformed machine draft") from error


def read_drafts(path, expected):
    rows = read_rows(path)
    if len(rows) != len(expected) or {r["id"] for r in rows} != set(expected):
        raise ValueError("Machine draft sample list differs from assigned batch")
    for row in rows:
        validate_draft(row, expected[row["id"]])
    return {r["id"]: r for r in rows}
