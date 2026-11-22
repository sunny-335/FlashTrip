"""附件上传 / 下载：按行程英文名 + 4 位随机字符建文件夹并持久化复用。

目录：data_dir()/uploads/<trip_folder_name>/<new_id()>_<filename>。
文件夹名一经生成即写入 config.json 的 upload_folders[trip_id]，同时在目录内
落 .folder 标记；配置丢失时还能从既有 Attachment.storage_path 前缀或标记找回，
**绝不在每次上传时换文件夹**。文件类型限图片与常见业务附件，kind=moment 强制图片。
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

import json as _json

from app.api.v1.deps import current_user_optional, get_db, require_permission
from app.core.config import data_dir
from app.core.config_store import get_config_store
from app.core.errors import AppError, ErrorCode
from app.core.response import ok
from app.core.security import new_id
from app.models.attachment import Attachment
from app.models.moment import Moment
from app.models.trip import Trip
from app.services.slug import trip_folder_name
from app.services.sync_service import emit, row_to_dict

router = APIRouter(tags=["uploads"])
_MAX_SIZE = 20 * 1024 * 1024

# 图片（旅途瞬间只允许这一类）
_IMAGE_MIMES = {
    "image/png", "image/jpg", "image/jpeg", "image/webp",
    "image/gif", "image/heic", "image/heif",
}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".heic", ".heif"}
# 已有业务附件：PDF / Office / 文本 / 压缩包
_DOC_MIMES = {
    "application/pdf", "text/plain", "text/csv", "application/json",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/zip", "application/x-zip-compressed", "application/octet-stream",
}
_DOC_EXTS = {
    ".pdf", ".txt", ".csv", ".json", ".doc", ".docx",
    ".xls", ".xlsx", ".ppt", ".pptx", ".zip",
}
_ALLOWED_MIMES = _IMAGE_MIMES | _DOC_MIMES
_ALLOWED_EXTS = _IMAGE_EXTS | _DOC_EXTS


def _rid(request: Request) -> str:
    return getattr(request.state, "request_id", "")


def _validate_file(*, mime: str | None, ext: str, kind: str, size: int) -> None:
    """20MB 上限 + 类型白名单；非法一律 AppError(VALIDATION, 中文原因)。"""
    if size > _MAX_SIZE:
        raise AppError(ErrorCode.VALIDATION, "文件超过 20MB 限制，请压缩后再上传")
    m = str(mime or "").split(";")[0].strip().lower()
    e = str(ext or "").lower()
    if kind == "moment":
        # 有扩展名时以扩展名为准（防伪造 content-type）；无扩展名时信任图片 MIME
        if (e and e in _IMAGE_EXTS) or (not e and m in _IMAGE_MIMES):
            return
        raise AppError(ErrorCode.VALIDATION, "旅途瞬间仅支持图片格式（png/jpeg/webp/gif/heic）")
    if (e and e in _ALLOWED_EXTS) or (not e and m in _ALLOWED_MIMES):
        return
    raise AppError(
        ErrorCode.VALIDATION,
        "不支持的文件类型，仅允许图片与常见业务附件（PDF/文档/表格/文本/压缩包）",
    )


def _folder_from_attachment(db: Session, trip_id: str, root: Path) -> str | None:
    """config.json 丢失时，从既有 Attachment.storage_path 前缀找回文件夹。"""
    try:
        row = (
            db.query(Attachment)
            .filter(Attachment.trip_id == trip_id)
            .order_by(Attachment.created_at.asc())
            .first()
        )
        if row is None:
            return None
        name = Path(str(row.storage_path)).parent.name
        return name if name and (root / name).is_dir() else None
    except Exception:  # noqa: BLE001  附件表未就绪时继续走标记扫描
        return None


def _folder_from_marker(root: Path, trip_id: str) -> str | None:
    """扫描已有目录里的 .folder 标记，找回该行程此前生成的文件夹。"""
    if not root.is_dir():
        return None
    for child in root.iterdir():
        if not child.is_dir():
            continue
        marker = child / ".folder"
        try:
            if marker.is_file() and marker.read_text(encoding="utf-8").strip() == trip_id:
                return child.name
        except OSError:
            continue
    return None


def _resolve_folder(db: Session, trip_id: str) -> Path:
    """返回该行程专属目录；同一 trip_id 永远复用同一文件夹。"""
    root = data_dir() / "uploads"
    root.mkdir(parents=True, exist_ok=True)
    store = get_config_store()
    cfg = store.load()
    folders = cfg.get("upload_folders")
    if not isinstance(folders, dict):
        folders = {}
    name = folders.get(trip_id)
    if not name or not (root / str(name)).is_dir():
        name = _folder_from_attachment(db, trip_id, root) or _folder_from_marker(root, trip_id)
    if not name:
        taken = {child.name for child in root.iterdir() if child.is_dir()} if root.is_dir() else set()
        try:
            trip = db.get(Trip, trip_id)
        except Exception:  # noqa: BLE001  行程表异常时退化为用 id 生成目录名
            trip = None
        title = str(getattr(trip, "title", None) or trip_id)
        name = trip_folder_name(title, existing=taken)
        folders[trip_id] = name
        cfg["upload_folders"] = folders
        store.save(cfg)  # 持久化，重启后仍复用
    folder = root / str(name)
    folder.mkdir(parents=True, exist_ok=True)
    marker = folder / ".folder"
    if not marker.is_file():
        marker.write_text(trip_id, encoding="utf-8")
    return folder


@router.post("/uploads")
async def upload(request: Request, file: UploadFile = File(...),
                 trip_id: str = Form(...), kind: str = Form(default="file"),
                 db: Session = Depends(get_db),
                 user: Any = Depends(require_permission("trip:read"))):
    # 只取文件名，杜绝 ../ 路径穿越
    safe_name = Path(file.filename or "upload").name or "upload"
    data = await file.read(_MAX_SIZE + 1)
    _validate_file(mime=file.content_type, ext=Path(safe_name).suffix,
                   kind=kind, size=len(data))
    folder = _resolve_folder(db, trip_id)
    path = folder / f"{new_id()}_{safe_name}"
    path.write_bytes(data)

    attachment = Attachment(
        trip_id=trip_id,
        uploader_id=getattr(user, "id", None),
        filename=safe_name,
        storage_path=str(path),
        mime=file.content_type,
        size=len(data),
        checksum=hashlib.sha256(data).hexdigest(),
        kind=kind,
    )
    db.add(attachment)
    db.commit()
    result = row_to_dict(attachment)
    emit(trip_id, "attachment.created", result, getattr(user, "id", None))
    return ok(result, request_id=_rid(request))


def _public_moment_media(db: Session, attachment_id: str) -> bool:
    """未登录访问的安全边界：附件必须被至少一条「对外展示」的瞬间引用。

    只放行公开分享页真正需要的图片；私有瞬间的附件、以及从未被瞬间引用的
    业务附件一律要求登录，避免通过附件 ID 枚举越权读取。
    """
    rows = db.query(Moment.media_json).filter(Moment.is_public.is_(True)).all()
    for (raw,) in rows:
        if not raw:
            continue
        try:
            ids = _json.loads(raw) if isinstance(raw, str) else raw
        except (ValueError, TypeError):
            continue
        if isinstance(ids, list) and attachment_id in ids:
            return True
    return False


@router.get("/uploads/{attachment_id}")
def download(attachment_id: str, request: Request, db: Session = Depends(get_db),
             user: Any = Depends(current_user_optional)):
    attachment = db.get(Attachment, attachment_id)
    if attachment is None:
        raise AppError(ErrorCode.NOT_FOUND, "附件不存在")
    # 登录用户按既有权限体系访问；未登录仅放行公开瞬间引用的图片
    if user is None and not _public_moment_media(db, attachment_id):
        raise AppError(ErrorCode.UNAUTHORIZED, "请先登录后再查看该附件")
    path = Path(attachment.storage_path)
    if not path.is_file():
        raise AppError(ErrorCode.NOT_FOUND, "附件文件已丢失")
    return FileResponse(path, filename=attachment.filename,
                        media_type=attachment.mime or "application/octet-stream")
