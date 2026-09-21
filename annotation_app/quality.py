"""Human-review checks for OCR-only annotations."""

from jsonschema import ValidationError

from annotation_app.schema import validate


def review_issues(record):
    try:
        validate(record)
    except (ValueError, ValidationError) as error:
        return [{"level": "error", "code": "schema", "detail": str(error)}]

    review = record["review"]
    if review["status"] == "excluded":
        return []

    issues = []

    def add(code, detail):
        issues.append({"level": "error", "code": code, "detail": detail})

    if not record["ocr"]:
        add("empty_ocr", "Ảnh chưa có vùng chữ nào.")
    if not review["reviewer"]:
        add("reviewer_required", "Chưa có người xác nhận.")
    if not review["ocr_confirmed"]:
        add("ocr_not_verified", "Cần kiểm tra toàn bộ vùng chữ trên ảnh.")

    for region in record["ocr"]:
        rid = region["id"]
        legibility = region["legibility"]
        text = region["text"]
        if legibility == "unreviewed":
            add("region_not_reviewed", rid)
        if legibility == "clear" and not text.strip():
            add("empty_text", rid + ": vùng đọc rõ phải có transcript.")
        if text.strip() in {"a", "###", "abc abc abc"}:
            add("placeholder", rid + ": transcript có vẻ là placeholder.")

    return issues
