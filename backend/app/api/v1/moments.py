"""旅途瞬间 CRUD：逐条对外展示开关 + 协作按发布者查看。

- POST/PUT 接受 is_public；未提交时取 UserPreferences.moment_default_public（默认私有）。
- GET 的 viewer 语义：?public=1 只返回公开；普通登录用户返回本人全部 +
  他人 is_public=True 的记录（协作成员按发布者设置查看）。
- author_id 一律服务端注入，协作成员只要有 moment:write 权限即可发布。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db, require_permission
from app.core.errors import AppError, ErrorCode
from app.core.response import ok
from app.models.moment import Moment
from app.services.sync_service import apply_payload, emit, row_to_dict

router = APIRouter(tags=["moments"])


def _rid(request: Request) -> str:
    return getattr(request.state, "request_id", "")


def _get(db: Session, trip_id: str, item_id: str) -> Moment:
    obj = db.get(Moment, item_id)
    if obj is None or obj.trip_id != trip_id:
        raise AppError(ErrorCode.NOT_FOUND, "瞬间记录不存在")
    return obj


def _to_bool(value: Any, default: bool = False) -> bool:
    """兼容布尔与 '1'/'true' 字符串；None 用默认值。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _default_public(db: Session, user_id: Any) -> bool:
    """取当前用户的全局默认可见性；无偏好行 / 表未就绪时默认私有。"""
    if user_id is None:
        return False
    try:
        from app.models.config import UserPreferences

        pref = db.get(UserPreferences, user_id)
        return bool(getattr(pref, "moment_default_public", False))
    except Exception:  # noqa: BLE001  偏好表未迁移时安全降级为私有
        return False


@router.get("/trips/{trip_id}/moments")
def list_moments(trip_id: str, request: Request,
                 public: str | None = Query(default=None),
                 db: Session = Depends(get_db),
                 user: Any = Depends(require_permission("trip:read"))):
    """viewer 语义：public=1 只返回公开；否则本人全部 + 他人公开。"""
    query = db.query(Moment).filter(Moment.trip_id == trip_id)
    viewer_id = getattr(user, "id", None)
    if _to_bool(public):
        query = query.filter(Moment.is_public.is_(True))
    elif viewer_id is None:
        query = query.filter(Moment.is_public.is_(True))
    else:
        query = query.filter(
            or_(Moment.author_id == viewer_id, Moment.is_public.is_(True))
        )
    rows = query.order_by(Moment.taken_at.desc()).all()
    return ok([row_to_dict(r) for r in rows], request_id=_rid(request))


@router.post("/trips/{trip_id}/moments")
def create_moment(trip_id: str, request: Request, payload: dict = Body(default={}),
                  db: Session = Depends(get_db),
                  user: Any = Depends(require_permission("moment:write"))):
    body = dict(payload or {})
    # 发布者由服务端注入，杜绝客户端伪造 author_id
    body.pop("author_id", None)
    if "is_public" not in body or body["is_public"] is None:
        body["is_public"] = _default_public(db, getattr(user, "id", None))
    else:
        body["is_public"] = _to_bool(body["is_public"])
    obj = Moment(trip_id=trip_id, author_id=getattr(user, "id", None))
    apply_payload(obj, body)
    db.add(obj)
    db.commit()
    data = row_to_dict(obj)
    emit(trip_id, "moment.created", data, getattr(user, "id", None))
    return ok(data, request_id=_rid(request))


@router.get("/trips/{trip_id}/moments/{item_id}")
def get_moment(trip_id: str, item_id: str, request: Request, db: Session = Depends(get_db),
               user: Any = Depends(require_permission("trip:read"))):
    obj = _get(db, trip_id, item_id)
    # 与列表保持同一 viewer 语义：他人私有瞬间不可单条读取
    if not bool(obj.is_public) and obj.author_id != getattr(user, "id", None):
        raise AppError(ErrorCode.FORBIDDEN, "无权查看该瞬间")
    return ok(row_to_dict(obj), request_id=_rid(request))


@router.put("/trips/{trip_id}/moments/{item_id}")
def update_moment(trip_id: str, item_id: str, request: Request, payload: dict = Body(default={}),
                  db: Session = Depends(get_db),
                  user: Any = Depends(require_permission("moment:write"))):
    obj = _get(db, trip_id, item_id)
    body = dict(payload or {})
    # 发布者不可被改写；未提交 is_public 时保留数据库原值
    body.pop("author_id", None)
    if "is_public" in body and body["is_public"] is not None:
        body["is_public"] = _to_bool(body["is_public"])
    else:
        body.pop("is_public", None)
    apply_payload(obj, body)
    db.commit()
    data = row_to_dict(obj)
    emit(trip_id, "moment.updated", data, getattr(user, "id", None))
    return ok(data, request_id=_rid(request))


@router.delete("/trips/{trip_id}/moments/{item_id}")
def delete_moment(trip_id: str, item_id: str, request: Request, db: Session = Depends(get_db),
                  user: Any = Depends(require_permission("moment:write"))):
    obj = _get(db, trip_id, item_id)
    obj.deleted_at = datetime.now(timezone.utc)
    db.commit()
    emit(trip_id, "moment.deleted", {"id": item_id}, getattr(user, "id", None))
    return ok({"id": item_id, "deleted": True}, request_id=_rid(request))
