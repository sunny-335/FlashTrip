"""附件上传 / 下载：物理文件落在 data_dir()/uploads/<trip_id>。"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db, require_permission, require_user
from app.core.config import data_dir
from app.core.errors import AppError, ErrorCode
from app.core.response import ok
from app.core.security import new_id
from app.models.attachment import Attachment
from app.services.sync_service import emit, row_to_dict

router = APIRouter(tags=["uploads"])
_MAX_SIZE = 20 * 1024 * 1024


def _rid(request: Request) -> str:
    return getattr(request.state, "request_id", "")


@router.post("/uploads")
async def upload(request: Request, file: UploadFile = File(...),
                 trip_id: str = Form(...), kind: str = Form(default="file"),
                 db: Session = Depends(get_db),
                 user: Any = Depends(require_permission("trip:read"))):
    # 只取文件名，杜绝 ../ 路径穿越
    safe_name = Path(file.filename or "upload").name or "upload"
    data = await file.read(_MAX_SIZE + 1)
    if len(data) > _MAX_SIZE:
        raise AppError(ErrorCode.VALIDATION, "文件超过 20MB 限制")
    folder = data_dir() / "uploads" / trip_id
    folder.mkdir(parents=True, exist_ok=True)
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


@router.get("/uploads/{attachment_id}")
def download(attachment_id: str, request: Request, db: Session = Depends(get_db),
             user: Any = Depends(require_user)):
    attachment = db.get(Attachment, attachment_id)
    if attachment is None:
        raise AppError(ErrorCode.NOT_FOUND, "附件不存在")
    path = Path(attachment.storage_path)
    if not path.is_file():
        raise AppError(ErrorCode.NOT_FOUND, "附件文件已丢失")
    return FileResponse(path, filename=attachment.filename,
                        media_type=attachment.mime or "application/octet-stream")
