"""Local batch annotation app: password login, human review, atomic JSONL saves."""

import json
import os
import secrets
import threading
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from jsonschema import ValidationError
from pydantic import BaseModel, Field
from shapely.geometry import Polygon

from annotation_app.data import digest, read_json, verify_password
from annotation_app.geometry import crop_png
from annotation_app.quality import review_issues
from annotation_app.storage import Conflict, Store, EXCLUSION_REASONS

ROOT = Path(__file__).resolve().parents[1]


class SaveRequest(BaseModel):
    record: dict
    review: dict
    revision: int = Field(ge=0)


class RevisionRequest(BaseModel):
    revision: int = Field(ge=0)


class ExcludeRequest(RevisionRequest):
    reason: str


class CropRequest(BaseModel):
    polygon: list[list[float]] = Field(min_length=3, max_length=512)
    rotation: int = 0


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=128)


def create_app(batches=None, state_root=None):
    batches = Path(
        batches or os.environ.get("VIETRECEIPT_BATCHES", ROOT / "datasets/batches")
    ).resolve()
    # Keep OCR-only workspaces separate from any older annotation state.
    state_root = Path(state_root or ROOT / "artifacts/annotation") / digest(
        [str(batches), "ocr-only"]
    )
    stores, sessions, attempts = {}, {}, {}
    lock = threading.RLock()
    app = FastAPI(
        title="VietReceipt Annotation", docs_url=None, redoc_url=None, openapi_url=None
    )

    def session(request):
        token = request.cookies.get("receipt_session")
        with lock:
            item = sessions.get(token)
            if not item or item["expires"] < time.monotonic():
                sessions.pop(token, None)
                raise HTTPException(401, "Hãy đăng nhập bằng mật khẩu được giao.")
            return item

    def selected(request):
        item = session(request)
        with lock:
            bid = item["batch"]
            if bid not in stores:
                stores[bid] = Store(batches, bid, state_root / bid)
            store = stores[bid]
            if (
                request.method in ("POST", "PUT", "DELETE")
                and request.headers.get("x-workspace-id") != store.workspace_id
            ):
                raise HTTPException(
                    409, "Phiên làm việc đã đổi. Tải lại trang trước khi lưu."
                )
            return store

    @app.middleware("http")
    async def headers(request, call_next):
        if (
            request.method in ("POST", "PUT", "DELETE")
            and request.headers.get("x-label-workspace") != "1"
        ):
            return JSONResponse(
                {"detail": "Thiếu xác nhận nguồn yêu cầu."}, status_code=403
            )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(Conflict)
    async def conflict(request, error):
        return JSONResponse({"detail": str(error)}, status_code=409)

    @app.exception_handler(RuntimeError)
    @app.exception_handler(ValueError)
    @app.exception_handler(ValidationError)
    async def invalid(request, error):
        return JSONResponse({"detail": str(error)}, status_code=422)

    @app.exception_handler(KeyError)
    @app.exception_handler(FileNotFoundError)
    async def missing(request, error):
        return JSONResponse(
            {"detail": "Không tìm thấy ảnh trong batch được giao."}, status_code=404
        )

    @app.post("/api/login")
    def login(payload: LoginRequest, request: Request):
        address = request.client.host if request.client else "local"
        now = time.monotonic()
        with lock:
            recent = [t for t in attempts.get(address, []) if now - t < 60]
            attempts[address] = recent
            if len(recent) >= 10:
                raise HTTPException(
                    429, "Đã thử quá nhiều lần. Đợi một phút rồi thử lại."
                )
            recent.append(now)
            config = read_json(batches / "config.json")
            matches = [
                b
                for b in config["batches"]
                if verify_password(payload.password, b["password_hash"])
            ]
            if len(matches) != 1:
                raise HTTPException(401, "Mật khẩu không đúng.")
            bid = matches[0]["id"]
            # Validate assigned data before granting access; other batches may be absent locally.
            if bid not in stores:
                stores[bid] = Store(batches, bid, state_root / bid)
            token = secrets.token_urlsafe(32)
            sessions.pop(request.cookies.get("receipt_session"), None)
            sessions.update({token: {"batch": bid, "expires": now + 12 * 3600}})
            attempts.pop(address, None)
        response = JSONResponse({"ok": True})
        response.set_cookie(
            "receipt_session",
            token,
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
            max_age=12 * 3600,
        )
        return response

    @app.post("/api/logout")
    def logout(request: Request):
        with lock:
            sessions.pop(request.cookies.get("receipt_session"), None)
        response = JSONResponse({"ok": True})
        response.delete_cookie("receipt_session")
        return response

    @app.get("/api/session")
    def session_info(request: Request):
        try:
            session(request)
        except HTTPException:
            return {"authenticated": False}
        return {"authenticated": True}

    @app.get("/api/config")
    def config(request: Request):
        store = selected(request)
        return {
            "member": store.member,
            "batch": store.batch["id"],
            "workspace_id": store.workspace_id,
            "total": len(store.originals),
            "offline": True,
        }

    @app.get("/api/receipts")
    def receipts(request: Request):
        return selected(request).listing()

    @app.get("/api/receipts/{rid}")
    def receipt(rid: str, request: Request):
        return selected(request).presentation(rid)

    @app.put("/api/receipts/{rid}")
    def save(rid: str, payload: SaveRequest, request: Request):
        return selected(request).save(
            rid, payload.record, payload.review, payload.revision
        )

    @app.get("/api/receipts/{rid}/image")
    def image(rid: str, request: Request):
        return FileResponse(selected(request).image_path(rid))

    @app.post("/api/receipts/{rid}/crop")
    def crop(rid: str, payload: CropRequest, request: Request):
        store = selected(request)
        record = store.get(rid)["record"]
        if payload.rotation not in (0, 90, 180, 270) or any(
            len(p) != 2 for p in payload.polygon
        ):
            raise ValueError("Hình học không hợp lệ.")
        import math

        if any(
            not (
                math.isfinite(x)
                and math.isfinite(y)
                and 0 <= x <= record["width"]
                and 0 <= y <= record["height"]
            )
            for x, y in payload.polygon
        ):
            raise ValueError("Vùng vượt ngoài ảnh.")
        shape = Polygon(payload.polygon)
        if not shape.is_valid or shape.area < 0.01:
            raise ValueError("Polygon không hợp lệ.")
        return Response(
            crop_png(store.image_path(rid), payload.polygon, payload.rotation),
            media_type="image/png",
        )

    @app.get("/api/receipts/{rid}/qc")
    def quality(rid: str, request: Request):
        return {"rows": selected(request).qc(rid)}

    @app.post("/api/receipts/{rid}/complete")
    def complete(rid: str, payload: RevisionRequest, request: Request):
        result, rows = selected(request).complete(rid, payload.revision)
        if result is None:
            return JSONResponse(
                {"detail": "Còn mục cần kiểm tra.", "rows": rows}, status_code=422
            )
        return {**result, "qc": rows}

    @app.post("/api/receipts/{rid}/exclude")
    def exclude(rid: str, payload: ExcludeRequest, request: Request):
        if payload.reason not in EXCLUSION_REASONS:
            raise ValueError("Lý do loại ảnh không hợp lệ.")
        return selected(request).exclude(rid, payload.revision, payload.reason)

    @app.post("/api/receipts/{rid}/restore")
    def restore(rid: str, payload: RevisionRequest, request: Request):
        return selected(request).restore(rid, payload.revision)

    @app.get("/api/export")
    def export(request: Request):
        store = selected(request)
        with store.transaction():
            rows = [store.get(rid)["record"] for rid in sorted(store.originals)]
        complete = all(
            r["review"]["status"] in ("completed", "excluded")
            and r["review"]["reviewer"] == store.member
            and (r["review"]["status"] == "excluded" or not any(issue["level"] == "error" for issue in review_issues(r)))
            for r in rows
        )
        name = (
            store.batch["id"] + ("-completed" if complete else "-incomplete") + ".jsonl"
        )
        return Response(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
            media_type="application/x-ndjson",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    static = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/favicon.ico")
    def favicon():
        return FileResponse(static / "favicon.ico", media_type="image/x-icon")

    @app.get("/")
    def index():
        return FileResponse(static / "index.html")

    app.state.stores = stores
    return app


app = create_app()
