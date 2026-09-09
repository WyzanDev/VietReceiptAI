#!/usr/bin/env python3
"""Migrate existing assignments to member/dataset/split without editing annotation data.

Default is a read-only plan. --apply builds and audits a separate tree, preserves the
whole previous task tree under reference/, then switches to the verified layout.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import shutil
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("submission_audit", PROJECT / "src/08_audit_annotation_submissions.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)
LAYOUT = "member/dataset/source_split"
COMMON_FILES = ("DATASET_SCHEMA.md", "ANNOTATION_GUIDE.md", "OCR_GUIDE.md",
                "TOKEN_ALIGNMENT.md", "annotation_schema.json", "requirements-ocr.txt")
TOOLS = ("05_run_paddleocr.py", "06_token_alignment.py")


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_rows(path, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def fingerprint(root):
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Review symlink before migration: {path}")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def plan(registry):
    groups = defaultdict(list)
    for row in registry:
        groups[row["package"]].append(row)
    destinations = set()
    result = []
    for old, rows in sorted(groups.items()):
        scopes = {(r["member"], r["dataset"], r["source_split"]) for r in rows}
        if len(scopes) != 1:
            raise ValueError(f"Mixed scope in old package: {old}")
        member, dataset, split = next(iter(scopes))
        if any(not value or value in (".", "..") or "/" in value or "\\" in value
               for value in (member, dataset, split)):
            raise ValueError(f"Unsafe package identity: {scopes}")
        if Path(old).is_absolute() or ".." in Path(old).parts:
            raise ValueError(f"Unsafe old package: {old}")
        new = f"{member}/{dataset}/{split}"
        if new in destinations:
            raise ValueError(f"Two packages would overwrite {new}; manual reconciliation required")
        destinations.add(new)
        result.append(dict(old_package=old, package=new, member=member, dataset=dataset,
                           source_split=split, images=len(rows)))
    return result


def leaf_readme(row):
    return f'''# {row['member']} — {row['dataset']} / {row['source_split']}

Gói này có **{row['images']} ảnh**. Dataset và split được giữ cố định, không chuyển ảnh sang gói khác.
Đường dẫn từ repository: `task/{row['package']}/`.

## Thực hiện tại đúng thư mục này

1. Đọc `ANNOTATION_GUIDE.md`, `DATASET_SCHEMA.md`, `OCR_GUIDE.md` và `TOKEN_ALIGNMENT.md`.
2. Kích hoạt môi trường OCR chung, cài `python -m pip install -r requirements-ocr.txt`.
3. Chạy thử `python tools/05_run_paddleocr.py --task-dir . --device cpu --limit 3`.
   Khi chạy đủ gói thì bỏ `--limit 3`. Không dùng `--force` với kết quả đã verify.
4. Verify OCR **toàn trang**, gồm cả token ngoài bốn trường; kiểm tra bbox và giá trị bốn trường KIE.
   UIT và MC-OCR train có nhãn nguồn làm bản nháp; MC-OCR validation cần tạo nhãn.
   Chữ `a` placeholder không phải đáp án. Nhãn nguồn có transcript thật vẫn cần kiểm tra theo ảnh.
5. Sửa text máy ở `ocr.tokens[].verified_text`; chép giá trị KIE nguyên văn ở `fields.*.regions[].raw_text`.
   Không chuẩn hóa giờ/ngày/số tiền/chính tả. Giữ `06:00 pm`; mọi `normalized_value` để `""`.
6. Đặt trạng thái hoàn thành theo hướng dẫn, chạy `python tools/06_token_alignment.py --task-dir .`.
   Đọc và xử lý cảnh báo/lỗi; căn chỉnh tự động không thay thế kiểm tra text bằng mắt.
7. Nộp `annotations.jsonl`, `aligned_annotations.jsonl`, `alignment_qc.csv` tại đúng gói này.

Giữ nguyên `task_id`, `image_id`, `image_file`, `dataset`, `source_split`, ảnh và manifest.
`source_annotations.jsonl` (nếu có) chỉ là bản nháp nguồn để đối chiếu, không chỉnh sửa/nộp như mẫu mới.
Các đường dẫn `images/...` tính từ thư mục này. Không chạy OCR/alignment tại gốc member.
Hướng dẫn tổng hợp: [MERGE_GUIDE.md](../../../MERGE_GUIDE.md).
'''


def write_docs(stage, packages):
    for name in ("DATASET_SCHEMA.md", "ANNOTATION_GUIDE.md", "OCR_GUIDE.md", "TOKEN_ALIGNMENT.md"):
        path = stage / "common" / name
        text = path.read_text(encoding="utf-8")
        text = text.replace("Tại thư mục member:", "Tại thư mục gói `task/memberN/<dataset>/<split>/` có `annotations.jsonl`:")
        text = text.replace("tại thư mục member và", "tại thư mục gói `<dataset>/<split>/` và")
        text = text.replace("(áp dụng cho cả hai đợt)", "(áp dụng cho mọi gói)")
        text += ("\n## Vị trí gói công việc\n\n"
                 "Mỗi gói nằm ở `task/memberN/<dataset>/<source_split>/`. "
                 "Lệnh dùng `--task-dir .` phải chạy tại thư mục này, không tại gốc member.\n"
                 "`r2-` trong task_id và `round` trong registry chỉ là dấu vết lần giao việc cũ; "
                 "giữ nguyên, không đổi ID và không tạo thư mục theo đợt.\n")
        path.write_text(text, encoding="utf-8")
    for row in packages:
        leaf = stage / row["package"]
        for name in COMMON_FILES:
            shutil.copy2(stage / "common" / name, leaf / name)
        for name in TOOLS:
            shutil.copy2(PROJECT / "src" / name, leaf / "tools" / name)
        (leaf / "README.md").write_text(leaf_readme(row), encoding="utf-8")
    for i in range(1, 9):
        own = [r for r in packages if r["member"] == f"member{i}"]
        total = sum(r["images"] for r in own)
        text = f"# Member{i} — tổng {total} ảnh\n\n"
        text += "Tất cả phần việc cũ và bổ sung được tập trung tại đây, chia riêng dataset và split.\n\n"
        for row in own:
            relative = f"{row['dataset']}/{row['source_split']}"
            text += f"- [{relative}]({relative}/README.md): **{row['images']} ảnh**.\n"
        text += ("\nMở từng gói ở trên để chạy OCR/verify/alignment. Không chạy tại thư mục member.\n"
                 "Không chuẩn hóa nội dung. Không chuyển ảnh val/test vào train, kể cả cùng người làm.\n"
                 "Không đổi ID hoặc tên ảnh. Chỉ sửa/nộp kết quả trong gói mình được giao.\n\n"
                 "[Hướng dẫn chung](../README.md) · [Nhận bài và gộp](../MERGE_GUIDE.md)\n")
        (stage / f"member{i}/README.md").write_text(text, encoding="utf-8")
    counts = defaultdict(Counter)
    for row in packages:
        counts[row["member"]][(row["dataset"], row["source_split"])] += row["images"]
    text = '''# Phân công annotation VietReceiptAI

**3.631 ảnh — 8 thành viên — 16 gói dataset/split.** Phần cũ và bổ sung đã được gom về từng member;
không còn thư mục công việc `round2`. Không chia lại ảnh, không thay người phụ trách hoặc split.

```text
task/
├── README.md
├── MERGE_GUIDE.md
├── assignment_registry.jsonl   # Danh sách giao việc cố định
├── assignment_summary.csv    # Toàn bộ 16 gói hiện tại
├── build_report.json
├── common/                   # Schema và hướng dẫn chuẩn
└── member1/ ... member8/
    ├── README.md
    └── <dataset>/<split>/
        ├── README.md, hướng dẫn, schema, requirements-ocr.txt
        ├── images/
        ├── annotations.jsonl
        ├── manifest.csv
        ├── source_annotations.jsonl  # Chỉ có ở gói bổ sung, nếu đã được tạo
        └── tools/
```

## Tổng phần việc mỗi người

| Member | UIT train | UIT val | UIT test | MC train | MC validation | Tổng |
|---|---:|---:|---:|---:|---:|---:|
'''
    keys = [("UIT-MLReceipts", "train"), ("UIT-MLReceipts", "val"),
            ("UIT-MLReceipts", "test"), ("MC-OCR", "train"), ("MC-OCR", "validation")]
    for i in range(1, 9):
        values = [counts[f"member{i}"][key] for key in keys]
        text += f"| [member{i}](member{i}/README.md) | " + " | ".join(map(str, [*values, sum(values)])) + " |\n"
    text += '''
## Cách làm

Mở README của member, chọn gói dataset/split rồi làm theo README tại đó.
Ví dụ từ gốc repository: `cd task/member1/MC-OCR/train` trước khi chạy lệnh trong hướng dẫn.
Mỗi gói có tài liệu/công cụ riêng để có thể giao độc lập; `common/` là bản chuẩn do người tổng hợp quản lý.

- Giữ cấu hình đã thống nhất: PaddleOCR **3.7.0**, PP-OCRv6, `lang="vi"`.
- Verify **OCR toàn trang và bốn trường KIE**, sau đó chạy token alignment.
- **Không chuẩn hóa nội dung**: giữ `06:00 pm`, ngày tháng, số tiền, đơn vị và chính tả trên ảnh.
  `normalized_value` luôn là `""`.
- Giữ nguyên ảnh, ID và split. Tiền tố `r2-` chỉ để truy vết lần giao cũ, không phải đường dẫn mới.
- Cấu trúc mới không chứng minh annotation đã hoàn thành; nhãn nguồn và pre-OCR vẫn cần verify.

## Nhận bài và cập nhật từ cấu trúc cũ

Đọc [MERGE_GUIDE.md](MERGE_GUIDE.md) trước khi cập nhật nhánh hoặc nhận bài.
`assignment_registry.jsonl` là sổ đối chiếu toàn bộ 3.631 ảnh; không sửa để làm bài nộp vượt kiểm tra.
Script `src/08_audit_annotation_submissions.py` kiểm tra cấu trúc/ảnh/split, không chạy OCR hoặc tự gộp nhãn.
Script `src/09_restructure_member_tasks.py` chuyển cấu trúc; script 04/07 là bước tạo gói lịch sử,
không chạy lại lên dữ liệu đang annotation.
'''
    (stage / "README.md").write_text(text, encoding="utf-8")


def migrate(root, apply=False):
    registry = checker.read_jsonl(root / "assignment_registry.jsonl")
    packages = plan(registry)
    if all(r["old_package"] == r["package"] for r in packages):
        return {"status": "already_current", "audit": checker.audit(root)}
    if not apply:
        return {"status": "plan_only", "registered_images": len(registry), "packages": packages}
    before = checker.audit(root)
    if before["errors"]:
        raise ValueError(f"Fix pre-migration audit errors first: {before['errors'][:5]}")
    original_fingerprint = fingerprint(root)
    # Only generated container READMEs/reports may disappear from the active layout.
    # Refuse to silently strand other user output outside registered packages.
    package_prefixes = tuple(r["old_package"] + "/" for r in packages)
    for relative in original_fingerprint:
        if relative.startswith(package_prefixes) or not relative.startswith("round2/"):
            continue
        parts = Path(relative).parts
        if relative in ("round2/README.md", "round2/assignment_summary.csv", "round2/build_report.json"):
            continue
        if len(parts) == 3 and parts[1].startswith("member") and parts[2] == "README.md":
            continue
        raise ValueError(f"Unassigned file outside a package; review before migration: {relative}")
    # Build a separate full tree; do not modify any existing member work in place.
    staging_parent = Path(tempfile.mkdtemp(prefix=".task-layout-staging-", dir=root.parent))
    stage = staging_parent / "task"
    stage.mkdir()
    known_members = {r["member"] for r in registry}
    for path in root.iterdir():
        if path.name in known_members or path.name == "round2":
            continue
        if path.is_dir():
            shutil.copytree(path, stage / path.name)
        else:
            shutil.copy2(path, stage / path.name)
    for row in packages:
        shutil.copytree(root / row["old_package"], stage / row["package"])
    mapping = {r["old_package"]: r["package"] for r in packages}
    # Each package remains whole, including any human-edited or derived output.
    for row in registry:
        row["package"] = mapping[row["package"]]
    with (stage / "assignment_registry.jsonl").open("w", encoding="utf-8") as stream:
        for row in registry:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    for package in packages:
        manifest = stage / package["package"] / "manifest.csv"
        with manifest.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        if rows and "package" in rows[0]:
            for row in rows:
                row["package"] = package["package"]
            write_rows(manifest, rows)
    write_docs(stage, packages)
    write_rows(stage / "assignment_summary.csv", [
        {k: r[k] for k in ("member", "dataset", "source_split", "images", "package")} for r in packages])
    post = checker.audit(stage)
    if post["errors"]:
        raise ValueError(f"Staged audit failed; original untouched: {post['errors'][:5]}")
    # All non-document annotation/output/image files must be byte-for-byte unchanged.
    preserved = 0
    for row in packages:
        original = root / row["old_package"]
        copied = stage / row["package"]
        allowed_changes = {"README.md", "manifest.csv", *COMMON_FILES, *(f"tools/{n}" for n in TOOLS)}
        for relative, digest in fingerprint(original).items():
            if relative not in allowed_changes:
                if hashlib.sha256((copied / relative).read_bytes()).hexdigest() != digest:
                    raise ValueError(f"Content changed: {original / relative}")
                preserved += 1
    report = {"layout": LAYOUT, "images": len(registry), "packages": len(packages),
              "members": 8, "text_policy": "verbatim; normalized_value is empty",
              "annotation_content_preserved": True, "preserved_package_files": preserved,
              "ocr_run_by_migration": False, "audit": post,
              "path_migration": packages}
    dump(stage / "build_report.json", report)
    if fingerprint(root) != original_fingerprint:
        raise ValueError("Source changed while staging. Original untouched; stop edits and retry.")
    backup_parent = root.parent / "reference"
    backup_parent.mkdir(exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix="task-layout-backup-" + datetime.now().strftime("%Y%m%d-%H%M%S-") , dir=backup_parent))
    root.rename(backup / "task")
    try:
        stage.rename(root)
    except BaseException:
        (backup / "task").rename(root)
        raise
    staging_parent.rmdir()  # Only the verified, now-empty staging directory.
    return {"status": "migrated", "backup": str(backup / "task"), **report}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-root", type=Path, default=PROJECT / "task")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(migrate(args.task_root.resolve(), args.apply), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
