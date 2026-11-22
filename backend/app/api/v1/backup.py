"""备份 API：配置、列表、导出 zip、导入恢复、删除、按保留数清理。"""
from __future__ import annotations

import io
from typing import Any

from fastapi import APIRouter, Body, Depends, File, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.api.v1.deps import require_permission
from app.core.response import ok
from app.services import backup_service

router = APIRouter(tags=["backup"])


def _rid(request: Request) -> str:
    return getattr(getattr(request, "state", None), "request_id", "") or ""


@router.get("/backup/config")
def get_config(request: Request, user: Any = Depends(require_permission("trip:settings"))):
    return ok(backup_service.get_backup_config(), request_id=_rid(request))


@router.put("/backup/config")
def put_config(request: Request, cfg: dict | None = Body(default=None),
               user: Any = Depends(require_permission("trip:settings"))):
    return ok(backup_service.save_backup_config(cfg or {}), request_id=_rid(request))


@router.get("/backup/list")
def list_backups(request: Request, user: Any = Depends(require_permission("trip:settings"))):
    return ok(backup_service.list_backups(), request_id=_rid(request))


@router.post("/backup/export")
def export(request: Request, user: Any = Depends(require_permission("trip:settings"))):
    """触发一次手动备份并以 zip 流返回。"""
    info = backup_service.create_backup("manual")
    data = backup_service.get_backup_bytes(info["filename"])
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{info["filename"]}"'},
    )


@router.post("/backup/import")
async def import_backup(request: Request, file: UploadFile = File(...),
                        user: Any = Depends(require_permission("trip:settings"))):
    data = await file.read()
    return ok(backup_service.import_backup(data), request_id=_rid(request))


@router.delete("/backup/{backup_id}")
def delete_backup(backup_id: str, request: Request,
                  user: Any = Depends(require_permission("trip:settings"))):
    return ok(backup_service.delete_backup(backup_id), request_id=_rid(request))


@router.post("/backup/prune")
def prune(request: Request, user: Any = Depends(require_permission("trip:settings"))):
    return ok({"pruned": backup_service.prune_backups()}, request_id=_rid(request))
