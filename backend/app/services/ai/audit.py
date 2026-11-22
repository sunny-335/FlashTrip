"""AI 调用审计：落 ai_audit_logs 与 ai_messages。

db 为 None 时静默跳过（便于纯逻辑测试与无库环境）；任何落库失败都降级为日志
告警，绝不因为审计写失败而中断对话流，且日志中不含密钥与请求正文。
"""
from __future__ import annotations

import json
from typing import Any

from app.core.logging import get_logger

log = get_logger(__name__)


def _json(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def record(db=None, *, user_id: str | None = None, trip_id: str | None = None,
           provider: str | None = None, model: str | None = None, action: str = "chat",
           payload: Any = None, status: str = "ok", error: str | None = None) -> None:
    """写一条 ai_audit_logs。payload 由调用方保证不含密钥。"""
    if db is None:
        return
    try:
        from app.models.ai import AiAuditLog

        db.add(
            AiAuditLog(
                user_id=user_id,
                trip_id=trip_id,
                provider=provider,
                model=model,
                action=action,
                payload_json=_json(payload),
                status=status,
                error=error,
            )
        )
        db.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("ai.audit_failed", error_type=type(exc).__name__)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass


def record_message(db=None, *, conversation_id: str, role: str, content: str | None = None,
                   tool_calls_json: Any = None, tool_call_id: str | None = None,
                   provider: str | None = None, model: str | None = None,
                   prompt_tokens: int | None = None, completion_tokens: int | None = None,
                   cost: Any = None, latency_ms: int | None = None) -> None:
    """写一条 ai_messages（含 token / cost / latency）。"""
    if db is None:
        return
    try:
        from app.models.ai import AiMessage

        db.add(
            AiMessage(
                conversation_id=conversation_id,
                role=role,
                content=content,
                tool_calls_json=_json(tool_calls_json),
                tool_call_id=tool_call_id,
                provider=provider,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost=cost,
                latency_ms=latency_ms,
            )
        )
        db.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("ai.message_audit_failed", error_type=type(exc).__name__)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
