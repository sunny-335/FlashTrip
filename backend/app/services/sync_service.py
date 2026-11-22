"""协作同步：进程内 asyncio 事件总线 + 可选 Redis Pub/Sub + SSE 补发。

REST 写入 -> emit() 落 sync_events（自增 id 即 Last-Event-ID 游标）-> 广播；
SSE 订阅先补发 since 游标之后的历史事件，再实时推送并定时 ping 保活；
配置 redis.url 时额外跨进程广播，禁用 SSE 时由 events_since() 轮询降级。
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime

from app.core.config import resolve_redis_url
from app.core.logging import get_logger
from app.db.session import get_session
from app.models.sync import SyncEvent

log = get_logger(__name__)

# 进程内订阅者：trip_id -> Queue 集合（单进程 uvicorn 拓扑）
_SUBSCRIBERS: dict[str, set[asyncio.Queue]] = {}
_PING_INTERVAL = 15
_MAX_BATCH = 200


def row_to_dict(row: Any) -> dict[str, Any]:
    """ORM 行 -> 可序列化字典（供各业务 API 复用，不依赖具体模型字段）。"""
    out: dict[str, Any] = {}
    for column in row.__table__.columns:
        value = getattr(row, column.name, None)
        if isinstance(value, (datetime, date)):
            value = value.isoformat()
        elif isinstance(value, Decimal):
            value = float(value)
        elif isinstance(value, bytes):
            continue
        out[column.name] = value
    return out


def apply_payload(obj: Any, payload: dict | None, *,
                  skip: tuple[str, ...] = ("id", "trip_id", "created_at", "updated_at", "deleted_at")) -> None:
    """把请求体白名单式写回 ORM 对象；JSON/日期字段自动转换，trip_id 不可被改写。"""
    columns = {c.name: c for c in obj.__table__.columns}
    for key, value in (payload or {}).items():
        if key not in columns or key in skip:
            continue
        column = columns[key]
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        elif isinstance(column.type, DateTime) and isinstance(value, str):
            try:
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                continue
        setattr(obj, key, value)


def _json(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def _event_dict(row: SyncEvent) -> dict:
    try:
        payload = json.loads(row.payload_json) if row.payload_json else {}
    except ValueError:
        payload = {}
    created = getattr(row, "created_at", None)
    return {
        "id": row.id,
        "trip_id": row.trip_id,
        "event_type": row.event_type,
        "payload": payload,
        "actor_id": row.actor_id,
        "created_at": created.isoformat() if isinstance(created, datetime) else "",
    }


def _channel(trip_id: str) -> str:
    return f"flashtrip:sync:{trip_id}"


def _broadcast_local(trip_id: str, event: dict) -> None:
    for queue in list(_SUBSCRIBERS.get(trip_id, ())):
        try:
            queue.put_nowait(event)
        except Exception:  # noqa: BLE001  单个慢订阅者不影响其他订阅者
            pass


def _broadcast_redis(trip_id: str, event: dict) -> None:
    url = resolve_redis_url()
    if not url:
        return
    try:
        import redis

        client = redis.Redis.from_url(url, socket_timeout=2)
        try:
            client.publish(_channel(trip_id), json.dumps(event, ensure_ascii=False, default=str))
        finally:
            client.close()
    except Exception as exc:  # noqa: BLE001  Redis 不可用不能阻断进程内广播
        log.warning("sync.redis_publish_failed", error_type=type(exc).__name__)


def emit(trip_id: str, event_type: str, payload: Any = None,
         actor_id: str | None = None) -> dict:
    """写 sync_events 并广播；落库失败也降级为纯进程内广播，绝不静默丢事件。"""
    event: dict[str, Any] = {
        "id": 0,
        "trip_id": trip_id,
        "event_type": event_type,
        "payload": payload if not isinstance(payload, str) else {},
        "actor_id": actor_id,
        "created_at": datetime.now().astimezone().isoformat(),
    }
    if isinstance(payload, str):
        try:
            event["payload"] = json.loads(payload)
        except ValueError:
            event["payload"] = {"text": payload}
    try:
        SessionLocal = get_session()
        with SessionLocal() as session:
            row = SyncEvent(
                trip_id=trip_id, event_type=event_type,
                payload_json=_json(event["payload"]), actor_id=actor_id,
            )
            session.add(row)
            session.commit()
            event["id"] = row.id
            event["created_at"] = row.created_at.isoformat() if isinstance(row.created_at, datetime) else event["created_at"]
    except Exception as exc:  # noqa: BLE001  事件表未迁移时仅告警
        log.warning("sync.event_persist_failed", error_type=type(exc).__name__)
    _broadcast_local(trip_id, event)
    _broadcast_redis(trip_id, event)
    return event


def events_since(trip_id: str, cursor: int = 0, limit: int = _MAX_BATCH) -> list[dict]:
    """REST 降级用的增量拉取（id 严格大于 cursor）。"""
    try:
        SessionLocal = get_session()
        with SessionLocal() as session:
            rows = (
                session.query(SyncEvent)
                .filter(SyncEvent.trip_id == trip_id, SyncEvent.id > int(cursor or 0))
                .order_by(SyncEvent.id.asc())
                .limit(limit)
                .all()
            )
            return [_event_dict(row) for row in rows]
    except Exception as exc:  # noqa: BLE001
        log.warning("sync.events_since_failed", error_type=type(exc).__name__)
        return []


def _sse(event: dict) -> str:
    data = {
        "id": event.get("id"),
        "event_type": event.get("event_type"),
        "payload": event.get("payload") or {},
        "actor_id": event.get("actor_id"),
        "created_at": event.get("created_at"),
    }
    return f"id: {event.get('id') or 0}\nevent: {data['event_type']}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


async def _start_redis_relay(trip_id: str, queue: asyncio.Queue):
    """把跨进程 Redis 消息桥接到本地队列（与进程内消息共用同一条 SSE 流）。"""
    url = resolve_redis_url()
    if not url:
        return None
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(url)
        pubsub = client.pubsub()
        await pubsub.subscribe(_channel(trip_id))
    except Exception as exc:  # noqa: BLE001
        log.warning("sync.redis_subscribe_failed", error_type=type(exc).__name__)
        return None

    async def _listen() -> None:
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                try:
                    queue.put_nowait(json.loads(message["data"]))
                except Exception:  # noqa: BLE001
                    pass
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            pass
        finally:
            try:
                await pubsub.close()
                await client.close()
            except Exception:  # noqa: BLE001
                pass

    return asyncio.create_task(_listen())


async def subscribe(trip_id: str, last_event_id: int = 0) -> AsyncIterator[str]:
    """SSE 流：先补发历史事件，再实时推送，空闲定时 ping。"""
    queue: asyncio.Queue = asyncio.Queue()
    _SUBSCRIBERS.setdefault(trip_id, set()).add(queue)
    relay = await _start_redis_relay(trip_id, queue)
    cursor = int(last_event_id or 0)
    try:
        for event in events_since(trip_id, cursor):
            cursor = max(cursor, int(event["id"] or 0))
            yield _sse(event)
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=_PING_INTERVAL)
            except asyncio.TimeoutError:
                yield ": ping\n\n"
                continue
            event_id = int(event.get("id") or 0)
            if event_id and event_id <= cursor:
                continue  # 补发与实时广播重合时去重
            cursor = max(cursor, event_id)
            yield _sse(event)
    finally:
        _SUBSCRIBERS.get(trip_id, set()).discard(queue)
        if relay is not None:
            relay.cancel()
