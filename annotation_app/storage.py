"""Batch JSONL persistence, SQLite review history, and OCR editor presentation."""

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path

from annotation_app.data import (
    child as safe_child,
    exclusive_lock,
    load_batches,
    pending_save,
    processing_lock,
    read_json,
    read_rows,
    write_json,
    write_rows,
)
from annotation_app.drafts import read_drafts
from annotation_app.quality import review_issues
from annotation_app.schema import box, digest, file_hash, validate


EXCLUSION_REASONS = (
    "unreadable",
    "cropped",
    "overexposed",
    "underexposed",
    "not_receipt",
    "duplicate",
    "corrupted",
)


class Conflict(ValueError):
    pass


def fingerprint(region):
    return digest(region)


def synchronized(method):
    from functools import wraps

    @wraps(method)
    def call(self, *args, **kwargs):
        with self.transaction():
            return method(self, *args, **kwargs)

    return call


class Store:
    def __init__(self, batches, batch_id, state):
        self.root = Path(batches).resolve()
        self.state = Path(state)
        self.state.mkdir(parents=True, exist_ok=True)
        self.db_path = self.state / "workspace.sqlite3"
        self.lock = threading.RLock()
        self.depth = 0
        self.draft_stamp = None
        self.drafts = {}
        with exclusive_lock(processing_lock(self.root)):
            _, selected = load_batches(self.root, [batch_id], allow_pending=True)
            self.batch = selected[0]
            self.member = self.batch["member"]
            self.path = safe_child(self.root, self.batch["annotations"])
            self.folder = self.path.parent
            self.pending_path = pending_save(self.root, batch_id)
            self.originals = {r["id"]: r for r in read_rows(self.path)}
            self.expected = {s["id"]: s for s in self.batch["samples"]}
            self.source_hash = ""
            with self.connect() as db:
                db.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS config(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY,record TEXT NOT NULL,ui TEXT NOT NULL,revision INTEGER NOT NULL);
                    CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY,document TEXT,record TEXT,ui TEXT,revision INTEGER,updated REAL);
                    """
                )
                identity = digest([str(self.root), self.batch, "ocr-only"])
                config = dict(db.execute("SELECT key,value FROM config"))
                if config and config.get("identity") != identity:
                    raise Conflict("Phân công đã đổi. Dùng thư mục trạng thái mới.")
                if not config:
                    config = {"identity": identity, "workspace_id": uuid.uuid4().hex}
                    db.executemany("INSERT INTO config VALUES (?,?)", config.items())
                self.workspace_id = config["workspace_id"]
            self._sync()

    @staticmethod
    def initial_ui(record):
        return {
            "rotation": 0,
            "reviewed": (
                {str(i): fingerprint(r) for i, r in enumerate(record["ocr"])}
                if record["review"]["ocr_confirmed"]
                else {}
            ),
            "ocr_confirmed": record["review"]["ocr_confirmed"],
            "token_ids": {r["id"]: i for i, r in enumerate(record["ocr"])},
        }

    @contextmanager
    def transaction(self):
        with self.lock:
            if self.depth:
                yield
                return
            with exclusive_lock(processing_lock(self.root)):
                self.depth += 1
                try:
                    self._sync()
                    yield
                finally:
                    self.depth -= 1

    def _publish(self):
        if self.pending_path.exists() and read_json(self.pending_path)["database"] != str(
            self.db_path.resolve()
        ):
            raise Conflict("Cần mở lại workspace có lần lưu bị gián đoạn trước khi tiếp tục.")
        with self.connect() as db:
            pending = db.execute("SELECT value FROM config WHERE key='pending'").fetchone()
            if not pending:
                self.pending_path.unlink(missing_ok=True)
                return
            expected = json.loads(pending[0])
            rows = [
                json.loads(row[0])
                for row in db.execute("SELECT record FROM documents ORDER BY id")
            ]
        current = read_rows(self.path)
        if digest(current) != expected["after"]:
            if digest(current) != expected["before"]:
                raise Conflict("JSONL đã đổi trong lúc khôi phục lưu; cần đối chiếu thủ công.")
            write_rows(self.path, rows)
        with self.connect() as db:
            db.execute("DELETE FROM config WHERE key='pending'")
        self.pending_path.unlink(missing_ok=True)
        self.source_hash = file_hash(self.path)

    def _sync(self):
        self._publish()
        current_hash = file_hash(self.path)
        if current_hash == self.source_hash:
            return
        records = read_rows(self.path)
        if len(records) != len(self.expected) or {r["id"] for r in records} != set(self.expected):
            raise Conflict("Danh sách ảnh trong batch đã đổi.")
        with self.connect() as db:
            for record in records:
                validate(record)
                info = self.expected[record["id"]]
                if any(record[k] != info[k] for k in ("image", "source", "split", "width", "height")):
                    raise Conflict("Định danh ảnh nguồn đã đổi.")
                old = db.execute("SELECT record,ui,revision FROM documents WHERE id=?", (record["id"],)).fetchone()
                if old and json.loads(old[0]) == record:
                    continue
                ui = self.initial_ui(record)
                revision = 0
                if old:
                    old_ui = json.loads(old[1])
                    revision = old[2] + 1
                    ui["rotation"] = old_ui.get("rotation", 0)
                    ui["token_ids"] = old_ui.get("token_ids", ui["token_ids"])
                    ui["reviewed"] = old_ui.get("reviewed", ui["reviewed"])
                    db.execute(
                        "INSERT INTO history(document,record,ui,revision,updated) VALUES (?,?,?,?,?)",
                        (record["id"], *old, time.time()),
                    )
                db.execute(
                    "INSERT OR REPLACE INTO documents VALUES (?,?,?,?)",
                    (record["id"], json.dumps(record, ensure_ascii=False), json.dumps(ui), revision),
                )
        self.source_hash = current_hash

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db_path, timeout=15)
        db.execute("PRAGMA journal_mode=WAL")
        try:
            with db:
                yield db
        finally:
            db.close()

    @synchronized
    def get(self, rid):
        with self.connect() as db:
            row = db.execute("SELECT record,ui,revision FROM documents WHERE id=?", (rid,)).fetchone()
        if row is None:
            raise KeyError(rid)
        return {"record": json.loads(row[0]), "ui": json.loads(row[1]), "revision": row[2]}

    @synchronized
    def image_path(self, rid):
        path = safe_child(self.folder, self.originals[rid]["image"])
        if file_hash(path) != self.expected[rid]["sha256"]:
            raise Conflict("Ảnh đã thay đổi so với checksum được giao.")
        return path

    def check_source(self):
        if file_hash(self.path) != self.source_hash:
            raise Conflict("Annotation nguồn đã đổi ngoài app.")

    @synchronized
    def presentation(self, rid):
        current = self.get(rid)
        record = current["record"]
        ui = current["ui"]
        raw, suggestions, draft_error, draft_status = self.machine_draft(rid, ui)
        tokens = []
        for region in record["ocr"]:
            origin = raw.get(region["id"], {})
            token_id = ui["token_ids"].setdefault(region["id"], len(ui["token_ids"]))
            tokens.append(
                {
                    "token_id": token_id,
                    "raw_text": origin.get("text", ""),
                    "verified_text": region["text"],
                    "confidence": origin.get("confidence", 0),
                    "legibility": region["legibility"],
                    "bbox": box(region["polygon"]),
                    "polygon": region["polygon"],
                }
            )
        return {
            "record": {
                "task_id": rid,
                "dataset": record["source"]["dataset"],
                "source_split": record["source"]["split"],
                "image_id": record["source"]["image_id"],
                "image_file": record["image"],
                "width": record["width"],
                "height": record["height"],
                "assignment": {
                    "member": self.member,
                    "status": record["review"]["status"],
                    "reviewer": record["review"]["reviewer"],
                    "exclusion_reason": record["review"]["exclusion_reason"],
                },
                "ocr": {
                    "status": "verified" if record["review"]["ocr_confirmed"] else "generated" if tokens else "not_run",
                    "tokens": tokens,
                },
            },
            "review": {
                "rotation": ui.get("rotation", 0),
                "reviewed": ui.get("reviewed", {}),
                "ocr_confirmed": record["review"]["ocr_confirmed"],
            },
            "revision": current["revision"],
            "suggestions": suggestions,
            "source_issues": [],
            "draft_error": draft_error,
            "draft_status": draft_status,
        }

    @synchronized
    def listing(self):
        result = []
        with self.connect() as db:
            documents = db.execute("SELECT id,record,ui,revision FROM documents ORDER BY id").fetchall()
        for rid, encoded, encoded_ui, revision in documents:
            record = json.loads(encoded)
            ui = json.loads(encoded_ui)
            result.append(
                {
                    "task_id": rid,
                    "image_id": record["source"]["image_id"],
                    "dataset": record["source"]["dataset"],
                    "split": record["split"],
                    "status": record["review"]["status"],
                    "ocr_status": "verified" if record["review"]["ocr_confirmed"] else "generated" if record["ocr"] else "not_run",
                    "tokens": len(record["ocr"]),
                    "reviewed": len(ui.get("reviewed", {})),
                    "revision": revision,
                    "exclusion_reason": record["review"]["exclusion_reason"],
                }
            )
        return result

    def save(self, rid, wire, review, revision):
        with self.transaction():
            self.check_source()
            before = self.get(rid)
            if revision != before["revision"]:
                raise Conflict("Ảnh đã thay đổi ở cửa sổ khác. Tải lại trước khi lưu.")
            old = before["record"]
            record = deepcopy(old)
            ui = deepcopy(before["ui"])
            expected = {
                "task_id": rid,
                "dataset": old["source"]["dataset"],
                "source_split": old["source"]["split"],
                "image_id": old["source"]["image_id"],
                "image_file": old["image"],
                "width": old["width"],
                "height": old["height"],
            }
            if any(wire.get(key) != value for key, value in expected.items()):
                raise ValueError("Không được đổi định danh ảnh hoặc phân công.")
            if wire.get("assignment", {}).get("member") != self.member:
                raise ValueError("Không được đổi phân công.")
            if review.get("rotation") not in (0, 90, 180, 270) or not isinstance(review.get("reviewed"), dict) or not isinstance(review.get("ocr_confirmed"), bool):
                raise ValueError("Trạng thái duyệt không hợp lệ.")

            inverse = {v: k for k, v in ui.get("token_ids", {}).items()}
            next_id = max([-1, *inverse]) + 1
            regions = []
            for token in wire.get("ocr", {}).get("tokens", []):
                token_id = token.get("token_id")
                if type(token_id) is not int or token_id < 0:
                    raise ValueError("Invalid token id")
                canonical = inverse.get(token_id, f"manual-{token_id}")
                ui.setdefault("token_ids", {})[canonical] = token_id
                regions.append(
                    {
                        "id": canonical,
                        "polygon": token["polygon"],
                        "text": token.get("verified_text", ""),
                        "legibility": token.get("legibility", "clear"),
                    }
                )
                next_id = max(next_id, token_id + 1)
            record["ocr"] = regions
            ui["reviewed"] = {
                str(ui["token_ids"][region["id"]]): fingerprint(region)
                for region in regions
                if review["reviewed"].get(str(ui["token_ids"][region["id"]])) in (True, fingerprint(region))
            }
            rotated = review["rotation"] != ui.get("rotation", 0)
            ui["rotation"] = review["rotation"]
            if rotated:
                ui["reviewed"] = {}
            confirmed = bool(review["ocr_confirmed"] and regions and len(ui["reviewed"]) == len(regions))
            if regions != old["ocr"] or rotated:
                confirmed = False
            ui["ocr_confirmed"] = confirmed
            record["review"]["ocr_confirmed"] = confirmed
            record["review"]["status"] = "needs_review" if wire.get("assignment", {}).get("status") == "needs_review" else "in_progress"
            record["review"]["reviewer"] = self.member
            record["review"]["exclusion_reason"] = None
            validate(record)
            self._write(rid, record, ui, revision, before)
            return self.presentation(rid)

    def _write(self, rid, record, ui, revision, before):
        before_hash = digest(read_rows(self.path))
        self.check_source()
        self.image_path(rid)
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE documents SET record=?,ui=?,revision=? WHERE id=? AND revision=?",
                (json.dumps(record, ensure_ascii=False), json.dumps(ui), revision + 1, rid, revision),
            )
            if cursor.rowcount != 1:
                raise Conflict("Revision conflict")
            db.execute(
                "INSERT INTO history(document,record,ui,revision,updated) VALUES (?,?,?,?,?)",
                (rid, json.dumps(before["record"], ensure_ascii=False), json.dumps(before["ui"]), revision, time.time()),
            )
            rows = [json.loads(row[0]) for row in db.execute("SELECT record FROM documents ORDER BY id")]
            write_json(self.pending_path, {"database": str(self.db_path.resolve())})
            db.execute("INSERT OR REPLACE INTO config VALUES ('pending',?)", (json.dumps({"before": before_hash, "after": digest(rows)}),))
        self._publish()

    @synchronized
    def qc(self, rid):
        return review_issues(self.get(rid)["record"])

    def complete(self, rid, revision):
        with self.transaction():
            self.check_source()
            before = self.get(rid)
            if before["revision"] != revision:
                raise Conflict("Revision conflict")
            if before["record"]["review"]["status"] == "excluded":
                return None, [{"level": "error", "code": "excluded", "detail": "Khôi phục ảnh trước khi hoàn tất."}]
            issues = self.qc(rid)
            if any(row["level"] == "error" for row in issues):
                return None, issues
            record = deepcopy(before["record"])
            record["review"]["status"] = "completed"
            self._write(rid, record, before["ui"], revision, before)
            return self.presentation(rid), issues

    def exclude(self, rid, revision, reason):
        if reason not in EXCLUSION_REASONS:
            raise ValueError("Lý do loại ảnh không hợp lệ.")
        with self.transaction():
            before = self.get(rid)
            if before["revision"] != revision:
                raise Conflict("Revision conflict")
            record = deepcopy(before["record"])
            record["review"]["status"] = "excluded"
            record["review"]["reviewer"] = self.member
            record["review"]["ocr_confirmed"] = False
            record["review"]["exclusion_reason"] = reason
            self._write(rid, record, before["ui"], revision, before)
            return self.presentation(rid)

    def restore(self, rid, revision):
        with self.transaction():
            before = self.get(rid)
            if before["revision"] != revision:
                raise Conflict("Revision conflict")
            record = deepcopy(before["record"])
            record["review"]["status"] = "in_progress"
            record["review"]["reviewer"] = self.member
            record["review"]["ocr_confirmed"] = False
            record["review"]["exclusion_reason"] = None
            ui = deepcopy(before["ui"])
            ui["reviewed"] = {}
            ui["ocr_confirmed"] = False
            self._write(rid, record, ui, revision, before)
            return self.presentation(rid)

    def machine_draft(self, rid, ui):
        path = self.folder / "machine_drafts.jsonl"
        if not path.exists():
            return {}, {}, "Chưa có file bản nháp máy trong batch.", "not_run"
        stat = path.stat()
        stamp = (stat.st_mtime_ns, stat.st_size)
        if stamp != self.draft_stamp:
            try:
                self.drafts = read_drafts(path, self.expected)
            except (ValueError, KeyError, TypeError) as error:
                raise Conflict("Bản nháp máy không hợp lệ: " + str(error)) from error
            self.draft_stamp = stamp
        draft = self.drafts[rid]
        raw = {region["id"]: region for region in draft["ocr"]["regions"]}
        current = {region["id"]: region for region in self.get(rid)["record"]["ocr"]}
        suggestions = {}
        for result in draft["llm"]["regions"]:
            region_id = result["id"]
            if result["status"] == "success" and region_id in ui.get("token_ids", {}) and current.get(region_id, {}).get("polygon") == raw[region_id]["polygon"]:
                suggestions["ocr:" + str(ui["token_ids"][region_id])] = {**result["suggestion"], "model": draft["llm"]["model"]}
        errors = []
        if draft["ocr"].get("error"):
            errors.append(draft["ocr"]["error"])
        if draft["ocr"].get("invalid_regions"):
            errors.append("OCR có vùng lỗi; cần kiểm tra toàn trang.")
        if draft["llm"]["status"] not in ("success", "not_run"):
            errors.append("LLM chưa xử lý đầy đủ; cần đối chiếu các vùng còn lại.")
        return raw, suggestions, " | ".join(errors) or None, draft["ocr"]["status"]
