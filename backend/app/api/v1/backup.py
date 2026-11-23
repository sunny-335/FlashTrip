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
    items = backup_service.list_backups()
    for item in items:
        item["download_url"] = f"/api/v1/backup/{item['id']}/download"
    return ok(items, request_id=_rid(request))


@router.post("/backup/export")
def export(request: Request, user: Any = Depends(require_permission("trip:settings"))):
    """立即备份：只创建备份并返回元信息，不在此端点回传 zip（下载走按 id 下载端点）。"""
    info = backup_service.create_backup("manual")
    payload = dict(info)
    payload["download_url"] = f"/api/v1/backup/{info['id']}/download"
    return ok(payload, request_id=_rid(request))


@router.get("/backup/{backup_id}/download")
def download(backup_id: str, request: Request,
             user: Any = Depends(require_permission("trip:settings"))):
    """按备份 id 下载 zip；文件不存在时返回语义化 404。"""
    filename, data = backup_service.get_backup_bytes_by_id(backup_id)
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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
