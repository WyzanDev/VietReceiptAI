"""Shared local data integrity, IO, locking, and batch authentication."""

import hashlib
import hmac
import json
import os
import secrets
from contextlib import contextmanager
from pathlib import Path

from annotation_app.schema import validate

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BATCHES = ROOT / "datasets/batches"


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()


def checksum(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_rows(path):
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + secrets.token_hex(6) + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def write_json(path, value):
    atomic_text(
        path, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )


def write_rows(path, rows):
    atomic_text(
        path,
        "".join(
            json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n" for row in rows
        ),
    )


def child(root, relative):
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Unsafe relative path")
    result = (Path(root) / relative).resolve()
    if not result.is_relative_to(Path(root).resolve()):
        raise ValueError("Path escapes its data directory")
    return result


@contextmanager
def exclusive_lock(path):
    """OS locks are released on interruption; no stale PID file blocks resume."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            if path.stat().st_size == 0:
                stream.write(b"0")
                stream.flush()
                stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError(
                    "Another preparation process holds this lock"
                ) from exc
        else:
            import fcntl

            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError(
                    "Another preparation process holds this lock"
                ) from exc
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def password_hash(password):
    salt = secrets.token_bytes(16)
    result = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return f"scrypt$16384$8$1${salt.hex()}${result.hex()}"


def verify_password(password, encoded):
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$")
        if (algorithm, n, r, p) != ("scrypt", "16384", "8", "1"):
            return False
        result = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1
        )
        return hmac.compare_digest(result.hex(), expected)
    except (ValueError, TypeError, AttributeError):
        return False


def pending_save(root, batch_id):
    return (
        ROOT
        / "artifacts/locks"
        / (digest([str(Path(root).resolve()), batch_id]) + ".pending.json")
    )


def load_batches(root, selected=None, image_ids=None, *, allow_pending=False):
    root = Path(root).resolve()
    config = read_json(root / "config.json")
    batches = config["batches"]
    if len(batches) != 8 or len({b["member"] for b in batches}) != 8:
        raise ValueError("Expected eight batches assigned to eight distinct members")
    if (
        digest([[s["id"] for s in b["samples"]] for b in batches])
        != config["assignment_hash"]
    ):
        raise ValueError("Batch assignments changed")
    if len({b["id"] for b in batches}) != len(batches):
        raise ValueError("Duplicate batch IDs")
    if selected and not set(selected) <= {b["id"] for b in batches}:
        raise ValueError("Unknown --batch")
    available = {
        s["id"]
        for b in batches
        if not selected or b["id"] in selected
        for s in b["samples"]
    }
    if image_ids and not set(image_ids) <= available:
        raise ValueError(
            "Unknown --image-id or image does not belong to selected batches"
        )
    seen = set()
    for batch in batches:
        expected = {s["id"]: s for s in batch["samples"]}
        if len(expected) != len(batch["samples"]) or seen.intersection(expected):
            raise ValueError("Duplicate sample assignments")
        seen.update(expected)
        if batch["sample_count"] != len(expected):
            raise ValueError("Incorrect sample_count")
        if selected and batch["id"] not in selected:
            continue
        if not allow_pending and pending_save(root, batch["id"]).exists():
            raise ValueError(
                "App has an unfinished save. Reopen its workspace to recover before processing or merging."
            )
        path = child(root, batch["annotations"])
        rows = read_rows(path)
        if len(rows) != len(expected) or {r["id"] for r in rows} != set(expected):
            raise ValueError(f"Missing/extra/duplicate samples in {path}")
        actual_images = set()
        for row in rows:
            validate(row)
            info = expected[row["id"]]
            if any(
                row[k] != info[k]
                for k in ("source", "split", "image", "width", "height")
            ):
                raise ValueError("Source identity changed")
            image = child(path.parent, row["image"])
            if (
                image.parent != child(root, batch["images"])
                or checksum(image) != info["sha256"]
            ):
                raise ValueError(f"Image checksum/path mismatch: {row['id']}")
            actual_images.add(image)
        if actual_images != {
            p.resolve() for p in child(root, batch["images"]).iterdir()
        }:
            raise ValueError("Unexpected files in batch images directory")
    if len(seen) != config["sample_count"]:
        raise ValueError("Incorrect total sample_count")
    return config, [b for b in batches if not selected or b["id"] in selected]


def processing_lock(root):
    return ROOT / "artifacts/locks" / (digest(str(Path(root).resolve())) + ".lock")
